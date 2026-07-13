"""Módulo admin — operaciones básicas de administración de chat.

Comandos: /promote /demote /pin /unpin /purge /title /id /admins
"""

from telegram import Update, ChatMemberAdministrator
from telegram.constants import ParseMode
from telegram.ext import Application, CommandHandler, ContextTypes

from utils.decorators import user_admin, bot_admin, group_only, refresh_admin_cache
from utils.common import extract_target_user
from utils.logger import log

__mod_name__ = "Administración"


@group_only
@user_admin
@bot_admin
async def promote_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    user_id, nombre = extract_target_user(update)
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
    user_id, nombre = extract_target_user(update)
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


async def id_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    message = update.effective_message
    if message.reply_to_message:
        u = message.reply_to_message.from_user
        await message.reply_text(f"👤 {u.full_name}: <code>{u.id}</code>", parse_mode=ParseMode.HTML)
    else:
        await message.reply_text(f"💬 ID de este chat: <code>{chat.id}</code>", parse_mode=ParseMode.HTML)


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
