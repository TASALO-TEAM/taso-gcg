"""Planificador de la publicación automática.

Un solo tick por minuto (en vez de un job de APScheduler por publicación): lee
`pub_jobs`, y si a un job activo le toca (día y hora de Cuba) ejecuta sus
destinos. Así editar hora o días desde el bot no exige reprogramar nada,
sobrevive a reinicios y cuesta una consulta diminuta por minuto.

Garantías:
- Idempotente: `store.reservar` impide dos publicaciones del mismo (job, destino, día).
- Un destino caído no bloquea a los demás.
- Reintenta un destino fallido tras ESPERA_REINTENTO, hasta MAX_INTENTOS; solo al
  agotarlos manda UN aviso (mismo criterio que nitter_watch: avisar lo que requiere atención).
- Modo prueba (`simular`): no envía ni descifra secretos; usa otra clave de día
  ("~sim") para no bloquear la publicación real de ese día.
"""

import time
from datetime import datetime
from zoneinfo import ZoneInfo

from core.config import LOG_CHAT_ID, PUB_DRY_RUN
from modules.publisher import store
from modules.publisher.base import DESTINOS, FUENTES, Resultado
from utils.logger import log

TZ = ZoneInfo("America/Havana")
# shortcut: la ventana no cruza medianoche (un job a las 23:30 no recupera a las 00:10); subir si hace falta.
VENTANA_MIN = 180        # si el bot estuvo caído, publica hasta 3 h tarde; pasado eso se salta el día
MAX_INTENTOS = 3
ESPERA_REINTENTO = 600   # segundos entre intentos de un mismo destino

# shortcut: la espera entre reintentos vive en memoria; tras un reinicio se reintenta enseguida.
_ultimo_intento: dict[tuple, float] = {}


def toca(job: dict, ahora: datetime) -> bool:
    """¿Corresponde publicar este job ahora? Día de la semana (lun=0) y ventana desde su hora."""
    dias = job["dias"]
    if dias != "*" and str(ahora.weekday()) not in dias.split(","):
        return False
    pasados = (ahora.hour * 60 + ahora.minute) - (job["hora"] * 60 + job["minuto"])
    return 0 <= pasados < VENTANA_MIN


def _limpiar(texto: str, secreto: str | None) -> str:
    """Quita el secreto de cualquier texto que vaya a log, base de datos o aviso."""
    return texto.replace(secreto, "***") if secreto else texto


async def _avisar(bot, texto: str) -> None:
    if not (bot and LOG_CHAT_ID):
        return
    try:
        await bot.send_message(LOG_CHAT_ID, texto)
    except Exception as e:
        log(f"Publicador: no se pudo avisar al LOG_CHAT_ID: {e}", "warning")


async def _fallo(bot, job: dict, d: dict, clave: str, error: str, simular: bool) -> None:
    await store.marcar(job["id"], d["id"], clave, "error", error=error)
    n = await store.intentos(job["id"], d["id"], clave)
    log(f"Publicador: '{job['nombre']}' → {d['tipo']} falló (intento {n}/{MAX_INTENTOS}): {error}", "warning")
    if n >= MAX_INTENTOS:
        pref = "🧪 (prueba) " if simular else "🔴 "
        await _avisar(bot, f"{pref}No se pudo publicar '{job['nombre']}' en {d['tipo']} tras {n} intentos: {error[:300]}")


async def _publicar_uno(bot, job: dict, d: dict, contenido, clave: str, simular: bool) -> None:
    secreto = None
    try:
        fn = DESTINOS.get(d["tipo"])
        if fn is None:
            raise RuntimeError(f"destino '{d['tipo']}' sin implementar")
        cuenta = None
        if d["cuenta_id"]:
            cuenta = await store.get_cuenta(d["cuenta_id"])
            if not cuenta or not cuenta["activa"]:
                raise RuntimeError("la cuenta del destino está inactiva o fue borrada")
            if not simular:
                secreto = await store.obtener_secreto(d["cuenta_id"])
        r = await fn(contenido, d, cuenta, secreto, simular)
    except Exception as e:
        r = Resultado(False, error=f"{type(e).__name__}: {e}")
    if not r.ok:
        await _fallo(bot, job, d, clave, _limpiar(r.error or "error desconocido", secreto), simular)
        return
    estado = "simulado" if (simular or r.simulado) else "ok"
    await store.marcar(job["id"], d["id"], clave, estado, url=r.url)
    _ultimo_intento.pop((job["id"], d["id"], clave), None)
    log(f"Publicador: '{job['nombre']}' → {d['tipo']} {estado}" + (f" {r.url}" if r.url else ""))


async def ejecutar_job(job: dict, fecha: str, bot=None, simular: bool = True) -> None:
    """Publica el job en todos sus destinos activos que aún no estén hechos hoy."""
    clave = fecha + ("~sim" if simular else "")
    pendientes = []
    for d in await store.listar_destinos(job["id"], solo_activos=True):
        k = (job["id"], d["id"], clave)
        if time.monotonic() - _ultimo_intento.get(k, -ESPERA_REINTENTO) < ESPERA_REINTENTO:
            continue                       # reintento demasiado pronto
        if await store.reservar(job["id"], d["id"], clave, MAX_INTENTOS):
            _ultimo_intento[k] = time.monotonic()
            pendientes.append(d)
    if not pendientes:
        return
    try:
        fuente = FUENTES.get(job["fuente"])
        if fuente is None:
            raise RuntimeError(f"fuente '{job['fuente']}' sin implementar")
        contenido = await fuente()
    except Exception as e:
        for d in pendientes:
            await _fallo(bot, job, d, clave, f"fuente: {type(e).__name__}: {e}", simular)
        return
    for d in pendientes:                   # uno a uno: un destino caído no bloquea al resto
        await _publicar_uno(bot, job, d, contenido, clave, simular)


async def tick(bot=None, ahora: datetime | None = None) -> None:
    """Job periódico de APScheduler (cada 60 s)."""
    ahora = ahora or datetime.now(TZ)
    fecha = ahora.date().isoformat()
    simular = None                         # se lee de la base solo si hay algo que publicar
    for job in await store.listar_jobs(solo_activos=True):
        if not toca(job, ahora):
            continue
        try:
            if simular is None:
                simular = await store.modo_prueba(PUB_DRY_RUN)
            await ejecutar_job(job, fecha, bot, simular)
        except Exception as e:             # un job roto no debe tumbar a los demás
            log(f"Publicador: error ejecutando '{job['nombre']}': {e}", "error")
