"""Módulo reporting — /report notifica a los admins del chat vía mención."""

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import Application, CommandHandler, ContextTypes

from utils.decorators import group_only

__mod_name__ = "Reportes"


@group_only
async def report_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.effective_message
    chat = update.effective_chat
    if not message.reply_to_message:
        await message.reply_text("Responde al mensaje que quieres reportar con /report.")
        return

    try:
        admins = await context.bot.get_chat_administrators(chat.id)
    except Exception:
        await message.reply_text("No pude obtener la lista de administradores.")
        return

    menciones = " ".join(
        a.user.mention_html() for a in admins if not a.user.is_bot
    )
    if not menciones:
        await message.reply_text("No hay administradores disponibles para notificar.")
        return

    reportado = message.reply_to_message.from_user
    texto = (
        f"🚨 <b>Reporte</b>\n"
        f"{update.effective_user.mention_html()} reportó un mensaje de "
        f"{reportado.mention_html() if reportado else 'usuario desconocido'}.\n"
        f"{menciones}"
    )
    await message.reply_to_message.reply_text(texto, parse_mode=ParseMode.HTML)


def register(application: Application, sudo_users):
    application.add_handler(CommandHandler(["report", "reportar"], report_cmd))
