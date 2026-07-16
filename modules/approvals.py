"""Módulo approvals — usuarios de confianza inmunes a antiflood/blacklist/locks
(pero no a acciones manuales de un admin como /ban). Concepto tomado de Rose."""

import html

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import Application, CommandHandler, ContextTypes

from core.database import db
from utils.decorators import user_admin, sudo_only, group_only
from utils.common import extract_target_user, raw_text_after_command

__mod_name__ = "Aprobaciones"


@group_only
@user_admin
async def approve_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id, nombre = await extract_target_user(update, context)
    if not user_id:
        await update.effective_message.reply_text("Responde al mensaje de quien quieres aprobar.")
        return
    razon = raw_text_after_command(update) if context.args else None
    chat_row = await db.ensure_chat(update.effective_chat)
    await db.execute(
        "INSERT INTO approvals(chat_id, user_id, razon, aprobado_por) VALUES (?,?,?,?) "
        "ON CONFLICT(chat_id, user_id) DO UPDATE SET razon = excluded.razon",
        (chat_row["id"], user_id, razon, update.effective_user.id),
    )
    await update.effective_message.reply_text(
        f"✅ {nombre} está aprobado — ya no lo afectan antiflood, blacklist ni locks."
    )


@group_only
async def approval_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id, nombre = await extract_target_user(update, context)
    if not user_id:
        await update.effective_message.reply_text("Responde al mensaje de quien quieres consultar.")
        return
    chat_row = await db.ensure_chat(update.effective_chat)
    fila = await db.fetchone(
        "SELECT razon FROM approvals WHERE chat_id = ? AND user_id = ?", (chat_row["id"], user_id)
    )
    if not fila:
        await update.effective_message.reply_text(f"{nombre} no está aprobado.")
        return
    texto = f"✅ {nombre} está aprobado."
    if fila["razon"]:
        texto += f"\nMotivo: {fila['razon']}"
    await update.effective_message.reply_text(texto)


@group_only
async def approved_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_row = await db.ensure_chat(update.effective_chat)
    filas = await db.fetchall(
        "SELECT user_id, razon FROM approvals WHERE chat_id = ?", (chat_row["id"],)
    )
    if not filas:
        await update.effective_message.reply_text("No hay usuarios aprobados en este chat.")
        return
    lineas = [f"• <code>{f['user_id']}</code> — {html.escape(f['razon'] or 'sin motivo')}" for f in filas]
    await update.effective_message.reply_text(
        "✅ <b>Usuarios aprobados:</b>\n" + "\n".join(lineas), parse_mode=ParseMode.HTML
    )


@group_only
@user_admin
async def unapprove_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id, nombre = await extract_target_user(update, context)
    if not user_id:
        await update.effective_message.reply_text("Responde al mensaje de quien quieres desaprobar.")
        return
    chat_row = await db.ensure_chat(update.effective_chat)
    await db.execute(
        "DELETE FROM approvals WHERE chat_id = ? AND user_id = ?", (chat_row["id"], user_id)
    )
    await update.effective_message.reply_text(f"❌ {nombre} ya no está aprobado.")


@group_only
@sudo_only
async def unapproveall_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Reservado al dueño real del chat en Rose; aquí lo dejamos a SUDO_USERS para
    evitar que cualquier admin borre todas las aprobaciones por accidente."""
    chat_row = await db.ensure_chat(update.effective_chat)
    await db.execute("DELETE FROM approvals WHERE chat_id = ?", (chat_row["id"],))
    await update.effective_message.reply_text("🧹 Todas las aprobaciones fueron eliminadas.")


def register(application: Application, sudo_users):
    application.add_handler(CommandHandler("approve", approve_cmd))
    application.add_handler(CommandHandler("approval", approval_cmd))
    application.add_handler(CommandHandler("approved", approved_cmd))
    application.add_handler(CommandHandler("unapprove", unapprove_cmd))
    application.add_handler(CommandHandler("unapproveall", unapproveall_cmd))
