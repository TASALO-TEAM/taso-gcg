"""Fuentes de contenido de la publicación automática.

`year`: estado del año (progreso, días que faltan y frase del día) desde taso-api
`GET /api/v1/year/state` (público, sin clave). Mismo formato que el comando /y de taso-bot,
en texto plano para que sirva igual en Telegram, Nostr y los microblogs de Hive.

`tspl`: reenvía el digest de TSPL que taso-bot ya generó y empujó a taso-api
(`GET /api/v1/tspl/digest/latest`, con clave). No arma nada: es exactamente el mensaje que
reciben los usuarios de taso-bot, así que no se duplica el trabajo (ni Groq ni noticias).
"""

from datetime import datetime, timedelta, timezone

import re
import httpx

from core.config import TASALO_ADMIN_KEY, TASO_API_URL
from modules.publisher.base import Contenido, fuente

HTTP_TIMEOUT = 10
FRASE_RESPALDO = "⏳ El tiempo vuela, pero tú eres el piloto."
TAGS_YEAR = ("tasalo", "estadodelano")
TAGS_TSPL = ("tasalo", "tspl")
# taso-bot lo arma a las 11:00 UTC y se publica hacia las 13:30 UTC; pasado este margen es de ayer.
EDAD_MAX_TSPL_H = 18


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


TITULO_TSPL = "TASALO Spotlight: Resumen del día"     # respaldo si el blog no trae su propio encabezado
_H1 = re.compile(r"^# +(.+?)[ \t]*$", re.M)


def _separar_titulo(md: str | None) -> tuple[str, str | None]:
    """El `# encabezado` del blog de taso-bot es el título del post: sube al título y sale del cuerpo
    (en Hive el título va aparte; dejarlo en el cuerpo lo repetiría debajo de la imagen)."""
    m = _H1.search(md or "")
    if not m:
        return TITULO_TSPL, md
    titulo = m.group(1).replace(" - ", " \u2014 ", 1)
    antes, despues = md[: m.start()].rstrip("\n"), md[m.end():].lstrip("\n")
    return titulo, f"{antes}\n\n{despues}" if antes else despues


def armar_tspl(data: dict, ahora: datetime | None = None) -> Contenido:
    """Convierte la respuesta del digest en Contenido, tal cual la armó taso-bot.
    ValueError si falta el texto, la fecha es inválida o el digest es de otro día."""
    texto = (data.get("telegram_text") or "").strip()
    if not texto:
        raise ValueError("el digest de TSPL no trae texto")
    try:
        generado = datetime.fromisoformat(str(data["generated_at"]).replace("Z", "+00:00"))
    except (KeyError, ValueError):
        raise ValueError("el digest de TSPL no trae una fecha válida")
    if generado.tzinfo is None:
        raise ValueError("el digest de TSPL trae una fecha sin zona horaria")
    ahora = ahora or datetime.now(timezone.utc)
    if ahora - generado > timedelta(hours=EDAD_MAX_TSPL_H):
        raise ValueError(f"el digest de TSPL es viejo (generado {generado:%Y-%m-%d %H:%M} UTC)")
    titulo, blog = _separar_titulo(data.get("blog_markdown"))
    return Contenido(
        titulo=titulo,
        cuerpo_md=(blog or texto),
        texto_corto=texto,
        tags=TAGS_TSPL,
        extra={"parse_mode": "Markdown"},   # el texto de /tspl es Markdown v1
    )


@fuente("tspl")
async def fuente_tspl() -> Contenido:
    if not TASALO_ADMIN_KEY:
        raise RuntimeError("falta TASALO_ADMIN_KEY en .env para leer el digest de taso-api")
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
        r = await client.get(f"{TASO_API_URL.rstrip('/')}/api/v1/tspl/digest/latest",
                             headers={"X-API-Key": TASALO_ADMIN_KEY})
        if r.status_code == 404:
            raise LookupError("taso-bot todavía no ha empujado el digest de TSPL")
        r.raise_for_status()
        return armar_tspl(r.json())
