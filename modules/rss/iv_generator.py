"""Generador de enlaces Instant View — adaptado de BitBreadRSS/services/iv_generator.py.

Diferencia con el original: las plantillas (rhash por dominio) ya no viven en
un JSON aparte (global_templates.json), sino en la tabla iv_templates de
taso_gcg.db, para mantener un único punto de persistencia en todo el proyecto.
"""

import urllib.parse

from core.database import db


async def create_instant_view_link(original_url: str, user_rhash: str = None, custom_label: str = None) -> str:
    """Genera el link usando la jerarquía de rhashes: el del usuario > el de la
    tabla iv_templates (por dominio o universal) > sin Instant View (URL cruda)."""
    rhash = user_rhash if user_rhash and user_rhash.lower() != "none" else await db.find_iv_rhash(original_url)

    if not rhash:
        return original_url

    encoded_url = urllib.parse.quote(original_url, safe="")
    iv_url = f"https://t.me/iv?url={encoded_url}&rhash={rhash}"
    label = custom_label if custom_label else "Leer en Telegram ⚡"
    return f'<a href="{iv_url}">{label}</a>'
