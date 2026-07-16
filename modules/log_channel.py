"""Módulo log_channel — canal donde se reportan las acciones de moderación.

Flujo (igual al de Rose, ya probado y familiar para cualquiera que haya usado
un bot de este tipo):
1. Se manda /setlog en el canal (el bot debe ser admin ahí).
2. El bot responde pidiendo reenviar ese mensaje al grupo que se quiere vincular.
3. Al reenviarlo en el grupo, queda vinculado.
"""

from telegram import MessageOriginChannel, Update
from telegram.constants import ParseMode
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

from core.database import db
from utils.decorators import user_admin, sudo_only

__mod_name__ = "Log de administración"

CATEGORIAS_VALIDAS = ("settings", "admin", "user", "automated", "reports", "other")

# Guarda temporalmente qué canal espera confirmación de vínculo (en memoria, vive
# solo mientras el bot está arriba — es un flujo de segundos, no hace falta DB).
_pendientes_setlog: dict[int, int] = {}  # {mensaje_id: tg_chat_id_del_canal}


@sudo_only
async def setlog_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    if chat.type != "channel":
        await update.effective_message.reply_text("Este comando se manda dentro del canal que quieres usar como log.")
        return
    msg = await update.effective_message.reply_text(
        "📎 Reenvía este mensaje al grupo que quieres que quede registrado en este canal."
    )
    _pendientes_setlog[msg.message_id] = chat.id


async def _detectar_reenvio_setlog(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Detecta el reenvío del mensaje de confirmación de /setlog dentro del grupo.

    Bug original: se exigía `message.reply_to_message`, algo que un reenvío
    normal de Telegram NUNCA trae (reenviar y responder son dos acciones
    distintas e incompatibles en el cliente) — por eso nunca se podía enlazar
    ningún canal. El dato correcto ya viene en `forward_origin`: para un
    reenvío que viene de un canal, Telegram entrega un `MessageOriginChannel`
    con el chat de origen y el message_id original, que es justo lo que hace
    falta para encontrar el /setlog pendiente (y de paso confirmar que el
    reenvío viene del mismo canal que lo pidió, no de cualquier otro).
    """
    message = update.effective_message
    origen = message.forward_origin
    if not isinstance(origen, MessageOriginChannel):
        return
    tg_chat_id_canal = _pendientes_setlog.pop(origen.message_id, None)
    if tg_chat_id_canal is None or tg_chat_id_canal != origen.chat.id:
        return

    chat_row = await db.ensure_chat(update.effective_chat)
    await db.execute(
        "INSERT INTO log_channels(chat_id, log_chat_tg_id) VALUES (?,?) "
        "ON CONFLICT(chat_id) DO UPDATE SET log_chat_tg_id = excluded.log_chat_tg_id",
        (chat_row["id"], tg_chat_id_canal),
    )
    await message.reply_text("✅ Este grupo ahora reporta sus acciones de moderación al canal indicado.")


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
    application.add_handler(MessageHandler(filters.FORWARDED & filters.ChatType.GROUPS, _detectar_reenvio_setlog))
