"""Módulo start — /start y /help.

Esto faltaba: con 21 módulos de funcionalidad no había ni un /start ni un /help
centralizado. Sigue la convención HELP_TOPICS/TOPIC_ALIASES que ya usas en
taso-bot: resumen compacto con botones + página de detalle por tema.
"""

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes

from core.config import BOT_VERSION

__mod_name__ = "Inicio"

CB_PREFIX = "help:"

HELP_TOPICS = {
    "admin": ("🛡️ Administración",
              "/promote /demote — dar o quitar admin (respondiendo al mensaje)\n"
              "/pin /unpin — fijar o desfijar\n"
              "/purge — borra desde el mensaje respondido hasta ahora\n"
              "/title /id /admins — info del chat/usuario"),
    "bans": ("🔨 Bans y silencios",
             "/ban /tban <1h|30m|1d> — banear perm./temporal\n"
             "/unban /kick\n"
             "/mute /tmute <duración> /unmute"),
    "warns": ("⚠️ Avisos",
              "/warn [motivo] (respondiendo)\n"
              "/warns — ver avisos de alguien\n"
              "/resetwarns\n"
              "/setwarnlimit <n> — límite antes de sancionar"),
    "antiflood": ("🌊 AntiFlood",
                  "/setflood <n> — más de n mensajes en 10s dispara la acción (0 = off)\n"
                  "/setfloodaction <mute|kick|ban>"),
    "locks": ("🔒 Bloqueos de contenido",
              "/lock <tipo> /unlock <tipo> /locks\n"
              "Tipos: stickers, links, forwards, photos, videos, documents, voice, polls, games, inlinebots"),
    "blacklist": ("🚫 Lista negra",
                  "/addblacklist <palabra> [delete|warn|ban]\n"
                  "/rmblacklist <palabra>\n/blacklist"),
    "filters": ("🔁 Filtros (auto-respuestas)",
                "/filter <palabra> <respuesta>\n/stop <palabra>\n/filters"),
    "notes": ("📝 Notas",
              "/save <nombre> <contenido> (o respondiendo)\n"
              "/get <nombre> o #nombre\n/clear <nombre>\n/notes"),
    "welcome": ("👋 Bienvenida",
                "/setwelcome <texto> /setgoodbye <texto>\n"
                "Placeholders: {mencion} {nombre} {chat}\n/welcome on|off"),
    "rules": ("📜 Reglas", "/rules — verlas\n/setrules <texto> — configurarlas"),
    "reporting": ("🚨 Reportes", "/report (respondiendo a un mensaje) — avisa a los admins"),
    "approvals": ("✅ Aprobaciones",
                  "/approve (respondiendo) [motivo] — inmune a antiflood/blacklist/locks\n"
                  "/approval /approved /unapprove /unapproveall"),
    "federation": ("🌐 Federación TASALO",
                   "/fban (respondiendo) [motivo] — banea en TODOS los chats oficiales\n"
                   "/funban /fbanlist"),
    "log": ("📋 Log de administración",
            "/setlog (en el canal) — vincula ese canal como log\n"
            "/unsetlog /logchannel\n/log <categorías> /nolog <categorías>"),
    "disabling": ("🔕 Deshabilitar comandos",
                  "/disable <cmd> /enable <cmd> /disabled /disableable\n"
                  "/disabledel on|off /disableadmin on|off"),
    "join": ("🚪 Solicitudes de ingreso", "/joincaptcha on|off — exige botón de confirmación"),
    "connection": ("🔗 Conexión remota",
                   "/connect <@usuario|id_chat> (en PM) — gestiona un chat sin escribir ahí\n"
                   "/connection /disconnect"),
    "broadcast": ("📣 Difusión TASALO",
                  "/broadcast <texto> (o respondiendo) — a todos los chats oficiales\n"
                  "/marcaroficial /desmarcaroficial /oficiales"),
    "stats": ("📊 Estadísticas", "/stats — estado del bot, memoria, chats, feeds"),
    "rss": ("📰 RSS",
            "/addfeed — asistente para añadir un feed\n"
            "/myfeeds — ver y pausar/eliminar\n"
            "/setinterval /setstyle /setrhash /rmfeed /testfeed"),
}

TOPIC_ALIASES = {
    "moderacion": "admin", "mod": "admin", "moderación": "admin",
    "ban": "bans", "baneos": "bans",
    "aviso": "warns", "avisos": "warns",
    "flood": "antiflood",
    "lock": "locks", "bloqueos": "locks",
    "negra": "blacklist",
    "filtro": "filters", "filtros": "filters",
    "nota": "notes",
    "bienvenida": "welcome",
    "regla": "rules", "reglas": "rules",
    "reporte": "reporting", "reportes": "reporting",
    "aprobar": "approvals", "aprobaciones": "approvals",
    "fed": "federation", "federacion": "federation", "federación": "federation",
    "logs": "log",
    "disable": "disabling", "deshabilitar": "disabling",
    "captcha": "join", "solicitudes": "join",
    "conexion": "connection", "conexión": "connection", "connect": "connection",
    "difusion": "broadcast", "difusión": "broadcast",
    "estadisticas": "stats", "estadísticas": "stats",
    "feed": "rss", "feeds": "rss", "noticias": "rss",
}


def _teclado_resumen() -> InlineKeyboardMarkup:
    claves = list(HELP_TOPICS.keys())
    filas = []
    for i in range(0, len(claves), 2):
        par = claves[i:i + 2]
        filas.append([
            InlineKeyboardButton(HELP_TOPICS[k][0], callback_data=f"{CB_PREFIX}{k}") for k in par
        ])
    return InlineKeyboardMarkup(filas)


def _texto_resumen() -> str:
    return (
        "🤖 <b>taso-gcg</b> — Gestión de Canales y Grupos TASALO\n\n"
        "Toca un tema para ver sus comandos, o escribe <code>/help &lt;tema&gt;</code> directo.\n"
        "Esta lista cubre el 100% de los comandos del bot — no hace falta buscar en otro lado."
    )


async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    if chat.type == "private":
        texto = (
            f"👋 ¡Hola! Soy <b>taso-gcg</b> v{BOT_VERSION}, el bot de administración y RSS "
            f"del ecosistema TASALO.\n\n"
            f"Puedo:\n"
            f"• Moderar grupos y canales (bans, avisos, locks, filtros, bienvenida, etc.)\n"
            f"• Sincronizar bans entre los chats oficiales de TASALO (federación)\n"
            f"• Publicar noticias RSS automáticamente\n\n"
            f"Añádeme a un grupo/canal y hazme administrador para empezar. "
            f"Usa /help para ver todos los comandos."
        )
        await update.effective_message.reply_text(texto, parse_mode=ParseMode.HTML)
    else:
        await update.effective_message.reply_text(
            "🤖 taso-gcg activo en este chat. Usa /help para ver los comandos disponibles."
        )


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.args:
        clave = context.args[0].lower()
        clave = TOPIC_ALIASES.get(clave, clave)
        if clave in HELP_TOPICS:
            titulo, texto = HELP_TOPICS[clave]
            await update.effective_message.reply_text(f"<b>{titulo}</b>\n\n{texto}", parse_mode=ParseMode.HTML)
            return
        await update.effective_message.reply_text(
            f"No conozco el tema «{context.args[0]}». Usa /help sin argumentos para ver la lista."
        )
        return

    await update.effective_message.reply_text(
        _texto_resumen(), parse_mode=ParseMode.HTML, reply_markup=_teclado_resumen()
    )


async def _on_help_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    clave = query.data.replace(CB_PREFIX, "")

    if clave == "volver":
        await query.edit_message_text(
            _texto_resumen(), parse_mode=ParseMode.HTML, reply_markup=_teclado_resumen()
        )
        return

    if clave not in HELP_TOPICS:
        return
    titulo, texto = HELP_TOPICS[clave]
    teclado = InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Volver", callback_data=f"{CB_PREFIX}volver")]])
    await query.edit_message_text(f"<b>{titulo}</b>\n\n{texto}", parse_mode=ParseMode.HTML, reply_markup=teclado)


def register(application: Application, sudo_users):
    application.add_handler(CommandHandler("start", start_cmd))
    application.add_handler(CommandHandler("help", help_cmd))
    application.add_handler(CallbackQueryHandler(_on_help_button, pattern=f"^{CB_PREFIX}"))
