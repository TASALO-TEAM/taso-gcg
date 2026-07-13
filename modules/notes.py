"""Módulo notes — snippets de texto guardados por chat, accesibles con #nombre."""

import re

from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

from core.database import db
from utils.decorators import user_admin, group_only

__mod_name__ = "Notas"

HASHTAG_RE = re.compile(r"#(\w+)")


@group_only
@user_admin
async def save_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.effective_message.reply_text("Uso: /save <nombre> <contenido>  (o responde a un mensaje)")
        return
    nombre = context.args[0].lower()
    message = update.effective_message
    if message.reply_to_message:
        contenido = message.reply_to_message.text or message.reply_to_message.caption or ""
    else:
        contenido = " ".join(context.args[1:])
    if not contenido:
        await update.effective_message.reply_text("No encontré contenido para guardar.")
        return

    chat_row = await db.ensure_chat(update.effective_chat)
    await db.execute(
        "INSERT INTO notes(chat_id, nombre, contenido, creado_por) VALUES (?,?,?,?) "
        "ON CONFLICT(chat_id, nombre) DO UPDATE SET contenido = excluded.contenido",
        (chat_row["id"], nombre, contenido, update.effective_user.id),
    )
    await update.effective_message.reply_text(f"💾 Nota «{nombre}» guardada. Úsala con #{nombre} o /get {nombre}")


@group_only
@user_admin
async def clear_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.effective_message.reply_text("Uso: /clear <nombre>")
        return
    nombre = context.args[0].lower()
    chat_row = await db.ensure_chat(update.effective_chat)
    await db.execute("DELETE FROM notes WHERE chat_id = ? AND nombre = ?", (chat_row["id"], nombre))
    await update.effective_message.reply_text(f"🗑️ Nota «{nombre}» eliminada.")


async def get_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.effective_message.reply_text("Uso: /get <nombre>")
        return
    await _responder_nota(update, context.args[0].lower())


@group_only
async def notes_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_row = await db.ensure_chat(update.effective_chat)
    filas = await db.fetchall("SELECT nombre FROM notes WHERE chat_id = ?", (chat_row["id"],))
    if not filas:
        await update.effective_message.reply_text("No hay notas guardadas en este chat.")
        return
    lineas = ", ".join(f"#{f['nombre']}" for f in filas)
    await update.effective_message.reply_text(f"📝 Notas disponibles: {lineas}")


async def _responder_nota(update: Update, nombre: str):
    chat_row = await db.ensure_chat(update.effective_chat)
    fila = await db.fetchone(
        "SELECT contenido FROM notes WHERE chat_id = ? AND nombre = ?", (chat_row["id"], nombre)
    )
    if fila:
        await update.effective_message.reply_text(fila["contenido"])


async def _detectar_hashtag(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    message = update.effective_message
    if not chat or not message or not message.text or chat.type not in ("group", "supergroup"):
        return
    match = HASHTAG_RE.search(message.text)
    if match:
        await _responder_nota(update, match.group(1).lower())


def register(application: Application, sudo_users):
    application.add_handler(CommandHandler("save", save_cmd))
    application.add_handler(CommandHandler("clear", clear_cmd))
    application.add_handler(CommandHandler("get", get_cmd))
    application.add_handler(CommandHandler("notes", notes_cmd))
    application.add_handler(
        MessageHandler(filters.Regex(HASHTAG_RE) & filters.ChatType.GROUPS, _detectar_hashtag)
    )
