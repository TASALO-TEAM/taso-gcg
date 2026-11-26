import base64
import sqlite3

import pytest

from core import secrets
from modules.publisher import store
from modules.publisher.store import PubError


@pytest.fixture
def clave(monkeypatch):
    k = secrets.generar_clave()
    monkeypatch.setenv(secrets.ENV_ACTUAL, k)
    monkeypatch.delenv(secrets.ENV_ANTERIOR, raising=False)
    return k


@pytest.fixture
async def s(test_db, monkeypatch, clave):
    monkeypatch.setattr(store, "db", test_db)
    return store


# ---------- cifrado ----------
def test_cifrar_descifrar_ida_y_vuelta(clave):
    t = secrets.cifrar("hive:ersus93", "5Kposting")
    assert "5Kposting" not in t and t.startswith("v1.")
    assert secrets.descifrar("hive:ersus93", t) == "5Kposting"


def test_cifrado_no_determinista(clave):
    assert secrets.cifrar("a", "x") != secrets.cifrar("a", "x")


def test_secreto_movido_a_otra_fila_no_descifra(clave):
    t = secrets.cifrar("hive:ersus93", "5Kposting")
    with pytest.raises(secrets.SecretoError):
        secrets.descifrar("hive:otra", t)


def test_manipulado_no_descifra(clave):
    t = secrets.cifrar("n", "valor")
    raw = bytearray(base64.urlsafe_b64decode(t[3:] + "=="))
    raw[-1] ^= 1
    malo = "v1." + base64.urlsafe_b64encode(bytes(raw)).decode()
    with pytest.raises(secrets.SecretoError):
        secrets.descifrar("n", malo)


def test_sin_clave_maestra_no_guarda(monkeypatch):
    monkeypatch.delenv(secrets.ENV_ACTUAL, raising=False)
    assert not secrets.disponible()
    with pytest.raises(secrets.SecretoError):
        secrets.cifrar("n", "v")


def test_clave_maestra_invalida(monkeypatch):
    monkeypatch.setenv(secrets.ENV_ACTUAL, "corta")
    with pytest.raises(secrets.SecretoError):
        secrets.cifrar("n", "v")


def test_rotacion_de_clave(monkeypatch, clave):
    t = secrets.cifrar("n", "valor")
    nueva = secrets.generar_clave()
    monkeypatch.setenv(secrets.ENV_ACTUAL, nueva)
    with pytest.raises(secrets.SecretoError):
        secrets.descifrar("n", t)                       # sin la anterior, no
    monkeypatch.setenv(secrets.ENV_ANTERIOR, clave)
    assert secrets.descifrar("n", t) == "valor"          # con la anterior, sí
    t2 = secrets.recifrar("n", t)
    monkeypatch.delenv(secrets.ENV_ANTERIOR)
    assert secrets.descifrar("n", t2) == "valor"         # ya con la actual sola


def test_enmascarar_nunca_devuelve_completo():
    assert secrets.enmascarar("5Kabcdefghij") == "…ghij"
    assert secrets.enmascarar("corto") == "…"


# ---------- cuentas ----------
async def test_secreto_se_guarda_cifrado_en_la_db(s, test_db):
    cid = await s.guardar_cuenta("hive", "@ersus93", "5Kposting", {"comunidad": "hive-123"})
    crudo = await test_db.fetchone("SELECT secreto_cifrado FROM pub_cuentas WHERE id = ?", (cid,))
    assert "5Kposting" not in crudo["secreto_cifrado"]
    assert await s.obtener_secreto(cid) == "5Kposting"


async def test_get_cuenta_nunca_expone_el_secreto(s):
    cid = await s.guardar_cuenta("hive", "ersus93", "5Kposting")
    c = await s.get_cuenta(cid)
    assert c["tiene_secreto"] is True and "secreto_cifrado" not in c
    assert "5Kposting" not in repr(await s.listar_cuentas())


async def test_editar_cuenta_conserva_secreto_si_no_se_envia(s):
    cid = await s.guardar_cuenta("hive", "ersus93", "5Kposting", {"tags": ["a"]})
    assert await s.guardar_cuenta("hive", "ersus93", None, {"tags": ["b"]}) == cid
    assert (await s.get_cuenta(cid))["params"] == {"tags": ["b"]}
    assert await s.obtener_secreto(cid) == "5Kposting"


async def test_guardar_cuenta_sin_clave_maestra_falla_y_no_guarda(s, monkeypatch):
    monkeypatch.delenv(secrets.ENV_ACTUAL)
    with pytest.raises(secrets.SecretoError):
        await s.guardar_cuenta("hive", "ersus93", "5Kposting")
    assert await s.listar_cuentas() == []


async def test_secreto_copiado_a_otra_cuenta_no_funciona(s, test_db):
    a = await s.guardar_cuenta("hive", "cuenta_a", "5Ka")
    b = await s.guardar_cuenta("hive", "cuenta_b", "5Kb")
    fila = await test_db.fetchone("SELECT secreto_cifrado FROM pub_cuentas WHERE id = ?", (a,))
    await test_db.execute("UPDATE pub_cuentas SET secreto_cifrado = ? WHERE id = ?", (fila["secreto_cifrado"], b))
    with pytest.raises(secrets.SecretoError):
        await s.obtener_secreto(b)


async def test_borrar_cuenta_desactiva_destinos(s):
    j = await s.crear_job("año", "year")
    c = await s.guardar_cuenta("nostr", "tasalo", "nsec1x")
    d = await s.agregar_destino(j, "nostr", c)
    await s.borrar_cuenta(c)
    f = (await s.listar_destinos(j))[0]
    assert f["id"] == d and f["cuenta_id"] is None and f["activo"] == 0


async def test_red_invalida(s):
    with pytest.raises(PubError):
        await s.guardar_cuenta("mastodon", "x", "y")


# ---------- jobs y destinos ----------
async def test_crear_y_editar_job_valida(s):
    j = await s.crear_job("tspl blog", "tspl", 8, 45)
    await s.editar_job(j, hora=9, minuto=0, dias="0,2,4")
    job = await s.get_job(j)
    assert (job["hora"], job["minuto"], job["dias"]) == (9, 0, "0,2,4")
    for malo in ({"hora": 24}, {"minuto": 60}, {"dias": "7"}, {"dias": "a"}, {"fuente": "x"}, {"id": 5}):
        with pytest.raises(PubError):
            await s.editar_job(j, **malo)
    assert (await s.get_job(j))["hora"] == 9


async def test_job_duplicado_falla(s):
    await s.crear_job("x", "year")
    with pytest.raises(sqlite3.IntegrityError):
        await s.crear_job("x", "year")


async def test_destinos_pausar_y_listar_activos(s):
    j = await s.crear_job("año", "year")
    d1 = await s.agregar_destino(j, "telegram", params={"chat_id": -100})
    await s.agregar_destino(j, "nostr")
    await s.editar_destino(d1, activo=0)
    assert [d["tipo"] for d in await s.listar_destinos(j, solo_activos=True)] == ["nostr"]
    with pytest.raises(PubError):
        await s.agregar_destino(j, "facebook")
    with pytest.raises(PubError):
        await s.agregar_destino(999, "nostr")


async def test_borrar_job_borra_destinos(s):
    j = await s.crear_job("año", "year")
    await s.agregar_destino(j, "nostr")
    await s.borrar_job(j)
    assert await s.listar_destinos(j) == []


# ---------- idempotencia ----------
async def test_reservar_una_sola_vez_por_dia(s):
    assert await s.reservar(1, 1, "2026-11-27") is True
    assert await s.reservar(1, 1, "2026-11-27") is False       # en curso
    assert await s.reservar(1, 1, "2026-11-28") is True        # otro día
    assert await s.reservar(1, 2, "2026-11-27") is True        # otro destino


async def test_tras_ok_no_se_repite_pero_tras_error_si(s):
    await s.reservar(1, 1, "2026-11-27")
    await s.marcar(1, 1, "2026-11-27", "ok", url="https://x")
    assert await s.reservar(1, 1, "2026-11-27") is False
    await s.reservar(2, 1, "2026-11-27")
    await s.marcar(2, 1, "2026-11-27", "error", error="timeout")
    assert await s.reservar(2, 1, "2026-11-27") is True
    h = await s.historial(2)
    assert h[0]["intentos"] == 2 and h[0]["estado"] == "reservado" and h[0]["error"] is None


async def test_simulado_tampoco_se_repite(s):
    await s.reservar(1, 1, "2026-11-27")
    await s.marcar(1, 1, "2026-11-27", "simulado")
    assert await s.reservar(1, 1, "2026-11-27") is False
