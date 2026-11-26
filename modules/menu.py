"""Módulo menu - /menu: navegación por botones sobre el registro de comandos.

Inicio -> sección -> tema. Cada pantalla es una función pura (`pantalla`) que recibe lo que
el registro sabe y quién pulsa; el handler solo la dibuja. Lo que ve cada persona sale de
`Cmd.level` y `Cmd.ambito`, así que un módulo nuevo aparece solo (test_menu exige que su
tema pertenezca a una sección). Los botones solo muestran: los permisos reales siguen en
cada comando. Sin sondeos ni tareas: solo trabaja cuando alguien pulsa.
"""

import html

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes

from core.config import SUDO_USERS
from core.registry import Cmd, Topic
from core.ui import cb, fila_nav, guard_callback, mostrar, parse
from modules.start import _datos, _ordenados, texto_tema
from utils.decorators import is_user_admin

__mod_name__ = "Menú"

COMMANDS = (
    Cmd("menu", "Menú con botones", topic="inicio", menu=True),
)

NS = "menu"
# (clave, título, temas de /help que agrupa). Un tema fuera de aquí no sería alcanzable.
SECCIONES = (
    ("mod", "🛡 Moderación", ("admin", "bans", "warns", "antiflood", "locks", "blacklist",
                              "approvals", "reporting", "join", "log", "disabling")),
    ("cont", "📝 Contenido", ("filters", "notes", "welcome", "rules")),
    ("rss", "📰 RSS", ("rss",)),
    ("conn", "🔗 Conexión", ("connection",)),
    ("tasalo", "🌐 TASALO", ("federation", "broadcast", "stats", "pub")),
)
# Temas que no son una sección: se llega a ellos por otro lado (/help, /start).
FUERA_DE_SECCIONES = {"inicio"}


def visibles(cmds, niveles: set[str], privado: bool) -> list[Cmd]:
    """Comandos que tienen sentido para quien mira: su nivel y el tipo de chat."""
    oculto = "grupo" if privado else "privado"
    return [c for c in cmds if c.level in niveles and c.ambito != oculto]


def _secciones(topics, cmds) -> list[tuple[str, str, list[Topic]]]:
    con_comandos = {c.topic for c in cmds}
    por_clave = {t.key: t for t in topics}
    salida = []
    for clave, titulo, claves in SECCIONES:
        ts = [por_clave[k] for k in claves if k in por_clave and k in con_comandos]
        if ts:
            salida.append((clave, titulo, ts))
    return salida


def _filas(botones, por_fila: int = 2) -> list[list[InlineKeyboardButton]]:
    return [botones[i:i + por_fila] for i in range(0, len(botones), por_fila)]


def _inicio(secciones) -> tuple[str, InlineKeyboardMarkup]:
    botones = [InlineKeyboardButton(titulo, callback_data=cb(NS, "s", clave)) for clave, titulo, _ in secciones]
    filas = _filas(botones) + [[InlineKeyboardButton("❓ Ayuda", callback_data="help:volver")]]
    texto = "📋 <b>Menú de taso-gcg</b>\n\nElige una sección. Lo que ves depende de tus permisos en este chat."
    return texto, InlineKeyboardMarkup(filas)


def _tema(topic: Topic, cmds, atras: str | None) -> tuple[str, InlineKeyboardMarkup]:
    return texto_tema(topic, cmds), InlineKeyboardMarkup([fila_nav(atras=atras)])


def pantalla(args, cmds, topics, niveles: set[str], privado: bool) -> tuple[str, InlineKeyboardMarkup]:
    """(texto HTML, teclado) de la pantalla pedida. Lo desconocido o ya no visible cae al inicio."""
    cmds = visibles(cmds, niveles, privado)
    secciones = _secciones(_ordenados(topics), cmds)
    por_clave = {s[0]: s for s in secciones}
    modo = args[0] if args else "home"

    if modo == "s" and len(args) > 1 and args[1] in por_clave:
        clave, titulo, ts = por_clave[args[1]]
        if len(ts) == 1:  # una sección de un solo tema: directo a la página
            return _tema(ts[0], cmds, atras=None)
        botones = [InlineKeyboardButton(t.title, callback_data=cb(NS, "t", t.key, clave)) for t in ts]
        return (f"<b>{html.escape(titulo)}</b>\n\nElige un tema.",
                InlineKeyboardMarkup(_filas(botones) + [fila_nav()]))

    if modo == "t" and len(args) > 2:
        topic = next((t for t in topics if t.key == args[1]), None)
        if topic is not None and any(c.topic == topic.key for c in cmds):
            sec = por_clave.get(args[2])
            atras = cb(NS, "s", args[2]) if sec and len(sec[2]) > 1 else None
            return _tema(topic, cmds, atras)

    return _inicio(secciones)


async def _niveles(update: Update, context: ContextTypes.DEFAULT_TYPE) -> set[str]:
    """Qué niveles de comando ve quien mira (en privado, admin: se gestiona vía /connect)."""
    user = update.effective_user.id
    if user in SUDO_USERS:
        return {"todos", "admin", "sudo"}
    chat = update.effective_chat
    if chat.type == "private" or await is_user_admin(context, chat.id, user):
        return {"todos", "admin"}
    return {"todos"}


async def menu_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cmds, topics = _datos(context)
    privado = update.effective_chat.type == "private"
    texto, teclado = pantalla(("home",), cmds, topics, await _niveles(update, context), privado)
    await update.effective_message.reply_text(texto, parse_mode=ParseMode.HTML, reply_markup=teclado)


@guard_callback()  # ya responde la query: aquí no se llama a query.answer()
async def _on_menu_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    parsed = parse(update.callback_query.data or "")
    args = parsed[1] if parsed else ()
    cmds, topics = _datos(context)
    privado = update.effective_chat.type == "private"
    texto, teclado = pantalla(args, cmds, topics, await _niveles(update, context), privado)
    await mostrar(update, texto, teclado)


def register(application: Application, sudo_users):
    application.add_handler(CommandHandler("menu", menu_cmd))
    application.add_handler(CallbackQueryHandler(_on_menu_button, pattern=f"^{NS}:"))
