"""T0.1 — los botones de /myfeeds exigen ser admin del chat dueño del feed."""
import os
import sys
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import utils.decorators as decorators  # noqa: E402
import modules.rss.handlers as handlers  # noqa: E402

CHAT_A = -1001  # chat dueño del feed
CHAT_B = -1002  # otro chat donde el usuario sí es admin
ADMIN_A, ADMIN_B, EXTRANO = 10, 20, 999


async def _preparar(test_db, monkeypatch):
    monkeypatch.setattr(handlers, "db", test_db)
    monkeypatch.setattr(decorators, "db", test_db)
    monkeypatch.setattr(decorators, "SUDO_USERS", set())
    await test_db.execute("INSERT INTO chats(tg_chat_id, tipo) VALUES (?, 'supergroup')", (CHAT_A,))
    await test_db.execute("INSERT INTO chats(tg_chat_id, tipo) VALUES (?, 'supergroup')", (CHAT_B,))
    await test_db.cache_admins(CHAT_A, [(ADMIN_A, False)])
    await test_db.cache_admins(CHAT_B, [(ADMIN_B, False)])
    chat = await test_db.fetchone("SELECT id FROM chats WHERE tg_chat_id = ?", (CHAT_A,))
    await test_db.execute(
        "INSERT INTO feeds(chat_id, numero_local, url, url_original, titulo, estilo) "
        "VALUES (?, 1, 'https://x.test/rss', 'https://x.test', 'Feed', 'texto')",
        (chat["id"],),
    )
    return (await test_db.fetchone("SELECT id FROM feeds"))["id"]


def _update(data, user_id):
    update = MagicMock()
    update.callback_query.data = data
    update.callback_query.from_user.id = user_id
    update.callback_query.answer = AsyncMock()
    update.callback_query.edit_message_text = AsyncMock()
    return update


async def _feeds(test_db):
    return await test_db.fetchall("SELECT * FROM feeds")


@pytest.mark.asyncio
@pytest.mark.parametrize("usuario", [EXTRANO, ADMIN_B])  # no-admin y admin de OTRO chat
async def test_eliminar_denegado(test_db, monkeypatch, usuario):
    feed_id = await _preparar(test_db, monkeypatch)
    update = _update(f"rss:del:{feed_id}", usuario)
    await handlers._on_toggle_or_delete(update, MagicMock())
    assert len(await _feeds(test_db)) == 1
    update.callback_query.answer.assert_awaited_once()
    assert update.callback_query.answer.await_args.kwargs.get("show_alert") is True
    update.callback_query.edit_message_text.assert_not_awaited()


@pytest.mark.asyncio
async def test_eliminar_permitido_al_admin_del_chat(test_db, monkeypatch):
    feed_id = await _preparar(test_db, monkeypatch)
    update = _update(f"rss:del:{feed_id}", ADMIN_A)
    await handlers._on_toggle_or_delete(update, MagicMock())
    assert await _feeds(test_db) == []


@pytest.mark.asyncio
async def test_pausar_denegado_y_permitido(test_db, monkeypatch):
    feed_id = await _preparar(test_db, monkeypatch)
    await handlers._on_toggle_or_delete(_update(f"rss:toggle:{feed_id}", EXTRANO), MagicMock())
    assert (await _feeds(test_db))[0]["activo"] == 1
    await handlers._on_toggle_or_delete(_update(f"rss:toggle:{feed_id}", ADMIN_A), MagicMock())
    assert (await _feeds(test_db))[0]["activo"] == 0


@pytest.mark.asyncio
async def test_cambiar_estilo_denegado_y_estilo_invalido(test_db, monkeypatch):
    feed_id = await _preparar(test_db, monkeypatch)
    await handlers._on_set_style(_update(f"rss:sset:{feed_id}:social", EXTRANO), MagicMock())
    assert (await _feeds(test_db))[0]["estilo"] == "texto"
    await handlers._on_set_style(_update(f"rss:sset:{feed_id}:inventado", ADMIN_A), MagicMock())
    assert (await _feeds(test_db))[0]["estilo"] == "texto"
    await handlers._on_set_style(_update(f"rss:sset:{feed_id}:social", ADMIN_A), MagicMock())
    assert (await _feeds(test_db))[0]["estilo"] == "social"


@pytest.mark.asyncio
async def test_menu_de_estilo_denegado(test_db, monkeypatch):
    feed_id = await _preparar(test_db, monkeypatch)
    update = _update(f"rss:smenu:{feed_id}", EXTRANO)
    await handlers._on_style_menu(update, MagicMock())
    update.callback_query.edit_message_text.assert_not_awaited()


@pytest.mark.asyncio
async def test_boton_de_feed_inexistente_no_lanza(test_db, monkeypatch):
    await _preparar(test_db, monkeypatch)
    update = _update("rss:del:9999", ADMIN_A)
    await handlers._on_toggle_or_delete(update, MagicMock())
    update.callback_query.edit_message_text.assert_not_awaited()


@pytest.mark.asyncio
async def test_myfeeds_solo_admin(test_db, monkeypatch):
    await _preparar(test_db, monkeypatch)
    chat_row = await test_db.fetchone("SELECT * FROM chats WHERE tg_chat_id = ?", (CHAT_A,))
    monkeypatch.setattr(handlers, "_resolver_chat_destino", AsyncMock(return_value=chat_row))

    update = MagicMock()
    update.effective_user.id = EXTRANO
    update.effective_message.reply_text = AsyncMock()
    await handlers.myfeeds_cmd(update, MagicMock())
    update.effective_message.reply_text.assert_awaited_once()
    assert "administradores" in update.effective_message.reply_text.await_args.args[0]

    update_admin = MagicMock()
    update_admin.effective_user.id = ADMIN_A
    update_admin.effective_message.reply_text = AsyncMock()
    await handlers.myfeeds_cmd(update_admin, MagicMock())
    assert "Feed" in update_admin.effective_message.reply_text.await_args.args[0]
