"""Módulo welcome — bienvenida/despedida configurables, con placeholders simples."""

import html

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

from core.database import db
from utils.common import raw_text_after_command
from utils.decorators import user_admin, group_only

__mod_name__ = "Bienvenida"

DEFAULT_WELCOME = "👋 ¡Bienvenido/a {mencion} a {chat}!"
DEFAULT_GOODBYE = "👋 {mencion} salió del grupo."


def _reemplazar(texto: str, user, chat) -> str:
    # Se escapa primero el texto del admin (puede traer < > & sueltos) y recién
    # después se insertan los placeholders con HTML real, para no romper el
    # parse_mode="HTML" ni escapar la mención generada.
    texto = html.escape(texto)
    return (
        texto.replace("{mencion}", user.mention_html())
        .replace("{nombre}", html.escape(user.full_name))
        .replace("{chat}", html.escape(chat.title or ""))
    )


async def _on_member_join(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    chat_row = await db.ensure_chat(chat)
    settings = await db.get_chat_settings(chat_row["id"])
    if not settings["welcome_enabled"]:
        return
    texto_base = settings["welcome_text"] or DEFAULT_WELCOME
    for miembro in update.effective_message.new_chat_members:
        if miembro.is_bot and miembro.id == context.bot.id:
            continue  # el propio bot entrando no cuenta
        texto = _reemplazar(texto_base, miembro, chat)
        await update.effective_message.reply_text(texto, parse_mode=ParseMode.HTML)


async def _on_member_left(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    chat_row = await db.ensure_chat(chat)
    settings = await db.get_chat_settings(chat_row["id"])
    if not settings["goodbye_enabled"]:
        return
    miembro = update.effective_message.left_chat_member
    if not miembro or miembro.id == context.bot.id:
        return
    texto_base = settings["goodbye_text"] or DEFAULT_GOODBYE
    texto = _reemplazar(texto_base, miembro, chat)
    await update.effective_message.reply_text(texto, parse_mode=ParseMode.HTML)


@group_only
@user_admin
async def setwelcome_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.effective_message.reply_text(
            "Uso: /setwelcome <texto>\nPlaceholders: {mencion} {nombre} {chat}"
        )
        return
    texto = raw_text_after_command(update)
    chat_row = await db.ensure_chat(update.effective_chat)
    await db.update_chat_settings(chat_row["id"], welcome_enabled=1, welcome_text=texto)
    await update.effective_message.reply_text("✅ Mensaje de bienvenida configurado.")


@group_only
@user_admin
async def setgoodbye_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.effective_message.reply_text(
            "Uso: /setgoodbye <texto>\nPlaceholders: {mencion} {nombre} {chat}"
        )
        return
    texto = raw_text_after_command(update)
    chat_row = await db.ensure_chat(update.effective_chat)
    await db.update_chat_settings(chat_row["id"], goodbye_enabled=1, goodbye_text=texto)
    await update.effective_message.reply_text("✅ Mensaje de despedida configurado.")


@group_only
@user_admin
async def welcome_toggle_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args or context.args[0].lower() not in ("on", "off"):
        await update.effective_message.reply_text("Uso: /welcome on|off")
        return
    chat_row = await db.ensure_chat(update.effective_chat)
    await db.update_chat_settings(chat_row["id"], welcome_enabled=1 if context.args[0].lower() == "on" else 0)
    await update.effective_message.reply_text(f"✅ Bienvenida: {context.args[0].lower()}")


def register(application: Application, sudo_users):
    application.add_handler(CommandHandler("setwelcome", setwelcome_cmd))
    application.add_handler(CommandHandler("setgoodbye", setgoodbye_cmd))
    application.add_handler(CommandHandler("welcome", welcome_toggle_cmd))
    application.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, _on_member_join))
    application.add_handler(MessageHandler(filters.StatusUpdate.LEFT_CHAT_MEMBER, _on_member_left))
