"""Módulo federation — versión simplificada del concepto de "federación" de Rose,
adaptada al caso concreto de TASALO: en vez de un sistema genérico multi-federación
con dueños/admins propios, usamos UNA sola federación implícita = "todos los chats
marcados es_oficial_tasalo". Un /fban en cualquiera de ellos se aplica en todos.

Por qué así y no como Rose: Rose necesita soportar miles de comunidades distintas
gestionando sus propias federaciones independientes. TASALO es una sola organización
gestionando sus propios chats — el modelo "una federación == tus chats oficiales" da
el mismo beneficio (bans sincronizados) sin la complejidad de gestionar membresías
de federación por separado.
"""

import asyncio
import html

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import Application, CommandHandler, ContextTypes

from core.database import db
from utils.decorators import user_admin, sudo_only, group_only
from utils.common import extract_target_user, raw_text_after_command

__mod_name__ = "Federación TASALO"


@group_only
@user_admin
async def fban_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Banea a un usuario en TODOS los chats oficiales TASALO a la vez."""
    user_id, nombre = extract_target_user(update)
    if not user_id:
        await update.effective_message.reply_text("Responde al mensaje de quien quieres banear de la federación.")
        return
    razon = raw_text_after_command(update) if context.args else None

    await db.execute(
        "INSERT INTO fed_bans(user_id, razon, baneado_por) VALUES (?,?,?) "
        "ON CONFLICT(user_id) DO UPDATE SET razon = excluded.razon",
        (user_id, razon, update.effective_user.id),
    )

    chats = await db.chats_oficiales()
    aplicados, fallidos = 0, 0
    for chat in chats:
        try:
            await context.bot.ban_chat_member(chat["tg_chat_id"], user_id)
            aplicados += 1
        except Exception:
            fallidos += 1
        await asyncio.sleep(0.3)

    texto = f"🌐 {nombre} baneado de la federación TASALO ({aplicados} chat(s)"
    if fallidos:
        texto += f", {fallidos} fallo(s)"
    texto += ")."
    if razon:
        texto += f"\nMotivo: {razon}"
    await update.effective_message.reply_text(texto)


@group_only
@user_admin
async def funban_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Revierte un fban en todos los chats oficiales."""
    user_id, nombre = extract_target_user(update)
    if not user_id:
        await update.effective_message.reply_text("Responde al mensaje o menciona a quien quieres desbanear.")
        return

    await db.execute("DELETE FROM fed_bans WHERE user_id = ?", (user_id,))

    chats = await db.chats_oficiales()
    for chat in chats:
        try:
            await context.bot.unban_chat_member(chat["tg_chat_id"], user_id, only_if_banned=True)
        except Exception:
            pass
        await asyncio.sleep(0.3)

    await update.effective_message.reply_text(f"✅ {nombre} fue removido de la federación TASALO.")


@sudo_only
async def fbanlist_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    filas = await db.fetchall("SELECT user_id, razon FROM fed_bans ORDER BY creado_en DESC LIMIT 50")
    if not filas:
        await update.effective_message.reply_text("No hay bans en la federación TASALO.")
        return
    lineas = [f"• <code>{f['user_id']}</code> — {html.escape(f['razon'] or 'sin motivo')}" for f in filas]
    await update.effective_message.reply_text(
        "🌐 <b>Federación TASALO — baneados:</b>\n" + "\n".join(lineas), parse_mode=ParseMode.HTML
    )


async def enforce_fed_ban_on_join(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Si alguien con fban intenta entrar a un chat oficial recién agregado, se banea al vuelo."""
    chat = update.effective_chat
    message = update.effective_message
    if not message or not message.new_chat_members:
        return
    chat_row = await db.fetchone("SELECT * FROM chats WHERE tg_chat_id = ?", (chat.id,))
    if not chat_row or not chat_row["es_oficial_tasalo"]:
        return
    for miembro in message.new_chat_members:
        if await db.is_fed_banned(miembro.id):
            try:
                await context.bot.ban_chat_member(chat.id, miembro.id)
            except Exception:
                pass


def register(application: Application, sudo_users):
    from telegram.ext import MessageHandler, filters
    application.add_handler(CommandHandler("fban", fban_cmd))
    application.add_handler(CommandHandler("funban", funban_cmd))
    application.add_handler(CommandHandler("fbanlist", fbanlist_cmd))
    application.add_handler(
        MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, enforce_fed_ban_on_join), group=0
    )
