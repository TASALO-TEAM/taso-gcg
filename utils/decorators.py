"""Decoradores de permisos para handlers de PTB (async).

Equivalente conceptual a modules/helper_funcs/chat_status.py de Rose-Bot,
pero reescrito para PTB 22 (async) y con caché de admins en SQLite para no
golpear getChatAdministrators en cada comando de moderación.
"""

import functools
from telegram import Update, ChatMember
from telegram.ext import ContextTypes

from core.config import SUDO_USERS, ADMIN_CACHE_TTL_SECONDS
from core.database import db
from utils.logger import log

ADMIN_STATUSES = (ChatMember.ADMINISTRATOR, ChatMember.OWNER)


async def _get_admin_ids(chat_id: int) -> set[int]:
    """Devuelve el set de user_id admins de un chat, usando caché de DB con TTL."""
    cached = await db.get_cached_admins(chat_id, ADMIN_CACHE_TTL_SECONDS)
    if cached is not None:
        return {row["user_id"] for row in cached}
    return set()  # el refresco real ocurre en refresh_admin_cache (ver abajo)


async def refresh_admin_cache(context: ContextTypes.DEFAULT_TYPE, chat_id: int) -> set[int]:
    """Fuerza refresco desde la API de Telegram y actualiza la caché en DB."""
    try:
        admins = await context.bot.get_chat_administrators(chat_id)
    except Exception as e:
        log(f"No se pudo refrescar admins de {chat_id}: {e}", "warning")
        return set()
    pares = [(a.user.id, a.status == ChatMember.OWNER) for a in admins]
    await db.cache_admins(chat_id, pares)
    return {uid for uid, _ in pares}


async def is_user_admin(context: ContextTypes.DEFAULT_TYPE, chat_id: int, user_id: int) -> bool:
    if user_id in SUDO_USERS:
        return True
    admin_ids = await _get_admin_ids(chat_id)
    if not admin_ids:
        admin_ids = await refresh_admin_cache(context, chat_id)
    return user_id in admin_ids


async def is_bot_admin(context: ContextTypes.DEFAULT_TYPE, chat_id: int) -> bool:
    try:
        member = await context.bot.get_chat_member(chat_id, context.bot.id)
        return member.status in ADMIN_STATUSES
    except Exception:
        return False


def user_admin(func):
    """El comando solo se ejecuta si quien lo manda es admin del chat (o sudo)."""
    @functools.wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        user = update.effective_user
        chat = update.effective_chat
        if not user or not chat:
            return
        if await is_user_admin(context, chat.id, user.id):
            return await func(update, context, *args, **kwargs)
        if update.effective_message:
            await update.effective_message.reply_text(
                "🚫 Este comando es solo para administradores del chat."
            )
    return wrapper


def bot_admin(func):
    """El comando solo se ejecuta si el bot mismo es admin (necesita permisos para actuar)."""
    @functools.wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        chat = update.effective_chat
        if not chat:
            return
        if await is_bot_admin(context, chat.id):
            return await func(update, context, *args, **kwargs)
        if update.effective_message:
            await update.effective_message.reply_text(
                "⚠️ Necesito ser administrador en este chat para hacer eso."
            )
    return wrapper


def sudo_only(func):
    """Reservado para los dueños del bot (SUDO_USERS) — usado en broadcast, chats oficiales, etc."""
    @functools.wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        user = update.effective_user
        if user and user.id in SUDO_USERS:
            return await func(update, context, *args, **kwargs)
        if update.effective_message:
            await update.effective_message.reply_text("🚫 Comando reservado al equipo TASALO.")
    return wrapper


def group_only(func):
    """El comando solo tiene sentido dentro de un grupo/supergrupo, no en privado."""
    @functools.wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        chat = update.effective_chat
        if chat and chat.type in ("group", "supergroup"):
            return await func(update, context, *args, **kwargs)
        if update.effective_message:
            await update.effective_message.reply_text("Este comando solo funciona dentro de un grupo.")
    return wrapper
