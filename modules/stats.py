"""Módulo stats — resumen operativo del bot.

Nota (ver ESTADO_DESARROLLO.md): Telegram anunció soporte de "rich messages"
para bots (tablas nativas, hasta 32.768 caracteres) en 2026, pero al momento
de este desarrollo la superficie pública de python-telegram-bot todavía no
expone un parse_mode dedicado para eso. Se deja el formato HTML monoespaciado
de abajo como base sólida y se documenta como mejora futura migrar a rich
text nativo en cuanto la librería lo soporte.
"""

import os
import platform
import time

import psutil
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import Application, CommandHandler, ContextTypes

from core.config import BOT_VERSION
from core.database import db
from utils.decorators import sudo_only

__mod_name__ = "Estadísticas"

_inicio = time.time()
_proc = psutil.Process(os.getpid())
_proc.cpu_percent(interval=None)  # primera lectura "en falso" para iniciar el contador


def _uptime_legible(segundos: float) -> str:
    dias, resto = divmod(int(segundos), 86400)
    horas, resto = divmod(resto, 3600)
    minutos, _ = divmod(resto, 60)
    partes = []
    if dias:
        partes.append(f"{dias}d")
    if horas:
        partes.append(f"{horas}h")
    partes.append(f"{minutos}m")
    return " ".join(partes)


@sudo_only
async def stats_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    total_chats = await db.fetchone("SELECT COUNT(*) as n FROM chats WHERE activo = 1")
    total_grupos = await db.fetchone(
        "SELECT COUNT(*) as n FROM chats WHERE activo = 1 AND tipo IN ('group','supergroup')"
    )
    total_canales = await db.fetchone("SELECT COUNT(*) as n FROM chats WHERE activo = 1 AND tipo = 'channel'")
    total_oficiales = await db.fetchone("SELECT COUNT(*) as n FROM chats WHERE es_oficial_tasalo = 1")
    feeds_activos = await db.fetchone("SELECT COUNT(*) as n FROM feeds WHERE activo = 1")
    feeds_con_error = await db.fetchone(
        "SELECT COUNT(*) as n FROM feed_stats WHERE errores > 0"
    )
    total_warns = await db.fetchone("SELECT COUNT(*) as n FROM warns")

    mem_mb = _proc.memory_info().rss / (1024 * 1024)
    cpu_pct = _proc.cpu_percent(interval=None)
    db_size_kb = os.path.getsize(db.path) / 1024 if os.path.exists(db.path) else 0

    texto = (
        f"📊 <b>taso-gcg — Estado</b>\n"
        f"————————————————————\n"
        f"🤖 Versión: <code>{BOT_VERSION}</code>\n"
        f"🐍 Python: <code>{platform.python_version()}</code>\n"
        f"⏱️ Uptime: <code>{_uptime_legible(time.time() - _inicio)}</code>\n"
        f"🧠 Memoria: <code>{mem_mb:.1f} MB</code>  |  CPU: <code>{cpu_pct:.1f}%</code>\n"
        f"💾 Base de datos: <code>{db_size_kb:.1f} KB</code>\n"
        f"————————————————————\n"
        f"💬 Chats gestionados: <code>{total_chats['n']}</code>\n"
        f"   Grupos: <code>{total_grupos['n']}</code>  |  Canales: <code>{total_canales['n']}</code>\n"
        f"⭐ Oficiales TASALO: <code>{total_oficiales['n']}</code>\n"
        f"📰 Feeds RSS activos: <code>{feeds_activos['n']}</code>"
        f" (con errores: <code>{feeds_con_error['n']}</code>)\n"
        f"⚠️ Avisos registrados: <code>{total_warns['n']}</code>"
    )
    await update.effective_message.reply_text(texto, parse_mode=ParseMode.HTML)


def register(application: Application, sudo_users):
    application.add_handler(CommandHandler("stats", stats_cmd))
