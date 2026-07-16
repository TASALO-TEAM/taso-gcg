"""Tests del /id "pro": antes con reply a un post de canal reventaba (asumía
`from_user` siempre presente) y no había forma de sacarle el ID a un canal.
Ahora entrega bloques 👤/💬 con toda la info, incluyendo el origen real de
un mensaje reenviado."""

import datetime as dt
import os
import sys
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from telegram import MessageOriginChannel  # noqa: E402

import modules.admin as admin  # noqa: E402


class UsuarioFalso:
    def __init__(self, id, username=None, first_name="ersus", last_name=None,
                 is_bot=False, language_code="es", is_premium=False):
        self.id = id
        self.username = username
        self.first_name = first_name
        self.last_name = last_name
        self.is_bot = is_bot
        self.language_code = language_code
        self.is_premium = is_premium
        self.full_name = first_name if not last_name else f"{first_name} {last_name}"


class ChatFalso:
    def __init__(self, id, type="channel", title="BitBread Channel", username="BitBreadChannel"):
        self.id = id
        self.type = type
        self.title = title
        self.username = username
        self.full_name = None
        self.first_name = None


def test_bloque_usuario_tiene_el_formato_esperado():
    u = UsuarioFalso(id=1148031284, username="iamersus", first_name="ersus")
    bloque = admin._bloque_usuario(u, "You")
    lineas = bloque.splitlines()
    assert lineas[0] == "👤 <b>You</b>"
    assert " ├ id: <code>1148031284</code>" in lineas
    assert " ├ is_bot: false" in lineas
    assert " ├ first_name: ersus" in lineas
    assert " ├ username: @iamersus" in lineas
    assert lineas[-1].startswith(" └ created: ~ ") and lineas[-1].endswith("(?)")


def test_bloque_usuario_sin_username_ni_premium():
    u = UsuarioFalso(id=5, username=None, is_premium=False)
    bloque = admin._bloque_usuario(u, "You")
    assert " ├ username: -" in bloque.splitlines()
    assert "es (-)" in bloque  # sin Telegram Premium


def test_bloque_usuario_marca_premium():
    u = UsuarioFalso(id=5, is_premium=True)
    bloque = admin._bloque_usuario(u, "You")
    assert "es (⭐)" in bloque


def test_bloque_chat_tiene_el_formato_esperado():
    chat = ChatFalso(id=-1003273654121, title="BitBread Channel", username="BitBreadChannel", type="channel")
    bloque = admin._bloque_chat(chat, "Origin chat")
    lineas = bloque.splitlines()
    assert lineas[0] == "💬 <b>Origin chat</b>"
    assert " ├ id: <code>-1003273654121</code>" in lineas
    assert " ├ title: BitBread Channel" in lineas
    assert " ├ username: @BitBreadChannel" in lineas
    assert lineas[-1] == " └ type: channel"


def test_bloques_de_mensaje_reenviado_de_canal_agrega_origin_chat():
    """El caso reportado: alguien reenvía un post del canal a un grupo y
    responde /id a ese reenvío — antes esto no daba nada útil sobre el canal."""
    autor = UsuarioFalso(id=999, username="miembro_grupo", first_name="Miembro")
    origen = MessageOriginChannel(
        date=dt.datetime.now(),
        chat=ChatFalso(id=-1003273654121, title="BitBread Channel", username="BitBreadChannel"),
        message_id=10,
    )
    mensaje = MagicMock(from_user=autor, sender_chat=None, forward_origin=origen)

    bloques = admin._bloques_de_mensaje(mensaje)
    assert len(bloques) == 2
    assert bloques[0].startswith("👤 <b>Miembro</b>")
    assert bloques[1].startswith("💬 <b>Origin chat</b>")
    assert "BitBreadChannel" in bloques[1]


def test_bloques_de_mensaje_post_directo_de_canal_sin_usuario_real():
    """Un post directo del canal (sin reenviar) no tiene from_user real,
    solo sender_chat — antes esto tumbaba el comando con un AttributeError."""
    canal = ChatFalso(id=-1003273654121, title="BitBread Channel")
    mensaje = MagicMock(from_user=None, sender_chat=canal, forward_origin=None)

    bloques = admin._bloques_de_mensaje(mensaje)
    assert len(bloques) == 1
    assert bloques[0].startswith("💬")
    assert "BitBreadChannel" in bloques[0]


@pytest.mark.asyncio
async def test_id_cmd_caso_base_you_mas_origin_chat():
    """/id sin argumentos ni reply: yo + el chat donde se usó — el ejemplo
    exacto que pidió Ersus."""
    usuario = UsuarioFalso(id=1148031284, username="iamersus", first_name="ersus")
    chat = ChatFalso(id=-1003273654121, title="BitBread Channel", username="BitBreadChannel", type="channel")

    message = MagicMock(reply_to_message=None)
    message.reply_text = AsyncMock()
    update = MagicMock(effective_message=message, effective_chat=chat, effective_user=usuario)
    context = MagicMock(args=[])

    await admin.id_cmd(update, context)

    message.reply_text.assert_awaited_once()
    texto_enviado = message.reply_text.await_args.args[0]
    assert "👤 <b>You</b>" in texto_enviado
    assert "💬 <b>Origin chat</b>" in texto_enviado
    assert "iamersus" in texto_enviado
    assert "BitBreadChannel" in texto_enviado
