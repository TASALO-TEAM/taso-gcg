from datetime import datetime

import pytest

from core import secrets
from modules.publisher import scheduler as sch
from modules.publisher import store
from modules.publisher.base import DESTINOS, FUENTES, Contenido, Resultado

FECHA = "2026-11-26"            # jueves
CONTENIDO = Contenido("Título", "# cuerpo", "corto")


class FakeBot:
    def __init__(self):
        self.enviados = []

    async def send_message(self, chat, texto):
        self.enviados.append(texto)


@pytest.fixture
async def p(test_db, monkeypatch):
    monkeypatch.setenv(secrets.ENV_ACTUAL, secrets.generar_clave())
    monkeypatch.delenv(secrets.ENV_ANTERIOR, raising=False)
    monkeypatch.setattr(store, "db", test_db)
    monkeypatch.setattr(sch, "LOG_CHAT_ID", "-100")
    monkeypatch.setattr(sch, "ESPERA_REINTENTO", 0)
    sch._ultimo_intento.clear()
    return sch


async def montar(tipos=("telegram", "nostr"), cuenta_id=None):
    job_id = await store.crear_job("estado", "year")
    for t in tipos:
        await store.agregar_destino(job_id, t, cuenta_id=cuenta_id)
    return await store.get_job(job_id)


def poner(monkeypatch, fuente=None, **destinos):
    async def fuente_ok():
        return CONTENIDO
    monkeypatch.setitem(FUENTES, "year", fuente or fuente_ok)
    for tipo, fn in destinos.items():
        monkeypatch.setitem(DESTINOS, tipo, fn)


async def estados(job):
    return {h["destino_id"]: (h["estado"], h["intentos"]) for h in await store.historial(job["id"])}


# ---------- ventana horaria ----------
def test_toca_ventana_y_dias():
    job = {"hora": 8, "minuto": 30, "dias": "*"}
    d = lambda h, m: datetime(2026, 11, 26, h, m, tzinfo=sch.TZ)
    assert not sch.toca(job, d(8, 29))
    assert sch.toca(job, d(8, 30))
    assert sch.toca(job, d(11, 29))             # 179 min tarde: aún recupera
    assert not sch.toca(job, d(11, 30))         # pasada la ventana, se salta el día
    assert sch.toca({**job, "dias": "3"}, d(9, 0))        # jueves = 3
    assert not sch.toca({**job, "dias": "0,1"}, d(9, 0))


# ---------- publicación ----------
async def test_publica_una_vez_y_es_idempotente(p, monkeypatch):
    llamadas = []

    async def fuente():
        llamadas.append("fuente")
        return CONTENIDO

    async def dest(c, d, cuenta, secreto, simular):
        llamadas.append(d["tipo"])
        return Resultado(True, url="https://x/" + d["tipo"])

    poner(monkeypatch, fuente, telegram=dest, nostr=dest)
    job = await montar()
    await p.ejecutar_job(job, FECHA, FakeBot(), simular=False)
    await p.ejecutar_job(job, FECHA, FakeBot(), simular=False)      # segundo arranque del día
    assert llamadas == ["fuente", "telegram", "nostr"]
    assert await estados(job) == {1: ("ok", 1), 2: ("ok", 1)}


async def test_destino_caido_no_bloquea_y_avisa_una_sola_vez(p, monkeypatch):
    bot, n = FakeBot(), {"telegram": 0, "nostr": 0}

    async def telegram(*a):
        n["telegram"] += 1
        raise RuntimeError("timeout")

    async def nostr(*a):
        n["nostr"] += 1
        return Resultado(True)

    poner(monkeypatch, telegram=telegram, nostr=nostr)
    job = await montar()
    for _ in range(5):
        await p.ejecutar_job(job, FECHA, bot, simular=False)
    assert n == {"telegram": p.MAX_INTENTOS, "nostr": 1}
    assert await estados(job) == {1: ("error", p.MAX_INTENTOS), 2: ("ok", 1)}
    assert len(bot.enviados) == 1 and "telegram" in bot.enviados[0]


async def test_reintento_respeta_la_espera(p, monkeypatch):
    monkeypatch.setattr(p, "ESPERA_REINTENTO", 600)
    n = []

    async def dest(*a):
        n.append(1)
        raise RuntimeError("fallo")

    poner(monkeypatch, telegram=dest)
    job = await montar(("telegram",))
    await p.ejecutar_job(job, FECHA, FakeBot(), simular=False)
    await p.ejecutar_job(job, FECHA, FakeBot(), simular=False)      # demasiado pronto
    assert len(n) == 1


async def test_fuente_ausente_marca_error(p, monkeypatch):
    monkeypatch.delitem(FUENTES, "year", raising=False)
    job = await montar(("telegram",))
    await p.ejecutar_job(job, FECHA, FakeBot(), simular=False)
    h = (await store.historial(job["id"]))[0]
    assert h["estado"] == "error" and "sin implementar" in h["error"]


async def test_cuenta_inactiva_es_error(p, monkeypatch):
    async def dest(*a):
        return Resultado(True)

    poner(monkeypatch, nostr=dest)
    cuenta = await store.guardar_cuenta("nostr", "tasalo", secreto="nsec1x")
    await store.editar_cuenta(cuenta, activa=False)
    job = await montar(("nostr",), cuenta_id=cuenta)
    await p.ejecutar_job(job, FECHA, FakeBot(), simular=False)
    assert "inactiva" in (await store.historial(job["id"]))[0]["error"]


# ---------- modo prueba ----------
async def test_prueba_no_descifra_ni_bloquea_lo_real(p, monkeypatch):
    recibido = []

    async def dest(c, d, cuenta, secreto, simular):
        recibido.append((secreto, simular))
        return Resultado(True)

    poner(monkeypatch, hive_wave=dest)
    cuenta = await store.guardar_cuenta("hive", "ersus93", secreto="5Ksecreto")
    job = await montar(("hive_wave",), cuenta_id=cuenta)
    await p.ejecutar_job(job, FECHA, FakeBot(), simular=True)
    await p.ejecutar_job(job, FECHA, FakeBot(), simular=False)      # lo real el mismo día sí sale
    assert recibido == [(None, True), ("5Ksecreto", False)]
    assert sorted(h["estado"] for h in await store.historial(job["id"])) == ["ok", "simulado"]


# ---------- seguridad ----------
async def test_el_secreto_no_se_filtra(p, monkeypatch):
    logs, bot = [], FakeBot()
    monkeypatch.setattr(sch, "log", lambda m, nivel="info": logs.append(m))

    async def dest(c, d, cuenta, secreto, simular):
        raise RuntimeError(f"clave rechazada: {secreto}")

    poner(monkeypatch, hive_wave=dest)
    cuenta = await store.guardar_cuenta("hive", "ersus93", secreto="5Ksecreto")
    job = await montar(("hive_wave",), cuenta_id=cuenta)
    for _ in range(p.MAX_INTENTOS):
        await p.ejecutar_job(job, FECHA, bot, simular=False)
    todo = " ".join(logs + bot.enviados + [str(h) for h in await store.historial()])
    assert "5Ksecreto" not in todo and "***" in todo


# ---------- tick ----------
async def test_tick_solo_publica_en_su_ventana(p, monkeypatch):
    monkeypatch.setattr(p, "PUB_DRY_RUN", False)
    n = []

    async def dest(*a):
        n.append(1)
        return Resultado(True)

    poner(monkeypatch, telegram=dest)
    await montar(("telegram",))                                     # 8:30 por defecto
    hav = lambda h, m: datetime(2026, 11, 26, h, m, tzinfo=sch.TZ)
    await p.tick(FakeBot(), hav(7, 0))
    assert n == []
    await p.tick(FakeBot(), hav(8, 40))
    await p.tick(FakeBot(), hav(8, 41))                             # no repite
    assert len(n) == 1
