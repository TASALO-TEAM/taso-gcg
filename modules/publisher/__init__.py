"""Publicación automática de TASALO (taso-gcg como Gestor de Canales).

Piezas: `base` (tipos y registros de fuentes/destinos), `store` (base de datos,
cuentas con secretos cifrados y registro idempotente) y `scheduler` (tick por
minuto). Los destinos (Telegram, Nostr, Hive) y el panel /pub se añaden por
fases; ver docs/plans/2026-11-26-publicacion-automatica.plan.md.
"""

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger


def register(application, sudo_users) -> None:
    """Arranca el tick de publicación. Sin jobs en la base no hace nada visible
    (una consulta diminuta por minuto). El panel /pub llega en P5."""
    from modules.publisher.scheduler import tick

    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        tick, IntervalTrigger(seconds=60), args=[application.bot],
        id="pub_tick", max_instances=1, coalesce=True,
    )
    scheduler.start()
    application.bot_data["pub_scheduler"] = scheduler
