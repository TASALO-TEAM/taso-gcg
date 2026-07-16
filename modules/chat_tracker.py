"""Registro automático de chats (y de usuarios).

Cada vez que el bot recibe cualquier update de un chat (mensaje, o cambio de
su propio estado de membresía), nos aseguramos de que ese chat exista en la
tabla `chats`. Así el resto de módulos (warns, locks, feeds...) siempre pueden
asumir que el chat ya está en la base de datos.

Además, cada mensaje con remitente real actualiza la caché de usuarios
(tabla `users`, ver core/database.py). Esto es lo único que hace posible
resolver un `@username` a su user_id en /ban, /mute, /id, etc. — la Bot API
de Telegram no deja buscar un usuario cualquiera por username si el bot
nunca lo ha "visto" antes, a diferencia de grupos/canales.
"""

from telegram import Update
from telegram.ext import Application, ChatMemberHandler, MessageHandler, filters, ContextTypes

from core.database import db
from utils.logger import log


async def _track_from_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat:
        await db.ensure_chat(update.effective_chat)
    if update.effective_user:
        await db.upsert_user(update.effective_user)


async def _on_bot_membership_change(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Se dispara cuando añaden/expulsan/promueven al bot en un chat."""
    result = update.my_chat_member
    if not result:
        return
    chat = result.chat
    await db.ensure_chat(chat)

    nuevo_estado = result.new_chat_member.status
    if nuevo_estado in ("member", "administrator"):
        log(f"Bot añadido/actualizado en: {chat.title or chat.id} ({nuevo_estado})")
    elif nuevo_estado in ("left", "kicked"):
        row = await db.fetchone("SELECT id FROM chats WHERE tg_chat_id = ?", (chat.id,))
        if row:
            await db.execute("UPDATE chats SET activo = 0 WHERE id = ?", (row["id"],))
        log(f"Bot removido de: {chat.title or chat.id}")


def register(application: Application, sudo_users):
    # Cualquier mensaje de texto en grupo/canal actualiza el registro del chat
    application.add_handler(
        MessageHandler(filters.ALL & filters.ChatType.GROUPS, _track_from_message), group=-1
    )
    application.add_handler(ChatMemberHandler(_on_bot_membership_change, ChatMemberHandler.MY_CHAT_MEMBER))
