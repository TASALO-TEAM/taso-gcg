import httpx
import pytest

from modules.publisher import destinos, fuentes, store
from modules.publisher import scheduler as sch
from modules.publisher.base import CTX, DESTINOS, FUENTES, Contenido

DATA = {
    "ok": True,
    "progress": {"year": 2026, "percent": 90.35065008993215, "days_left": 35, "date_str": "26/11/2026"},
    "quote": {"ok": True, "quote": "Nunca pierdas tu tiempo.", "index": 330},
}


def test_armar_year_formato():
    c = fuentes.armar_year(DATA)
    assert "ESTADO DEL AÑO 2026" in c.texto_corto
    assert "Progreso: 90.35%" in c.texto_corto
    assert "Faltan 35 días para 2027" in c.texto_corto
    assert "▓" * 18 + "░" * 2 in c.texto_corto        # 90 % de 20 cuadros
    assert "Recta final" in c.texto_corto
    assert '"Nunca pierdas tu tiempo."' in c.texto_corto
    assert c.titulo == "Estado del año 2026: 90.35%"
    assert c.tags == fuentes.TAGS_YEAR


@pytest.mark.parametrize("pct,esperado", [(0.5, "Recién"), (5, "motores"), (30, "propósitos"), (60, "Se nos va"), (99, "Recta final")])
def test_animo_por_tramos(pct, esperado):
    assert esperado in fuentes._animo(pct)


def test_barra_acotada_en_los_extremos():
    for pct in (0, 100, 150, -3):
        d = {"progress": {"year": 2026, "percent": pct, "days_left": 0, "date_str": ""}}
        barra = [ln for ln in fuentes.armar_year(d).texto_corto.splitlines() if ln.startswith("📊")][0]
        assert len(barra.split(" ", 1)[1]) == 20


def test_frase_de_respaldo_si_no_hay_cita():
    d = {"progress": DATA["progress"], "quote": None}
    assert fuentes.FRASE_RESPALDO in fuentes.armar_year(d).texto_corto


@pytest.mark.parametrize("data", [{}, {"progress": {}}, {"progress": {"year": "x", "percent": 1, "days_left": 1}}])
def test_armar_year_sin_progreso_falla(data):
    with pytest.raises(ValueError):
        fuentes.armar_year(data)


def _cliente_falso(monkeypatch, handler):
    real = httpx.AsyncClient
    monkeypatch.setattr(fuentes.httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(handler), **kw))


async def test_fuente_year_consulta_la_api(monkeypatch):
    vistas = []

    def handler(req):
        vistas.append(str(req.url))
        return httpx.Response(200, json=DATA)

    _cliente_falso(monkeypatch, handler)
    monkeypatch.setattr(fuentes, "TASO_API_URL", "http://api.local:8040/")
    c = await fuentes.fuente_year()
    assert vistas == ["http://api.local:8040/api/v1/year/state"]
    assert isinstance(c, Contenido)


async def test_fuente_year_error_http(monkeypatch):
    _cliente_falso(monkeypatch, lambda req: httpx.Response(503))
    with pytest.raises(httpx.HTTPStatusError):
        await fuentes.fuente_year()


# ---------- destino telegram ----------
class FakeBot:
    def __init__(self):
        self.enviados = []

    async def send_message(self, chat, texto):
        self.enviados.append((chat, texto))
        return type("M", (), {"message_id": 77})()


@pytest.fixture
def bot(monkeypatch):
    b = FakeBot()
    monkeypatch.setitem(CTX, "bot", b)
    return b


C = Contenido("t", "cuerpo", "hola mundo")


async def test_telegram_envia_y_devuelve_url(bot):
    r = await destinos.destino_telegram(C, {"params": {"chat": "@tasalospl"}}, None, None, False)
    assert r.ok and r.url == "https://t.me/tasalospl/77" and not r.simulado
    assert bot.enviados == [("@tasalospl", "hola mundo")]


async def test_telegram_id_numerico_sin_url(bot):
    r = await destinos.destino_telegram(C, {"params": {"chat": "-1001234"}}, None, None, False)
    assert r.ok and r.url is None
    assert bot.enviados[0][0] == -1001234


async def test_telegram_simulado_no_envia(bot):
    r = await destinos.destino_telegram(C, {"params": {"chat": "@x"}}, None, None, True)
    assert r.ok and r.simulado and bot.enviados == []


@pytest.mark.parametrize("params", [{}, {"chat": ""}, {"chat": "canal"}, {"chat": "@"}, {"chat": 0}])
async def test_telegram_chat_invalido(bot, params):
    with pytest.raises(ValueError):
        await destinos.destino_telegram(C, {"params": params}, None, None, False)
    assert bot.enviados == []


async def test_telegram_recorta_mensaje_largo(bot):
    largo = Contenido("t", "c", "a" * 5000)
    await destinos.destino_telegram(largo, {"params": {"chat": "@x"}}, None, None, False)
    assert len(bot.enviados[0][1]) == destinos.LIMITE_TELEGRAM


async def test_telegram_sin_bot(monkeypatch):
    monkeypatch.delitem(CTX, "bot", raising=False)
    with pytest.raises(RuntimeError):
        await destinos.destino_telegram(C, {"params": {"chat": "@x"}}, None, None, False)


# ---------- de punta a punta con el planificador ----------
@pytest.fixture
async def e2e(test_db, monkeypatch, bot):
    monkeypatch.setattr(store, "db", test_db)
    monkeypatch.setattr(sch, "ESPERA_REINTENTO", 0)
    sch._ultimo_intento.clear()
    monkeypatch.setitem(FUENTES, "year", fuentes.fuente_year)
    monkeypatch.setitem(DESTINOS, "telegram", destinos.destino_telegram)
    _cliente_falso(monkeypatch, lambda req: httpx.Response(200, json=DATA))
    job_id = await store.crear_job("estado", "year")
    await store.agregar_destino(job_id, "telegram", params={"chat": "@tasalospl"})
    return await store.get_job(job_id)


async def test_e2e_publica_una_vez_al_dia(e2e, bot):
    await sch.ejecutar_job(e2e, "2026-11-26", bot=None, simular=False)
    await sch.ejecutar_job(e2e, "2026-11-26", bot=None, simular=False)    # idempotente
    assert len(bot.enviados) == 1 and "ESTADO DEL AÑO 2026" in bot.enviados[0][1]
    await sch.ejecutar_job(e2e, "2026-11-27", bot=None, simular=False)    # otro día, otro mensaje
    assert len(bot.enviados) == 2


async def test_e2e_modo_prueba_no_envia(e2e, bot):
    await sch.ejecutar_job(e2e, "2026-11-26", bot=None, simular=True)
    assert bot.enviados == []
