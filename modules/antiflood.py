"""Módulo antiflood — cuenta mensajes consecutivos por usuario en una ventana
de tiempo corta y aplica una acción si se excede el límite del chat.

Deliberadamente en memoria (no en SQLite): es un chequeo que corre en CADA
mensaje de CADA chat, tiene que ser instantáneo y no necesita sobrevivir un
reinicio del bot (un flood es, por definición, algo que pasa ahora mismo).
"""

import time

from telegram import Update, ChatPermissions
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

from core.database import db
from modules.log_channel import enviar_log
from modules.moderation_context import explicar_en_log
from utils.decorators import user_admin, group_only

__mod_name__ = "AntiFlood"

VENTANA_SEGUNDOS = 10
# _tracker[chat_id][user_id] = [timestamps recientes]
_tracker: dict[int, dict[int, list[float]]] = {}


async def _check_flood(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    user = update.effective_user
    if not chat or not user or chat.type not in ("group", "supergroup"):
        return

    chat_row = await db.ensure_chat(chat)
    if await db.is_approved(chat_row["id"], user.id):
        return  # usuario aprobado: inmune a antiflood
    settings = await db.get_chat_settings(chat_row["id"])
    limite = settings["flood_limit"]
    if limite <= 0:
        return  # antiflood desactivado en este chat

    ahora = time.time()
    chat_bucket = _tracker.setdefault(chat.id, {})
    marcas = chat_bucket.setdefault(user.id, [])
    marcas.append(ahora)
    # Descartar marcas fuera de la ventana
    marcas[:] = [t for t in marcas if ahora - t <= VENTANA_SEGUNDOS]

    if len(marcas) > limite:
        cantidad_mensajes = len(marcas)
        marcas.clear()
        accion = settings["flood_action"]
        try:
            if accion == "ban":
                await context.bot.ban_chat_member(chat.id, user.id)
                texto = f"🔨 {user.full_name} baneado por flood."
            elif accion == "kick":
                await context.bot.ban_chat_member(chat.id, user.id)
                await context.bot.unban_chat_member(chat.id, user.id)
                texto = f"👢 {user.full_name} expulsado por flood."
            else:  # mute por defecto
                await context.bot.restrict_chat_member(
                    chat.id, user.id, permissions=ChatPermissions(can_send_messages=False)
                )
                texto = f"🔇 {user.full_name} silenciado por flood."
            await update.effective_message.reply_text(texto)
            await enviar_log(context, chat.id, "automated", texto)
            explicar_en_log(context, chat.id, "automated", {
                "tipo": "flood",
                "mensajes_enviados": cantidad_mensajes,
                "ventana_segundos": VENTANA_SEGUNDOS,
                "accion_aplicada": accion,
            })
        except Exception:
            pass


@group_only
@user_admin
async def setflood_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args or not context.args[0].isdigit():
        await update.effective_message.reply_text(
            "Uso: /setflood <n>  (0 desactiva). Ej: /setflood 5"
        )
        return
    chat_row = await db.ensure_chat(update.effective_chat)
    limite = int(context.args[0])
    await db.update_chat_settings(chat_row["id"], flood_limit=limite)
    if limite == 0:
        await update.effective_message.reply_text("✅ Antiflood desactivado.")
    else:
        await update.effective_message.reply_text(
            f"✅ Antiflood activado: más de {limite} mensajes en {VENTANA_SEGUNDOS}s dispara la acción."
        )


@group_only
@user_admin
async def setfloodaction_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    opciones = ("mute", "kick", "ban")
    if not context.args or context.args[0].lower() not in opciones:
        await update.effective_message.reply_text(f"Uso: /setfloodaction <{'|'.join(opciones)}>")
        return
    chat_row = await db.ensure_chat(update.effective_chat)
    await db.update_chat_settings(chat_row["id"], flood_action=context.args[0].lower())
    await update.effective_message.reply_text(f"✅ Acción de antiflood: {context.args[0].lower()}")


def register(application: Application, sudo_users):
    application.add_handler(CommandHandler("setflood", setflood_cmd))
    application.add_handler(CommandHandler("setfloodaction", setfloodaction_cmd))
    # group=1: corre después del chat_tracker (group=-1) pero antes de otros módulos de contenido
    application.add_handler(MessageHandler(filters.ALL & filters.ChatType.GROUPS, _check_flood), group=1)
