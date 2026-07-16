"""Utilidades comunes. clean_html/truncate_text reciclados casi intactos de
BitBreadRSS/utils/common.py — ya cumplían bien su función."""

import datetime as dt
import re

from telegram.constants import MessageEntityType

from core.database import db

DURATION_RE = re.compile(r"^(\d+)([smhd])$")
UNIT_SECONDS = {"s": 1, "m": 60, "h": 3600, "d": 86400}


def clean_html(raw_html: str) -> str:
    """Limpia etiquetas HTML complejas dejando solo las básicas soportadas por Telegram."""
    if not raw_html:
        return ""
    text = raw_html.replace("<br>", "\n").replace("<br/>", "\n").replace("<p>", "").replace("</p>", "\n\n")
    text = re.sub(r"<(script|style).*?>.*?</\1>", "", text, flags=re.DOTALL)
    text = re.sub(r"<(?!\/?(b|strong|i|em|u|s|a|code|pre)\b)[^>]*>", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def truncate_text(text: str, limit: int = 1000) -> str:
    """Corta el texto asegurando no romper etiquetas HTML abiertas al final."""
    if len(text) <= limit:
        return text
    cut_text = text[:limit - 3] + "..."
    if cut_text.count("<a") != cut_text.count("</a>"):
        cut_text += "</a>"
    return cut_text


def parse_duration(texto: str) -> int | None:
    """Convierte '30m', '2h', '1d', '45s' a segundos. None si el formato es inválido."""
    if not texto:
        return None
    match = DURATION_RE.match(texto.strip().lower())
    if not match:
        return None
    cantidad, unidad = match.groups()
    return int(cantidad) * UNIT_SECONDS[unidad]


def humanize_seconds(segundos: int) -> str:
    """30 -> '30s', 3600 -> '1h', etc. Solo la unidad más grande relevante."""
    for unidad, factor in (("d", 86400), ("h", 3600), ("m", 60)):
        if segundos >= factor and segundos % factor == 0:
            return f"{segundos // factor}{unidad}"
    return f"{segundos}s"


def formatted_text_after_command(update, skip_tokens: int = 0) -> str:
    """Como raw_text_after_command, pero además reconoce negritas, cursivas,
    subrayado, tachado, spoiler, código y links que el usuario haya aplicado
    con el formato nativo de Telegram (toolbar del cliente), y los devuelve ya
    convertidos a las mismas etiquetas HTML que usamos al reenviar con
    parse_mode="HTML" — así el admin no tiene que escribir HTML a mano ni
    perder el formato al guardar el texto.

    El resultado ya viene HTML-safe (texto literal escapado, solo las
    entidades reales quedan como tags): no volver a pasarlo por html.escape().
    """
    message = update.effective_message
    texto_html = message.text_html or message.caption_html or ""
    if not texto_html:
        return ""
    resto = texto_html
    for _ in range(skip_tokens + 1):
        partes = resto.split(maxsplit=1)
        resto = partes[1] if len(partes) > 1 else ""
    return resto


def formatted_text_of_message(message) -> str:
    """HTML (con negritas/cursivas/etc. ya convertidas) del texto o caption de
    un mensaje puntual — para cuando se guarda el contenido de un mensaje al
    que se está respondiendo (ej. /save)."""
    if not message:
        return ""
    return message.text_html or message.caption_html or ""


def raw_text_after_command(update, skip_tokens: int = 0) -> str:
    """Devuelve el texto tal cual lo escribió el usuario después del comando
    (y, opcionalmente, de los primeros `skip_tokens` argumentos), preservando
    saltos de línea y espacios múltiples.

    A diferencia de " ".join(context.args), que reconstruye el texto separando
    cada palabra con un solo espacio y destruye cualquier formato (saltos de
    línea, sangría, espacios dobles), esto solo recorta los tokens iniciales
    que ya se consumieron (comando, nombre, disparador, etc.) y deja el resto
    intacto — igual que hace el reply_to_message en /save.
    """
    message = update.effective_message
    texto = message.text or message.caption or ""
    if texto.startswith("/"):
        partes = texto.split(maxsplit=1)
        texto = partes[1] if len(partes) > 1 else ""
    for _ in range(skip_tokens):
        partes = texto.split(maxsplit=1)
        texto = partes[1] if len(partes) > 1 else ""
    return texto


async def extract_target_user(update, context):
    """Determina sobre qué usuario aplica un comando de moderación, en orden:
    1. Respondiendo a un mensaje (el más confiable: el user_id viene directo).
    2. `text_mention` — mención por nombre visible sin @username propio;
       Telegram ya manda el user_id embebido en la entidad, no hay que resolver nada.
    3. `mention` — @username en texto plano. Aquí Telegram NO manda el user_id,
       solo el texto "@fulano", así que hay que resolverlo aparte (ver
       `resolve_username`). Esto es lo que antes faltaba por completo: un
       "/ban @persona" nunca funcionaba porque solo se miraba `text_mention`.

    Devuelve (user_id, nombre_visible) o (None, None) si no se pudo resolver.
    """
    message = update.effective_message
    if message.reply_to_message and message.reply_to_message.from_user:
        u = message.reply_to_message.from_user
        return u.id, u.full_name

    if not message.entities:
        return None, None

    texto = message.text or message.caption or ""
    for ent in message.entities:
        if ent.type == MessageEntityType.TEXT_MENTION and ent.user:
            return ent.user.id, ent.user.full_name
        if ent.type == MessageEntityType.MENTION:
            username = texto[ent.offset:ent.offset + ent.length].lstrip("@")
            resultado = await resolve_username(context, username)
            if resultado:
                return resultado
    return None, None


async def resolve_username(context, username: str):
    """Resuelve un @username a (user_id, nombre_visible).

    Primero contra la caché local (tabla `users`, alimentada por chat_tracker
    con cada mensaje que el bot ve pasar) — funciona siempre que la persona
    haya escrito al menos un mensaje en algún chat donde esté el bot. Si no
    está en caché, se intenta `get_chat("@username")` como último recurso:
    rara vez funciona para usuarios normales (restricción de la propia API,
    no del bot), pero no cuesta nada probarlo antes de rendirse.
    """
    username = username.lstrip("@")
    fila = await db.find_user_by_username(username)
    if fila:
        nombre = fila["first_name"] or f"@{username}"
        if fila["last_name"]:
            nombre = f"{nombre} {fila['last_name']}"
        return fila["user_id"], nombre
    try:
        chat = await context.bot.get_chat(f"@{username}")
    except Exception:
        return None
    if chat.type == "private":
        return chat.id, chat.first_name or f"@{username}"
    return None


# --- Estimación de fecha de creación de cuenta a partir del user_id ---
#
# Telegram no expone esto por API. La técnica (la misma que usan bots
# públicos como "Creation Date" o "GetIDs Bot") es interpolar entre puntos
# de referencia conocidos: el user_id crece con el tiempo, pero NO de forma
# perfectamente uniforme (Telegram reparte IDs por "shards" entre varios
# servidores de registro), así que esto es siempre un estimado aproximado,
# nunca un dato exacto — de ahí el "(?)" en el resultado. Los puntos de
# referencia de abajo son órdenes de magnitud públicamente conocidos
# (crecimiento de usuarios de Telegram a lo largo de los años); si Ersus
# junta datos propios más precisos, esta tabla se puede ajustar sin tocar
# el resto de la función.
_CHECKPOINTS_CREACION = [
    (1, "2013-08-14"),
    (10_000_000, "2014-03-01"),
    (50_000_000, "2015-06-01"),
    (100_000_000, "2016-06-01"),
    (200_000_000, "2018-03-01"),
    (400_000_000, "2019-09-01"),
    (700_000_000, "2020-08-01"),
    (1_000_000_000, "2021-02-01"),
    (1_500_000_000, "2021-10-01"),
    (2_000_000_000, "2022-08-01"),
    (3_500_000_000, "2023-03-01"),
    (5_000_000_000, "2023-10-01"),
    (6_500_000_000, "2024-09-01"),
    (7_500_000_000, "2025-06-01"),
    (8_300_000_000, "2026-07-01"),
]
_PUNTOS_CREACION = [(uid, dt.date.fromisoformat(f)) for uid, f in _CHECKPOINTS_CREACION]


def _interpolar_fecha(user_id, id_a, fecha_a, id_b, fecha_b) -> dt.date:
    if id_b == id_a:
        return fecha_a
    proporcion = (user_id - id_a) / (id_b - id_a)
    dias_totales = (fecha_b - fecha_a).days
    return fecha_a + dt.timedelta(days=round(dias_totales * proporcion))


def estimate_account_creation(user_id: int) -> str:
    """Devuelve algo como '~ 3/2020 (?)'. Ver nota de _CHECKPOINTS_CREACION:
    esto es SIEMPRE un estimado, nunca un dato oficial de Telegram."""
    puntos = _PUNTOS_CREACION
    if user_id <= puntos[0][0]:
        fecha = puntos[0][1]
    elif user_id >= puntos[-1][0]:
        id_a, fecha_a = puntos[-2]
        id_b, fecha_b = puntos[-1]
        fecha = _interpolar_fecha(user_id, id_a, fecha_a, id_b, fecha_b)
    else:
        fecha = puntos[-1][1]  # por si el loop no encuentra tramo (no debería pasar)
        for (id_a, fecha_a), (id_b, fecha_b) in zip(puntos, puntos[1:]):
            if id_a <= user_id <= id_b:
                fecha = _interpolar_fecha(user_id, id_a, fecha_a, id_b, fecha_b)
                break
    return f"~ {fecha.month}/{fecha.year} (?)"
