"""Módulo blacklist — palabras prohibidas por chat, con acción configurable."""

from telegram import Update, ChatPermissions
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

from core.database import db
from utils.decorators import user_admin, bot_admin, group_only

__mod_name__ = "Lista negra"

ACCIONES_VALIDAS = ("delete", "warn", "ban")


async def _check_blacklist(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    message = update.effective_message
    if not chat or not message or chat.type not in ("group", "supergroup"):
        return
    texto = (message.text or message.caption or "").lower()
    if not texto:
        return

    chat_row = await db.ensure_chat(chat)
    if await db.is_approved(chat_row["id"], message.from_user.id):
        return  # usuario aprobado: inmune a la lista negra
    palabras = await db.fetchall(
        "SELECT palabra, accion FROM blacklist WHERE chat_id = ?", (chat_row["id"],)
    )
    for fila in palabras:
        if fila["palabra"].lower() in texto:
            await _aplicar_accion(update, context, fila["accion"])
            return


async def _aplicar_accion(update: Update, context: ContextTypes.DEFAULT_TYPE, accion: str):
    message = update.effective_message
    chat = update.effective_chat
    user = update.effective_user
    try:
        await message.delete()
    except Exception:
        pass

    if accion == "warn":
        chat_row = await db.ensure_chat(chat)
        await db.execute(
            "INSERT INTO warns(chat_id, user_id, razon, dado_por) VALUES (?,?,?,?)",
            (chat_row["id"], user.id, "Palabra prohibida", context.bot.id),
        )
    elif accion == "ban":
        try:
            await context.bot.ban_chat_member(chat.id, user.id)
        except Exception:
            pass


@group_only
@user_admin
async def addblacklist_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.effective_message.reply_text(
            "Uso: /addblacklist <palabra> [delete|warn|ban]  (delete por defecto)"
        )
        return
    accion = "delete"
    palabras = context.args
    if context.args[-1].lower() in ACCIONES_VALIDAS:
        accion = context.args[-1].lower()
        palabras = context.args[:-1]
    palabra = " ".join(palabras).lower()
    if not palabra:
        await update.effective_message.reply_text("Indica la palabra a prohibir.")
        return

    chat_row = await db.ensure_chat(update.effective_chat)
    await db.execute(
        "INSERT INTO blacklist(chat_id, palabra, accion) VALUES (?,?,?) "
        "ON CONFLICT(chat_id, palabra) DO UPDATE SET accion = excluded.accion",
        (chat_row["id"], palabra, accion),
    )
    await update.effective_message.reply_text(f"🚫 Añadida a la lista negra: «{palabra}» ({accion})")


@group_only
@user_admin
async def rmblacklist_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.effective_message.reply_text("Uso: /rmblacklist <palabra>")
        return
    palabra = " ".join(context.args).lower()
    chat_row = await db.ensure_chat(update.effective_chat)
    await db.execute(
        "DELETE FROM blacklist WHERE chat_id = ? AND palabra = ?", (chat_row["id"], palabra)
    )
    await update.effective_message.reply_text(f"✅ Eliminada de la lista negra: «{palabra}»")


@group_only
async def blacklist_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_row = await db.ensure_chat(update.effective_chat)
    filas = await db.fetchall(
        "SELECT palabra, accion FROM blacklist WHERE chat_id = ?", (chat_row["id"],)
    )
    if not filas:
        await update.effective_message.reply_text("No hay palabras en la lista negra de este chat.")
        return
    lineas = [f"• {f['palabra']} ({f['accion']})" for f in filas]
    await update.effective_message.reply_text("🚫 Lista negra:\n" + "\n".join(lineas))


def register(application: Application, sudo_users):
    application.add_handler(CommandHandler("addblacklist", addblacklist_cmd))
    application.add_handler(CommandHandler("rmblacklist", rmblacklist_cmd))
    application.add_handler(CommandHandler("blacklist", blacklist_cmd))
    application.add_handler(MessageHandler(filters.TEXT & filters.ChatType.GROUPS, _check_blacklist), group=2)
