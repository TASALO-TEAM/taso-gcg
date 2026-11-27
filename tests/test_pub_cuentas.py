"""Panel de cuentas de /pub: validadores, pantallas, flujo de texto y que la clave nunca se filtre."""

import time
from types import SimpleNamespace

import pytest

from core import secrets
from modules import pub
from modules.publisher import cuentas, hive, store
from modules.publisher.store import PubError

WIF = "5KfAkEwIfSecretoDePruebaQueNoEsReal"


def _datas(tec):
    return [b.callback_data for fila in tec.inline_keyboard for b in fila]


# ---------- validadores ----------
@pytest.mark.parametrize("t,esperado", [("@ErSuS93", "ersus93"), ("tasalo", "tasalo"), ("a.b-c9", "a.b-c9")])
def test_nombre_valido(t, esperado):
    assert cuentas.parsear_nombre(t) == esperado


@pytest.mark.parametrize("t", ["", "ab", "9abc", "con espacio", "x" * 17, "mal_guion", "@"])
def test_nombre_invalido(t):
    with pytest.raises(PubError):
        cuentas.parsear_nombre(t)


@pytest.mark.parametrize("t,esperado", [("hive-123456", "hive-123456"), ("https://peakd.com/c/hive-174695/trending", "hive-174695"),
                                        ("#HIVE-174695", "hive-174695"), ("-", "")])
def test_comunidad(t, esperado):
    assert cuentas.parsear_comunidad(t) == esperado


def test_comunidad_invalida():
    with pytest.raises(PubError, match="comunidad"):
        cuentas.parsear_comunidad("mi comunidad")


def test_tags():
    assert cuentas.parsear_tags("#TSPL, tasas  cuba;tspl") == ["tspl", "tasas", "cuba"]
    assert cuentas.parsear_tags("-") == []
    with pytest.raises(PubError, match="Demasiadas"):
        cuentas.parsear_tags(" ".join(f"t{i}" for i in range(9)))


def test_beneficiarios():
    assert cuentas.parsear_beneficiarios("tasalo:5 otra:2.5%") == [{"account": "tasalo", "weight": 500}, {"account": "otra", "weight": 250}]
    assert cuentas.parsear_beneficiarios("-") == []


@pytest.mark.parametrize("t,msg", [("tasalo", "cuenta:porcentaje"), ("tasalo:abc", "número"), ("tasalo:0", "entre"),
                                   ("tasalo:101", "entre"), ("tasalo:5 tasalo:5", "dos veces"),
                                   ("aaa:60 bbb:50", "100"), (" ".join(f"cu{i}x:1" for i in range(9)), "máximo")])
def test_beneficiarios_invalidos(t, msg):
    with pytest.raises(PubError, match=msg):
        cuentas.parsear_beneficiarios(t)


# ---------- pantallas ----------
CUENTA = {"id": 4, "red": "hive", "nombre": "ersus93", "activa": 1, "tiene_secreto": True,
          "params": {"comunidad": "hive-123456", "tags": ["tspl"], "beneficiarios": [{"account": "tasalo", "weight": 500}]}}


def test_pantalla_cuenta_no_muestra_la_clave_y_los_callbacks_son_validos():
    texto, tec = cuentas.pantalla_cuenta(CUENTA, [{"job": "Resumen TSPL", "tipo": "hive_blog", "activo": 1}])
    assert "guardada" in texto and "hive-123456" in texto and "tasalo 5%" in texto and "Resumen TSPL" in texto
    datas = _datas(tec)
    for esperado in ("pub:ce:4:k", "pub:ce:4:c", "pub:ce:4:t", "pub:ce:4:b", "pub:ca:4", "pub:cd:4", "pub:cl:4:w", "pub:cl:4:s", "pub:cl:4:b", "pub:cs"):
        assert esperado in datas
    assert all(len(d.encode()) <= 64 for d in datas)


def test_pantalla_cuenta_sin_clave_lo_dice():
    texto, _ = cuentas.pantalla_cuenta({**CUENTA, "tiene_secreto": False}, [])
    assert "falta" in texto


def test_pantalla_cuentas_avisa_si_falta_la_clave_maestra():
    texto, tec = cuentas.pantalla_cuentas([], clave_maestra=False)
    assert "PUBLISHER_MASTER_KEY" in texto and "pub:cn" in _datas(tec)


def test_html_escapado():
    texto, _ = cuentas.pantalla_cuenta({**CUENTA, "nombre": "<i>x"}, [])
    assert "<i>x" not in texto


def test_borrar_avisa_de_los_destinos_que_se_desactivan():
    texto, tec = cuentas.pantalla_borrar(CUENTA, [{"job": "Resumen TSPL", "tipo": "hive_blog"}])
    assert "Resumen TSPL" in texto and "pub:cdc:4" in _datas(tec)


# ---------- flujo con base de datos ----------
@pytest.fixture
async def s(test_db, monkeypatch):
    monkeypatch.setattr(store, "db", test_db)
    monkeypatch.setenv(secrets.ENV_ACTUAL, secrets.generar_clave())
    monkeypatch.delenv(secrets.ENV_ANTERIOR, raising=False)
    verificadas = []

    async def verificar(cuenta, wif):
        verificadas.append((cuenta, wif))
        if wif != WIF:
            raise hive.HiveError("esa clave no es la de posting de @" + cuenta)

    monkeypatch.setattr(hive, "verificar_clave", verificar)
    monkeypatch.setattr(pub, "SUDO_USERS", {1})
    return SimpleNamespace(verificadas=verificadas)


class Chat:
    def __init__(self):
        self.enviados = []

    async def send_message(self, texto, **kw):
        self.enviados.append(texto)


class Msg:
    def __init__(self, texto, borrable=True):
        self.text, self.borrado, self.chat, self._b = texto, False, Chat(), borrable

    async def delete(self):
        if not self._b:
            raise RuntimeError("no se puede")
        self.borrado = True


def _upd(msg, uid=1, tipo="private"):
    return SimpleNamespace(effective_message=msg, effective_user=SimpleNamespace(id=uid), effective_chat=SimpleNamespace(type=tipo))


def _ctx():
    return SimpleNamespace(user_data={})


async def _alta(ctx):
    """Recorre el alta completa y devuelve (id de cuenta, mensaje con la clave)."""
    await pub._despachar("cn", (), ctx)
    await pub._on_texto(_upd(Msg("@ErSuS93")), ctx)
    m = Msg(WIF)
    await pub._on_texto(_upd(m), ctx)
    cuenta = (await store.listar_cuentas("hive"))[0]
    return cuenta["id"], m


async def test_alta_completa_guarda_cifrada_y_borra_el_mensaje(s):
    ctx = _ctx()
    cid, m = await _alta(ctx)
    assert m.borrado
    assert s.verificadas == [("ersus93", WIF)]
    assert await store.obtener_secreto(cid) == WIF
    raw = await store.db.fetchone("SELECT secreto_cifrado FROM pub_cuentas WHERE id = ?", (cid,))
    assert WIF not in raw["secreto_cifrado"]
    assert (await store.get_cuenta(cid))["tiene_secreto"] is True
    assert cuentas.vigente(ctx.user_data) is None            # el flujo termina


async def test_la_clave_no_aparece_en_ningun_mensaje_del_bot(s):
    ctx = _ctx()
    await pub._despachar("cn", (), ctx)
    nombre, clave = Msg("ersus93"), Msg(WIF)
    await pub._on_texto(_upd(nombre), ctx)
    await pub._on_texto(_upd(clave), ctx)
    for m in (nombre, clave):
        assert all(WIF not in t for t in m.chat.enviados)
    assert len(clave.chat.enviados) == 1 and "guardada" in clave.chat.enviados[0]
    pantalla, _ = await pub._cuenta((await store.listar_cuentas())[0]["id"])
    assert WIF not in pantalla


async def test_clave_incorrecta_no_se_guarda_y_permite_reintentar(s):
    ctx = _ctx()
    await pub._despachar("cn", (), ctx)
    await pub._on_texto(_upd(Msg("ersus93")), ctx)
    mala = Msg("5KclaveEquivocada")
    await pub._on_texto(_upd(mala), ctx)
    assert mala.borrado                                      # se borra aunque sea incorrecta
    assert await store.listar_cuentas() == []
    assert "no es la de posting" in mala.chat.enviados[0] and "5KclaveEquivocada" not in mala.chat.enviados[0]
    assert cuentas.vigente(ctx.user_data)["paso"] == "clave"  # sigue esperando
    await pub._on_texto(_upd(Msg(WIF)), ctx)
    assert len(await store.listar_cuentas()) == 1


async def test_si_no_se_puede_borrar_el_mensaje_avisa(s):
    ctx = _ctx()
    await pub._despachar("cn", (), ctx)
    await pub._on_texto(_upd(Msg("ersus93")), ctx)
    m = Msg(WIF, borrable=False)
    await pub._on_texto(_upd(m), ctx)
    assert "bórralo" in m.chat.enviados[0] and WIF not in m.chat.enviados[0]


async def test_sin_clave_maestra_no_pide_la_clave(s, monkeypatch):
    monkeypatch.delenv(secrets.ENV_ACTUAL)
    ctx = _ctx()
    texto, _ = await pub._despachar("cn", (), ctx)
    assert "PUBLISHER_MASTER_KEY" in texto and cuentas.vigente(ctx.user_data) is None


@pytest.mark.parametrize("uid,tipo", [(2, "private"), (1, "group"), (1, "supergroup")])
async def test_ignora_a_quien_no_es_sudo_o_no_es_privado(s, uid, tipo):
    ctx = _ctx()
    cuentas.iniciar(ctx.user_data, paso="clave", nombre="ersus93")
    m = Msg(WIF)
    await pub._on_texto(_upd(m, uid=uid, tipo=tipo), ctx)
    assert not m.borrado and m.chat.enviados == [] and s.verificadas == []


async def test_sin_pregunta_abierta_no_hace_nada(s):
    m = Msg("hola")
    await pub._on_texto(_upd(m), _ctx())
    assert not m.borrado and m.chat.enviados == []


async def test_la_espera_caduca(s, monkeypatch):
    ctx = _ctx()
    await pub._despachar("cn", (), ctx)
    reloj = time.monotonic()
    monkeypatch.setattr(cuentas.time, "monotonic", lambda: reloj + cuentas.ESPERA_S + 1)
    m = Msg(WIF)
    await pub._on_texto(_upd(m), ctx)
    assert not m.borrado and s.verificadas == [] and ctx.user_data == {}


async def test_cancelar_limpia_el_estado(s):
    ctx = _ctx()
    await pub._despachar("cn", (), ctx)
    await pub._despachar("cx", (), ctx)
    assert cuentas.vigente(ctx.user_data) is None


async def test_editar_campos_y_borrar_con_guion(s):
    ctx = _ctx()
    cid, _ = await _alta(ctx)
    for campo, texto in (("c", "hive-123456"), ("t", "tspl tasas"), ("b", "tasalo:5")):
        await pub._despachar("ce", (cid, campo), ctx)
        m = Msg(texto)
        await pub._on_texto(_upd(m), ctx)
        assert "Guardado" in m.chat.enviados[0]
    assert (await store.get_cuenta(cid))["params"] == {"comunidad": "hive-123456", "tags": ["tspl", "tasas"],
                                                      "beneficiarios": [{"account": "tasalo", "weight": 500}]}
    await pub._despachar("ce", (cid, "b"), ctx)
    await pub._on_texto(_upd(Msg("-")), ctx)
    assert "beneficiarios" not in (await store.get_cuenta(cid))["params"]
    assert await store.obtener_secreto(cid) == WIF              # editar campos no toca la clave


async def test_dato_invalido_no_cambia_nada_y_sigue_preguntando(s):
    ctx = _ctx()
    cid, _ = await _alta(ctx)
    await pub._despachar("ce", (cid, "b"), ctx)
    m = Msg("tasalo:200")
    await pub._on_texto(_upd(m), ctx)
    assert "⚠️" in m.chat.enviados[0] and (await store.get_cuenta(cid))["params"] == {}
    assert cuentas.vigente(ctx.user_data)["paso"] == "campo"


async def test_cambiar_la_clave_conserva_los_ajustes(s):
    ctx = _ctx()
    cid, _ = await _alta(ctx)
    await store.editar_cuenta(cid, params={"comunidad": "hive-123456"})
    await pub._despachar("ce", (cid, "k"), ctx)
    await pub._on_texto(_upd(Msg(WIF)), ctx)
    assert (await store.get_cuenta(cid))["params"] == {"comunidad": "hive-123456"}
    assert len(await store.listar_cuentas()) == 1


async def test_enlazar_a_un_trabajo_sin_duplicar_y_borrar_desactiva(s):
    ctx = _ctx()
    cid, _ = await _alta(ctx)
    job = await store.crear_job("Resumen TSPL", "tspl")
    pantalla, tec = await pub._despachar("cl", (cid, "b"), ctx)
    assert f"pub:cj:{cid}:b:{job}" in _datas(tec)
    await pub._despachar("cj", (cid, "b", job), ctx)
    texto, _ = await pub._despachar("cj", (cid, "b", job), ctx)          # segundo intento
    assert "ya publica" in texto
    destinos = await store.listar_destinos(job)
    assert [(d["tipo"], d["cuenta_id"]) for d in destinos] == [("hive_blog", cid)]
    texto, _ = await pub._despachar("cd", (cid,), ctx)
    assert "Resumen TSPL" in texto
    await pub._despachar("cdc", (cid,), ctx)
    assert await store.listar_cuentas() == []
    d = (await store.listar_destinos(job))[0]
    assert d["cuenta_id"] is None and d["activo"] == 0


async def test_pausar_cuenta(s):
    ctx = _ctx()
    cid, _ = await _alta(ctx)
    await pub._despachar("ca", (cid,), ctx)
    assert (await store.get_cuenta(cid))["activa"] == 0


async def test_botones_viejos_o_de_cuentas_borradas_no_rompen(s):
    ctx = _ctx()
    texto, _ = await pub._despachar("c", (999,), ctx)
    assert "Cuentas de publicación" in texto
    texto, _ = await pub._despachar("ce", (999, "k"), ctx)
    assert "Cuentas de publicación" in texto
    cid, _ = await _alta(ctx)
    with pytest.raises(ValueError):
        await pub._despachar("ce", (cid, "z"), ctx)


async def test_el_trabajo_muestra_la_cuenta_del_destino(s):
    ctx = _ctx()
    cid, _ = await _alta(ctx)
    job = await store.crear_job("Resumen TSPL", "tspl")
    await pub._despachar("cj", (cid, "w", job), ctx)
    texto, _ = await pub._job(job)
    assert "hive_wave @ersus93" in texto


async def test_home_ofrece_cuentas():
    texto, tec = pub.pantalla_home([], prueba=True)
    assert "pub:cs" in _datas(tec)
