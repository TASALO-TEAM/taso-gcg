"""Módulo connection — permite ver y ajustar la configuración básica de un
grupo/canal desde el chat privado con el bot, sin tener que escribir ahí.

Cambios sobre la primera versión:
- La conexión ahora se guarda en SQLite (tabla `connections`), no en
  `context.user_data` — así sobrevive a un reinicio del bot. Antes, al
  reiniciar el proceso se perdía "de forma invisible" (los feeds seguían
  funcionando porque esos sí ya estaban en DB, pero /connection aparecía
  como si nunca te hubieras conectado).
- /connect ahora acepta @username del canal/grupo además del ID numérico,
  para no obligar a sacar el ID con /id salvo que sea un chat sin username
  (típicamente grupos privados sin enlace público).
- /connection sin argumentos ahora lista los chats a los que ya te
  conectaste antes (tabla `connection_history`), marcando cuál está activo
  ahora mismo. /connection <n> (o el botón equivalente) cambia la conexión
  activa a la posición n de esa lista y muestra su detalle — ya no hace
  falta volver a teclear el id/@usuario cada vez que cambias de chat.

Nota de alcance (ver ESTADO_DESARROLLO.md): esta primera versión cubre
consulta de info/config y ajustes básicos vía connection. Redirigir TODOS
los comandos de moderación (ban/warn/etc.) a través de la conexión es un
cambio más invasivo (tocar cada módulo) que se deja para una iteración
posterior, documentado como pendiente.
"""

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes

from core.database import db
from utils.decorators import is_user_admin, refresh_admin_cache

__mod_name__ = "Conexiones"

CB_PREFIX = "conn:"


async def get_connected_chat_id(user_id: int) -> int | None:
    return await db.get_connection(user_id)


async def _resolver_entrada_chat(context: ContextTypes.DEFAULT_TYPE, entrada: str):
    """Acepta tanto un ID numérico (-100123456789) como un @username.
    Devuelve (tg_chat_id, error) — error es None si todo salió bien."""
    entrada = entrada.strip()
    if entrada.lstrip("-").isdigit():
        return int(entrada), None

    username = entrada.lstrip("@")
    try:
        chat = await context.bot.get_chat(f"@{username}")
        return chat.id, None
    except Exception as e:
        return None, str(e)

async def connect_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != "private":
        await update.effective_message.reply_text("Usa /connect en el chat privado conmigo.")
        return
    if not context.args:
        await update.effective_message.reply_text(
            "Uso: /connect <@usuario_del_canal>  o  /connect <id_del_chat>\n"
            "El @usuario solo funciona si el canal/grupo es público. Si es privado, "
            "usa /id dentro de él para sacar el ID numérico."
        )
        return

    tg_chat_id, error = await _resolver_entrada_chat(context, context.args[0])
    if error:
        await update.effective_message.reply_text(
            f"No pude encontrar ese chat por username: {error}\n"
            "Si es un grupo/canal privado, usa /id dentro de él y conéctate con el ID."
        )
        return

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

    await db.set_connection(user_id, tg_chat_id)
    await db.record_connection_history(user_id, tg_chat_id, chat.title)
    await update.effective_message.reply_text(f"🔗 Conectado a: <b>{chat.title}</b>", parse_mode=ParseMode.HTML)


async def disconnect_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await db.clear_connection(update.effective_user.id)
    await update.effective_message.reply_text("🔌 Desconectado.")

async def _render_detalle_conexion(chat_row: dict) -> str:
    """Texto de detalle de un chat conectado — usado tanto por /connection
    tras seleccionar uno de la lista como por el flujo directo anterior."""
    settings = await db.get_chat_settings(chat_row["id"])
    feeds_activos = await db.fetchone(
        "SELECT COUNT(*) as n FROM feeds WHERE chat_id = ? AND activo = 1", (chat_row["id"],)
    )
    locks_activos = await db.fetchall(
        "SELECT tipo FROM locks WHERE chat_id = ? AND activo = 1", (chat_row["id"],)
    )
    return (
        f"🔗 <b>Conectado a:</b> {chat_row['titulo']}\n"
        f"ID: <code>{chat_row['tg_chat_id']}</code>\n"
        f"Oficial TASALO: {'✅' if chat_row['es_oficial_tasalo'] else '❌'}\n"
        f"Feeds RSS activos: {feeds_activos['n']}\n"
        f"Límite de avisos: {settings['warn_limit']}\n"
        f"Antiflood: {'activo' if settings['flood_limit'] else 'desactivado'}\n"
        f"Bloqueos: {', '.join(l['tipo'] for l in locks_activos) or 'ninguno'}"
    )


async def _activar_y_mostrar(update: Update, context: ContextTypes.DEFAULT_TYPE, tg_chat_id: int):
    """Fija tg_chat_id como conexión activa y responde con su detalle."""
    chat_row = await db.fetchone("SELECT * FROM chats WHERE tg_chat_id = ?", (tg_chat_id,))
    if not chat_row:
        await update.effective_message.reply_text("El chat conectado ya no existe en la base de datos.")
        return
    await db.set_connection(update.effective_user.id, tg_chat_id)
    texto = await _render_detalle_conexion(chat_row)
    await update.effective_message.reply_text(texto, parse_mode=ParseMode.HTML)


async def _render_lista_conexiones(user_id: int) -> tuple[str, InlineKeyboardMarkup | None]:
    """Arma el texto + botones de la lista de chats ya usados, marcando
    con ✅ el que está activo ahora mismo."""
    historial = await db.get_connection_history(user_id)
    if not historial:
        return "No estás conectado a ningún chat. Usa /connect <@usuario|id>.", None

    activo_id = await db.get_connection(user_id)
    lineas = []
    botones = []
    for i, h in enumerate(historial, start=1):
        marca = "✅ " if h["tg_chat_id"] == activo_id else ""
        titulo = h["titulo"] or str(h["tg_chat_id"])
        lineas.append(f"{marca}{i}. {titulo}")
        botones.append([InlineKeyboardButton(
            f"{marca}{i}. {titulo}", callback_data=f"{CB_PREFIX}sel:{h['tg_chat_id']}"
        )])

    activo_row = await db.fetchone("SELECT titulo FROM chats WHERE tg_chat_id = ?", (activo_id,)) if activo_id else None
    encabezado = f"🔗 Conectado ahora: <b>{activo_row['titulo']}</b>\n\n" if activo_row else ""
    texto = encabezado + "Tus chats:\n" + "\n".join(lineas) + "\n\nToca uno o usa /connection <n>."
    return texto, InlineKeyboardMarkup(botones)

async def connection_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    if context.args and context.args[0].isdigit():
        posicion = int(context.args[0])
        historial = await db.get_connection_history(user_id)
        if posicion < 1 or posicion > len(historial):
            await update.effective_message.reply_text(
                f"No hay un chat #{posicion} en tu lista. Usa /connection para verla."
            )
            return
        await _activar_y_mostrar(update, context, historial[posicion - 1]["tg_chat_id"])
        return

    texto, teclado = await _render_lista_conexiones(user_id)
    await update.effective_message.reply_text(texto, parse_mode=ParseMode.HTML, reply_markup=teclado)


async def _on_seleccionar_conexion(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    tg_chat_id = int(query.data.replace(f"{CB_PREFIX}sel:", ""))
    chat_row = await db.fetchone("SELECT * FROM chats WHERE tg_chat_id = ?", (tg_chat_id,))
    if not chat_row:
        await query.edit_message_text("El chat conectado ya no existe en la base de datos.")
        return
    await db.set_connection(update.effective_user.id, tg_chat_id)
    texto = await _render_detalle_conexion(chat_row)
    await query.edit_message_text(texto, parse_mode=ParseMode.HTML)


def register(application: Application, sudo_users):
    application.add_handler(CommandHandler("connect", connect_cmd))
    application.add_handler(CommandHandler("disconnect", disconnect_cmd))
    application.add_handler(CommandHandler("connection", connection_cmd))
    application.add_handler(CallbackQueryHandler(_on_seleccionar_conexion, pattern=f"^{CB_PREFIX}sel:"))
