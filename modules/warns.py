"""Módulo warns — avisos acumulables con acción automática al llegar al límite."""

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import Application, CommandHandler, ContextTypes

from core.database import db
from utils.decorators import user_admin, bot_admin, group_only
from utils.common import extract_target_user

__mod_name__ = "Avisos"


@group_only
@user_admin
async def warn_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    user_id, nombre = extract_target_user(update)
    if not user_id:
        await update.effective_message.reply_text("Responde al mensaje de quien quieres avisar.")
        return

    razon = " ".join(context.args) if context.args else None
    chat_row = await db.ensure_chat(chat)
    dado_por = update.effective_user.id

    await db.execute(
        "INSERT INTO warns(chat_id, user_id, razon, dado_por) VALUES (?,?,?,?)",
        (chat_row["id"], user_id, razon, dado_por),
    )
    total = await db.fetchone(
        "SELECT COUNT(*) as n FROM warns WHERE chat_id = ? AND user_id = ?",
        (chat_row["id"], user_id),
    )
    settings = await db.get_chat_settings(chat_row["id"])
    limite = settings["warn_limit"]
    cantidad = total["n"]

    texto = f"⚠️ {nombre} recibió un aviso ({cantidad}/{limite})."
    if razon:
        texto += f"\nMotivo: {razon}"

    if cantidad >= limite:
        accion = settings["warn_action"]
        try:
            if accion == "ban":
                await context.bot.ban_chat_member(chat.id, user_id)
                texto += f"\n🔨 Límite alcanzado — {nombre} fue baneado."
            elif accion == "kick":
                await context.bot.ban_chat_member(chat.id, user_id)
                await context.bot.unban_chat_member(chat.id, user_id)
                texto += f"\n👢 Límite alcanzado — {nombre} fue expulsado."
            elif accion == "mute":
                from telegram import ChatPermissions
                await context.bot.restrict_chat_member(
                    chat.id, user_id, permissions=ChatPermissions(can_send_messages=False)
                )
                texto += f"\n🔇 Límite alcanzado — {nombre} fue silenciado."
            # Limpiar avisos tras aplicar la acción
            await db.execute(
                "DELETE FROM warns WHERE chat_id = ? AND user_id = ?", (chat_row["id"], user_id)
            )
        except Exception as e:
            texto += f"\n⚠️ No pude aplicar la sanción automática: {e}"

    await update.effective_message.reply_text(texto)


@group_only
async def warns_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id, nombre = extract_target_user(update)
    if not user_id:
        user_id, nombre = update.effective_user.id, update.effective_user.full_name
    chat_row = await db.ensure_chat(update.effective_chat)
    filas = await db.fetchall(
        "SELECT razon, creado_en FROM warns WHERE chat_id = ? AND user_id = ? ORDER BY creado_en",
        (chat_row["id"], user_id),
    )
    if not filas:
        await update.effective_message.reply_text(f"{nombre} no tiene avisos.")
        return
    lineas = [f"{i+1}. {f['razon'] or 'sin motivo'} ({f['creado_en']})" for i, f in enumerate(filas)]
    await update.effective_message.reply_text(
        f"<b>Avisos de {nombre}:</b>\n" + "\n".join(lineas), parse_mode=ParseMode.HTML
    )


@group_only
@user_admin
async def resetwarns_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id, nombre = extract_target_user(update)
    if not user_id:
        await update.effective_message.reply_text("Responde al mensaje de quien quieres limpiar los avisos.")
        return
    chat_row = await db.ensure_chat(update.effective_chat)
    await db.execute(
        "DELETE FROM warns WHERE chat_id = ? AND user_id = ?", (chat_row["id"], user_id)
    )
    await update.effective_message.reply_text(f"🧹 Avisos de {nombre} reiniciados.")


@group_only
@user_admin
async def setwarnlimit_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args or not context.args[0].isdigit():
        await update.effective_message.reply_text("Uso: /setwarnlimit 3")
        return
    chat_row = await db.ensure_chat(update.effective_chat)
    await db.update_chat_settings(chat_row["id"], warn_limit=int(context.args[0]))
    await update.effective_message.reply_text(f"✅ Límite de avisos: {context.args[0]}")


def register(application: Application, sudo_users):
    application.add_handler(CommandHandler("warn", warn_cmd))
    application.add_handler(CommandHandler("warns", warns_cmd))
    application.add_handler(CommandHandler("resetwarns", resetwarns_cmd))
    application.add_handler(CommandHandler("setwarnlimit", setwarnlimit_cmd))
