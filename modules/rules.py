"""Módulo rules — reglas fijadas del grupo."""

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

from core.database import db
from utils.decorators import user_admin, group_only

__mod_name__ = "Reglas"


@group_only
async def rules_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_row = await db.ensure_chat(update.effective_chat)
    settings = await db.get_chat_settings(chat_row["id"])
    if not settings["rules_text"]:
        await update.effective_message.reply_text("Este grupo todavía no tiene reglas configuradas.")
        return
    await update.effective_message.reply_text(f"📜 <b>Reglas del grupo:</b>\n\n{settings['rules_text']}",
                                               parse_mode="HTML")


@group_only
@user_admin
async def setrules_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.effective_message.reply_text("Uso: /setrules <texto de las reglas>")
        return
    texto = " ".join(context.args)
    chat_row = await db.ensure_chat(update.effective_chat)
    await db.update_chat_settings(chat_row["id"], rules_text=texto)
    await update.effective_message.reply_text("✅ Reglas actualizadas.")


def register(application: Application, sudo_users):
    application.add_handler(CommandHandler("rules", rules_cmd))
    application.add_handler(CommandHandler("setrules", setrules_cmd))
