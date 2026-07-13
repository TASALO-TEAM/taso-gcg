"""Módulo bans — ban/kick/unban, con variantes temporales (tban/tmute)."""

from datetime import datetime, timedelta, timezone

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

from utils.decorators import user_admin, bot_admin, group_only
from utils.common import extract_target_user, parse_duration, humanize_seconds

__mod_name__ = "Bans"


def _razon_desde_args(context, offset=0):
    args = context.args[offset:] if context.args else []
    return " ".join(args) if args else None


@group_only
@user_admin
@bot_admin
async def ban_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    user_id, nombre = extract_target_user(update)
    if not user_id:
        await update.effective_message.reply_text("Responde al mensaje de quien quieres banear.")
        return
    razon = _razon_desde_args(context)
    try:
        await context.bot.ban_chat_member(chat.id, user_id)
        texto = f"🔨 {nombre} fue baneado."
        if razon:
            texto += f"\nMotivo: {razon}"
        await update.effective_message.reply_text(texto)
    except Exception as e:
        await update.effective_message.reply_text(f"⚠️ No pude banearlo: {e}")


@group_only
@user_admin
@bot_admin
async def tban_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Uso: /tban (respondiendo) 1h [motivo]"""
    chat = update.effective_chat
    user_id, nombre = extract_target_user(update)
    if not user_id:
        await update.effective_message.reply_text("Responde al mensaje de quien quieres banear temporalmente.")
        return
    if not context.args:
        await update.effective_message.reply_text("Indica la duración, ej: /tban 1h")
        return
    segundos = parse_duration(context.args[0])
    if not segundos:
        await update.effective_message.reply_text("Duración inválida. Usa formato: 30m, 2h, 1d.")
        return
    hasta = datetime.now(timezone.utc) + timedelta(seconds=segundos)
    try:
        await context.bot.ban_chat_member(chat.id, user_id, until_date=hasta)
        await update.effective_message.reply_text(
            f"⏳ {nombre} baneado por {humanize_seconds(segundos)}."
        )
    except Exception as e:
        await update.effective_message.reply_text(f"⚠️ No pude aplicar el ban temporal: {e}")


@group_only
@user_admin
@bot_admin
async def unban_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    user_id, nombre = extract_target_user(update)
    if not user_id:
        await update.effective_message.reply_text("Responde al mensaje o menciona a quien quieres desbanear.")
        return
    try:
        await context.bot.unban_chat_member(chat.id, user_id, only_if_banned=True)
        await update.effective_message.reply_text(f"✅ {nombre} fue desbaneado.")
    except Exception as e:
        await update.effective_message.reply_text(f"⚠️ No pude desbanearlo: {e}")


@group_only
@user_admin
@bot_admin
async def kick_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    user_id, nombre = extract_target_user(update)
    if not user_id:
        await update.effective_message.reply_text("Responde al mensaje de quien quieres expulsar.")
        return
    try:
        await context.bot.ban_chat_member(chat.id, user_id)
        await context.bot.unban_chat_member(chat.id, user_id)  # kick real: ban + unban inmediato
        await update.effective_message.reply_text(f"👢 {nombre} fue expulsado (puede volver a entrar).")
    except Exception as e:
        await update.effective_message.reply_text(f"⚠️ No pude expulsarlo: {e}")


@group_only
@user_admin
@bot_admin
async def mute_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    user_id, nombre = extract_target_user(update)
    if not user_id:
        await update.effective_message.reply_text("Responde al mensaje de quien quieres mutear.")
        return
    try:
        await context.bot.restrict_chat_member(chat.id, user_id, permissions=_sin_permisos())
        await update.effective_message.reply_text(f"🔇 {nombre} fue silenciado.")
    except Exception as e:
        await update.effective_message.reply_text(f"⚠️ No pude silenciarlo: {e}")


@group_only
@user_admin
@bot_admin
async def tmute_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    user_id, nombre = extract_target_user(update)
    if not user_id:
        await update.effective_message.reply_text("Responde al mensaje de quien quieres silenciar.")
        return
    if not context.args:
        await update.effective_message.reply_text("Indica la duración, ej: /tmute 30m")
        return
    segundos = parse_duration(context.args[0])
    if not segundos:
        await update.effective_message.reply_text("Duración inválida. Usa formato: 30m, 2h, 1d.")
        return
    hasta = datetime.now(timezone.utc) + timedelta(seconds=segundos)
    try:
        await context.bot.restrict_chat_member(
            chat.id, user_id, permissions=_sin_permisos(), until_date=hasta
        )
        await update.effective_message.reply_text(
            f"🔇 {nombre} silenciado por {humanize_seconds(segundos)}."
        )
    except Exception as e:
        await update.effective_message.reply_text(f"⚠️ No pude silenciarlo: {e}")


@group_only
@user_admin
@bot_admin
async def unmute_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    user_id, nombre = extract_target_user(update)
    if not user_id:
        await update.effective_message.reply_text("Responde al mensaje de quien quieres quitarle el silencio.")
        return
    try:
        await context.bot.restrict_chat_member(chat.id, user_id, permissions=_permisos_normales())
        await update.effective_message.reply_text(f"🔊 {nombre} puede hablar de nuevo.")
    except Exception as e:
        await update.effective_message.reply_text(f"⚠️ No pude quitarle el silencio: {e}")


def _sin_permisos():
    from telegram import ChatPermissions
    return ChatPermissions(can_send_messages=False)


def _permisos_normales():
    from telegram import ChatPermissions
    return ChatPermissions(
        can_send_messages=True, can_send_polls=True, can_send_other_messages=True,
        can_add_web_page_previews=True, can_change_info=False, can_invite_users=True,
        can_pin_messages=False,
    )


def register(application: Application, sudo_users):
    application.add_handler(CommandHandler("ban", ban_cmd))
    application.add_handler(CommandHandler("tban", tban_cmd))
    application.add_handler(CommandHandler("unban", unban_cmd))
    application.add_handler(CommandHandler("kick", kick_cmd))
    application.add_handler(CommandHandler("mute", mute_cmd))
    application.add_handler(CommandHandler("tmute", tmute_cmd))
    application.add_handler(CommandHandler("unmute", unmute_cmd))
