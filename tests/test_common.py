import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import os
import sys
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.common import (  # noqa: E402
    parse_duration, humanize_seconds, clean_html, truncate_text,
    extract_target_user, resolve_username, estimate_account_creation,
)
import utils.common as common  # noqa: E402


def test_parse_duration_valida():
    assert parse_duration("30s") == 30
    assert parse_duration("5m") == 300
    assert parse_duration("2h") == 7200
    assert parse_duration("1d") == 86400


def test_parse_duration_invalida():
    assert parse_duration("") is None
    assert parse_duration("abc") is None
    assert parse_duration("10") is None  # falta la unidad
    assert parse_duration("10x") is None  # unidad inválida


def test_humanize_seconds():
    assert humanize_seconds(30) == "30s"
    assert humanize_seconds(60) == "1m"
    assert humanize_seconds(3600) == "1h"
    assert humanize_seconds(86400) == "1d"
    assert humanize_seconds(90) == "90s"  # no es múltiplo exacto de una unidad mayor


def test_clean_html_quita_etiquetas_no_soportadas():
    resultado = clean_html("<div><script>alert(1)</script><p>Hola <b>mundo</b></p></div>")
    assert "script" not in resultado
    assert "<b>mundo</b>" in resultado
    assert "<div>" not in resultado


def test_clean_html_vacio():
    assert clean_html("") == ""
    assert clean_html(None) == ""


def test_truncate_text_no_corta_si_cabe():
    texto = "Hola mundo"
    assert truncate_text(texto, limit=100) == texto


def test_truncate_text_corta_y_cierra_enlace():
    texto = "a" * 50 + "<a href='x'>enlace</a>"
    resultado = truncate_text(texto, limit=40)
    assert len(resultado) <= 44  # 40 + "</a>" si hizo falta cerrar
    assert resultado.count("<a") <= resultado.count("</a>")


def test_truncate_text_no_corta_a_mitad_de_etiqueta():
    """Bug real visto en producción: el corte caía dentro de un <a href="...
    sin llegar al '>' de cierre de la apertura, produciendo HTML roto que
    Telegram rechazaba con 'Can't parse entities: unclosed start tag'."""
    texto = "Texto de la noticia " + "x" * 20 + '<a href="https://ejemplo.com/articulo-largo">Fuente</a>'
    # limit cae justo a mitad del atributo href, antes del '>' de apertura
    resultado = truncate_text(texto, limit=45)
    # No debe quedar un '<' sin su '>' correspondiente
    assert resultado.count("<") == resultado.count(">")
    # No debe haber un fragmento de tag roto tipo '<a href="https'
    assert '<a href="https' not in resultado or resultado.rstrip("</a>").endswith(">")


def test_truncate_text_cierra_etiquetas_no_solo_a():
    """La versión anterior solo rebalanceaba <a>; <b>, <i>, etc. quedaban
    rotas si el corte caía después de su apertura."""
    texto = "Intro " + "y" * 40 + "<b>texto en negrita que se corta a mitad</b>"
    resultado = truncate_text(texto, limit=50)
    assert resultado.count("<b>") == resultado.count("</b>")


def test_truncate_text_cierra_etiquetas_anidadas_en_orden_inverso():
    texto = "z" * 30 + "<b>negrita <i>e itálica que se corta</i></b>"
    resultado = truncate_text(texto, limit=40)
    # Deben quedar balanceadas ambas, y en el orden correcto (LIFO): si <i>
    # se abrió después de <b>, debe cerrarse antes.
    assert resultado.count("<b>") == resultado.count("</b>")
    assert resultado.count("<i>") == resultado.count("</i>")
    if "<i>" in resultado and "</b>" in resultado:
        assert resultado.rindex("</i>") < resultado.rindex("</b>")


def test_truncate_text_texto_sin_html_no_cambia_de_comportamiento():
    texto = "Solo texto plano sin ninguna etiqueta HTML de por medio, " * 3
    resultado = truncate_text(texto, limit=50)
    assert len(resultado) <= 50
    assert resultado.endswith("...")


# --- extract_target_user / resolve_username ---
# La Bot API de Telegram solo manda el user_id embebido en las menciones
# `text_mention` (nombre visible sin @username propio). Para un `@usuario`
# en texto plano solo llega el texto — por eso hace falta resolverlo aparte
# contra la caché local (tabla `users`) o, como último recurso, contra la API.

from telegram.constants import MessageEntityType  # noqa: E402


class _EntidadFalsa:
    def __init__(self, type, offset, length, user=None):
        self.type = type
        self.offset = offset
        self.length = length
        self.user = user


class _UsuarioFalso:
    def __init__(self, id, username=None, first_name="Nombre", last_name=None, is_premium=False):
        self.id = id
        self.username = username
        self.first_name = first_name
        self.last_name = last_name
        self.is_bot = False
        self.language_code = "es"
        self.is_premium = is_premium


def _mensaje_falso(texto="", entidades=None, reply_to_message=None):
    m = MagicMock()
    m.text = texto
    m.caption = None
    m.entities = entidades or []
    m.reply_to_message = reply_to_message
    return m


def _update_falso(message):
    u = MagicMock()
    u.effective_message = message
    return u


@pytest.mark.asyncio
async def test_extract_target_user_prioriza_reply():
    respondido = MagicMock()
    respondido.from_user = MagicMock(id=10, full_name="Fulano")
    message = _mensaje_falso(texto="/ban", reply_to_message=respondido)

    user_id, nombre = await extract_target_user(_update_falso(message), context=MagicMock())
    assert (user_id, nombre) == (10, "Fulano")


@pytest.mark.asyncio
async def test_extract_target_user_text_mention_trae_el_id_embebido():
    texto = "/ban Juan Perez"
    ent = _EntidadFalsa(MessageEntityType.TEXT_MENTION, offset=4, length=11,
                         user=MagicMock(id=55, full_name="Juan Perez"))
    message = _mensaje_falso(texto=texto, entidades=[ent])

    user_id, nombre = await extract_target_user(_update_falso(message), context=MagicMock())
    assert (user_id, nombre) == (55, "Juan Perez")


@pytest.mark.asyncio
async def test_extract_target_user_mention_username_resuelto_por_cache(monkeypatch, test_db):
    """Este es el caso que antes NO funcionaba en absoluto: '/ban @usuario'
    ni siquiera se intentaba resolver, solo se miraba text_mention."""
    monkeypatch.setattr(common, "db", test_db)
    await test_db.upsert_user(_UsuarioFalso(id=777, username="pepito", first_name="Pepito"))

    texto = "/ban @pepito"
    ent = _EntidadFalsa(MessageEntityType.MENTION, offset=5, length=7)  # "@pepito"
    message = _mensaje_falso(texto=texto, entidades=[ent])

    user_id, nombre = await extract_target_user(_update_falso(message), context=MagicMock())
    assert (user_id, nombre) == (777, "Pepito")


@pytest.mark.asyncio
async def test_extract_target_user_mention_no_resoluble_devuelve_none(monkeypatch, test_db):
    monkeypatch.setattr(common, "db", test_db)
    context = MagicMock()
    context.bot.get_chat = AsyncMock(side_effect=Exception("no encontrado"))

    texto = "/ban @fantasma"
    ent = _EntidadFalsa(MessageEntityType.MENTION, offset=5, length=9)
    message = _mensaje_falso(texto=texto, entidades=[ent])

    user_id, nombre = await extract_target_user(_update_falso(message), context)
    assert (user_id, nombre) == (None, None)


@pytest.mark.asyncio
async def test_resolve_username_cae_a_la_api_si_no_hay_cache(monkeypatch, test_db):
    monkeypatch.setattr(common, "db", test_db)
    context = MagicMock()
    chat_falso = MagicMock(type="private", id=321, first_name="Ana")
    context.bot.get_chat = AsyncMock(return_value=chat_falso)

    assert await resolve_username(context, "ana_tg") == (321, "Ana")


# --- estimate_account_creation ---

def test_estimate_account_creation_formato():
    resultado = estimate_account_creation(100)
    assert resultado.startswith("~ ")
    assert resultado.endswith("(?)")


def test_estimate_account_creation_es_monotona():
    # A mayor id, la fecha estimada no debería retroceder
    ids = (1, 10_000_000, 1_000_000_000, 5_000_000_000, 9_000_000_000)
    fechas = [estimate_account_creation(uid) for uid in ids]
    anios = [int(f.split("/")[1].split()[0]) for f in fechas]
    assert anios == sorted(anios)


def test_estimate_account_creation_no_revienta_en_extremos():
    assert estimate_account_creation(0).endswith("(?)")
    assert estimate_account_creation(50_000_000_000).endswith("(?)")
