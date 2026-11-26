"""Tests de modules/rss/nostr.py — sin red: vectores oficiales de NIP-19,
firmas reales generadas con coincurve y relays falsos locales (honesto,
hostil y mudo) levantados con websockets.serve."""

import asyncio
import hashlib
import json
from contextlib import asynccontextmanager

import httpx
import pytest
from coincurve import PrivateKey
from websockets.asyncio.server import serve

from modules.rss import nostr
from modules.rss.nostr import NostrClient

# Vectores del texto de NIP-19 (el checksum bech32 valida cada cadena).
NPUB = "npub10elfcs4fr0l0r8af98jlmgdh9c8tcxjvz9qkw038js35mp4dma8qzvjptg"
NPUB_HEX = "7e7e9c42a91bfef19fa929e5fda1b72e0ebc1a4c1141673e2794234d86addf4e"
NPROFILE = ("nprofile1qqsrhuxx8l9ex335q7he0f09aej04zpazpl0ne2cgukyawd24mayt8gpp4mhxue69uhhytnc9e3k7mgpz4mhxue"
            "69uhkg6nzv9ejuumpv34kytnrdaksjlyr9p")
NPROFILE_HEX = "3bf0c63fcb93463407af97a5e5ee64fa883d107ef9e558472c4eb9aaaefa459d"

SK = PrivateKey(bytes([1]) * 32)
SK_ATACANTE = PrivateKey(bytes([2]) * 32)
PUB = SK.public_key_xonly.format().hex()


def firmar(sk, kind, content, tags=(), t=1_700_000_000, pubkey=None):
    pub = pubkey or sk.public_key_xonly.format().hex()
    ser = json.dumps([0, pub, t, kind, list(tags), content], separators=(",", ":"), ensure_ascii=False)
    eid = hashlib.sha256(ser.encode()).digest()
    return {"id": eid.hex(), "pubkey": pub, "created_at": t, "kind": kind,
            "tags": list(tags), "content": content, "sig": sk.sign_schnorr(eid).hex()}


# ------------------------------------------------------------------ bech32 / entrada
def test_npub_vector_oficial_ida_y_vuelta():
    assert nostr._decodificar("bech", NPUB) == (NPUB_HEX, [])
    assert nostr.hex_to_npub(NPUB_HEX) == NPUB


def test_nprofile_vector_oficial_trae_clave_y_relays():
    clave, relays = nostr._decodificar("bech", NPROFILE)
    assert clave == NPROFILE_HEX
    assert relays == ["wss://r.x.com", "wss://djbas.sadkb.com"]


def test_checksum_roto_se_rechaza():
    with pytest.raises(ValueError):
        nostr._decodificar("bech", NPUB[:-1] + "q")


@pytest.mark.parametrize("texto", [
    NPUB, f"nostr:{NPUB}", NPUB.upper(), NPUB_HEX, "ana@ejemplo.com", "_@ejemplo.com",
    f"https://njump.me/{NPUB}", f"https://primal.net/p/{NPUB}", f"https://www.habla.news/p/{NPUB}", NPROFILE,
])
def test_reconoce_entradas_de_nostr(texto):
    assert NostrClient.is_nostr_url(texto)


@pytest.mark.parametrize("texto", [
    "", None, "https://example.com/feed", "https://x.com/jack", "https://bsky.app/profile/a.bsky.social",
    "example.com", "https://njump.me/", "no es nostr",
])
def test_no_reconoce_otras_fuentes(texto):
    assert not NostrClient.is_nostr_url(texto)


async def test_nip05_resuelve_y_rechaza(monkeypatch):
    real = httpx.AsyncClient

    def handler(req):
        assert req.url.path == "/.well-known/nostr.json"
        return httpx.Response(200, json={"names": {"bob": PUB}})

    monkeypatch.setattr(nostr.httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(handler), **kw))
    assert (await NostrClient._clave("bob@ejemplo.com"))[0] == PUB
    with pytest.raises(ValueError):
        await NostrClient._clave("ana@ejemplo.com")      # nombre que el dominio no conoce
    with pytest.raises(ValueError):
        await NostrClient._clave("bob@127.0.0.1")        # IP: no se consulta


# ------------------------------------------------------------------ verificación
def test_evento_valido_pasa():
    assert nostr.verify_event(firmar(SK, 1, "hola"), PUB)


def test_contenido_alterado_no_pasa():
    ev = firmar(SK, 1, "hola")
    ev["content"] = "hola, compra mi token"
    assert not nostr.verify_event(ev, PUB)


def test_firma_de_otro_con_la_clave_de_la_victima_no_pasa():
    # El atacante arma un evento "de" la víctima con id correcto pero su propia firma.
    ev = firmar(SK_ATACANTE, 1, "falso", pubkey=PUB)
    assert not nostr.verify_event(ev, PUB)


def test_autor_distinto_y_basura_no_pasan():
    assert not nostr.verify_event(firmar(SK_ATACANTE, 1, "x"), PUB)
    assert not nostr.verify_event({"id": 1}, PUB)
    assert not nostr.verify_event({**firmar(SK, 1, "x"), "tags": "no-lista"}, PUB)


# ------------------------------------------------------------------ evento -> entrada
def entrada(ev):
    return nostr._a_entrada(ev, "Nostr / Ana")


def test_nota_escapa_html_enlaza_referencias_y_extrae_media():
    texto = (f"Hola <b>mundo</b> & más\nhttps://ex.com/foto.jpg https://ex.com/v.mp4 "
             f"https://articulo.com/x nostr:{NPUB}")
    e = entrada(firmar(SK, 1, texto))
    assert e["title"] == "Hola &lt;b&gt;mundo&lt;/b&gt; &amp; más"
    assert "<b>" not in e["description"] and "&lt;b&gt;" in e["description"]
    assert "foto.jpg" not in e["description"] and "v.mp4" not in e["description"]
    assert f'<a href="https://njump.me/{NPUB}">npub10elfcs4…</a>' in e["description"]
    assert (e["image"], e["video"]) == ("https://ex.com/foto.jpg", "https://ex.com/v.mp4")
    assert e["external_link"] == "https://articulo.com/x"
    assert e["link"].startswith("https://njump.me/note1") and e["source"] == "Nostr / Ana"
    assert set(e) == {"title", "link", "description", "image", "video", "external_link", "hash", "source"}


def test_respuestas_se_descartan_y_menciones_no():
    assert entrada(firmar(SK, 1, "re", [["e", "ab" * 32, "", "reply"]])) is None
    assert entrada(firmar(SK, 1, "re", [["e", "ab" * 32]])) is None
    assert entrada(firmar(SK, 1, "cito", [["e", "ab" * 32, "", "mention"]])) is not None


def test_titulo_largo_se_corta_y_nota_solo_imagen():
    assert len(entrada(firmar(SK, 1, "a" * 300))["title"]) == 120
    e = entrada(firmar(SK, 1, "https://ex.com/a.png"))
    assert e["image"] == "https://ex.com/a.png" and e["description"] == "(nota sin texto)"


def test_imeta_aporta_imagen():
    e = entrada(firmar(SK, 1, "foto", [["imeta", "url https://ex.com/a", "m image/jpeg"]]))
    assert e["image"] == "https://ex.com/a"


def test_articulo_largo_usa_etiquetas_y_hash_estable_ante_ediciones():
    tags = [["d", "mi-art"], ["title", "Hola <x>"], ["summary", "Resumen & más"], ["image", "https://i.com/x.png"]]
    a, b = firmar(SK, 30023, "cuerpo v1", tags), firmar(SK, 30023, "cuerpo v2", tags, t=1_700_000_500)
    ea, eb = entrada(a), entrada(b)
    assert ea["title"] == "Hola &lt;x&gt;" and ea["description"] == "Resumen &amp; más"
    assert ea["image"] == "https://i.com/x.png"
    assert ea["hash"] == eb["hash"] and a["id"] != b["id"]
    hrp, raw = nostr.bech32_decode(ea["link"].rsplit("/", 1)[1])
    assert hrp == "naddr" and b"mi-art" in raw and bytes.fromhex(PUB) in raw and raw.endswith(bytes([3, 4, 0, 0, 0x75, 0x47]))


def test_evento_malformado_no_tumba_el_feed():
    ev = firmar(SK, 1, "x")
    ev["tags"] = [5]
    assert nostr._entrada_segura(ev, "Nostr / Ana") is None


# ------------------------------------------------------------------ relays falsos
@asynccontextmanager
async def relay(eventos=(), crudo=(), mudo=False):
    async def handler(ws):
        req = json.loads(await ws.recv())
        if mudo:
            await ws.wait_closed()   # no responde hasta que el cliente se rinde
            return
        for c in crudo:
            await ws.send(c)
        for ev in eventos:
            await ws.send(json.dumps(["EVENT", req[1], ev]))
        await ws.send(json.dumps(["EOSE", req[1]]))
        async for _ in ws:
            pass

    async with serve(handler, "127.0.0.1", 0) as srv:
        yield f"ws://127.0.0.1:{srv.sockets[0].getsockname()[1]}"


@pytest.fixture
def rapido(monkeypatch):
    monkeypatch.setattr(nostr, "TOTAL_TIMEOUT", 0.5)
    monkeypatch.setattr(nostr, "OPEN_TIMEOUT", 0.5)


PERFIL = firmar(SK, 0, json.dumps({"display_name": "Ana <3"}))
NOTAS = [firmar(SK, 1, "primera", t=1_700_000_001), firmar(SK, 1, "segunda", t=1_700_000_002)]


async def test_parse_une_relays_dedup_y_ordena(monkeypatch, rapido):
    async with relay([PERFIL, NOTAS[0]]) as a, relay([NOTAS[0], NOTAS[1]]) as b:
        monkeypatch.setattr(nostr, "NOSTR_RELAYS", [a, b])
        parsed, err = await NostrClient.parse(f"nostr:{nostr.hex_to_npub(PUB)}")
    assert err is None and parsed["title"] == "Nostr: Ana <3"
    assert [e["title"] for e in parsed["entries"]] == ["segunda", "primera"]
    assert parsed["entries"][0]["source"] == "Nostr / Ana &lt;3"


async def test_relay_hostil_no_inyecta_nada(monkeypatch, rapido):
    falso_alterado = {**NOTAS[0], "content": "compra mi token"}
    falso_ajeno = firmar(SK_ATACANTE, 1, "estafa", pubkey=PUB)
    basura = ["no es json", json.dumps({"a": 1}), json.dumps(["EVENT", "otra-sub", NOTAS[1]])]
    async with relay([falso_alterado, falso_ajeno], crudo=basura) as mal, relay([NOTAS[0]]) as bien:
        monkeypatch.setattr(nostr, "NOSTR_RELAYS", [mal, bien])
        parsed, err = await NostrClient.parse(f"nostr:{nostr.hex_to_npub(PUB)}")
    assert err is None
    assert [e["title"] for e in parsed["entries"]] == ["primera"]


async def test_relay_mudo_y_caido_no_bloquean_al_sano(monkeypatch, rapido):
    async with relay(mudo=True) as mudo, relay(NOTAS) as bien:
        monkeypatch.setattr(nostr, "NOSTR_RELAYS", [mudo, "ws://127.0.0.1:1", bien])
        parsed, err = await NostrClient.parse(f"nostr:{nostr.hex_to_npub(PUB)}")
    assert err is None and len(parsed["entries"]) == 2


async def test_sin_relays_da_error_que_no_dispara_la_reparacion_waf(monkeypatch, rapido):
    monkeypatch.setattr(nostr, "NOSTR_RELAYS", ["ws://127.0.0.1:1"])
    parsed, err = await NostrClient.parse(f"nostr:{nostr.hex_to_npub(PUB)}")
    assert parsed is None and err
    assert not any(k in err for k in ("403", "429", "Cloudflare", "Timeout", "timed out"))


async def test_resolve_normaliza_y_pone_titulo(monkeypatch, rapido):
    async with relay([PERFIL]) as a:
        monkeypatch.setattr(nostr, "NOSTR_RELAYS", [a])
        url, titulo, err = await NostrClient.resolve(PUB)
        assert (url, titulo, err) == (f"nostr:{nostr.hex_to_npub(PUB)}", "Nostr: Ana <3", None)
    async with relay([]) as sin_perfil:
        monkeypatch.setattr(nostr, "NOSTR_RELAYS", [sin_perfil])
        url, titulo, err = await NostrClient.resolve(PUB)
        assert err is None and titulo.startswith("Nostr: npub1")   # sin perfil no es error


async def test_resolve_errores_claros(monkeypatch, rapido):
    monkeypatch.setattr(nostr, "NOSTR_RELAYS", ["ws://127.0.0.1:1"])
    assert (await NostrClient.resolve(PUB))[2]                      # ningún relay responde
    assert "no es válido" in (await NostrClient.resolve(NPUB[:-1] + "q"))[2]
    assert (await NostrClient.resolve("https://example.com"))[2]


# ------------------------------------------------------------------ ganchos en resolver / parser / monitor
async def test_resolver_y_parser_enrutan_nostr_sin_pasar_por_http(monkeypatch):
    from unittest.mock import AsyncMock
    from modules.rss.parser import RSSParser
    from modules.rss.resolver import RSSResolver

    monkeypatch.setattr(NostrClient, "resolve", AsyncMock(return_value=("nostr:x", "t", None)))
    monkeypatch.setattr(NostrClient, "parse", AsyncMock(return_value=({"title": "t", "entries": []}, None)))
    # Sin el gancho previo, el resolver convertía "npub1…" en https://npub1…
    assert (await RSSResolver.find_best_feed(NPUB))[0] == "nostr:x"
    NostrClient.resolve.assert_awaited_once_with(NPUB)
    assert (await RSSParser.parse(f"nostr:{NPUB}"))[1] is None
    NostrClient.parse.assert_awaited_once()


@pytest.mark.parametrize("url,repara", [(f"nostr:{NPUB}", False), ("https://example.com/feed", True)])
async def test_monitor_no_reresuelve_feeds_nostr_ante_error(monkeypatch, test_db, url, repara):
    from unittest.mock import AsyncMock, MagicMock
    import modules.rss.monitor as monitor
    from tests.test_monitor_dedup import ChatFalso

    monkeypatch.setattr(monitor, "db", test_db)
    chat = await test_db.ensure_chat(ChatFalso(id=-100888))
    feed_id = await test_db.execute(
        "INSERT INTO feeds(chat_id, url, url_original, titulo, estilo, intervalo_min, ultimo_check, activo, traducir) "
        "VALUES (?,?,?,?,?,?,?,?,?)", (chat["id"], url, None, "t", "social", 10, 0, 1, 0))
    feed = await test_db.fetchone(
        "SELECT feeds.*, chats.tg_chat_id as chat_tg_id, chats.activo as chat_activo "
        "FROM feeds JOIN chats ON feeds.chat_id = chats.id WHERE feeds.id = ?", (feed_id,))
    monkeypatch.setattr(monitor.RSSParser, "parse", AsyncMock(return_value=(None, "Timeout simulado")))
    reparar = AsyncMock(return_value=(None, None, "sin arreglo"))
    monkeypatch.setattr(monitor.RSSResolver, "find_best_feed", reparar)
    await monitor.RSSMonitor(bot=MagicMock())._procesar_feed(feed)
    assert reparar.await_count == (1 if repara else 0)
