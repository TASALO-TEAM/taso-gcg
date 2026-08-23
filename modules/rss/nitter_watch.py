"""Vigilante de recuperación de instancias Nitter — job periódico aparte del
RSSMonitor normal (ver 2026-08-22-nitter-instancias-fallback.md y
scripts/diagnostico_nitter.py para el contexto completo).

Por qué existe: el diagnóstico del 2026-08-22 confirmó 0/12 instancias del
pool respondiendo a este VPS. Mientras se sube manualmente el contenido de
esas cuentas, este job repasa TODO el pool cada cierto tiempo (mismo cliente
y mismo espaciado de 1s entre instancias que scripts/diagnostico_nitter.py,
para no golpearlas todas de una vez) y avisa a LOG_CHAT_ID -- el mismo grupo
donde el bot ya manda el aviso de arranque y los errores no controlados --
SOLO cuando una instancia que antes fallaba empieza a responder. No avisa en
cada ciclo si todo sigue igual, para no llenar el grupo de ruido repetido.
"""

import asyncio

from core.config import LOG_CHAT_ID
from core.database import db
from modules.rss.parser import RSSParser
from utils.logger import log

_ok_previo: set[str] = set()
_primera_pasada = True


async def _elegir_usuario_de_prueba() -> str | None:
    """Usa el @usuario de la primera fuente social (X/Twitter directo o
    espejo Nitter) que ya esté configurada como feed activo, en vez de
    depender de una cuenta ajena hardcodeada en el código."""
    feeds = await db.fetchall("SELECT url FROM feeds WHERE activo = 1")
    for feed in feeds:
        if RSSParser.is_social_source(feed["url"]):
            usuario = RSSParser._username_from_feed_url(feed["url"])
            if usuario:
                return usuario
    return None


async def check_nitter_recovery(bot):
    """Job de APScheduler. Sin argumentos propios más allá de `bot` (se pasa
    vía args= al registrar el job, ver handlers.py)."""
    global _primera_pasada

    usuario = await _elegir_usuario_de_prueba()
    if not usuario:
        return  # no hay ninguna fuente social configurada todavía, nada que probar

    ok_ahora = set()
    for instancia in RSSParser.NITTER_INSTANCES:
        url = f"{instancia}/{usuario}/rss"
        content, error = await RSSParser.fetch_content(url)
        if not error and RSSParser.is_valid_xml(content):
            ok_ahora.add(instancia)
        await asyncio.sleep(1)

    recien_recuperadas = ok_ahora - _ok_previo
    _ok_previo.clear()
    _ok_previo.update(ok_ahora)

    if _primera_pasada:
        # No avisar en el primer chequeo tras un arranque del proceso: no
        # sabemos si esto ya venía funcionando de antes, así que este ciclo
        # solo establece la base para comparar contra el siguiente.
        _primera_pasada = False
        return

    if not recien_recuperadas or not LOG_CHAT_ID:
        return

    lista = "\n".join(f"• {i}" for i in sorted(recien_recuperadas))
    try:
        await bot.send_message(
            LOG_CHAT_ID,
            f"🟢 Instancia(s) Nitter recuperada(s) (probado con @{usuario}):\n{lista}",
        )
    except Exception as e:
        log(f"No se pudo notificar recuperación de Nitter: {e}", "warning")
