"""Módulo broadcast — difusión a todos los chats marcados como oficiales de TASALO.

Reservado a SUDO_USERS: es una acción de alto impacto (llega a todos los
canales/grupos oficiales a la vez), no algo que un admin cualquiera deba poder
disparar por accidente.
"""

import asyncio

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import Application, CommandHandler, ContextTypes

from core.database import db
from utils.common import raw_text_after_command
from utils.decorators import sudo_only

__mod_name__ = "Difusión"


@sudo_only
async def broadcast_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.effective_message
    if not context.args and not message.reply_to_message:
        await message.reply_text(
            "Uso: /broadcast <texto>  (o responde a un mensaje con /broadcast)"
        )
        return

    texto = raw_text_after_command(update) if context.args else None
    origen = message.reply_to_message

    chats = await db.chats_oficiales()
    if not chats:
        await message.reply_text("No hay chats marcados como oficiales TASALO todavía. Usa /marcaroficial.")
        return

    enviados, fallidos = 0, 0
    for chat in chats:
        try:
            if origen:
                await origen.copy(chat["tg_chat_id"])
            else:
                await context.bot.send_message(chat["tg_chat_id"], texto, parse_mode=ParseMode.HTML)
            enviados += 1
        except Exception:
            fallidos += 1
        await asyncio.sleep(0.5)  # margen prudente frente a los límites de envío de Telegram

    await db.execute(
        "INSERT INTO broadcast_log(mensaje, chats_alcanzados, enviado_por) VALUES (?,?,?)",
        (texto or "[contenido reenviado]", enviados, update.effective_user.id),
    )
    await message.reply_text(f"📣 Difusión enviada a {enviados} chat(s). Fallos: {fallidos}.")


@sudo_only
async def marcaroficial_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Marca el chat actual (o el ID pasado como argumento) como oficial de TASALO."""
    if context.args and context.args[0].lstrip("-").isdigit():
        tg_chat_id = int(context.args[0])
    else:
        tg_chat_id = update.effective_chat.id

    row = await db.fetchone("SELECT * FROM chats WHERE tg_chat_id = ?", (tg_chat_id,))
    if not row:
        await update.effective_message.reply_text(
            "Ese chat todavía no está registrado (el bot debe estar ya en él)."
        )
        return
    await db.set_oficial_tasalo(tg_chat_id, True)
    await update.effective_message.reply_text(f"⭐ {row['titulo'] or tg_chat_id} marcado como oficial TASALO.")


@sudo_only
async def desmarcaroficial_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.args and context.args[0].lstrip("-").isdigit():
        tg_chat_id = int(context.args[0])
    else:
        tg_chat_id = update.effective_chat.id
    await db.set_oficial_tasalo(tg_chat_id, False)
    await update.effective_message.reply_text("Chat desmarcado como oficial TASALO.")


@sudo_only
async def oficiales_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chats = await db.chats_oficiales()
    if not chats:
        await update.effective_message.reply_text("No hay chats oficiales marcados todavía.")
        return
    lineas = [f"• {c['titulo']} (<code>{c['tg_chat_id']}</code>)" for c in chats]
    await update.effective_message.reply_text(
        "⭐ <b>Chats oficiales TASALO:</b>\n" + "\n".join(lineas), parse_mode=ParseMode.HTML
    )


def register(application: Application, sudo_users):
    application.add_handler(CommandHandler("broadcast", broadcast_cmd))
    application.add_handler(CommandHandler("marcaroficial", marcaroficial_cmd))
    application.add_handler(CommandHandler("desmarcaroficial", desmarcaroficial_cmd))
    application.add_handler(CommandHandler("oficiales", oficiales_cmd))
