"""Publicación automática de TASALO (taso-gcg como Gestor de Canales).

Piezas: `base` (tipos y registros de fuentes/destinos) y `store` (base de datos,
cuentas con secretos cifrados y registro idempotente). El planificador, los
destinos (Telegram, Nostr, Hive) y el panel /pub se añaden por fases; ver
docs/plans/2026-11-26-publicacion-automatica.plan.md.
"""


def register(application, sudo_users) -> None:
    """Sin handlers todavía (P1.2 programa los jobs, P5 añade /pub). Existe para
    que el cargador no avise de un módulo sin register()."""
