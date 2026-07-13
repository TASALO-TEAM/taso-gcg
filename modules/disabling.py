"""Módulo disabling — permite desactivar comandos puntuales para usuarios no-admin
en un chat (ej. si no quieres que cualquiera use /notes o /filters).

Intercepta CUALQUIER comando en group=-3 (antes que el resto de módulos) y corta
la propagación con ApplicationHandlerStop si el comando está desactivado — así
el handler "real" del comando ni se entera de que llegó el update.
"""

from telegram import Update
from telegram.ext import (
    Application, ApplicationHandlerStop, CommandHandler, MessageHandler,
    filters, ContextTypes,
)

from core.database import db
from utils.decorators import user_admin, is_user_admin

__mod_name__ = "Deshabilitar comandos"

# Comandos que tiene sentido poder deshabilitar (los "de lectura" que un usuario
# normal podría spammear, no los que ya son solo-admin de por sí).
DISABLEABLE = (
    "admins", "id", "rules", "notes", "filters", "warns", "connection",
    "oficiales", "approved", "locks", "disabled",
)


async def _check_disabled(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.effective_message
    chat = update.effective_chat
    if not message or not message.text or not message.text.startswith("/"):
        return
    comando = message.text[1:].split()[0].split("@")[0].lower()
    if comando not in DISABLEABLE:
        return

    chat_row = await db.ensure_chat(chat)
    if not await db.is_command_disabled(chat_row["id"], comando):
        return

    settings = await db.get_chat_settings(chat_row["id"])
    es_admin = await is_user_admin(context, chat.id, update.effective_user.id)
    if es_admin and not settings["disable_admin"]:
        return  # los admins siguen pudiendo usarlo salvo que disableadmin esté on

    if settings["disable_del"]:
        try:
            await message.delete()
        except Exception:
            pass
    raise ApplicationHandlerStop  # el comando desactivado ni llega a su handler real


async def disable_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args or context.args[0].lower() not in DISABLEABLE:
        await update.effective_message.reply_text(
            "Uso: /disable <comando>\nDeshabilitables: " + ", ".join(DISABLEABLE)
        )
        return
    comando = context.args[0].lower()
    chat_row = await db.ensure_chat(update.effective_chat)
    await db.execute(
        "INSERT OR IGNORE INTO disabled_commands(chat_id, comando) VALUES (?,?)",
        (chat_row["id"], comando),
    )
    await update.effective_message.reply_text(f"🚫 /{comando} deshabilitado para usuarios normales.")


async def enable_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.effective_message.reply_text("Uso: /enable <comando>")
        return
    comando = context.args[0].lower()
    chat_row = await db.ensure_chat(update.effective_chat)
    await db.execute(
        "DELETE FROM disabled_commands WHERE chat_id = ? AND comando = ?", (chat_row["id"], comando)
    )
    await update.effective_message.reply_text(f"✅ /{comando} habilitado de nuevo.")


async def disabled_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_row = await db.ensure_chat(update.effective_chat)
    filas = await db.fetchall(
        "SELECT comando FROM disabled_commands WHERE chat_id = ?", (chat_row["id"],)
    )
    if not filas:
        await update.effective_message.reply_text("No hay comandos deshabilitados en este chat.")
        return
    await update.effective_message.reply_text(
        "🚫 Deshabilitados: " + ", ".join(f"/{f['comando']}" for f in filas)
    )


async def disableable_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text("Comandos que se pueden deshabilitar:\n" + ", ".join(DISABLEABLE))


@user_admin
async def disabledel_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args or context.args[0].lower() not in ("on", "off"):
        await update.effective_message.reply_text("Uso: /disabledel on|off")
        return
    chat_row = await db.ensure_chat(update.effective_chat)
    await db.update_chat_settings(chat_row["id"], disable_del=1 if context.args[0].lower() == "on" else 0)
    await update.effective_message.reply_text(f"✅ Borrado de comandos deshabilitados: {context.args[0].lower()}")


@user_admin
async def disableadmin_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args or context.args[0].lower() not in ("on", "off"):
        await update.effective_message.reply_text("Uso: /disableadmin on|off")
        return
    chat_row = await db.ensure_chat(update.effective_chat)
    await db.update_chat_settings(chat_row["id"], disable_admin=1 if context.args[0].lower() == "on" else 0)
    await update.effective_message.reply_text(f"✅ Deshabilitar también para admins: {context.args[0].lower()}")


@user_admin
async def disable_cmd_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await disable_cmd(update, context)


@user_admin
async def enable_cmd_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await enable_cmd(update, context)


def register(application: Application, sudo_users):
    application.add_handler(CommandHandler("disable", disable_cmd_admin))
    application.add_handler(CommandHandler("enable", enable_cmd_admin))
    application.add_handler(CommandHandler("disabled", disabled_cmd))
    application.add_handler(CommandHandler("disableable", disableable_cmd))
    application.add_handler(CommandHandler("disabledel", disabledel_cmd))
    application.add_handler(CommandHandler("disableadmin", disableadmin_cmd))
    application.add_handler(
        MessageHandler(filters.COMMAND & filters.ChatType.GROUPS, _check_disabled), group=-3
    )
