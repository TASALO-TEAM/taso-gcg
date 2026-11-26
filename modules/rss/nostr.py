"""NostrClient — cuentas de Nostr como fuente de feed (solo lectura), con la
misma interfaz que BlueskyClient (is_nostr_url / resolve / parse), así que
monitor.py, estilos, dedup y traducción no saben que existe.

Nostr no tiene servidor central: se lee de varios relays públicos por
WebSocket. Un relay puede mentir, por eso CADA evento se verifica: el id se
recalcula (sha256 de la serialización NIP-01), el autor debe ser la cuenta
seguida y la firma Schnorr (BIP-340) se comprueba con coincurve. Un evento
que no pasa se descarta: un relay hostil no puede inyectar posts falsos.

Entrada aceptada en /addfeed: npub1…, nprofile1…, hex de 64 caracteres,
nombre@dominio (NIP-05), prefijo nostr: y enlaces de visores (njump, primal…).
Se guarda en feeds.url como `nostr:<npub>`.

Trae notas (kind 1, sin respuestas) y artículos largos (kind 30023); ignora
reposts. Recursos: 3 relays, timeouts cortos, tope de tamaño y de eventos por
relay, conexiones que se cierran en cada ciclo.
"""

import asyncio
import hashlib
import html
import json
import re
from urllib.parse import urlparse

import httpx
from coincurve import PublicKeyXOnly
from websockets.asyncio.client import connect

from core.config import NOSTR_RELAYS
from utils.logger import log

FETCH_LIMIT = 20          # entradas devueltas al monitor
REQ_LIMIT = 40            # se pide más: las respuestas se descartan después
OPEN_TIMEOUT = 8          # s para abrir cada relay
TOTAL_TIMEOUT = 12        # s máximos por relay (conexión + lectura)
MAX_MSG = 1_000_000       # bytes por mensaje del relay
MAX_EVENTOS = 100         # tope por relay (anti-inundación)
SUB = "taso"
VISORES = ("njump.me", "primal.net", "habla.news", "snort.social", "iris.to",
           "coracle.social", "nostrudel.ninja", "yakihonne.com", "nostr.com")

# ---------------------------------------------------------------- bech32 (NIP-19)
_CHARSET = "qpzry9x8gf2tvdw0s3jn54khce6mua7l"


def _polymod(values):
    gen = (0x3B6A57B2, 0x26508E6D, 0x1EA119FA, 0x3D4233DD, 0x2A1462B3)
    chk = 1
    for v in values:
        b = chk >> 25
        chk = ((chk & 0x1FFFFFF) << 5) ^ v
        for i in range(5):
            if (b >> i) & 1:
                chk ^= gen[i]
    return chk


def _hrp_expand(hrp):
    return [ord(c) >> 5 for c in hrp] + [0] + [ord(c) & 31 for c in hrp]


def _convertbits(data, frombits, tobits, pad):
    acc = bits = 0
    out = []
    maxv = (1 << tobits) - 1
    max_acc = (1 << (frombits + tobits - 1)) - 1
    for v in data:
        acc = ((acc << frombits) | v) & max_acc
        bits += frombits
        while bits >= tobits:
            bits -= tobits
            out.append((acc >> bits) & maxv)
    if pad:
        if bits:
            out.append((acc << (tobits - bits)) & maxv)
    elif bits >= frombits or ((acc << (tobits - bits)) & maxv):
        raise ValueError("relleno inválido")
    return out


def bech32_decode(texto: str) -> tuple[str, bytes]:
    """(hrp, bytes). Sin el límite de 90 caracteres: NIP-19 lo quita."""
    s = texto.strip().lower()
    pos = s.rfind("1")
    if pos < 1 or pos + 7 > len(s):
        raise ValueError("bech32 inválido")
    data = [_CHARSET.find(c) for c in s[pos + 1:]]
    if -1 in data or _polymod(_hrp_expand(s[:pos]) + data) != 1:
        raise ValueError("bech32 inválido")
    return s[:pos], bytes(_convertbits(data[:-6], 5, 8, False))


def bech32_encode(hrp: str, raw: bytes) -> str:
    data = _convertbits(raw, 8, 5, True)
    pm = _polymod(_hrp_expand(hrp) + data + [0] * 6) ^ 1
    check = [(pm >> 5 * (5 - i)) & 31 for i in range(6)]
    return hrp + "1" + "".join(_CHARSET[d] for d in data + check)


def _tlv(raw: bytes):
    i, out = 0, []
    while i + 2 <= len(raw):
        t, n = raw[i], raw[i + 1]
        v = raw[i + 2:i + 2 + n]
        if len(v) < n:
            raise ValueError("TLV truncado")
        out.append((t, v))
        i += 2 + n
    return out


def hex_to_npub(clave: str) -> str:
    return bech32_encode("npub", bytes.fromhex(clave))


def _naddr(autor: str, kind: int, d: str) -> str:
    d_b = d.encode()
    raw = bytes([0, len(d_b)]) + d_b + bytes([2, 32]) + bytes.fromhex(autor) + bytes([3, 4]) + kind.to_bytes(4, "big")
    return bech32_encode("naddr", raw)


# ---------------------------------------------------------------- entrada del admin
_BECH = re.compile(r"(?:npub1|nprofile1)[a-z0-9]+", re.I)
_HEX = re.compile(r"[0-9a-fA-F]{64}")
_NIP05 = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")


def _forma(texto):
    """('bech'|'hex'|'nip05', token) si el texto tiene pinta de cuenta de
    Nostr; None si no. Barato y sin red: es lo que decide el enrutado."""
    t = (texto or "").strip()
    if t.lower().startswith("nostr:"):
        t = t[6:]
    if "://" in t:
        p = urlparse(t)
        if p.netloc.lower().removeprefix("www.") in VISORES:
            m = _BECH.search(p.path)
            if m:
                return "bech", m.group(0)
        return None
    if _BECH.fullmatch(t):
        return "bech", t
    if _HEX.fullmatch(t):
        return "hex", t
    if _NIP05.fullmatch(t):
        return "nip05", t
    return None


def _decodificar(tipo: str, token: str) -> tuple[str, list[str]]:
    """(pubkey_hex, relays_sugeridos). ValueError con mensaje para el admin."""
    if tipo == "hex":
        return token.lower(), []
    try:
        hrp, raw = bech32_decode(token)
        if hrp == "npub" and len(raw) == 32:
            return raw.hex(), []
        if hrp == "nprofile":
            campos = _tlv(raw)
            clave = next(v for t, v in campos if t == 0 and len(v) == 32)
            pistas = [v.decode() for t, v in campos if t == 1 and v.startswith(b"wss://")]
            return clave.hex(), pistas[:2]
    except (ValueError, StopIteration, UnicodeDecodeError):
        pass
    raise ValueError("El npub/nprofile no es válido (revisa que esté completo).")


async def _nip05(identificador: str) -> str:
    nombre, dominio = identificador.rsplit("@", 1)
    if re.fullmatch(r"[\d.]+", dominio):
        raise ValueError("NIP-05 inválido.")
    try:
        # NIP-05: no se siguen redirecciones.
        async with httpx.AsyncClient(timeout=10, follow_redirects=False) as c:
            r = await c.get(f"https://{dominio}/.well-known/nostr.json", params={"name": nombre})
        clave = r.json()["names"][nombre]
        if _HEX.fullmatch(clave):
            return clave.lower()
    except Exception:
        pass
    raise ValueError(f"No pude verificar «{identificador}» (NIP-05). Prueba con el npub.")


# ---------------------------------------------------------------- relays + verificación
def verify_event(ev, autor: str) -> bool:
    """Id recalculado + autor esperado + firma Schnorr. Cualquier anomalía = False."""
    try:
        if ev["pubkey"] != autor:
            return False
        if not (isinstance(ev["kind"], int) and isinstance(ev["created_at"], int)
                and isinstance(ev["tags"], list) and isinstance(ev["content"], str)):
            return False
        ser = json.dumps([0, ev["pubkey"], ev["created_at"], ev["kind"], ev["tags"], ev["content"]],
                         separators=(",", ":"), ensure_ascii=False)
        eid = hashlib.sha256(ser.encode()).digest()
        if eid.hex() != ev["id"]:
            return False
        return PublicKeyXOnly(bytes.fromhex(autor)).verify(bytes.fromhex(ev["sig"]), eid)
    except Exception:
        return False


async def _query_relay(relay: str, filtros: list[dict]):
    """(eventos_sin_verificar, respondió). Nunca lanza."""
    eventos: list[dict] = []

    async def leer():
        async with connect(relay, open_timeout=OPEN_TIMEOUT, close_timeout=2, max_size=MAX_MSG) as ws:
            await ws.send(json.dumps(["REQ", SUB, *filtros]))
            async for crudo in ws:
                try:
                    msg = json.loads(crudo)
                except ValueError:
                    continue
                if not isinstance(msg, list) or len(msg) < 2 or msg[1] != SUB:
                    continue
                if msg[0] == "EVENT" and len(msg) >= 3 and isinstance(msg[2], dict):
                    eventos.append(msg[2])
                    if len(eventos) >= MAX_EVENTOS:
                        return True
                elif msg[0] == "EOSE":
                    await ws.send(json.dumps(["CLOSE", SUB]))
                    return True
                elif msg[0] == "CLOSED":
                    return False
        return False

    try:
        ok = await asyncio.wait_for(leer(), TOTAL_TIMEOUT)
    except Exception as e:
        log(f"Nostr: {relay} sin respuesta ({type(e).__name__})", "debug")
        return eventos, False
    return eventos, ok


async def _query(filtros: list[dict], autor: str, relays: list[str]):
    """([eventos verificados, únicos], relays_que_respondieron)."""
    res = await asyncio.gather(*(_query_relay(r, filtros) for r in relays))
    vistos: dict[str, dict] = {}
    respondieron = invalidos = 0
    for eventos, ok in res:
        if ok or eventos:
            respondieron += 1
        for ev in eventos:
            eid = ev.get("id")
            if isinstance(eid, str) and eid in vistos:
                continue
            if verify_event(ev, autor):
                vistos[eid] = ev
            else:
                invalidos += 1
    if invalidos:
        log(f"Nostr: {invalidos} evento(s) con id/firma inválidos descartados ({autor[:8]}…)", "warning")
    return list(vistos.values()), respondieron


# ---------------------------------------------------------------- evento -> entrada
_URL = re.compile(r"https?://[^\s<>\"]+")
_REF = re.compile(r"nostr:((?:npub|nprofile|note|nevent|naddr)1[a-z0-9]+)")
_IMG = (".jpg", ".jpeg", ".png", ".webp")


def _nombre(eventos) -> str | None:
    perfiles = sorted((e for e in eventos if e["kind"] == 0), key=lambda e: e["created_at"], reverse=True)
    for p in perfiles:
        try:
            d = json.loads(p["content"])
            n = d.get("display_name") or d.get("displayName") or d.get("name")
            if isinstance(n, str) and n.strip():
                return n.strip()[:40]
        except ValueError:
            continue
    return None


def _es_respuesta(tags) -> bool:
    """NIP-10: una nota con etiqueta e (salvo marcada 'mention') responde a otra."""
    return any(t and t[0] == "e" and (len(t) < 4 or t[3] != "mention") for t in tags)


def _media(texto: str, tags):
    """(imagen, video, urls_usadas, enlace_externo). Solo mp4 directo sirve a send_video."""
    imagen = video = None
    for t in tags:
        if t and t[0] == "imeta":
            props = dict(s.split(" ", 1) for s in t[1:] if " " in s)
            url, mime = props.get("url", ""), props.get("m", "")
            if url.startswith("https://"):
                if mime.startswith("video/mp4") and not video:
                    video = url
                elif mime in ("image/jpeg", "image/png", "image/webp") and not imagen:
                    imagen = url
    usadas, externo = [], None
    for u in (m.rstrip(".,;:!?)") for m in _URL.findall(texto)):
        ruta = urlparse(u).path.lower()
        if ruta.endswith(_IMG) and not imagen:
            imagen = u
            usadas.append(u)
        elif ruta.endswith(".mp4") and not video:
            video = u
            usadas.append(u)
        elif not ruta.endswith(_IMG + (".mp4",)) and not externo:
            externo = u
    return imagen, video, usadas, externo


def _texto_html(texto: str) -> str:
    """Escapa TODO texto externo y convierte nostr:npub… en enlaces a njump."""
    seguro = html.escape(texto, quote=False)
    return _REF.sub(lambda m: f'<a href="https://njump.me/{m.group(1)}">{m.group(1)[:12]}…</a>', seguro)


def _corto(npub: str) -> str:
    return f"{npub[:12]}…{npub[-6:]}"


def _a_entrada(ev: dict, origen: str) -> dict | None:
    kind, tags, autor = ev["kind"], ev["tags"], ev["pubkey"]
    if kind == 1:
        if _es_respuesta(tags):
            return None
        texto = ev["content"].strip()
        imagen, video, usadas, externo = _media(texto, tags)
        for u in usadas:
            texto = texto.replace(u, "")
        texto = re.sub(r"\n{3,}", "\n\n", texto).strip() or "(nota sin texto)"
        linea = next((x.strip() for x in texto.splitlines() if x.strip()), texto)
        titulo = linea if len(linea) <= 120 else linea[:119] + "…"
        return {
            "title": html.escape(titulo, quote=False),
            "link": "https://njump.me/" + bech32_encode("note", bytes.fromhex(ev["id"])),
            "description": _texto_html(texto),
            "image": imagen, "video": video, "external_link": externo,
            "hash": ev["id"], "source": origen,
        }
    if kind == 30023:
        etiqueta = {t[0]: t[1] for t in tags if len(t) >= 2 and isinstance(t[0], str)}
        d = etiqueta.get("d", "")
        resumen = etiqueta.get("summary") or ev["content"].strip()[:400]
        imagen = etiqueta.get("image")
        return {
            "title": html.escape(etiqueta.get("title") or "(artículo sin título)", quote=False),
            "link": "https://njump.me/" + _naddr(autor, 30023, d),
            "description": _texto_html(resumen),
            "image": imagen if isinstance(imagen, str) and imagen.startswith("https://") else None,
            "video": None, "external_link": None,
            # Estable ante ediciones del artículo (el id cambia en cada edición).
            "hash": hashlib.md5(f"30023:{autor}:{d}".encode()).hexdigest(), "source": origen,
        }
    return None


def _entrada_segura(ev: dict, origen: str) -> dict | None:
    """Una etiqueta mal formada (firmada por la propia cuenta) no tumba el feed."""
    try:
        return _a_entrada(ev, origen)
    except Exception as e:
        log(f"Nostr: evento {str(ev.get('id'))[:8]} no se pudo convertir ({type(e).__name__})", "warning")
        return None


# ---------------------------------------------------------------- interfaz pública
class NostrClient:

    @staticmethod
    def is_nostr_url(url: str) -> bool:
        return _forma(url) is not None

    @staticmethod
    async def _clave(url: str) -> tuple[str, list[str]]:
        forma = _forma(url)
        if not forma:
            raise ValueError("No reconocí una cuenta de Nostr (usa npub…, nprofile…, hex o nombre@dominio).")
        if forma[0] == "nip05":
            return await _nip05(forma[1]), []
        return _decodificar(*forma)

    @classmethod
    async def resolve(cls, url: str):
        """(url_canonica, titulo, error), mismo contrato que find_best_feed.
        Sin kind 0 no es error (muchas cuentas no tienen perfil); sin ningún
        relay disponible sí, para no crear un feed que no podrá leerse."""
        try:
            clave, pistas = await cls._clave(url)
        except ValueError as e:
            return None, None, str(e)
        npub = hex_to_npub(clave)
        relays = list(dict.fromkeys(NOSTR_RELAYS + pistas))
        eventos, respondieron = await _query([{"authors": [clave], "kinds": [0], "limit": 1}], clave, relays)
        if not respondieron:
            return None, None, "Ningún relay de Nostr respondió ahora; reintenta en unos minutos."
        return f"nostr:{npub}", f"Nostr: {_nombre(eventos) or _corto(npub)}", None

    @classmethod
    async def parse(cls, url: str):
        """({"title","entries":[...]}, None) o (None, error). Mismo contrato que
        BlueskyClient.parse. Perfil (kind 0) y notas viajan en un solo REQ."""
        try:
            clave, _ = await cls._clave(url)
        except ValueError as e:
            return None, str(e)
        filtros = [{"authors": [clave], "kinds": [1, 30023], "limit": REQ_LIMIT},
                   {"authors": [clave], "kinds": [0], "limit": 1}]
        eventos, respondieron = await _query(filtros, clave, NOSTR_RELAYS)
        if not respondieron:
            return None, "Ningún relay de Nostr respondió."
        nombre = _nombre(eventos) or _corto(hex_to_npub(clave))
        origen = f"Nostr / {html.escape(nombre, quote=False)}"
        notas = sorted((e for e in eventos if e["kind"] in (1, 30023)),
                       key=lambda e: e["created_at"], reverse=True)
        entradas = [x for x in (_entrada_segura(e, origen) for e in notas) if x][:FETCH_LIMIT]
        return {"title": f"Nostr: {nombre}", "entries": entradas}, None
