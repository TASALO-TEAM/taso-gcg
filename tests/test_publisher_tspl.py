"""Fuente `tspl` (reenvía el digest que taso-bot ya armó) y formato Markdown del destino telegram."""

from datetime import datetime, timedelta, timezone

import httpx
import pytest
from telegram.error import BadRequest

from modules.publisher import destinos, fuentes, store
from modules.publisher.base import CTX, Contenido

AHORA = datetime(2026, 11, 27, 13, 30, tzinfo=timezone.utc)   # 8:30 en Cuba
GENERADO = (AHORA - timedelta(hours=2, minutes=30)).isoformat()  # 11:00 UTC, cuando taso-bot lo arma


def _data(**extra):
    d = {"ok": True, "telegram_text": "*TSPL*\n_hola_", "blog_markdown": "# Blog\n\ncuerpo",
         "generated_at": GENERADO, "updated_at": GENERADO}
    d.update(extra)
    return d


# ---------- armar_tspl ----------
def test_armar_tspl_reenvia_el_texto_tal_cual():
    c = fuentes.armar_tspl(_data(), ahora=AHORA)
    assert c.texto_corto == "*TSPL*\n_hola_"            # el mismo mensaje que reciben los usuarios de taso-bot
    assert c.cuerpo_md == "cuerpo" and c.titulo == "Blog"      # el "# t\u00edtulo" pasa al t\u00edtulo del post
    assert c.extra["parse_mode"] == "Markdown"
    assert c.tags == fuentes.TAGS_TSPL


BLOG = ("![](https://img/x.png)\n\n# \U0001F4CA TASALO Spotlight - 26 nov 2026\n\nlede del d\u00eda\n\n## Noticias\n\n- una")


def test_titulo_del_blog_sale_del_encabezado_y_no_se_repite_en_el_cuerpo():
    c = fuentes.armar_tspl(_data(blog_markdown=BLOG), ahora=AHORA)
    assert c.titulo == "\U0001F4CA TASALO Spotlight \u2014 26 nov 2026"
    assert c.cuerpo_md == "![](https://img/x.png)\n\nlede del d\u00eda\n\n## Noticias\n\n- una"


def test_encabezado_sin_imagen_delante():
    c = fuentes.armar_tspl(_data(blog_markdown="# T - 1\n\ncuerpo"), ahora=AHORA)
    assert c.titulo == "T \u2014 1" and c.cuerpo_md == "cuerpo"


@pytest.mark.parametrize("md", [None, "", "sin encabezado\n\n## solo h2"])
def test_sin_encabezado_el_titulo_es_el_de_respaldo(md):
    c = fuentes.armar_tspl(_data(blog_markdown=md), ahora=AHORA)
    assert c.titulo == fuentes.TITULO_TSPL == "TASALO Spotlight: Resumen del d\u00eda"


def test_armar_tspl_sin_blog_usa_el_texto_de_telegram():
    c = fuentes.armar_tspl(_data(blog_markdown=None), ahora=AHORA)
    assert c.cuerpo_md == c.texto_corto


def test_armar_tspl_descarta_un_digest_viejo():
    viejo = (AHORA - timedelta(hours=fuentes.EDAD_MAX_TSPL_H + 1)).isoformat()
    with pytest.raises(ValueError, match="viejo"):
        fuentes.armar_tspl(_data(generated_at=viejo), ahora=AHORA)


@pytest.mark.parametrize("data", [{}, _data(telegram_text=""), _data(generated_at="no-es-fecha"),
                                  _data(generated_at="2026-11-27T11:00:00")])   # sin zona horaria
def test_armar_tspl_datos_invalidos(data):
    with pytest.raises(ValueError):
        fuentes.armar_tspl(data, ahora=AHORA)


# ---------- fuente_tspl (HTTP) ----------
def _cliente_falso(monkeypatch, handler):
    real = httpx.AsyncClient
    monkeypatch.setattr(fuentes.httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(handler), **kw))


async def test_fuente_tspl_pide_el_digest_con_la_clave(monkeypatch):
    vistas = []

    def handler(req):
        vistas.append(req)
        return httpx.Response(200, json=_data(generated_at=datetime.now(timezone.utc).isoformat()))

    monkeypatch.setattr(fuentes, "TASALO_ADMIN_KEY", "clave-test")
    _cliente_falso(monkeypatch, handler)
    c = await fuentes.fuente_tspl()
    assert c.texto_corto == "*TSPL*\n_hola_"
    assert str(vistas[0].url).endswith("/api/v1/tspl/digest/latest")
    assert vistas[0].headers["X-API-Key"] == "clave-test"


async def test_fuente_tspl_sin_clave_no_llama_a_la_api(monkeypatch):
    monkeypatch.setattr(fuentes, "TASALO_ADMIN_KEY", "")
    _cliente_falso(monkeypatch, lambda req: pytest.fail("no debe llamar a la API"))
    with pytest.raises(RuntimeError, match="TASALO_ADMIN_KEY"):
        await fuentes.fuente_tspl()


async def test_fuente_tspl_sin_digest_todavia(monkeypatch):
    monkeypatch.setattr(fuentes, "TASALO_ADMIN_KEY", "clave-test")
    _cliente_falso(monkeypatch, lambda req: httpx.Response(404, json={"detail": "no"}))
    with pytest.raises(LookupError, match="taso-bot"):
        await fuentes.fuente_tspl()


# ---------- destino telegram: Markdown con respaldo en texto plano ----------
class BotFalso:
    def __init__(self, falla_markdown=False):
        self.llamadas = []
        self.falla_markdown = falla_markdown

    async def send_message(self, chat, texto, **kw):
        self.llamadas.append((chat, texto, kw))
        if self.falla_markdown and kw.get("parse_mode"):
            raise BadRequest("Can't parse entities")
        return type("M", (), {"message_id": 7})()


@pytest.fixture
def bot():
    b = BotFalso()
    CTX["bot"] = b
    yield b
    CTX.pop("bot", None)


def _c(extra=None):
    return Contenido("t", "largo", "*hola*", extra=extra or {})


D = {"params": {"chat": "@tasalospl"}}


async def test_telegram_usa_el_parse_mode_del_contenido(bot):
    r = await destinos.destino_telegram(_c({"parse_mode": "Markdown"}), D, None, None, False)
    assert r.ok and r.url == "https://t.me/tasalospl/7"
    assert bot.llamadas[0][2] == {"parse_mode": "Markdown"}


async def test_telegram_sin_parse_mode_sigue_en_texto_plano(bot):
    await destinos.destino_telegram(_c(), D, None, None, False)
    assert bot.llamadas[0][2] == {}                      # el estado del año no cambia


async def test_telegram_si_el_markdown_falla_reenvia_en_texto_plano():
    b = BotFalso(falla_markdown=True)
    CTX["bot"] = b
    try:
        r = await destinos.destino_telegram(_c({"parse_mode": "Markdown"}), D, None, None, False)
    finally:
        CTX.pop("bot", None)
    assert r.ok
    assert [k.get("parse_mode") for _, _, k in b.llamadas] == ["Markdown", None]


async def test_telegram_simulado_no_envia(bot):
    r = await destinos.destino_telegram(_c({"parse_mode": "Markdown"}), D, None, None, True)
    assert r.simulado and bot.llamadas == []


# ---------- orden: el estado del año sale primero ----------
async def test_year_va_primero_aunque_se_creara_despues(test_db, monkeypatch):
    monkeypatch.setattr(store, "db", test_db)
    await store.crear_job("TSPL", "tspl", 8, 30)
    await store.crear_job("Año", "year", 8, 30)
    assert [j["fuente"] for j in await store.listar_jobs()] == ["year", "tspl"]
