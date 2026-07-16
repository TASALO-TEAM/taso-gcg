"""Módulo admin — operaciones básicas de administración de chat.

Comandos: /promote /demote /pin /unpin /purge /title /id /admins
"""

from html import escape

from telegram import (
    MessageOriginChannel,
    MessageOriginChat,
    MessageOriginHiddenUser,
    MessageOriginUser,
    Update,
)
from telegram.constants import ParseMode
from telegram.ext import Application, CommandHandler, ContextTypes

from core.database import db
from utils.decorators import user_admin, bot_admin, group_only, refresh_admin_cache
from utils.common import estimate_account_creation, extract_target_user, resolve_username
from utils.logger import log

__mod_name__ = "Administración"


@group_only
@user_admin
@bot_admin
async def promote_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    user_id, nombre = await extract_target_user(update, context)
    if not user_id:
        await update.effective_message.reply_text("Responde al mensaje de la persona que quieres promover.")
        return
    try:
        await context.bot.promote_chat_member(
            chat.id, user_id,
            can_change_info=True, can_delete_messages=True, can_invite_users=True,
            can_restrict_members=True, can_pin_messages=True, can_promote_members=False,
        )
        await refresh_admin_cache(context, chat.id)
        await update.effective_message.reply_text(f"✅ {nombre} ahora es administrador.")
    except Exception as e:
        await update.effective_message.reply_text(f"⚠️ No pude promoverlo: {e}")


@group_only
@user_admin
@bot_admin
async def demote_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    user_id, nombre = await extract_target_user(update, context)
    if not user_id:
        await update.effective_message.reply_text("Responde al mensaje de la persona que quieres degradar.")
        return
    try:
        await context.bot.promote_chat_member(
            chat.id, user_id,
            can_change_info=False, can_delete_messages=False, can_invite_users=False,
            can_restrict_members=False, can_pin_messages=False, can_promote_members=False,
        )
        await refresh_admin_cache(context, chat.id)
        await update.effective_message.reply_text(f"⬇️ {nombre} ya no es administrador.")
    except Exception as e:
        await update.effective_message.reply_text(f"⚠️ No pude degradarlo: {e}")


@group_only
@user_admin
@bot_admin
async def pin_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.effective_message
    if not message.reply_to_message:
        await message.reply_text("Responde al mensaje que quieres fijar.")
        return
    silencioso = bool(context.args and context.args[0].lower() in ("silent", "s"))
    try:
        await context.bot.pin_chat_message(
            update.effective_chat.id,
            message.reply_to_message.message_id,
            disable_notification=silencioso,
        )
        await message.reply_text("📌 Mensaje fijado.")
    except Exception as e:
        await message.reply_text(f"⚠️ No pude fijarlo: {e}")


@group_only
@user_admin
@bot_admin
async def unpin_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if update.effective_message.reply_to_message:
            await context.bot.unpin_chat_message(
                update.effective_chat.id,
                update.effective_message.reply_to_message.message_id,
            )
        else:
            await context.bot.unpin_all_chat_messages(update.effective_chat.id)
        await update.effective_message.reply_text("📌 Desfijado.")
    except Exception as e:
        await update.effective_message.reply_text(f"⚠️ No pude desfijar: {e}")


@group_only
@user_admin
@bot_admin
async def purge_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Borra desde el mensaje respondido hasta el comando /purge, inclusive."""
    message = update.effective_message
    if not message.reply_to_message:
        await message.reply_text("Responde al primer mensaje que quieres borrar.")
        return
    chat_id = update.effective_chat.id
    desde = message.reply_to_message.message_id
    hasta = message.message_id
    borrados = 0
    for msg_id in range(hasta, desde - 1, -1):
        try:
            await context.bot.delete_message(chat_id, msg_id)
            borrados += 1
        except Exception:
            continue
    log(f"/purge en {chat_id}: {borrados} mensajes borrados")


@group_only
async def title_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    await update.effective_message.reply_text(
        f"🏷️ <b>{chat.title}</b>\nID: <code>{chat.id}</code>\nTipo: {chat.type}",
        parse_mode=ParseMode.HTML,
    )


def _campo_usuario(obj) -> dict:
    """Normaliza un telegram.User o una fila de la tabla `users` (dict) a la
    misma forma, para no tener que repetir el renderizado dos veces."""
    if isinstance(obj, dict):
        return {
            "id": obj["user_id"], "is_bot": bool(obj.get("is_bot")),
            "first_name": obj.get("first_name"), "last_name": obj.get("last_name"),
            "username": obj.get("username"), "language_code": obj.get("language_code"),
            "is_premium": bool(obj.get("is_premium")),
        }
    return {
        "id": obj.id, "is_bot": obj.is_bot,
        "first_name": obj.first_name, "last_name": obj.last_name,
        "username": obj.username, "language_code": getattr(obj, "language_code", None),
        "is_premium": bool(getattr(obj, "is_premium", False)),
    }


def _bloque_usuario(obj, etiqueta: str) -> str:
    u = _campo_usuario(obj)
    lineas = [
        f"👤 <b>{escape(etiqueta)}</b>",
        f" ├ id: <code>{u['id']}</code>",
        f" ├ is_bot: {'true' if u['is_bot'] else 'false'}",
        f" ├ first_name: {escape(u['first_name'] or '-')}",
    ]
    if u["last_name"]:
        lineas.append(f" ├ last_name: {escape(u['last_name'])}")
    lineas.append(f" ├ username: {('@' + u['username']) if u['username'] else '-'}")
    # El "(⭐/-)" es el estado de Telegram Premium, no un dato aparte del idioma.
    marca_premium = "⭐" if u["is_premium"] else "-"
    lineas.append(f" ├ language_code: {u['language_code'] or '-'} ({marca_premium})")
    lineas.append(f" └ created: {estimate_account_creation(u['id'])}")
    return "\n".join(lineas)


def _bloque_chat(chat, etiqueta: str) -> str:
    titulo = getattr(chat, "title", None) or getattr(chat, "full_name", None) or "-"
    username = getattr(chat, "username", None)
    return (
        f"💬 <b>{escape(etiqueta)}</b>\n"
        f" ├ id: <code>{chat.id}</code>\n"
        f" ├ title: {escape(titulo)}\n"
        f" ├ username: {('@' + username) if username else '-'}\n"
        f" └ type: {chat.type}"
    )


def _bloques_de_mensaje(message) -> list[str]:
    """A partir de un mensaje (el respondido), arma uno o dos bloques:
    quién/qué lo mandó, y si además viene reenviado, de dónde viene en
    realidad — esto último es lo que permite sacarle el ID a un canal:
    se reenvía un post suyo al grupo, se responde a ese reenvío con /id,
    y "Origin chat" muestra el canal real aunque el mensaje reenviado en
    sí lo haya mandado un miembro del grupo (o nadie, si vino directo del
    canal, donde no hay usuario real detrás, solo el canal como remitente)."""
    bloques = []
    if message.from_user:
        bloques.append(_bloque_usuario(message.from_user, message.from_user.full_name))
    elif message.sender_chat:
        bloques.append(_bloque_chat(message.sender_chat, message.sender_chat.title or "Origin chat"))

    origen = message.forward_origin
    if isinstance(origen, MessageOriginChannel):
        bloques.append(_bloque_chat(origen.chat, "Origin chat"))
    elif isinstance(origen, MessageOriginChat):
        bloques.append(_bloque_chat(origen.sender_chat, "Origin chat"))
    elif isinstance(origen, MessageOriginUser) and not message.from_user:
        bloques.append(_bloque_usuario(origen.sender_user, origen.sender_user.full_name))
    elif isinstance(origen, MessageOriginHiddenUser):
        bloques.append(
            f"💬 <b>Origin</b>\n └ nombre: {escape(origen.sender_user_name)} "
            "(reenvíos ocultos: Telegram no da más datos que el nombre)"
        )
    return bloques


async def _bloque_desde_argumento(context: ContextTypes.DEFAULT_TYPE, entrada: str) -> str | None:
    """Resuelve un argumento de /id: un ID numérico (de usuario o de chat) o
    un @username (de usuario o de chat/canal). Devuelve el bloque ya
    renderizado, o None si no se pudo identificar nada."""
    entrada = entrada.strip()

    if entrada.lstrip("-").isdigit():
        num = int(entrada)
        if num > 0:  # positivo = user_id; probamos la caché local antes de gastar una llamada
            fila = await db.get_user(num)
            if fila:
                nombre = fila["first_name"] or f"Usuario {num}"
                if fila["last_name"]:
                    nombre = f"{nombre} {fila['last_name']}"
                return _bloque_usuario(fila, nombre)
        try:
            chat = await context.bot.get_chat(num)
        except Exception:
            return None
        if chat.type == "private":
            return _bloque_usuario(chat, chat.full_name or "Usuario")
        return _bloque_chat(chat, "Chat")

    username = entrada.lstrip("@")
    resultado = await resolve_username(context, username)
    if resultado:
        user_id, nombre = resultado
        fila = await db.get_user(user_id)
        if fila:
            return _bloque_usuario(fila, nombre)
        return f"👤 <b>{escape(nombre)}</b>\n └ id: <code>{user_id}</code>"

    try:
        chat = await context.bot.get_chat(f"@{username}")
        return _bloque_chat(chat, "Chat")
    except Exception:
        return None


async def id_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.effective_message
    chat = update.effective_chat

    if context.args:
        bloque = await _bloque_desde_argumento(context, context.args[0])
        if not bloque:
            await message.reply_text(
                "No pude identificar eso. Si es una persona, tiene que haber "
                "escrito al menos un mensaje en algún chat donde esté el bot "
                "para poder resolverla por @usuario — es una limitación de la "
                "propia API de Telegram, no hay forma de saltársela."
            )
            return
        await message.reply_text(bloque, parse_mode=ParseMode.HTML)
        return

    if message.reply_to_message:
        bloques = _bloques_de_mensaje(message.reply_to_message)
        if not bloques:
            await message.reply_text("No pude sacar información de ese mensaje.")
            return
        await message.reply_text("\n\n".join(bloques), parse_mode=ParseMode.HTML)
        return

    # Sin argumento ni respuesta: quién pregunta + en qué chat está.
    # update.effective_user viene vacío en un post directo de canal (ahí no
    # hay un usuario real detrás, todo lo manda el canal de forma anónima).
    bloques = []
    if update.effective_user:
        bloques.append(_bloque_usuario(update.effective_user, "You"))
    bloques.append(_bloque_chat(chat, "Origin chat"))
    await message.reply_text("\n\n".join(bloques), parse_mode=ParseMode.HTML)


@group_only
async def admins_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    admins = await context.bot.get_chat_administrators(chat.id)
    lineas = []
    for a in admins:
        rol = "👑 Dueño" if a.status == "creator" else "🛡️ Admin"
        nombre = a.user.full_name
        lineas.append(f"{rol} — {nombre}")
    await update.effective_message.reply_text(
        "<b>Administradores:</b>\n" + "\n".join(lineas), parse_mode=ParseMode.HTML
    )


def register(application: Application, sudo_users):
    application.add_handler(CommandHandler("promote", promote_cmd))
    application.add_handler(CommandHandler("demote", demote_cmd))
    application.add_handler(CommandHandler("pin", pin_cmd))
    application.add_handler(CommandHandler("unpin", unpin_cmd))
    application.add_handler(CommandHandler("purge", purge_cmd))
    application.add_handler(CommandHandler("title", title_cmd))
    application.add_handler(CommandHandler("id", id_cmd))
    application.add_handler(CommandHandler("admins", admins_cmd))
