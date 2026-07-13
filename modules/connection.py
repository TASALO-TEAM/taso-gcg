"""Módulo connection — permite ver y ajustar la configuración básica de un
grupo/canal desde el chat privado con el bot, sin tener que escribir ahí.

Nota de alcance (ver ESTADO_DESARROLLO.md): esta primera versión cubre
consulta de info/config y ajustes básicos vía connection. Redirigir TODOS
los comandos de moderación (ban/warn/etc.) a través de la conexión es un
cambio más invasivo (tocar cada módulo) que se deja para una iteración
posterior, documentado como pendiente.
"""

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import Application, CommandHandler, ContextTypes

from core.database import db
from utils.decorators import is_user_admin, refresh_admin_cache

__mod_name__ = "Conexiones"


def get_connected_chat_id(context: ContextTypes.DEFAULT_TYPE) -> int | None:
    return context.user_data.get("connected_chat")


async def connect_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != "private":
        await update.effective_message.reply_text("Usa /connect en el chat privado conmigo.")
        return
    if not context.args or not context.args[0].lstrip("-").isdigit():
        await update.effective_message.reply_text(
            "Uso: /connect <id_del_chat>\n"
            "Tip: usa /id dentro del grupo/canal para obtener su ID."
        )
        return

    tg_chat_id = int(context.args[0])
    user_id = update.effective_user.id

    await refresh_admin_cache(context, tg_chat_id)
    if not await is_user_admin(context, tg_chat_id, user_id):
        await update.effective_message.reply_text(
            "No pude confirmar que seas administrador de ese chat (o el bot no está ahí)."
        )
        return

    try:
        chat = await context.bot.get_chat(tg_chat_id)
    except Exception as e:
        await update.effective_message.reply_text(f"No pude acceder a ese chat: {e}")
        return

    context.user_data["connected_chat"] = tg_chat_id
    await update.effective_message.reply_text(f"🔗 Conectado a: <b>{chat.title}</b>", parse_mode=ParseMode.HTML)


async def disconnect_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.pop("connected_chat", None)
    await update.effective_message.reply_text("🔌 Desconectado.")


async def connection_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tg_chat_id = get_connected_chat_id(context)
    if not tg_chat_id:
        await update.effective_message.reply_text("No estás conectado a ningún chat. Usa /connect <id>.")
        return

    chat_row = await db.fetchone("SELECT * FROM chats WHERE tg_chat_id = ?", (tg_chat_id,))
    if not chat_row:
        await update.effective_message.reply_text("El chat conectado ya no existe en la base de datos.")
        return

    settings = await db.get_chat_settings(chat_row["id"])
    feeds_activos = await db.fetchone(
        "SELECT COUNT(*) as n FROM feeds WHERE chat_id = ? AND activo = 1", (chat_row["id"],)
    )
    locks_activos = await db.fetchall(
        "SELECT tipo FROM locks WHERE chat_id = ? AND activo = 1", (chat_row["id"],)
    )

    texto = (
        f"🔗 <b>Conectado a:</b> {chat_row['titulo']}\n"
        f"ID: <code>{chat_row['tg_chat_id']}</code>\n"
        f"Oficial TASALO: {'✅' if chat_row['es_oficial_tasalo'] else '❌'}\n"
        f"Feeds RSS activos: {feeds_activos['n']}\n"
        f"Límite de avisos: {settings['warn_limit']}\n"
        f"Antiflood: {'activo' if settings['flood_limit'] else 'desactivado'}\n"
        f"Bloqueos: {', '.join(l['tipo'] for l in locks_activos) or 'ninguno'}"
    )
    await update.effective_message.reply_text(texto, parse_mode=ParseMode.HTML)


def register(application: Application, sudo_users):
    application.add_handler(CommandHandler("connect", connect_cmd))
    application.add_handler(CommandHandler("disconnect", disconnect_cmd))
    application.add_handler(CommandHandler("connection", connection_cmd))
