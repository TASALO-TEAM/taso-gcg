from datetime import datetime
from types import SimpleNamespace

import pytest

from modules import pub
from modules.publisher import scheduler as sch
from modules.publisher import store
from modules.publisher.base import CTX, DESTINOS, FUENTES, Contenido


def _botones(teclado):
    return [b for fila in teclado.inline_keyboard for b in fila]


def _datas(teclado):
    return [b.callback_data for b in _botones(teclado)]


JOB = {"id": 3, "nombre": "Estado del año", "fuente": "year", "hora": 8, "minuto": 30, "dias": "*", "activo": 1}
DEST = {"id": 9, "job_id": 3, "tipo": "telegram", "activo": 1, "params": {"chat": "@tasalospl"}}


# ---------- pantallas puras ----------
@pytest.mark.parametrize("h,m,delta,esperado", [(8, 30, 15, (8, 45)), (8, 30, -15, (8, 15)), (23, 50, 15, (0, 5)), (0, 5, -15, (23, 50))])
def test_desplazar_da_la_vuelta(h, m, delta, esperado):
    assert pub.desplazar({"hora": h, "minuto": m}, delta) == esperado


def test_home_sin_trabajos_ofrece_crear():
    texto, tec = pub.pantalla_home([], prueba=True)
    assert "ACTIVADO" in texto and "pub:new:year" in _datas(tec) and "pub:pm" in _datas(tec)


def test_home_con_trabajo_year_no_ofrece_crear_otro():
    _, tec = pub.pantalla_home([JOB], prueba=False)
    assert "pub:new:year" not in _datas(tec) and "pub:j:3" in _datas(tec)


def test_job_tiene_todos_los_controles_y_callbacks_validos():
    hist = [{"estado": "ok", "fecha": "2026-11-26", "url": "https://t.me/tasalospl/5", "error": None}]
    texto, tec = pub.pantalla_job(JOB, [DEST], hist, prueba=True)
    datas = _datas(tec)
    for esperado in ("pub:ja:3", "pub:hm:3:-15", "pub:hm:3:15", "pub:da:9", "pub:t:3", "pub:n:3", "pub:h"):
        assert esperado in datas
    assert all(len(d.encode()) <= 64 for d in datas)
    assert "08:30" in texto and "@tasalospl" in texto and "✅ 2026-11-26" in texto


def test_job_sin_destinos_avisa_como_añadirlos():
    texto, _ = pub.pantalla_job(JOB, [], [], prueba=False)
    assert "/pubdest" in texto


def test_html_escapado():
    texto, tec = pub.pantalla_job({**JOB, "nombre": "<b>x</b>"}, [], [], prueba=False)
    assert "<b>x</b>" not in texto.replace("<b>&lt;b&gt;x&lt;/b&gt;</b>", "")
    assert "&lt;b&gt;x" in texto


def test_confirmar_sin_destinos_activos_no_ofrece_publicar():
    _, tec = pub.pantalla_confirmar(JOB, [{**DEST, "activo": 0}])
    assert not any(d.startswith("pub:nc") for d in _datas(tec))


def test_confirmar_pide_si_explicito():
    texto, tec = pub.pantalla_confirmar(JOB, [DEST])
    assert "DE VERDAD" in texto and "pub:nc:3" in _datas(tec)
    assert "aunque el modo prueba esté activado" in texto


# ---------- flujos con base de datos ----------
class FakeBot:
    def __init__(self):
        self.enviados = []

    async def send_message(self, chat, texto):
        self.enviados.append((chat, texto))
        return SimpleNamespace(message_id=5)


@pytest.fixture
async def ctx(test_db, monkeypatch):
    monkeypatch.setattr(store, "db", test_db)
    sch._ultimo_intento.clear()
    bot = FakeBot()
    monkeypatch.setitem(CTX, "bot", bot)

    async def fuente():
        return Contenido("t", "c", "texto de prueba <ok>")

    from modules.publisher import destinos
    monkeypatch.setitem(FUENTES, "year", fuente)
    monkeypatch.setitem(DESTINOS, "telegram", destinos.destino_telegram)
    return SimpleNamespace(bot=bot)


async def _crear(ctx):
    texto, tec = await pub._despachar("new", ("year",), ctx)
    return (await store.listar_jobs())[0], texto, tec


async def test_crear_estado_del_año(ctx):
    job, texto, _ = await _crear(ctx)
    assert (job["hora"], job["minuto"], job["fuente"]) == (8, 30, "year")
    d = (await store.listar_destinos(job["id"]))[0]
    assert d["tipo"] == "telegram" and d["params"] == {"chat": "@tasalospl"}
    assert "Creado" in texto


async def test_crear_dos_veces_no_rompe(ctx):
    await _crear(ctx)
    with pytest.raises(Exception):                # nombre único: el handler lo muestra como aviso
        await pub._despachar("new", ("year",), ctx)


async def test_pausar_mover_hora_y_destino(ctx):
    job, *_ = await _crear(ctx)
    await pub._despachar("ja", (str(job["id"]),), ctx)
    assert (await store.get_job(job["id"]))["activo"] == 0
    await pub._despachar("hm", (str(job["id"]), "15"), ctx)
    await pub._despachar("hm", (str(job["id"]), "15"), ctx)
    j = await store.get_job(job["id"])
    assert (j["hora"], j["minuto"]) == (9, 0)
    d = (await store.listar_destinos(job["id"]))[0]
    await pub._despachar("da", (str(d["id"]),), ctx)
    assert (await store.get_destino(d["id"]))["activo"] == 0


async def test_modo_prueba_alterna_y_persiste(ctx):
    assert await store.modo_prueba(True) is True
    await pub._despachar("pm", (), ctx)
    assert await store.modo_prueba(True) is False
    await pub._despachar("pm", (), ctx)
    assert await store.modo_prueba(False) is True


async def test_probar_muestra_resultado_y_vista_previa_sin_enviar(ctx):
    job, *_ = await _crear(ctx)
    texto, _ = await pub._despachar("t", (str(job["id"]),), ctx)
    assert ctx.bot.enviados == []
    assert "🧪 telegram" in texto and "texto de prueba &lt;ok&gt;" in texto
    await pub._despachar("t", (str(job["id"]),), ctx)      # se puede probar las veces que haga falta
    assert ctx.bot.enviados == []


async def test_publicar_ahora_pide_confirmacion_y_luego_envia(ctx):
    job, *_ = await _crear(ctx)
    texto, _ = await pub._despachar("n", (str(job["id"]),), ctx)
    assert "DE VERDAD" in texto and ctx.bot.enviados == []
    texto, _ = await pub._despachar("nc", (str(job["id"]),), ctx)
    assert ctx.bot.enviados == [("@tasalospl", "texto de prueba <ok>")]
    assert "✅ telegram" in texto and "https://t.me/tasalospl/5" in texto


async def test_publicar_ahora_no_bloquea_la_programada_de_hoy(ctx):
    job, *_ = await _crear(ctx)
    await pub._despachar("nc", (str(job["id"]),), ctx)
    await sch.ejecutar_job(job, datetime.now(sch.TZ).date().isoformat(), bot=None, simular=False)
    assert len(ctx.bot.enviados) == 2


async def test_fuente_caida_se_ve_en_el_resultado(ctx, monkeypatch):
    job, *_ = await _crear(ctx)

    async def rota():
        raise RuntimeError("taso-api caído")

    monkeypatch.setitem(FUENTES, "year", rota)
    texto, _ = await pub._despachar("nc", (str(job["id"]),), ctx)
    assert "❌" in texto and "taso-api caído" in texto


async def test_boton_viejo_o_inexistente_cae_al_inicio(ctx):
    texto, _ = await pub._despachar("j", ("999",), ctx)
    assert "Publicación automática" in texto
    texto, _ = await pub._despachar("zzz", (), ctx)
    assert "Publicación automática" in texto


# ---------- el planificador respeta el modo editable ----------
async def test_tick_lee_el_modo_prueba_de_la_base(ctx, monkeypatch):
    job, *_ = await _crear(ctx)
    monkeypatch.setattr(sch, "PUB_DRY_RUN", True)
    ahora = datetime(2026, 11, 26, 8, 40, tzinfo=sch.TZ)
    await sch.tick(ctx.bot, ahora)
    assert ctx.bot.enviados == []                                   # por defecto: prueba
    await store.set_modo_prueba(False)
    await sch.tick(ctx.bot, ahora)
    assert len(ctx.bot.enviados) == 1                               # el panel lo pasó a real


# ---------- plantilla TSPL en el panel ----------
def test_home_ofrece_year_y_tspl_hasta_que_se_crean():
    _, tec = pub.pantalla_home([], prueba=True)
    assert {"pub:new:year", "pub:new:tspl"} <= set(_datas(tec))
    tspl = {**JOB, "id": 4, "nombre": "Resumen TSPL", "fuente": "tspl"}
    _, tec = pub.pantalla_home([JOB, tspl], prueba=False)
    assert not {"pub:new:year", "pub:new:tspl"} & set(_datas(tec))


async def test_crear_tspl_a_las_8_30_hacia_el_canal(ctx):
    await pub._despachar("new", ("tspl",), ctx)
    job = (await store.listar_jobs())[0]
    assert (job["fuente"], job["hora"], job["minuto"]) == ("tspl", 8, 30)
    (dest,) = await store.listar_destinos(job["id"])
    assert dest["tipo"] == "telegram" and dest["params"] == {"chat": "@tasalospl"}


async def test_fuente_desconocida_en_new_se_ignora(ctx):
    await pub._despachar("new", ("noexiste",), ctx)
    assert await store.listar_jobs() == []
