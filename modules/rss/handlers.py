"""Handlers de comandos RSS + arranque del scheduler.

Diseño más simple que el de BitBreadRSS: ahí hacía falta un paso de "elegir
canal" porque el bot gestionaba canales que no eran necesariamente donde se
escribía el comando. Aquí, cada feed pertenece al chat donde se ejecuta
/addfeed (o al chat conectado vía /connect si se hace desde el PM), así que
ese paso completo desaparece — una conversación más corta y menos fricción.
"""

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler, ConversationHandler,
    MessageHandler, filters, ContextTypes,
)
import html

from core.database import db
from utils.decorators import user_admin, group_only
from modules.rss.parser import RSSParser
from modules.rss.resolver import RSSResolver
from modules.rss.monitor import RSSMonitor
from modules.connection import get_connected_chat_id

__mod_name__ = "RSS"

WAITING_URL = 1
WAITING_STYLE = 2
CB_PREFIX = "rss:"

ESTILOS_VALIDOS = ("bitbread", "texto", "social")
ESTILOS_LABELS = {
    "bitbread": "📸 BitBread (foto/video)",
    "texto": "📝 Solo texto",
    "social": "🐦 X/Twitter (sin repetir texto)",
}

_monitor: RSSMonitor | None = None


async def _resolver_chat_destino(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Devuelve el chat_row (fila de la tabla chats) donde debe operar el comando:
    el chat actual si es grupo, o el chat conectado (persistido en DB) si estamos en PM."""
    chat = update.effective_chat
    if chat.type in ("group", "supergroup", "channel"):
        return await db.ensure_chat(chat)
    tg_chat_id = await get_connected_chat_id(update.effective_user.id)
    if not tg_chat_id:
        return None
    return await db.fetchone("SELECT * FROM chats WHERE tg_chat_id = ?", (tg_chat_id,))


# --- /addfeed (conversación corta: URL -> estilo -> guardado) ---

async def addfeed_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_row = await _resolver_chat_destino(update, context)
    if not chat_row:
        await update.effective_message.reply_text(
            "Usa este comando dentro del grupo/canal, o conéctate primero con /connect <id>."
        )
        return ConversationHandler.END
    context.user_data["rss_target_chat_row"] = chat_row
    await update.effective_message.reply_text(
        "📰 Mándame la URL del sitio/feed que quieres seguir (o /cancel para salir)."
    )
    return WAITING_URL


async def addfeed_url(update: Update, context: ContextTypes.DEFAULT_TYPE):
    url = update.effective_message.text.strip()
    if url == "/cancel":
        await update.effective_message.reply_text("❌ Cancelado.")
        return ConversationHandler.END

    aviso = await update.effective_message.reply_text("🔍 Resolviendo el feed, dame un momento...")
    resolved_url, titulo, error = await RSSResolver.find_best_feed(url)
    if not resolved_url:
        await aviso.edit_text(f"❌ No pude encontrar un feed válido: {error}")
        return ConversationHandler.END

    context.user_data["rss_url"] = resolved_url
    context.user_data["rss_url_original"] = url
    context.user_data["rss_titulo"] = titulo

    es_social = RSSParser.is_social_source(resolved_url) or RSSParser.is_social_source(url)

    # Si es X/Twitter (o un espejo Nitter), la opción "social" va primero
    # porque es la recomendada: en estas fuentes el título y la descripción
    # suelen traer el mismo texto del post, y ese estilo evita repetirlo.
    orden = ("social", "bitbread", "texto") if es_social else ("bitbread", "texto", "social")
    botones = [
        InlineKeyboardButton(ESTILOS_LABELS[estilo], callback_data=f"{CB_PREFIX}style:{estilo}")
        for estilo in orden
    ]
    teclado = InlineKeyboardMarkup([[botones[0]], [botones[1]], [botones[2]]])

    aviso_extra = (
        "\n🐦 Parece una fuente de X/Twitter — te recomiendo el estilo "
        "<b>X/Twitter (sin repetir texto)</b>."
        if es_social else ""
    )
    await aviso.edit_text(
        f"✅ Encontrado: <b>{html.escape(titulo)}</b>\n¿Qué estilo de publicación prefieres?{aviso_extra}",
        parse_mode=ParseMode.HTML, reply_markup=teclado,
    )
    return WAITING_STYLE


async def addfeed_style(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    estilo = query.data.replace(f"{CB_PREFIX}style:", "")

    chat_row = context.user_data.pop("rss_target_chat_row")
    url = context.user_data.pop("rss_url")
    url_original = context.user_data.pop("rss_url_original")
    titulo = context.user_data.pop("rss_titulo")

    numero = await db.siguiente_numero_local(chat_row["id"])
    await db.execute(
        "INSERT INTO feeds(chat_id, numero_local, url, url_original, titulo, estilo) VALUES (?,?,?,?,?,?)",
        (chat_row["id"], numero, url, url_original, titulo, estilo),
    )
    await query.edit_message_text(
        f"🎉 Feed «{html.escape(titulo)}» añadido como <b>#{numero}</b>, estilo <b>{estilo}</b>. "
        f"Revisa /myfeeds para ajustarlo.",
        parse_mode=ParseMode.HTML,
    )
    return ConversationHandler.END


async def addfeed_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text("❌ Cancelado.")
    return ConversationHandler.END


# --- Comandos directos ---

async def myfeeds_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_row = await _resolver_chat_destino(update, context)
    if not chat_row:
        await update.effective_message.reply_text("Usa esto dentro del grupo/canal, o conéctate con /connect.")
        return
    feeds = await db.fetchall("SELECT * FROM feeds WHERE chat_id = ? ORDER BY numero_local", (chat_row["id"],))
    if not feeds:
        await update.effective_message.reply_text("No hay feeds configurados aquí. Usa /addfeed para crear uno.")
        return
    for f in feeds:
        estado = "🟢 activo" if f["activo"] else "🔴 pausado"
        texto = (
            f"📰 <b>{html.escape(f['titulo'] or f['url'])}</b> (#{f['numero_local']})\n"
            f"Estilo: {f['estilo']} | Intervalo: {f['intervalo_min']}m | {estado}"
        )
        botones = InlineKeyboardMarkup([[
            InlineKeyboardButton(
                "⏸️ Pausar" if f["activo"] else "▶️ Reanudar",
                callback_data=f"{CB_PREFIX}toggle:{f['id']}",
            ),
            InlineKeyboardButton("🎨 Estilo", callback_data=f"{CB_PREFIX}smenu:{f['id']}"),
            InlineKeyboardButton("🗑️ Eliminar", callback_data=f"{CB_PREFIX}del:{f['id']}"),
        ]])
        await update.effective_message.reply_text(texto, parse_mode=ParseMode.HTML, reply_markup=botones)


async def _on_style_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Botón '🎨 Estilo' de /myfeeds: abre el selector para cambiar el estilo
    de un feed ya creado, sin tener que eliminarlo y añadirlo de nuevo."""
    query = update.callback_query
    await query.answer()
    feed_id = int(query.data.replace(f"{CB_PREFIX}smenu:", ""))
    botones = InlineKeyboardMarkup([
        [InlineKeyboardButton(ESTILOS_LABELS[estilo], callback_data=f"{CB_PREFIX}sset:{feed_id}:{estilo}")]
        for estilo in ESTILOS_VALIDOS
    ])
    await query.edit_message_text("Elige el nuevo estilo para este feed:", reply_markup=botones)


async def _on_set_style(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    _, feed_id, estilo = query.data.replace(CB_PREFIX, "").split(":")
    await db.execute("UPDATE feeds SET estilo = ? WHERE id = ?", (estilo, int(feed_id)))
    await query.edit_message_text(
        f"✅ Estilo actualizado a <b>{ESTILOS_LABELS[estilo]}</b>. Usa /myfeeds para verlo.",
        parse_mode=ParseMode.HTML,
    )


async def _on_toggle_or_delete(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    accion, feed_id = query.data.replace(CB_PREFIX, "").split(":")
    feed_id = int(feed_id)

    if accion == "toggle":
        fila = await db.fetchone("SELECT activo FROM feeds WHERE id = ?", (feed_id,))
        if fila:
            nuevo = 0 if fila["activo"] else 1
            await db.execute("UPDATE feeds SET activo = ? WHERE id = ?", (nuevo, feed_id))
            await query.edit_message_text("✅ Estado actualizado. Usa /myfeeds para ver la lista actualizada.")
    elif accion == "del":
        await db.execute("DELETE FROM feeds WHERE id = ?", (feed_id,))
        await query.edit_message_text("🗑️ Feed eliminado.")


async def _resolver_feed_por_numero(update: Update, context: ContextTypes.DEFAULT_TYPE, numero_local: int):
    """Traduce el #numero_local que teclea el admin (propio de su chat) al
    feed real, verificando de paso que ese feed pertenezca al chat actual/
    conectado — así un admin no puede tocar por accidente (ni adivinando el
    número) un feed de otro chat. Devuelve (feed_row, mensaje_error)."""
    chat_row = await _resolver_chat_destino(update, context)
    if not chat_row:
        return None, "Usa este comando dentro del grupo/canal, o conéctate primero con /connect."
    feed = await db.get_feed_by_numero_local(chat_row["id"], numero_local)
    if not feed:
        return None, f"No hay ningún feed #{numero_local} en este chat. Revisa /myfeeds."
    return feed, None


async def setinterval_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args or not context.args[0].isdigit():
        await update.effective_message.reply_text("Uso: /setinterval <#feed> <minutos>")
        return
    if len(context.args) < 2 or not context.args[1].isdigit():
        await update.effective_message.reply_text("Uso: /setinterval <#feed> <minutos>")
        return
    numero, minutos = int(context.args[0]), int(context.args[1])
    feed, error = await _resolver_feed_por_numero(update, context, numero)
    if error:
        await update.effective_message.reply_text(error)
        return
    await db.execute("UPDATE feeds SET intervalo_min = ? WHERE id = ?", (minutos, feed["id"]))
    await update.effective_message.reply_text(f"✅ Intervalo del feed #{numero}: {minutos} min")


async def setstyle_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args or []) < 2 or context.args[0].isdigit() is False or context.args[1] not in ESTILOS_VALIDOS:
        await update.effective_message.reply_text("Uso: /setstyle <#feed> <bitbread|texto|social>")
        return
    numero = int(context.args[0])
    feed, error = await _resolver_feed_por_numero(update, context, numero)
    if error:
        await update.effective_message.reply_text(error)
        return
    await db.execute("UPDATE feeds SET estilo = ? WHERE id = ?", (context.args[1], feed["id"]))
    await update.effective_message.reply_text(f"✅ Estilo del feed #{numero}: {context.args[1]}")


async def settranslate_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args or []) < 2 or context.args[0].isdigit() is False or context.args[1] not in ("on", "off"):
        await update.effective_message.reply_text(
            "Uso: /settranslate <#feed> <on|off>\n"
            "Traduce título y descripción con IA antes de publicar (requiere GROQ_API_KEY)."
        )
        return
    numero, valor = int(context.args[0]), 1 if context.args[1] == "on" else 0
    feed, error = await _resolver_feed_por_numero(update, context, numero)
    if error:
        await update.effective_message.reply_text(error)
        return
    await db.execute("UPDATE feeds SET traducir = ? WHERE id = ?", (valor, feed["id"]))
    estado = "activada ✅" if valor else "desactivada"
    await update.effective_message.reply_text(f"Traducción del feed #{numero}: {estado}")


async def setrhash_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args or []) < 2 or not context.args[0].isdigit():
        await update.effective_message.reply_text(
            "Uso: /setrhash <#feed> <rhash|none>\n"
            "El rhash es el código de la plantilla de Instant View (t.me/iv?...&rhash=XXXX)."
        )
        return
    numero, rhash = int(context.args[0]), context.args[1]
    feed, error = await _resolver_feed_por_numero(update, context, numero)
    if error:
        await update.effective_message.reply_text(error)
        return
    valor = None if rhash.lower() == "none" else rhash
    await db.execute("UPDATE feeds SET rhash = ? WHERE id = ?", (valor, feed["id"]))
    await update.effective_message.reply_text(f"✅ rhash del feed #{numero} actualizado.")


async def rmfeed_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args or not context.args[0].isdigit():
        await update.effective_message.reply_text("Uso: /rmfeed <#feed>")
        return
    numero = int(context.args[0])
    feed, error = await _resolver_feed_por_numero(update, context, numero)
    if error:
        await update.effective_message.reply_text(error)
        return
    await db.execute("DELETE FROM feeds WHERE id = ?", (feed["id"],))
    await update.effective_message.reply_text(f"🗑️ Feed #{numero} eliminado.")


async def testfeed_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args or not context.args[0].isdigit():
        await update.effective_message.reply_text("Uso: /testfeed <#feed>")
        return
    numero = int(context.args[0])
    feed, error = await _resolver_feed_por_numero(update, context, numero)
    if error:
        await update.effective_message.reply_text(error)
        return
    ok, mensaje = await _monitor.force_check(feed["id"])
    await update.effective_message.reply_text(("✅ " if ok else "⚠️ ") + mensaje)


def register(application: Application, sudo_users):
    global _monitor
    _monitor = RSSMonitor(application.bot)

    conv = ConversationHandler(
        entry_points=[CommandHandler("addfeed", user_admin(addfeed_start))],
        states={
            WAITING_URL: [MessageHandler(filters.TEXT & ~filters.COMMAND, addfeed_url)],
            WAITING_STYLE: [CallbackQueryHandler(addfeed_style, pattern=f"^{CB_PREFIX}style:")],
        },
        fallbacks=[CommandHandler("cancel", addfeed_cancel)],
        per_message=False,
    )
    application.add_handler(conv)

    application.add_handler(CommandHandler("myfeeds", myfeeds_cmd))
    application.add_handler(CommandHandler("setinterval", user_admin(setinterval_cmd)))
    application.add_handler(CommandHandler("setstyle", user_admin(setstyle_cmd)))
    application.add_handler(CommandHandler("settranslate", user_admin(settranslate_cmd)))
    application.add_handler(CommandHandler("setrhash", user_admin(setrhash_cmd)))
    application.add_handler(CommandHandler("rmfeed", user_admin(rmfeed_cmd)))
    application.add_handler(CommandHandler("testfeed", user_admin(testfeed_cmd)))
    application.add_handler(
        CallbackQueryHandler(_on_toggle_or_delete, pattern=f"^{CB_PREFIX}(toggle|del):")
    )
    application.add_handler(CallbackQueryHandler(_on_style_menu, pattern=f"^{CB_PREFIX}smenu:"))
    application.add_handler(CallbackQueryHandler(_on_set_style, pattern=f"^{CB_PREFIX}sset:"))

    scheduler = AsyncIOScheduler()
    scheduler.add_job(_monitor.check_feeds, IntervalTrigger(seconds=60), id="rss_monitor", max_instances=1)
    scheduler.start()
    application.bot_data["rss_scheduler"] = scheduler
