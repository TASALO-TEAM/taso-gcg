"""Tests del fix de /setlog: antes se exigía `reply_to_message` en el reenvío
(algo que un reenvío normal de Telegram nunca trae), así que nunca se podía
enlazar ningún canal de log. El dato correcto viene en `forward_origin`."""

import datetime as dt
import os
import sys
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from telegram import MessageOriginChannel, MessageOriginUser  # noqa: E402

import modules.log_channel as log_channel  # noqa: E402


class ChatFalso:
    def __init__(self, id, type="supergroup", title="Chat de prueba", username=None):
        self.id = id
        self.type = type
        self.title = title
        self.username = username
        self.full_name = None
        self.first_name = None


def _mensaje_reenviado(forward_origin, chat_id=-100999):
    m = MagicMock()
    m.forward_origin = forward_origin
    m.reply_text = AsyncMock()
    return m


def _update_falso(message, chat):
    u = MagicMock()
    u.effective_message = message
    u.effective_chat = chat
    return u


@pytest.fixture(autouse=True)
def _limpiar_pendientes():
    log_channel._pendientes_setlog.clear()
    yield
    log_channel._pendientes_setlog.clear()


@pytest.mark.asyncio
async def test_reenvio_de_canal_vincula_correctamente(monkeypatch, test_db):
    monkeypatch.setattr(log_channel, "db", test_db)
    canal_id = -1003273654121
    log_channel._pendientes_setlog[42] = canal_id  # /setlog mandó el msg 42 en ese canal

    origen = MessageOriginChannel(date=dt.datetime.now(), chat=ChatFalso(id=canal_id), message_id=42)
    grupo = ChatFalso(id=-100555, type="supergroup")
    message = _mensaje_reenviado(origen)
    update = _update_falso(message, grupo)

    await log_channel._detectar_reenvio_setlog(update, context=MagicMock())

    chat_row = await test_db.fetchone("SELECT * FROM chats WHERE tg_chat_id = ?", (grupo.id,))
    fila = await test_db.fetchone("SELECT * FROM log_channels WHERE chat_id = ?", (chat_row["id"],))
    assert fila is not None
    assert fila["log_chat_tg_id"] == canal_id
    message.reply_text.assert_awaited_once()
    # El pendiente se consume (no se puede reusar dos veces)
    assert 42 not in log_channel._pendientes_setlog


@pytest.mark.asyncio
async def test_reenvio_de_canal_distinto_no_vincula(monkeypatch, test_db):
    """Si el message_id coincide mismo por casualidad pero el canal de origen
    NO es el que pidió el /setlog, no debe vincularse (chequeo de seguridad)."""
    monkeypatch.setattr(log_channel, "db", test_db)
    log_channel._pendientes_setlog[42] = -100111  # canal que sí pidió el setlog

    origen = MessageOriginChannel(date=dt.datetime.now(), chat=ChatFalso(id=-100999), message_id=42)
    grupo = ChatFalso(id=-100555, type="supergroup")
    message = _mensaje_reenviado(origen)
    update = _update_falso(message, grupo)

    await log_channel._detectar_reenvio_setlog(update, context=MagicMock())

    chat_row = await test_db.fetchone("SELECT * FROM chats WHERE tg_chat_id = ?", (grupo.id,))
    assert chat_row is None  # ni siquiera se llegó a tocar la DB
    message.reply_text.assert_not_awaited()


@pytest.mark.asyncio
async def test_reenvio_de_usuario_se_ignora(monkeypatch, test_db):
    """Un reenvío que no viene de un canal (viene de un usuario) no debe
    intentar vincular nada — antes ni esto se distinguía correctamente."""
    monkeypatch.setattr(log_channel, "db", test_db)
    log_channel._pendientes_setlog[42] = -100111

    origen = MessageOriginUser(date=dt.datetime.now(), sender_user=MagicMock(id=1, full_name="Alguien"))
    grupo = ChatFalso(id=-100555, type="supergroup")
    message = _mensaje_reenviado(origen)
    update = _update_falso(message, grupo)

    await log_channel._detectar_reenvio_setlog(update, context=MagicMock())

    assert 42 in log_channel._pendientes_setlog  # el pendiente sigue intacto
    message.reply_text.assert_not_awaited()


@pytest.mark.asyncio
async def test_mensaje_sin_reenvio_se_ignora(monkeypatch, test_db):
    monkeypatch.setattr(log_channel, "db", test_db)
    message = _mensaje_reenviado(forward_origin=None)
    update = _update_falso(message, ChatFalso(id=-100555))

    await log_channel._detectar_reenvio_setlog(update, context=MagicMock())
    message.reply_text.assert_not_awaited()
