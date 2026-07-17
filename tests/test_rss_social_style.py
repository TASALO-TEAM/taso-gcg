"""Tests del fix de duplicación de texto en fuentes de X/Twitter (estilo 'social').

Cubre solo la detección (RSSParser.is_social_source) y el mapeo de plantillas
por estilo (monitor.TEMPLATES_BY_STYLE); son las dos piezas de lógica pura sin
dependencias de red/Telegram que introdujo el fix.
"""

from modules.rss.parser import RSSParser
from modules.rss.monitor import TEMPLATES_BY_STYLE, SOCIAL_TEMPLATE, DEFAULT_TEMPLATE


def test_detecta_twitter_y_x_directo():
    assert RSSParser.is_social_source("https://twitter.com/WordsnWisdom26")
    assert RSSParser.is_social_source("https://x.com/WordsnWisdom26")


def test_detecta_instancias_nitter():
    assert RSSParser.is_social_source("https://nitter.net/WordsnWisdom26/rss")
    assert RSSParser.is_social_source("https://nitter.privacyredirect.com/algo")


def test_detecta_alias_sin_nitter_en_el_nombre():
    assert RSSParser.is_social_source("https://xcancel.com/WordsnWisdom26")
    assert RSSParser.is_social_source("https://twiiit.com/WordsnWisdom26")


def test_no_detecta_fuentes_normales():
    assert not RSSParser.is_social_source("https://www.coindesk.com/arc/outboundfeeds/rss/")
    assert not RSSParser.is_social_source("")
    assert not RSSParser.is_social_source(None)


def test_plantilla_social_no_repite_titulo():
    assert "#title#" not in SOCIAL_TEMPLATE
    assert "#description#" in SOCIAL_TEMPLATE


def test_mapeo_estilos_incluye_social():
    assert TEMPLATES_BY_STYLE["social"] == SOCIAL_TEMPLATE
    assert TEMPLATES_BY_STYLE["bitbread"] == DEFAULT_TEMPLATE
    assert TEMPLATES_BY_STYLE["texto"] == DEFAULT_TEMPLATE
