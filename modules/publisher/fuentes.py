"""Fuentes de contenido de la publicación automática.

`year`: estado del año (progreso, días que faltan y frase del día) desde taso-api
`GET /api/v1/year/state` (público, sin clave). Mismo formato que el comando /y de taso-bot,
en texto plano para que sirva igual en Telegram, Nostr y los microblogs de Hive.
"""

import httpx

from core.config import TASO_API_URL
from modules.publisher.base import Contenido, fuente

HTTP_TIMEOUT = 10
FRASE_RESPALDO = "⏳ El tiempo vuela, pero tú eres el piloto."
TAGS_YEAR = ("tasalo", "estadodelano")


def _animo(pct: float) -> str:
    if pct < 2:
        return "🍀 Recién estamos empezando..."
    if pct < 10:
        return "🌱 Arrancando motores..."
    if pct < 50:
        return "🏃‍♂️ Aún hay tiempo de cumplir propósitos."
    if pct < 80:
        return "🔥 ¡Se nos va el año!"
    return "🏁 Recta final, ¡agárrate!"


def armar_year(data: dict) -> Contenido:
    """Convierte la respuesta de /state en Contenido. Lanza ValueError si falta lo esencial."""
    prog = data.get("progress") or {}
    try:
        year = int(prog["year"])
        pct = float(prog["percent"])
        dias = int(prog["days_left"])
    except (KeyError, TypeError, ValueError):
        raise ValueError("respuesta de /state sin progreso del año")
    fecha = prog.get("date_str", "")
    llenos = max(0, min(20, int(20 * pct // 100)))
    barra = "▓" * llenos + "░" * (20 - llenos)
    frase = ((data.get("quote") or {}).get("quote") or FRASE_RESPALDO).strip()
    texto = (
        f"🗓 ESTADO DEL AÑO {year}\n"
        f"•••\n"
        f"📆 Fecha: {fecha}\n"
        f"⏳ Progreso: {pct:.2f}%\n"
        f"📊 {barra}\n\n"
        f"🔚 Faltan {dias} días para {year + 1}.\n"
        f"💭 {_animo(pct)}\n"
        f"•••\n"
        f"💡 Frase Del Día:\n"
        f"\"{frase}\""
    )
    return Contenido(
        titulo=f"Estado del año {year}: {pct:.2f}%",
        cuerpo_md=texto,
        texto_corto=texto,
        tags=TAGS_YEAR,
    )


@fuente("year")
async def fuente_year() -> Contenido:
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
        r = await client.get(f"{TASO_API_URL.rstrip('/')}/api/v1/year/state")
        r.raise_for_status()
        return armar_year(r.json())
