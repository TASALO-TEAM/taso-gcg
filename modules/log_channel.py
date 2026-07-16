"""Módulo log_channel — canal donde se reportan las acciones de moderación.

Flujo: un sudo manda /setlog @canalusername dentro del grupo que se quiere
vincular (el bot debe ser admin en ese canal). Se resuelve el canal por su
username público y se guarda el vínculo directo, sin pasos intermedios.

Nota de diseño: el flujo antiguo pedía mandar /setlog dentro del propio canal
y luego reenviar la confirmación al grupo. Eso era inviable: cuando un
mensaje se publica como post de un canal, Telegram no manda el campo `from`
(el post aparece como del canal, no de una persona), así que
`update.effective_user` siempre es None ahí — cualquier chequeo de permisos
basado en el usuario (como @sudo_only) nunca podía pasar. Por eso quedó
reescrito para que el comando se mande siempre desde un chat con un usuario
real detrás (el grupo).
"""

from telegram import Update
from telegram.constants import ParseMode
from telegram.error import TelegramError
from telegram.ext import Application, CommandHandler, ContextTypes

from core.database import db
from utils.decorators import ADMIN_STATUSES, user_admin, sudo_only

__mod_name__ = "Log de administración"

CATEGORIAS_VALIDAS = ("settings", "admin", "user", "automated", "reports", "other")


@sudo_only
async def setlog_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    if chat.type not in ("group", "supergroup"):
        await update.effective_message.reply_text(
            "Este comando se manda dentro del grupo que quieres vincular a un canal de log."
        )
        return
    if not context.args:
        await update.effective_message.reply_text(
            "Uso: /setlog @canalusername (el bot debe ser admin en ese canal)."
        )
        return
    username_canal = context.args[0].lstrip("@")

    try:
        canal = await context.bot.get_chat(f"@{username_canal}")
    except TelegramError:
        await update.effective_message.reply_text(
            f"No pude encontrar el canal @{username_canal}. Revisa que el username sea correcto "
            "y que el canal sea público."
        )
        return
    if canal.type != "channel":
        await update.effective_message.reply_text(f"@{username_canal} no es un canal.")
        return

    try:
        miembro_bot = await context.bot.get_chat_member(canal.id, context.bot.id)
    except TelegramError:
        await update.effective_message.reply_text(
            f"No pude verificar mis permisos en @{username_canal}. ¿Estoy agregado ahí?"
        )
        return
    if miembro_bot.status not in ADMIN_STATUSES:
        await update.effective_message.reply_text(
            f"Necesito ser administrador en @{username_canal} para usarlo como canal de log."
        )
        return

    chat_row = await db.ensure_chat(chat)
    await db.execute(
        "INSERT INTO log_channels(chat_id, log_chat_tg_id) VALUES (?,?) "
        "ON CONFLICT(chat_id) DO UPDATE SET log_chat_tg_id = excluded.log_chat_tg_id",
        (chat_row["id"], canal.id),
    )
    await update.effective_message.reply_text(
        f"✅ Este grupo ahora reporta sus acciones de moderación a @{username_canal}."
    )


@user_admin
async def unsetlog_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_row = await db.ensure_chat(update.effective_chat)
    await db.execute("DELETE FROM log_channels WHERE chat_id = ?", (chat_row["id"],))
    await update.effective_message.reply_text("🔕 Este grupo ya no reporta a ningún canal de log.")


async def logchannel_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_row = await db.ensure_chat(update.effective_chat)
    fila = await db.fetchone("SELECT * FROM log_channels WHERE chat_id = ?", (chat_row["id"],))
    if not fila:
        await update.effective_message.reply_text("Este grupo no tiene un canal de log configurado.")
        return
    try:
        canal = await context.bot.get_chat(fila["log_chat_tg_id"])
        nombre = canal.title
    except Exception:
        nombre = str(fila["log_chat_tg_id"])
    await update.effective_message.reply_text(f"📋 Canal de log actual: {nombre}\nCategorías: {fila['categorias']}")


@user_admin
async def log_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _actualizar_categorias(update, context, activar=True)


@user_admin
async def nolog_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _actualizar_categorias(update, context, activar=False)


async def _actualizar_categorias(update, context, activar: bool):
    solicitadas = [c.lower() for c in (context.args or []) if c.lower() in CATEGORIAS_VALIDAS]
    if not solicitadas:
        await update.effective_message.reply_text(
            "Categorías válidas: " + ", ".join(CATEGORIAS_VALIDAS)
        )
        return
    chat_row = await db.ensure_chat(update.effective_chat)
    fila = await db.fetchone("SELECT * FROM log_channels WHERE chat_id = ?", (chat_row["id"],))
    if not fila:
        await update.effective_message.reply_text("Este grupo no tiene un canal de log configurado. Usa /setlog primero.")
        return
    actuales = set(fila["categorias"].split(","))
    if activar:
        actuales |= set(solicitadas)
    else:
        actuales -= set(solicitadas)
    await db.execute(
        "UPDATE log_channels SET categorias = ? WHERE chat_id = ?",
        (",".join(sorted(actuales)), chat_row["id"]),
    )
    await update.effective_message.reply_text("✅ Categorías de log actualizadas.")


async def enviar_log(context: ContextTypes.DEFAULT_TYPE, tg_chat_id: int, categoria: str, texto: str):
    """Función de utilidad que otros módulos pueden importar para mandar un evento
    al canal de log del chat, si tiene uno configurado y la categoría está activa."""
    chat_row = await db.fetchone("SELECT id FROM chats WHERE tg_chat_id = ?", (tg_chat_id,))
    if not chat_row:
        return
    fila = await db.fetchone("SELECT * FROM log_channels WHERE chat_id = ?", (chat_row["id"],))
    if not fila or categoria not in fila["categorias"].split(","):
        return
    try:
        await context.bot.send_message(fila["log_chat_tg_id"], texto, parse_mode=ParseMode.HTML)
    except Exception:
        pass


def register(application: Application, sudo_users):
    application.add_handler(CommandHandler("setlog", setlog_cmd))
    application.add_handler(CommandHandler("unsetlog", unsetlog_cmd))
    application.add_handler(CommandHandler("logchannel", logchannel_cmd))
    application.add_handler(CommandHandler("log", log_cmd))
    application.add_handler(CommandHandler("nolog", nolog_cmd))
