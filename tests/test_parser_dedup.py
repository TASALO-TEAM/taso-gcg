"""Tests de las dos piezas nuevas en modules/rss/parser.py:
1. _clean_html decodifica entidades HTML (bug real: '&apos;' quedaba sin
   decodificar cuando la fuente doble-escapaba entidades).
2. _extract_external_link saca el link real al artículo desde un post tipo
   'tarjeta' (usado por monitor.py para el dedup por link externo)."""

import os
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from modules.rss.parser import RSSParser  # noqa: E402


# --- _clean_html: decodificación de entidades ---

def test_clean_html_decodifica_entidad_simple():
    assert RSSParser._clean_html("company&apos;s new terms") == "company's new terms"


def test_clean_html_decodifica_entidad_doble_escapada():
    """El bug real visto en producción: la fuente entrega '&amp;apos;' en el
    XML crudo; feedparser decodifica un nivel ('&amp;apos;' -> '&apos;') y
    sin esta segunda pasada queda la entidad literal en el texto final."""
    assert RSSParser._clean_html("company&apos;s terms") == "company's terms"
    assert RSSParser._clean_html("A &amp; B") == "A & B"
    assert RSSParser._clean_html("&quot;cita&quot;") == '"cita"'


def test_clean_html_sigue_preservando_tags_permitidos():
    resultado = RSSParser._clean_html("<b>negrita</b> y <script>malo</script>")
    assert "<b>negrita</b>" in resultado
    assert "<script>" not in resultado


def test_clean_html_texto_vacio():
    assert RSSParser._clean_html("") == ""
    assert RSSParser._clean_html(None) == ""


# --- _extract_external_link ---

def _entry_feedparser(link, summary):
    """feedparser.FeedParserDict se comporta como un dict; SimpleNamespace con
    .get basta para los accesos que usa _extract_external_link."""
    d = {"link": link, "summary": summary}

    class _FakeEntry(dict):
        pass

    return _FakeEntry(d)


def test_extract_external_link_encuentra_link_a_dominio_externo():
    entry = _entry_feedparser(
        "https://nitter.net/IntCyberDigest/status/2",
        'Read the article: <a href="https://www.internationalcyberdigest.com/nota">Fuente</a>',
    )
    assert RSSParser._extract_external_link(entry) == "https://www.internationalcyberdigest.com/nota"


def test_extract_external_link_ignora_links_al_propio_dominio():
    entry = _entry_feedparser(
        "https://nitter.net/IntCyberDigest/status/2",
        'Ver <a href="https://nitter.net/IntCyberDigest/status/2">este post</a>',
    )
    assert RSSParser._extract_external_link(entry) is None


def test_extract_external_link_ignora_twitter_y_x_com():
    entry = _entry_feedparser(
        "https://nitter.net/IntCyberDigest/status/2",
        'Cita a <a href="https://twitter.com/otro_usuario">@otro</a>',
    )
    assert RSSParser._extract_external_link(entry) is None


def test_extract_external_link_sin_links_devuelve_none():
    entry = _entry_feedparser("https://nitter.net/x/status/1", "Solo texto plano, sin enlaces.")
    assert RSSParser._extract_external_link(entry) is None


def test_extract_external_link_sin_contenido():
    entry = _entry_feedparser("https://nitter.net/x/status/1", "")
    assert RSSParser._extract_external_link(entry) is None
