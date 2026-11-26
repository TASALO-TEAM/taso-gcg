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

_ok_previo: set[str] = set()  # solo para el log: instancia suelta que sube/baja NO avisa

# Estado del pool: "sano" (>=1 instancia responde) o "caido" (ninguna). Se avisa
# solo al CONFIRMAR un cambio de estado (CONFIRMACIONES pasadas seguidas iguales),
# no por cada instancia que vuelve: con instancias intermitentes eso era ruido.
CONFIRMACIONES = 2
_estado_confirmado: str | None = None
_estado_pendiente: str | None = None
_contador = 0


def _registrar_pasada(estado_ahora: str) -> str | None:
    """Devuelve el nuevo estado si hubo un cambio real que avisar; si no, None.
    La primera confirmación tras arrancar solo fija la base (sin aviso)."""
    global _estado_confirmado, _estado_pendiente, _contador
    if estado_ahora == _estado_confirmado:
        _estado_pendiente, _contador = None, 0
        return None
    if estado_ahora == _estado_pendiente:
        _contador += 1
    else:
        _estado_pendiente, _contador = estado_ahora, 1
    if _contador < CONFIRMACIONES:
        return None
    previo, _estado_confirmado = _estado_confirmado, estado_ahora
    _estado_pendiente, _contador = None, 0
    return estado_ahora if previo is not None else None


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
    if recien_recuperadas:
        log(f"Nitter: instancia(s) recuperada(s): {sorted(recien_recuperadas)}", "info")

    cambio = _registrar_pasada("sano" if ok_ahora else "caido")
    if not cambio or not LOG_CHAT_ID:
        return

    if cambio == "sano":
        texto = (
            f"🟢 Nitter vuelve a responder ({len(ok_ahora)}/{len(RSSParser.NITTER_INSTANCES)} "
            f"instancias, probado con @{usuario}). Las fuentes de X se reanudan solas."
        )
    else:
        texto = (
            "🔴 Ninguna instancia Nitter responde desde hace varios chequeos: las fuentes de "
            "X/Twitter no se actualizarán hasta que alguna vuelva."
        )
    try:
        await bot.send_message(LOG_CHAT_ID, texto)
    except Exception as e:
        log(f"No se pudo notificar el estado de Nitter: {e}", "warning")
