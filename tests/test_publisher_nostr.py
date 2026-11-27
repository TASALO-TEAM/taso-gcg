"""Publicar en Nostr: clave, evento firmado, relays falsos locales, destino y alta de cuenta (nsec)."""

import json
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest
from coincurve import PrivateKey
from websockets.asyncio.server import serve

from core import secrets
from modules import pub
from modules.publisher import cuentas, destinos_nostr, nostr, store
from modules.publisher.base import Contenido, DESTINOS
from modules.rss import nostr as lectura

SK = bytes.fromhex("11" * 32)
NSEC = lectura.bech32_encode("nsec", SK)
PUB = PrivateKey(SK).public_key.format()[1:].hex()
C = Contenido("t", "# t\ncuerpo", "hola mundo", tags=("TSPL", "tasas"))


@pytest.fixture(autouse=True)
def rapido(monkeypatch):
    monkeypatch.setattr(nostr, "TOTAL_TIMEOUT", 0.5)
    monkeypatch.setattr(nostr, "OPEN_TIMEOUT", 0.5)


@asynccontextmanager
async def relay(respuesta="ok", recibidos=None):
    async def handler(ws):
        msg = json.loads(await ws.recv())
        if recibidos is not None:
            recibidos.append(msg)
        if respuesta == "mudo":
            await ws.wait_closed()
            return
        ok = respuesta == "ok"
        await ws.send(json.dumps(["OK", msg[1]["id"], ok, "" if ok else "blocked: spam"]))
        async for _ in ws:
            pass

    async with serve(handler, "127.0.0.1", 0) as srv:
        yield f"ws://127.0.0.1:{srv.sockets[0].getsockname()[1]}"


# ---------- clave ----------
def test_parsear_clave_acepta_nsec_y_hex():
    assert nostr.parsear_clave(NSEC) == SK
    assert nostr.parsear_clave(f"  {SK.hex()}\n") == SK
    assert nostr.npub_de(SK) == lectura.hex_to_npub(PUB)


@pytest.mark.parametrize("t", ["", "hola", "nsec1abc", "ab" * 31, "zz" * 32, lectura.hex_to_npub(PUB), "00" * 32])
def test_parsear_clave_rechaza_sin_filtrar_el_texto(t):
    with pytest.raises(nostr.NostrError) as e:
        nostr.parsear_clave(t)
    assert t.strip() == "" or t.strip() not in str(e.value)


def test_npub_pegada_explica_que_hace_falta_la_privada():
    with pytest.raises(nostr.NostrError, match="privada"):
        nostr.parsear_clave(lectura.hex_to_npub(PUB))


# ---------- evento ----------
def test_evento_firmado_verifica_y_lleva_tags():
    ev = nostr.evento(SK, "hola", [["t", "tspl"]], t=1_700_000_000)
    assert ev["pubkey"] == PUB and ev["kind"] == 1 and ev["created_at"] == 1_700_000_000
    assert lectura.verify_event(ev, PUB)
    assert not lectura.verify_event({**ev, "content": "otro"}, PUB)


def test_nota_url():
    ev = nostr.evento(SK, "x")
    hrp, raw = lectura.bech32_decode(nostr.nota_url(ev["id"]).rsplit("/", 1)[1])
    assert hrp == "note" and raw.hex() == ev["id"]


# ---------- relays ----------
async def test_publicar_cuenta_aceptados_y_rechazados():
    ev = nostr.evento(SK, "hola")
    recibidos = []
    async with relay("ok", recibidos) as a, relay("no") as b, relay("mudo") as c:
        ok, mal = await nostr.publicar(ev, [a, b, c, "ws://127.0.0.1:1"])
    assert ok == [a] and set(mal) == {b, c, "ws://127.0.0.1:1"}
    assert recibidos[0] == ["EVENT", ev]


async def test_publicar_ignora_ok_de_otro_evento():
    async def handler(ws):
        await ws.recv()
        await ws.send(json.dumps(["OK", "f" * 64, True, ""]))
        await ws.wait_closed()

    async with serve(handler, "127.0.0.1", 0) as srv:
        url = f"ws://127.0.0.1:{srv.sockets[0].getsockname()[1]}"
        ok, mal = await nostr.publicar(nostr.evento(SK, "x"), [url])
    assert ok == [] and mal == [url]


# ---------- destino ----------
CUENTA = {"id": 1, "nombre": lectura.hex_to_npub(PUB), "params": {}}


def test_destino_registrado():
    assert "nostr" in DESTINOS


async def test_simular_no_conecta(monkeypatch):
    async def boom(*a, **k):
        raise AssertionError("no debe conectar")

    monkeypatch.setattr(nostr, "publicar", boom)
    r = await destinos_nostr.destino_nostr(C, {"params": {}}, CUENTA, None, True)
    assert r.ok and r.simulado


async def test_publica_en_relays_de_la_cuenta_y_devuelve_enlace():
    recibidos = []
    async with relay("ok", recibidos) as a:
        r = await destinos_nostr.destino_nostr(C, {"params": {}}, {**CUENTA, "params": {"relays": [a]}}, NSEC, False)
    ev = recibidos[0][1]
    assert r.ok and r.url.startswith("https://njump.me/note1")
    assert ev["content"] == "hola mundo" and ["t", "tspl"] in ev["tags"] and ["t", "tasas"] in ev["tags"]
    assert lectura.verify_event(ev, PUB)


async def test_params_del_destino_mandan_y_max_chars_recorta():
    recibidos = []
    async with relay("ok", recibidos) as a, relay("ok") as b:
        await destinos_nostr.destino_nostr(C, {"params": {"relays": [a], "max_chars": 5}}, {**CUENTA, "params": {"relays": [b]}}, NSEC, False)
    assert recibidos and recibidos[0][1]["content"] == "hola…"


async def test_sin_clave_o_sin_cuenta_falla():
    with pytest.raises(RuntimeError, match="clave"):
        await destinos_nostr.destino_nostr(C, {"params": {}}, CUENTA, None, False)
    with pytest.raises(ValueError, match="cuenta"):
        await destinos_nostr.destino_nostr(C, {"params": {}}, None, NSEC, True)


async def test_si_ningun_relay_acepta_falla_sin_filtrar_la_clave():
    async with relay("no") as a:
        with pytest.raises(RuntimeError) as e:
            await destinos_nostr.destino_nostr(C, {"params": {}}, {**CUENTA, "params": {"relays": [a]}}, NSEC, False)
    assert NSEC not in str(e.value) and SK.hex() not in str(e.value)


async def test_usa_los_relays_por_defecto(monkeypatch):
    async with relay("ok") as a:
        monkeypatch.setattr(destinos_nostr, "NOSTR_RELAYS", [a])
        r = await destinos_nostr.destino_nostr(C, {"params": {}}, CUENTA, NSEC, False)
    assert r.ok


# ---------- relays editables ----------
def test_parsear_relays():
    assert cuentas.parsear_relays("wss://a.io wss://B.io/, wss://a.io") == ["wss://a.io", "wss://b.io"]
    assert cuentas.parsear_relays("-") == []


@pytest.mark.parametrize("t", ["ws://a.io", "a.io", "https://a.io", "wss://", " ".join(f"wss://r{i}.io" for i in range(7))])
def test_parsear_relays_invalidos(t):
    with pytest.raises(store.PubError):
        cuentas.parsear_relays(t)


# ---------- alta de cuenta (panel) ----------
@pytest.fixture
async def s(test_db, monkeypatch):
    monkeypatch.setattr(store, "db", test_db)
    monkeypatch.setenv(secrets.ENV_ACTUAL, secrets.generar_clave())
    monkeypatch.delenv(secrets.ENV_ANTERIOR, raising=False)
    monkeypatch.setattr(pub, "SUDO_USERS", {1})


class Chat:
    def __init__(self):
        self.enviados = []

    async def send_message(self, texto, **kw):
        self.enviados.append(texto)


class Msg:
    def __init__(self, texto):
        self.text, self.borrado, self.chat = texto, False, Chat()

    async def delete(self):
        self.borrado = True


def _upd(msg):
    return SimpleNamespace(effective_message=msg, effective_user=SimpleNamespace(id=1), effective_chat=SimpleNamespace(type="private"))


async def test_alta_nostr_guarda_cifrada_borra_mensaje_y_usa_el_npub(s):
    ctx = SimpleNamespace(user_data={})
    await pub._despachar("cn", ("n",), ctx)
    m = Msg(NSEC)
    await pub._on_texto(_upd(m), ctx)
    c = (await store.listar_cuentas("nostr"))[0]
    assert m.borrado and c["nombre"] == lectura.hex_to_npub(PUB)
    assert await store.obtener_secreto(c["id"]) == NSEC
    raw = await store.db.fetchone("SELECT secreto_cifrado FROM pub_cuentas WHERE id = ?", (c["id"],))
    assert NSEC not in raw["secreto_cifrado"]
    assert all(NSEC not in t and SK.hex() not in t for t in m.chat.enviados)


async def test_alta_acepta_hex_y_guarda_nsec_normalizada(s):
    ctx = SimpleNamespace(user_data={})
    await pub._despachar("cn", ("n",), ctx)
    await pub._on_texto(_upd(Msg(SK.hex())), ctx)
    c = (await store.listar_cuentas("nostr"))[0]
    assert await store.obtener_secreto(c["id"]) == NSEC


async def test_clave_mala_no_guarda_y_no_se_repite(s):
    ctx = SimpleNamespace(user_data={})
    await pub._despachar("cn", ("n",), ctx)
    m = Msg("nsec1" + "q" * 58)
    await pub._on_texto(_upd(m), ctx)
    assert await store.listar_cuentas("nostr") == []
    assert all(m.text not in t for t in m.chat.enviados) and m.borrado
    assert cuentas.vigente(ctx.user_data) is not None            # puede reintentar


async def test_cambiar_clave_exige_la_misma_identidad(s):
    cid = await store.guardar_cuenta("nostr", lectura.hex_to_npub(PUB), NSEC)
    ctx = SimpleNamespace(user_data={})
    await pub._despachar("ce", (str(cid), "k"), ctx)
    otra = Msg("22" * 32)
    await pub._on_texto(_upd(otra), ctx)
    assert await store.obtener_secreto(cid) == NSEC                # no cambió
    assert otra.borrado


async def test_editar_relays_de_la_cuenta(s):
    cid = await store.guardar_cuenta("nostr", lectura.hex_to_npub(PUB), NSEC)
    ctx = SimpleNamespace(user_data={})
    await pub._despachar("ce", (str(cid), "r"), ctx)
    await pub._on_texto(_upd(Msg("wss://nos.lol wss://relay.primal.net")), ctx)
    assert (await store.get_cuenta(cid))["params"]["relays"] == ["wss://nos.lol", "wss://relay.primal.net"]


async def test_enlazar_nostr_solo_en_cuentas_nostr(s):
    cid = await store.guardar_cuenta("nostr", lectura.hex_to_npub(PUB), NSEC)
    hid = await store.guardar_cuenta("hive", "ersus93", "5Kxx")
    jid = await store.crear_job("TSPL", "tspl")
    await pub._despachar("cj", (str(cid), "n", str(jid)), SimpleNamespace(user_data={}))
    assert [d["tipo"] for d in await store.listar_destinos(jid)] == ["nostr"]
    with pytest.raises(ValueError):
        await pub._despachar("cj", (str(hid), "n", str(jid)), SimpleNamespace(user_data={}))


def test_pantalla_cuenta_nostr_muestra_npub_corto_y_sus_botones():
    c = {"id": 7, "red": "nostr", "nombre": lectura.hex_to_npub(PUB), "activa": 1, "tiene_secreto": True, "params": {"relays": ["wss://nos.lol"]}}
    texto, tec = cuentas.pantalla_cuenta(c, [])
    datas = [b.callback_data for f in tec.inline_keyboard for b in f]
    assert c["nombre"] not in texto and "wss://nos.lol" in texto
    assert {"pub:ce:7:k", "pub:ce:7:r", "pub:cl:7:n"} <= set(datas)
    assert "pub:ce:7:c" not in datas and "pub:cl:7:w" not in datas
    assert all(len(d.encode()) <= 64 for d in datas)


def test_lista_de_cuentas_ofrece_nostr_y_acorta_el_npub():
    c = {"id": 7, "red": "nostr", "nombre": lectura.hex_to_npub(PUB), "activa": 1, "tiene_secreto": True, "params": {}}
    texto, tec = cuentas.pantalla_cuentas([c], True)
    assert "pub:cn:n" in [b.callback_data for f in tec.inline_keyboard for b in f] and c["nombre"] not in texto
