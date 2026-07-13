import os
import sys
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import utils.decorators as decorators  # noqa: E402


def _update_falso(user_id=1, chat_id=-100, chat_type="supergroup"):
    update = MagicMock()
    update.effective_user.id = user_id
    update.effective_chat.id = chat_id
    update.effective_chat.type = chat_type
    update.effective_message.reply_text = AsyncMock()
    return update


@pytest.mark.asyncio
async def test_sudo_only_permite_a_sudo(monkeypatch):
    monkeypatch.setattr(decorators, "SUDO_USERS", {1, 2, 3})
    llamado = AsyncMock()

    @decorators.sudo_only
    async def comando(update, context):
        await llamado()

    update = _update_falso(user_id=2)
    await comando(update, context=MagicMock())
    llamado.assert_awaited_once()
    update.effective_message.reply_text.assert_not_called()


@pytest.mark.asyncio
async def test_sudo_only_bloquea_a_no_sudo(monkeypatch):
    monkeypatch.setattr(decorators, "SUDO_USERS", {1, 2, 3})
    llamado = AsyncMock()

    @decorators.sudo_only
    async def comando(update, context):
        await llamado()

    update = _update_falso(user_id=999)
    await comando(update, context=MagicMock())
    llamado.assert_not_awaited()
    update.effective_message.reply_text.assert_awaited_once()


@pytest.mark.asyncio
async def test_group_only_permite_en_grupo():
    llamado = AsyncMock()

    @decorators.group_only
    async def comando(update, context):
        await llamado()

    update = _update_falso(chat_type="supergroup")
    await comando(update, context=MagicMock())
    llamado.assert_awaited_once()


@pytest.mark.asyncio
async def test_group_only_bloquea_en_privado():
    llamado = AsyncMock()

    @decorators.group_only
    async def comando(update, context):
        await llamado()

    update = _update_falso(chat_type="private")
    await comando(update, context=MagicMock())
    llamado.assert_not_awaited()
    update.effective_message.reply_text.assert_awaited_once()


@pytest.mark.asyncio
async def test_user_admin_usa_cache_de_db(monkeypatch, test_db):
    monkeypatch.setattr(decorators, "db", test_db)
    monkeypatch.setattr(decorators, "SUDO_USERS", set())

    await test_db.cache_admins(-100, [(5, False), (6, True)])

    llamado = AsyncMock()

    @decorators.user_admin
    async def comando(update, context):
        await llamado()

    update_admin = _update_falso(user_id=5, chat_id=-100)
    await comando(update_admin, context=MagicMock())
    llamado.assert_awaited_once()

    llamado.reset_mock()
    update_no_admin = _update_falso(user_id=999, chat_id=-100)
    await comando(update_no_admin, context=MagicMock())
    llamado.assert_not_awaited()
    update_no_admin.effective_message.reply_text.assert_awaited_once()


@pytest.mark.asyncio
async def test_user_admin_sudo_siempre_pasa(monkeypatch, test_db):
    monkeypatch.setattr(decorators, "db", test_db)
    monkeypatch.setattr(decorators, "SUDO_USERS", {777})

    llamado = AsyncMock()

    @decorators.user_admin
    async def comando(update, context):
        await llamado()

    update = _update_falso(user_id=777, chat_id=-100)
    await comando(update, context=MagicMock())
    llamado.assert_awaited_once()
