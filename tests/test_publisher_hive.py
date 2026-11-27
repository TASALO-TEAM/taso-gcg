"""Cliente Hive (claves, firma, nodos) y destinos hive_wave / hive_snap / hive_blog.

No se emite nada real: el nodo se simula. La firma se comprueba recuperando la clave pública
del resultado, que es lo que hace la cadena para autorizar la transacción.
"""

import hashlib
import json
from datetime import datetime, timedelta

import httpx
import pytest
from coincurve import PrivateKey, PublicKey

from modules.publisher import destinos_hive, hive
from modules.publisher.base import Contenido

CLAVE = bytes(range(1, 33))
B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"


def _b58e(b: bytes) -> str:
    n = int.from_bytes(b, "big")
    s = ""
    while n:
        n, r = divmod(n, 58)
        s = B58[r] + s
    return "1" * (len(b) - len(b.lstrip(b"\x00"))) + s


def _wif(clave: bytes = CLAVE) -> str:
    raw = b"\x80" + clave
    return _b58e(raw + hive._sha2(raw)[:4])


def _stm(clave: bytes = CLAVE) -> str:
    return "STM" + _b58e(hive.pub_de_clave(clave) + b"\x00\x00\x00\x00")   # el checksum no se usa al leer


def test_chain_id_es_el_de_la_red_principal():
    # Valor fijo, no derivado del código: un error aquí firma para otra red y la cadena rechaza todo.
    assert hive.CHAIN_ID.hex() == "beeab0de" + "00" * 28


# ---------- claves ----------
def test_wif_ida_y_vuelta():
    assert hive.wif_a_clave(_wif()) == CLAVE
    assert hive.wif_a_clave("  " + _wif() + "\n") == CLAVE      # tolera espacios al pegar


@pytest.mark.parametrize("malo", ["", "5abc", "no es una clave", "0OIl" * 13])
def test_wif_invalida_no_filtra_la_clave(malo):
    with pytest.raises(hive.HiveError) as e:
        hive.wif_a_clave(malo)
    assert malo.strip() == "" or malo not in str(e.value)


def test_wif_con_checksum_roto():
    w = _wif()
    roto = w[:-1] + ("2" if w[-1] != "2" else "3")
    with pytest.raises(hive.HiveError):
        hive.wif_a_clave(roto)


def test_wif_de_otra_red_se_rechaza():
    raw = b"\x81" + CLAVE                                       # prefijo distinto de 0x80
    with pytest.raises(hive.HiveError):
        hive.wif_a_clave(_b58e(raw + hive._sha2(raw)[:4]))


def test_pub_stm_coincide_con_la_clave():
    assert hive._pub_stm(_stm()) == hive.pub_de_clave(CLAVE)


# ---------- firma ----------
def _recuperar(sig_hex: str, digest: bytes) -> bytes:
    c = bytes.fromhex(sig_hex)
    rsv = c[1:] + bytes([c[0] - 31])
    return PublicKey.from_signature_and_message(rsv, digest, hasher=None).format(compressed=True)


def test_firma_recupera_la_clave_publica():
    firmadas = 0
    for i in range(40):                                        # ~mitad son no canónicas: devuelven None
        digest = hashlib.sha256(bytes([i])).digest()
        sig = hive.firmar(digest, CLAVE)
        if sig is None:
            continue
        firmadas += 1
        assert len(bytes.fromhex(sig)) == 65
        assert 31 <= bytes.fromhex(sig)[0] <= 34
        assert _recuperar(sig, digest) == hive.pub_de_clave(CLAVE)
    assert firmadas >= 5


def test_canonica_reglas():
    base = bytearray(65)
    base[1], base[2], base[33], base[34] = 0x40, 0x01, 0x40, 0x01
    assert hive._canonica(bytes(base))
    for pos in (1, 33):                                        # bit alto en r o s
        malo = bytearray(base)
        malo[pos] = 0x80
        assert not hive._canonica(bytes(malo))
    cero = bytearray(base)                                     # r con relleno innecesario
    cero[1], cero[2] = 0x00, 0x7F
    assert not hive._canonica(bytes(cero))


# ---------- operaciones ----------
def test_opciones_ordena_y_valida_beneficiarios():
    op = hive.op_opciones("ersus93", "p", [{"account": "zeta", "weight": 500}, {"account": "alfa", "weight": 250}])
    assert op[0] == "comment_options"
    assert op[1]["extensions"] == [[0, {"beneficiaries": [{"account": "alfa", "weight": 250}, {"account": "zeta", "weight": 500}]}]]
    assert hive.op_opciones("a", "p", [])[1]["extensions"] == []
    with pytest.raises(hive.HiveError, match="100"):
        hive.op_opciones("a", "p", [{"account": "x", "weight": 6000}, {"account": "y", "weight": 5000}])


def test_comentario_y_slug():
    op = hive.op_comentario("a", "p", "hola", "bob", "post", meta={"tags": ["x"]})
    assert op[1]["parent_author"] == "bob" and op[1]["title"] == ""
    assert json.loads(op[1]["json_metadata"]) == {"tags": ["x"]}
    assert hive.slug("Resumen TSPL: ¡hoy!") == "resumen-tspl-hoy"
    assert hive.slug("***") == "post"
    assert len(hive.slug("a" * 200)) <= 60


# ---------- transmitir (nodo simulado) ----------
PROPS = {"head_block_id": "00" * 4 + "11223344" + "00" * 12, "head_block_number": 70001, "time": "2026-11-27T02:43:12"}


@pytest.fixture
def nodo(monkeypatch):
    """Simula el nodo: serializa como `expiración + 00` (cambia el digest al cambiar la expiración)."""
    emitidas = []

    async def rpc(metodo, params, nodos=hive.NODOS):
        if metodo == "condenser_api.get_dynamic_global_properties":
            return PROPS
        if metodo == "condenser_api.get_transaction_hex":
            return (params[0]["expiration"].encode() + b"\x00").hex()
        if metodo == "condenser_api.broadcast_transaction_synchronous":
            emitidas.append(params[0])
            return {"id": "abc123"}
        raise AssertionError(metodo)

    monkeypatch.setattr(hive, "_rpc", rpc)
    return emitidas


async def test_transmitir_firma_con_el_digest_de_la_cadena(nodo):
    tid = await hive.transmitir([hive.op_comentario("a", "p", "hola")], _wif())
    assert tid == "abc123"
    tx = nodo[0]
    assert tx["ref_block_num"] == 70001 & 0xFFFF
    assert tx["ref_block_prefix"] == int.from_bytes(bytes.fromhex("11223344"), "little")
    digest = hashlib.sha256(hive.CHAIN_ID + tx["expiration"].encode()).digest()
    assert _recuperar(tx["signatures"][0], digest) == hive.pub_de_clave(CLAVE)
    espera = datetime.fromisoformat(PROPS["time"]) + timedelta(seconds=hive.EXPIRA_S)
    assert datetime.fromisoformat(tx["expiration"]) >= espera


async def test_transmitir_reintenta_si_la_firma_no_es_canonica(nodo, monkeypatch):
    real, llamadas = hive.firmar, []

    def firmar(digest, clave):
        llamadas.append(digest)
        return None if len(llamadas) < 3 else real(digest, clave)

    monkeypatch.setattr(hive, "firmar", firmar)
    monkeypatch.setattr(hive, "_canonica", lambda c: True)
    await hive.transmitir([hive.op_comentario("a", "p", "hola")], _wif())
    assert len(llamadas) == 3 and len(set(llamadas)) == 3       # cada intento firma un digest distinto
    base = datetime.fromisoformat(PROPS["time"]) + timedelta(seconds=hive.EXPIRA_S)
    assert datetime.fromisoformat(nodo[0]["expiration"]) == base + timedelta(seconds=2)


async def test_transmitir_sin_firma_canonica_no_emite(nodo, monkeypatch):
    monkeypatch.setattr(hive, "firmar", lambda d, c: None)
    with pytest.raises(hive.HiveError, match="canónica"):
        await hive.transmitir([hive.op_comentario("a", "p", "hola")], _wif())
    assert nodo == []


async def test_transmitir_rechaza_serializacion_con_firmas(monkeypatch):
    async def rpc(metodo, params, nodos=hive.NODOS):
        return PROPS if "global" in metodo else b"abc\x01".hex()
    monkeypatch.setattr(hive, "_rpc", rpc)
    with pytest.raises(hive.HiveError, match="inesperadas"):
        await hive.transmitir([hive.op_comentario("a", "p", "x")], _wif())


async def test_transmitir_con_clave_mala_no_toca_la_red(monkeypatch):
    async def rpc(*a, **k):
        raise AssertionError("no debe llamar al nodo")
    monkeypatch.setattr(hive, "_rpc", rpc)
    with pytest.raises(hive.HiveError):
        await hive.transmitir([hive.op_comentario("a", "p", "x")], "no-es-wif")


# ---------- verificar_clave ----------
def _cuenta(*stm):
    return [{"posting": {"key_auths": [[k, 1] for k in stm]}}]


async def test_verificar_clave(monkeypatch):
    res = {"v": _cuenta(_stm())}

    async def rpc(metodo, params, nodos=hive.NODOS):
        return res["v"]

    monkeypatch.setattr(hive, "_rpc", rpc)
    await hive.verificar_clave("ersus93", _wif())                      # no lanza
    with pytest.raises(hive.HiveError, match="no es la de posting"):
        await hive.verificar_clave("ersus93", _wif(bytes(range(2, 34))))
    res["v"] = []
    with pytest.raises(hive.HiveError, match="no existe"):
        await hive.verificar_clave("nadie", _wif())


# ---------- _rpc ----------
def _cliente(monkeypatch, handler):
    real = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(handler), **kw))


async def test_rpc_salta_al_siguiente_nodo_si_uno_cae(monkeypatch):
    def handler(req):
        if req.url.host == "a.test":
            raise httpx.ConnectError("caído")
        return httpx.Response(200, json={"result": [1]})

    _cliente(monkeypatch, handler)
    assert await hive._rpc("m", [], nodos=("https://a.test", "https://b.test")) == [1]


async def test_rpc_error_de_protocolo_no_prueba_otro_nodo(monkeypatch):
    vistos = []

    def handler(req):
        vistos.append(req.url.host)
        return httpx.Response(200, json={"error": {"message": "missing posting authority"}})

    _cliente(monkeypatch, handler)
    with pytest.raises(hive.HiveError, match="posting authority"):
        await hive._rpc("m", [], nodos=("https://a.test", "https://b.test"))
    assert vistos == ["a.test"]


async def test_rpc_todos_caidos(monkeypatch):
    def handler(req):
        raise httpx.ConnectError("caído")

    _cliente(monkeypatch, handler)
    with pytest.raises(hive.HiveError, match="ningún nodo"):
        await hive._rpc("m", [], nodos=("https://a.test", "https://b.test"))


async def test_contenedor_vigente(monkeypatch):
    async def rpc(metodo, params, nodos=hive.NODOS):
        assert params["account"] == "ecency.waves"
        return [{"author": "ecency.waves", "permlink": "waves-20261126g2144u"}]

    monkeypatch.setattr(hive, "_rpc", rpc)
    assert await hive.contenedor_vigente("ecency.waves") == {"author": "ecency.waves", "permlink": "waves-20261126g2144u"}
    monkeypatch.setattr(hive, "_rpc", lambda *a, **k: _vacio())
    with pytest.raises(hive.HiveError, match="contenedor"):
        await hive.contenedor_vigente("ecency.waves")


async def _vacio():
    return []


# ---------- destinos ----------
CUENTA = {"nombre": "ersus93", "params": {"comunidad": "hive-123456", "tags": ["cuba"],
                                          "beneficiarios": [{"account": "tasalo", "weight": 500}]}}
CONT = Contenido(titulo="TSPL 27/11", cuerpo_md="# Blog\n\ncuerpo largo", texto_corto="Resumen corto",
                 tags=("tspl", "tasas"))


@pytest.fixture
def cadena(monkeypatch):
    enviadas = []

    async def contenedor(cuenta):
        return {"author": cuenta, "permlink": f"{cuenta}-contenedor"}

    async def transmitir(ops, wif):
        enviadas.append((ops, wif))
        return "tx1"

    monkeypatch.setattr(hive, "contenedor_vigente", contenedor)
    monkeypatch.setattr(hive, "transmitir", transmitir)
    return enviadas


@pytest.mark.parametrize("fn,contenedor,tag", [(destinos_hive.destino_wave, "ecency.waves", "waves"),
                                               (destinos_hive.destino_snap, "peak.snaps", "snaps")])
async def test_microblog_responde_al_contenedor(cadena, fn, contenedor, tag):
    r = await fn(CONT, {"params": {}}, CUENTA, "WIF", False)
    assert r.ok and r.url.startswith("https://peakd.com/@ersus93/re-")
    ops, wif = cadena[0]
    assert wif == "WIF" and len(ops) == 1                     # sin comment_options: la cadena lo rechaza en waves
    c = ops[0][1]
    assert (c["parent_author"], c["parent_permlink"]) == (contenedor, f"{contenedor}-contenedor")
    assert c["body"] == "Resumen corto" and c["title"] == ""
    tags = json.loads(c["json_metadata"])["tags"]
    assert tags[0] == tag and {"tspl", "tasas", "cuba"} <= set(tags)


async def test_microblog_recorta_y_respeta_el_tope(cadena):
    largo = Contenido(titulo="t", cuerpo_md="c", texto_corto="x" * 500)
    await destinos_hive.destino_wave(largo, {"params": {"max_chars": 100}}, CUENTA, "WIF", False)
    cuerpo = cadena[0][0][0][1]["body"]
    assert len(cuerpo) == 100 and cuerpo.endswith("…")
    await destinos_hive.destino_wave(largo, {"params": {}}, CUENTA, "WIF", False)
    assert len(cadena[1][0][0][1]["body"]) == 500             # sin tope configurado no se toca


async def test_simulacion_no_toca_la_cadena(cadena):
    for fn in (destinos_hive.destino_wave, destinos_hive.destino_snap, destinos_hive.destino_blog):
        r = await fn(CONT, {"params": {}}, CUENTA, None, True)
        assert r.ok and r.simulado
    assert cadena == []


async def test_publicar_sin_clave_falla_claro(cadena):
    for fn in (destinos_hive.destino_wave, destinos_hive.destino_blog):
        with pytest.raises(RuntimeError, match="clave de posting"):
            await fn(CONT, {"params": {}}, CUENTA, None, False)
    assert cadena == []


async def test_destino_sin_cuenta(cadena):
    with pytest.raises(ValueError, match="cuenta"):
        await destinos_hive.destino_wave(CONT, {"params": {}}, None, "WIF", False)


async def test_blog_es_post_raiz_con_comunidad_y_beneficiarios(cadena):
    r = await destinos_hive.destino_blog(CONT, {"params": {}}, CUENTA, "WIF", False)
    assert r.ok
    ops, _ = cadena[0]
    c, o = ops[0][1], ops[1][1]
    assert ops[0][0] == "comment" and ops[1][0] == "comment_options"
    assert (c["parent_author"], c["parent_permlink"]) == ("", "hive-123456")
    assert c["title"] == "TSPL 27/11" and c["body"] == "# Blog\n\ncuerpo largo"
    assert json.loads(c["json_metadata"])["tags"][0] == "hive-123456"
    assert o["permlink"] == c["permlink"] and o["extensions"][0][1]["beneficiaries"] == [{"account": "tasalo", "weight": 500}]


async def test_blog_los_params_del_destino_pisan_los_de_la_cuenta(cadena):
    d = {"params": {"comunidad": "hive-999999", "beneficiarios": []}}
    await destinos_hive.destino_blog(CONT, d, CUENTA, "WIF", False)
    ops, _ = cadena[0]
    assert ops[0][1]["parent_permlink"] == "hive-999999"
    assert ops[1][1]["extensions"] == []


async def test_blog_valida_contenido_y_categoria(cadena):
    sin_cuerpo = Contenido(titulo="", cuerpo_md="", texto_corto="solo microblog")
    with pytest.raises(ValueError, match="título y cuerpo"):
        await destinos_hive.destino_blog(sin_cuerpo, {"params": {}}, CUENTA, "WIF", False)
    sin_categoria = Contenido(titulo="t", cuerpo_md="c", texto_corto="x")
    with pytest.raises(ValueError, match="comunidad"):
        await destinos_hive.destino_blog(sin_categoria, {"params": {}}, {"nombre": "a", "params": {}}, "WIF", False)
    assert cadena == []


def test_tags_sin_duplicados_y_con_tope():
    t = destinos_hive._tags(("waves",), ("#Waves", "TSPL"), [f"t{i}" for i in range(30)])
    assert t[0] == "waves" and t.count("waves") == 1 and "tspl" in t
    assert len(t) == destinos_hive.MAX_TAGS


def test_los_destinos_hive_quedan_registrados():
    from modules.publisher.base import DESTINOS
    assert {"hive_wave", "hive_snap", "hive_blog"} <= set(DESTINOS)
