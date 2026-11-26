"""Módulo start — /start y /help.

/help se genera desde el registro de comandos (core/registry.py): cada módulo declara
su TOPIC y sus COMMANDS, y aquí solo se presentan. Ya no hay texto de ayuda escrito a mano.
El prefijo de callback `help:` se conserva para que los mensajes viejos sigan funcionando.
"""

import html

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes

from core import registry
from core.config import BOT_VERSION
from core.registry import Cmd, Topic
from core.ui import guard_callback, mostrar

__mod_name__ = "Inicio"

TOPIC = Topic("inicio", "🏠 Inicio", aliases=("start", "ayuda"))
COMMANDS = (
    Cmd("start", "Iniciar / info del bot", topic="inicio", menu=True),
    Cmd("help", "Menú de ayuda por temas", topic="inicio", uso="[tema]", menu=True),
)

CB_PREFIX = "help:"

# Orden de los temas en /help (los que no estén aquí van al final, en orden de carga).
ORDEN_TEMAS = (
    "inicio", "admin", "bans", "warns", "antiflood", "locks", "blacklist", "filters", "notes",
    "welcome", "rules", "reporting", "approvals", "federation", "log", "disabling", "join",
    "connection", "broadcast", "stats", "rss",
)


def _ordenados(topics) -> list[Topic]:
    return sorted(topics, key=lambda t: ORDEN_TEMAS.index(t.key) if t.key in ORDEN_TEMAS else len(ORDEN_TEMAS))


def _datos(context) -> tuple[tuple[Cmd, ...], list[Topic]]:
    bot_data = context.application.bot_data
    return bot_data.get("cmds", ()), _ordenados(bot_data.get("topics", ()))


def texto_tema(topic: Topic, cmds) -> str:
    """HTML de la página de un tema: título + una línea por comando + nota opcional."""
    cuerpo = "\n".join(registry.linea_ayuda(c) for c in cmds if c.topic == topic.key)
    if topic.nota:
        cuerpo += f"\n\n{topic.nota}"
    return f"<b>{html.escape(topic.title)}</b>\n\n{html.escape(cuerpo)}"


def teclado_resumen(topics) -> InlineKeyboardMarkup:
    botones = [InlineKeyboardButton(t.title, callback_data=f"{CB_PREFIX}{t.key}") for t in topics]
    return InlineKeyboardMarkup([botones[i:i + 2] for i in range(0, len(botones), 2)])


def _texto_resumen() -> str:
    return (
        "🤖 <b>taso-gcg</b> — Gestión de Canales y Grupos TASALO\n\n"
        "Toca un tema para ver sus comandos, o escribe <code>/help &lt;tema&gt;</code> directo.\n"
        "Esta lista cubre el 100% de los comandos del bot — no hace falta buscar en otro lado.\n"
        "🔒 = solo admins del chat · 👑 = solo el equipo TASALO"
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
    cmds, topics = _datos(context)
    if context.args:
        topic = registry.resolver_tema(topics, context.args[0])
        if topic:
            await update.effective_message.reply_text(texto_tema(topic, cmds), parse_mode=ParseMode.HTML)
            return
        await update.effective_message.reply_text(
            f"No conozco el tema «{context.args[0]}». Usa /help sin argumentos para ver la lista."
        )
        return

    await update.effective_message.reply_text(
        _texto_resumen(), parse_mode=ParseMode.HTML, reply_markup=teclado_resumen(topics)
    )


@guard_callback()  # ya responde la query: aquí no se llama a query.answer()
async def _on_help_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    clave = update.callback_query.data.removeprefix(CB_PREFIX)
    cmds, topics = _datos(context)

    if clave == "volver":
        await mostrar(update, _texto_resumen(), teclado_resumen(topics))
        return

    topic = registry.resolver_tema(topics, clave)
    if topic is None:
        return
    volver = InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Volver", callback_data=f"{CB_PREFIX}volver")]])
    await mostrar(update, texto_tema(topic, cmds), volver)


def register(application: Application, sudo_users):
    application.add_handler(CommandHandler("start", start_cmd))
    application.add_handler(CommandHandler("help", help_cmd))
    application.add_handler(CallbackQueryHandler(_on_help_button, pattern=f"^{CB_PREFIX}"))
