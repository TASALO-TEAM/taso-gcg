"""Módulo join_requests — filtra solicitudes de ingreso a chats con "solicitud
para unirse" activada.

Telegram introdujo en 2026 los "AI Guardians" (bots admin que procesan
chat_join_request) — aquí implementamos el mismo mecanismo nativo sin
necesitar IA: si el chat tiene join_captcha activado, se le pide al
solicitante tocar un botón antes de aprobarlo (filtra bots simples de spam).
"""

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, ChatJoinRequestHandler, CallbackQueryHandler,
    CommandHandler, ContextTypes,
)

from core.database import db
from utils.decorators import user_admin, group_only

__mod_name__ = "Solicitudes de ingreso"

CB_PREFIX = "joinreq:"


async def _on_join_request(update: Update, context: ContextTypes.DEFAULT_TYPE):
    request = update.chat_join_request
    chat = request.chat
    user = request.from_user

    chat_row = await db.ensure_chat(chat)
    settings = await db.get_chat_settings(chat_row["id"])

    await db.execute(
        "INSERT INTO join_requests(chat_id, user_id, estado) VALUES (?,?,'pendiente') "
        "ON CONFLICT(chat_id, user_id) DO UPDATE SET estado='pendiente'",
        (chat.id, user.id),
    )

    if not settings["join_captcha"]:
        # Sin verificación configurada: aprobar automáticamente
        try:
            await context.bot.approve_chat_join_request(chat.id, user.id)
        except Exception:
            pass
        return

    # Con verificación: mandar un botón por PM al solicitante
    boton = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Confirmar que soy una persona", callback_data=f"{CB_PREFIX}{chat.id}")
    ]])
    try:
        await context.bot.send_message(
            user.id,
            f"👋 Solicitaste unirte a <b>{chat.title}</b>. Toca el botón para confirmar tu ingreso.",
            parse_mode="HTML",
            reply_markup=boton,
        )
    except Exception:
        # Si el usuario nunca inició chat con el bot, no se le puede escribir por PM;
        # se deja la solicitud pendiente para revisión manual de un admin.
        pass


async def _on_confirm_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    tg_chat_id = int(query.data.replace(CB_PREFIX, ""))
    user_id = query.from_user.id
    try:
        await context.bot.approve_chat_join_request(tg_chat_id, user_id)
        await query.edit_message_text("✅ ¡Listo! Ya puedes entrar al grupo.")
        chat_row = await db.fetchone("SELECT id FROM chats WHERE tg_chat_id = ?", (tg_chat_id,))
        if chat_row:
            await db.execute(
                "UPDATE join_requests SET estado='aprobada' WHERE chat_id = ? AND user_id = ?",
                (tg_chat_id, user_id),
            )
    except Exception as e:
        await query.edit_message_text(f"⚠️ No pude aprobar tu solicitud: {e}")
    await query.answer()


@group_only
@user_admin
async def joincaptcha_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args or context.args[0].lower() not in ("on", "off"):
        await update.effective_message.reply_text("Uso: /joincaptcha on|off")
        return
    chat_row = await db.ensure_chat(update.effective_chat)
    await db.update_chat_settings(chat_row["id"], join_captcha=1 if context.args[0].lower() == "on" else 0)
    await update.effective_message.reply_text(f"✅ Verificación de ingreso: {context.args[0].lower()}")


def register(application: Application, sudo_users):
    application.add_handler(ChatJoinRequestHandler(_on_join_request))
    application.add_handler(CallbackQueryHandler(_on_confirm_button, pattern=f"^{CB_PREFIX}"))
    application.add_handler(CommandHandler("joincaptcha", joincaptcha_cmd))
