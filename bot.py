"""taso-gcg — Gestión de Canales y Grupos de TASALO.

Punto de entrada único: moderación + RSS corren en el mismo proceso
(ver ESTADO_DESARROLLO.md para la justificación de esta decisión).
"""

import logging

from telegram.ext import Application, ApplicationBuilder, ContextTypes

from core.config import TOKEN, BOT_VERSION, LOG_CHAT_ID
from core.database import db
from core.loader import load_all
from utils.logger import log

# Bajamos el ruido de librerías de terceros; nuestro propio logger ya cubre lo importante
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("telegram.ext").setLevel(logging.ERROR)
logging.getLogger("apscheduler").setLevel(logging.WARNING)


async def post_init(application: Application):
    await db.init()
    cargados = load_all(application)
    log(f"🚀 taso-gcg v{BOT_VERSION} arrancando con {len(cargados)} módulos")

    if LOG_CHAT_ID:
        try:
            await application.bot.send_message(
                LOG_CHAT_ID, f"🚀 taso-gcg v{BOT_VERSION} en línea."
            )
        except Exception as e:
            log(f"No se pudo notificar el arranque al LOG_CHAT_ID: {e}", "warning")


async def post_shutdown(application: Application):
    scheduler = application.bot_data.get("rss_scheduler")
    if scheduler:
        scheduler.shutdown(wait=False)
    await db.close()
    log("👋 taso-gcg detenido limpiamente.")


def main():
    if not TOKEN:
        raise SystemExit("TELEGRAM_TOKEN no configurado — revisa tu .env")

    application = (
        ApplicationBuilder()
        .token(TOKEN)
        .post_init(post_init)
        .post_shutdown(post_shutdown)
        .build()
    )

    application.run_polling(allowed_updates=["message", "callback_query", "my_chat_member",
                                              "chat_member", "chat_join_request"])


if __name__ == "__main__":
    main()
