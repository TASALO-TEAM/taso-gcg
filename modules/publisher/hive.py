"""Cliente mínimo de Hive para publicar sin dependencias nuevas.

Decisión de diseño (menos código, menos riesgo): el NODO serializa la transacción
(`condenser_api.get_transaction_hex`) y aquí solo se firma con `coincurve`, que ya es
dependencia por Nostr. Así no hay serializador binario propio que pueda divergir de la
cadena. Cuesta una llamada extra por publicación (unas pocas al día).

Solo se usa la clave de POSTING (comentarios y blog); nunca la activa ni la owner.
La clave llega ya descifrada desde el planificador y NUNCA se loguea ni va en un error.
"""

import hashlib
import re
from datetime import datetime, timedelta, timezone

import httpx

from coincurve import PrivateKey

NODOS = ("https://api.hive.blog", "https://api.deathwing.me", "https://api.openhive.network")
CHAIN_ID = bytes.fromhex("beeab0de" + "00" * 28)
TIMEOUT = 15
EXPIRA_S = 60
MAX_PAGO = "1000000.000 HBD"
_B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"


class HiveError(RuntimeError):
    """Fallo de Hive. El mensaje nunca contiene la clave."""


# ---------- claves ----------
def _b58d(s: str) -> bytes:
    n = 0
    for c in s:
        n = n * 58 + _B58.index(c)          # ValueError si hay un carácter ajeno al alfabeto
    cuerpo = n.to_bytes((n.bit_length() + 7) // 8, "big")
    return b"\x00" * (len(s) - len(s.lstrip("1"))) + cuerpo


def _sha2(b: bytes) -> bytes:
    return hashlib.sha256(hashlib.sha256(b).digest()).digest()


def wif_a_clave(wif: str) -> bytes:
    """WIF (5...) a los 32 bytes de la clave privada. Valida el checksum."""
    try:
        raw = _b58d((wif or "").strip())
        ok = len(raw) == 37 and raw[0] == 0x80 and _sha2(raw[:-4])[:4] == raw[-4:]
    except ValueError:
        ok = False
    if not ok:
        raise HiveError("la clave de posting no es una WIF válida (debe empezar por 5 y tener 51 caracteres)")
    return raw[1:33]


def pub_de_clave(clave: bytes) -> bytes:
    return PrivateKey(clave).public_key.format(compressed=True)


def _pub_stm(stm: str) -> bytes:
    return _b58d(stm[3:])[:33]               # STM + base58(pub33 + checksum4); el checksum no hace falta


# ---------- firma ----------
def _canonica(c: bytes) -> bool:
    """Regla de canonicidad de Hive sobre la firma compacta (cabecera + r + s)."""
    return not (c[1] & 0x80) and not (c[1] == 0 and not (c[2] & 0x80)) \
        and not (c[33] & 0x80) and not (c[33] == 0 and not (c[34] & 0x80))


def firmar(digest: bytes, clave: bytes) -> str | None:
    """Firma recuperable de 65 bytes en hex, o None si no es canónica (se reintenta con otro digest)."""
    s = PrivateKey(clave).sign_recoverable(digest, hasher=None)      # r || s || recid
    c = bytes([31 + s[64]]) + s[:64]
    return c.hex() if _canonica(c) else None


# ---------- nodo ----------
async def _rpc(metodo: str, params, nodos=NODOS):
    ultimo = "sin respuesta"
    async with httpx.AsyncClient(timeout=TIMEOUT) as cli:
        for nodo in nodos:
            try:
                r = await cli.post(nodo, json={"jsonrpc": "2.0", "method": metodo, "params": params, "id": 1})
                j = r.json()
            except (httpx.HTTPError, ValueError) as e:
                ultimo = f"{nodo}: {type(e).__name__}"
                continue
            if "error" in j:                 # rechazo del protocolo: otro nodo diría lo mismo
                raise HiveError(str(j["error"].get("message", j["error"]))[:300])
            return j.get("result")
    raise HiveError(f"ningún nodo de Hive respondió ({ultimo})")


async def verificar_clave(cuenta: str, wif: str) -> None:
    """Comprueba que la clave es la de posting de la cuenta. Lanza HiveError si no."""
    clave = wif_a_clave(wif)
    res = await _rpc("condenser_api.get_accounts", [[cuenta]])
    if not res:
        raise HiveError(f"la cuenta @{cuenta} no existe en Hive")
    autorizadas = {_pub_stm(k[0]) for k in res[0]["posting"]["key_auths"]}
    if pub_de_clave(clave) not in autorizadas:
        raise HiveError(f"esa clave no es la de posting de @{cuenta}")


async def contenedor_vigente(cuenta: str) -> dict:
    """Post contenedor más reciente de @peak.snaps / @ecency.waves (aquí se responde con un wave o snap)."""
    posts = await _rpc("bridge.get_account_posts", {"sort": "posts", "account": cuenta, "limit": 1})
    if not posts:
        raise HiveError(f"@{cuenta} no tiene un post contenedor vigente")
    return {"author": posts[0]["author"], "permlink": posts[0]["permlink"]}


# ---------- operaciones ----------
def slug(texto: str, maximo: int = 60) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", (texto or "").lower()).strip("-")
    return (s[:maximo].strip("-")) or "post"


def op_comentario(autor, permlink, cuerpo, padre_autor="", padre_permlink="", titulo="", meta=None):
    import json
    return ["comment", {
        "parent_author": padre_autor, "parent_permlink": padre_permlink,
        "author": autor, "permlink": permlink, "title": titulo, "body": cuerpo,
        "json_metadata": json.dumps(meta or {}, ensure_ascii=False, separators=(",", ":")),
    }]


def op_opciones(autor, permlink, beneficiarios):
    ext = []
    if beneficiarios:
        b = sorted(({"account": x["account"], "weight": int(x["weight"])} for x in beneficiarios), key=lambda x: x["account"])
        if sum(x["weight"] for x in b) > 10000:
            raise HiveError("los beneficiarios suman más de 100%")
        ext = [[0, {"beneficiaries": b}]]
    return ["comment_options", {
        "author": autor, "permlink": permlink, "max_accepted_payout": MAX_PAGO, "percent_hbd": 10000,
        "allow_votes": True, "allow_curation_rewards": True, "extensions": ext,
    }]


async def transmitir(operaciones: list, wif: str) -> str:
    """Firma con la clave de posting y emite. Devuelve el id de la transacción."""
    clave = wif_a_clave(wif)
    props = await _rpc("condenser_api.get_dynamic_global_properties", [])
    cabeza = bytes.fromhex(props["head_block_id"])
    ahora = datetime.fromisoformat(props["time"]).replace(tzinfo=timezone.utc) + timedelta(seconds=EXPIRA_S)
    tx = {
        "ref_block_num": props["head_block_number"] & 0xFFFF,
        "ref_block_prefix": int.from_bytes(cabeza[4:8], "little"),
        "expiration": ahora.strftime("%Y-%m-%dT%H:%M:%S"),
        "operations": operaciones, "extensions": [], "signatures": [],
    }
    for _ in range(12):                      # ~50 % de las firmas no son canónicas: otro segundo de expiración, otro digest
        crudo = bytes.fromhex(await _rpc("condenser_api.get_transaction_hex", [tx]))
        if crudo[-1:] != b"\x00":
            raise HiveError("el nodo devolvió una transacción con firmas inesperadas")
        sig = firmar(hashlib.sha256(CHAIN_ID + crudo[:-1]).digest(), clave)
        if sig:
            tx["signatures"] = [sig]
            res = await _rpc("condenser_api.broadcast_transaction_synchronous", [tx])
            return str((res or {}).get("id", ""))
        tx["expiration"] = (datetime.fromisoformat(tx["expiration"]) + timedelta(seconds=1)).strftime("%Y-%m-%dT%H:%M:%S")
    raise HiveError("no se obtuvo una firma canónica")
