"""Módulo locks — restringe tipos de contenido específicos en el chat."""

import re

from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

from core.database import db
from utils.decorators import user_admin, bot_admin, group_only

__mod_name__ = "Locks"

TIPOS_VALIDOS = (
    "stickers", "links", "forwards", "photos", "videos", "documents",
    "voice", "polls", "games", "inlinebots",
)

URL_RE = re.compile(r"https?://|t\.me/|www\.", re.IGNORECASE)


def _mensaje_viola_lock(message, tipo: str) -> bool:
    if tipo == "stickers":
        return bool(message.sticker)
    if tipo == "links":
        texto = message.text or message.caption or ""
        return bool(URL_RE.search(texto))
    if tipo == "forwards":
        return bool(message.forward_origin)
    if tipo == "photos":
        return bool(message.photo)
    if tipo == "videos":
        return bool(message.video)
    if tipo == "documents":
        return bool(message.document)
    if tipo == "voice":
        return bool(message.voice or message.video_note)
    if tipo == "polls":
        return bool(message.poll)
    if tipo == "games":
        return bool(message.game)
    return False


async def _enforce_locks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    message = update.effective_message
    if not chat or not message or chat.type not in ("group", "supergroup"):
        return

    chat_row = await db.ensure_chat(chat)
    if message.from_user and await db.is_approved(chat_row["id"], message.from_user.id):
        return  # usuario aprobado: inmune a los locks
    activos = await db.fetchall(
        "SELECT tipo FROM locks WHERE chat_id = ? AND activo = 1", (chat_row["id"],)
    )
    if not activos:
        return

    for fila in activos:
        if _mensaje_viola_lock(message, fila["tipo"]):
            try:
                await message.delete()
            except Exception:
                pass
            return


@group_only
@user_admin
@bot_admin
async def lock_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args or context.args[0].lower() not in TIPOS_VALIDOS:
        await update.effective_message.reply_text(
            "Uso: /lock <tipo>\nTipos válidos: " + ", ".join(TIPOS_VALIDOS)
        )
        return
    tipo = context.args[0].lower()
    chat_row = await db.ensure_chat(update.effective_chat)
    await db.execute(
        "INSERT INTO locks(chat_id, tipo, activo) VALUES (?,?,1) "
        "ON CONFLICT(chat_id, tipo) DO UPDATE SET activo = 1",
        (chat_row["id"], tipo),
    )
    await update.effective_message.reply_text(f"🔒 Bloqueado: {tipo}")


@group_only
@user_admin
@bot_admin
async def unlock_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args or context.args[0].lower() not in TIPOS_VALIDOS:
        await update.effective_message.reply_text(
            "Uso: /unlock <tipo>\nTipos válidos: " + ", ".join(TIPOS_VALIDOS)
        )
        return
    tipo = context.args[0].lower()
    chat_row = await db.ensure_chat(update.effective_chat)
    await db.execute(
        "UPDATE locks SET activo = 0 WHERE chat_id = ? AND tipo = ?", (chat_row["id"], tipo)
    )
    await update.effective_message.reply_text(f"🔓 Desbloqueado: {tipo}")


@group_only
async def locks_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_row = await db.ensure_chat(update.effective_chat)
    activos = await db.fetchall(
        "SELECT tipo FROM locks WHERE chat_id = ? AND activo = 1", (chat_row["id"],)
    )
    if not activos:
        await update.effective_message.reply_text("No hay bloqueos activos en este chat.")
        return
    tipos = ", ".join(f["tipo"] for f in activos)
    await update.effective_message.reply_text(f"🔒 Bloqueados actualmente: {tipos}")


def register(application: Application, sudo_users):
    application.add_handler(CommandHandler("lock", lock_cmd))
    application.add_handler(CommandHandler("unlock", unlock_cmd))
    application.add_handler(CommandHandler("locks", locks_cmd))
    application.add_handler(MessageHandler(filters.ALL & filters.ChatType.GROUPS, _enforce_locks), group=2)
