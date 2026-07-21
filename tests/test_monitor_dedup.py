"""Tests del dedup por link externo (fix de "el mismo artículo se manda dos
veces" en fuentes tipo X/Twitter, donde un post con texto completo y un
segundo post 'tarjeta' con solo el link tienen títulos tan distintos que el
fuzzy-match por título no los agarra — ver plan
2026-07-20-html-entities-y-dedup-link-externo.md)."""

import os
import sys
import time
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import modules.rss.monitor as monitor  # noqa: E402
from modules.rss.monitor import RSSMonitor  # noqa: E402


class ChatFalso:
    def __init__(self, id, type="supergroup", title="Chat de prueba", username=None):
        self.id = id
        self.type = type
        self.title = title
        self.username = username
        self.full_name = None
        self.first_name = None


async def _crear_feed(test_db, traducir=0):
    chat = await test_db.ensure_chat(ChatFalso(id=-100777))
    feed_id = await test_db.execute(
        "INSERT INTO feeds(chat_id, url, url_original, titulo, estilo, intervalo_min, "
        "ultimo_check, activo, traducir) VALUES (?,?,?,?,?,?,?,?,?)",
        (chat["id"], "https://nitter.net/IntCyberDigest/rss", None, "IntCyberDigest",
         "social", 10, 0, 1, traducir),
    )
    return await test_db.fetchone(
        "SELECT feeds.*, chats.tg_chat_id as chat_tg_id, chats.activo as chat_activo "
        "FROM feeds JOIN chats ON feeds.chat_id = chats.id WHERE feeds.id = ?",
        (feed_id,),
    )


def _entry(hash_, title, link, external_link):
    return {
        "title": title,
        "link": link,
        "description": title,
        "image": None,
        "video": None,
        "external_link": external_link,
        "hash": hash_,
        "source": "IntCyberDigest",
    }


@pytest.fixture
def bot_falso():
    bot = MagicMock()
    bot.send_message = AsyncMock(return_value=True)
    bot.send_photo = AsyncMock(return_value=True)
    bot.send_video = AsyncMock(return_value=True)
    return bot


@pytest.mark.asyncio
async def test_segundo_post_con_mismo_link_externo_se_omite(monkeypatch, test_db, bot_falso):
    monkeypatch.setattr(monitor, "db", test_db)
    feed = await _crear_feed(test_db)

    entrada_completa = _entry(
        "hash1",
        "LG deja de mandar parches de seguridad si no aceptas que graben tu voz",
        "https://nitter.net/IntCyberDigest/status/1",
        "https://www.internationalcyberdigest.com/lg-ties-tv-security-updates-to-accepting-ai-voice-recording/",
    )
    entrada_tarjeta = _entry(
        "hash2",
        "Read the article",
        "https://nitter.net/IntCyberDigest/status/2",
        "https://www.internationalcyberdigest.com/lg-ties-tv-security-updates-to-accepting-ai-voice-recording/",
    )
    parsed = {"title": "IntCyberDigest", "entries": [entrada_completa, entrada_tarjeta]}
    monkeypatch.setattr(monitor.RSSParser, "parse", AsyncMock(return_value=(parsed, None)))

    m = RSSMonitor(bot=bot_falso)
    await m._procesar_feed(feed)

    # Solo el primer post (texto completo) se manda; el segundo (misma nota,
    # link externo repetido) se detecta como duplicado y se omite.
    assert bot_falso.send_message.await_count == 1

    historial = await test_db.fetchall(
        "SELECT entry_hash, link_externo_normalizado FROM feed_historial WHERE feed_id = ?", (feed["id"],)
    )
    assert len(historial) == 2  # ambos quedan registrados (uno enviado, uno omitido)
    assert all(h["link_externo_normalizado"] for h in historial)


@pytest.mark.asyncio
async def test_posts_sin_link_externo_no_se_bloquean_entre_si(monkeypatch, test_db, bot_falso):
    """Regresión: dos posts distintos que no traen ningún link externo (ej.
    fuentes que no son 'social') no deben tratarse como duplicados entre sí
    solo porque ambos tienen external_link=None."""
    monkeypatch.setattr(monitor, "db", test_db)
    feed = await _crear_feed(test_db)

    entrada1 = _entry("hash1", "Noticia A completamente distinta", "https://nitter.net/x/status/1", None)
    entrada2 = _entry("hash2", "Noticia B, otro tema, otro título", "https://nitter.net/x/status/2", None)
    parsed = {"title": "Feed", "entries": [entrada1, entrada2]}
    monkeypatch.setattr(monitor.RSSParser, "parse", AsyncMock(return_value=(parsed, None)))

    m = RSSMonitor(bot=bot_falso)
    await m._procesar_feed(feed)

    assert bot_falso.send_message.await_count == 2


@pytest.mark.asyncio
async def test_link_externo_distinto_no_se_omite(monkeypatch, test_db, bot_falso):
    """Dos posts con títulos distintos y links externos distintos (dos
    noticias reales, no la misma repetida) deben mandarse ambos."""
    monkeypatch.setattr(monitor, "db", test_db)
    feed = await _crear_feed(test_db)

    entrada1 = _entry("hash1", "Noticia sobre LG", "https://nitter.net/x/status/1",
                       "https://ejemplo.com/nota-lg")
    entrada2 = _entry("hash2", "Noticia sobre Samsung", "https://nitter.net/x/status/2",
                       "https://ejemplo.com/nota-samsung")
    parsed = {"title": "Feed", "entries": [entrada1, entrada2]}
    monkeypatch.setattr(monitor.RSSParser, "parse", AsyncMock(return_value=(parsed, None)))

    m = RSSMonitor(bot=bot_falso)
    await m._procesar_feed(feed)

    assert bot_falso.send_message.await_count == 2
