"""Módulo filters — respuestas automáticas por palabra clave (útil para FAQ de TASALO,
ej. "cómo uso el bot de tasas" -> respuesta guardada)."""

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import Application, CommandHandler, MessageHandler, filters as tg_filters, ContextTypes

from core.database import db
from utils.common import formatted_text_after_command
from utils.decorators import user_admin, group_only

__mod_name__ = "Filtros"


async def _check_filters(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    message = update.effective_message
    if not chat or not message or not message.text or chat.type not in ("group", "supergroup"):
        return

    chat_row = await db.ensure_chat(chat)
    disparadores = await db.fetchall(
        "SELECT disparador, respuesta FROM filters WHERE chat_id = ?", (chat_row["id"],)
    )
    texto = message.text.lower()
    for f in disparadores:
        if f["disparador"].lower() in texto:
            await message.reply_text(f["respuesta"], parse_mode=ParseMode.HTML)
            return


@group_only
@user_admin
async def filter_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Uso: /filter <disparador> <respuesta...>"""
    if len(context.args) < 2:
        await update.effective_message.reply_text("Uso: /filter <palabra clave> <respuesta>")
        return
    disparador = context.args[0].lower()
    respuesta = formatted_text_after_command(update, skip_tokens=1)
    chat_row = await db.ensure_chat(update.effective_chat)
    await db.execute(
        "INSERT INTO filters(chat_id, disparador, respuesta) VALUES (?,?,?) "
        "ON CONFLICT(chat_id, disparador) DO UPDATE SET respuesta = excluded.respuesta",
        (chat_row["id"], disparador, respuesta),
    )
    await update.effective_message.reply_text(f"✅ Filtro guardado para «{disparador}»")


@group_only
@user_admin
async def stop_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.effective_message.reply_text("Uso: /stop <palabra clave>")
        return
    disparador = " ".join(context.args).lower()
    chat_row = await db.ensure_chat(update.effective_chat)
    await db.execute(
        "DELETE FROM filters WHERE chat_id = ? AND disparador = ?", (chat_row["id"], disparador)
    )
    await update.effective_message.reply_text(f"🗑️ Filtro «{disparador}» eliminado.")


@group_only
async def filters_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_row = await db.ensure_chat(update.effective_chat)
    filas = await db.fetchall(
        "SELECT disparador FROM filters WHERE chat_id = ?", (chat_row["id"],)
    )
    if not filas:
        await update.effective_message.reply_text("No hay filtros configurados en este chat.")
        return
    lineas = ", ".join(f["disparador"] for f in filas)
    await update.effective_message.reply_text(f"📋 Filtros activos: {lineas}")


def register(application: Application, sudo_users):
    application.add_handler(CommandHandler("filter", filter_cmd))
    application.add_handler(CommandHandler("stop", stop_cmd))
    application.add_handler(CommandHandler("filters", filters_cmd))
    application.add_handler(
        MessageHandler(tg_filters.TEXT & tg_filters.ChatType.GROUPS & ~tg_filters.COMMAND, _check_filters),
        group=3,
    )
