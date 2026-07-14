"""Utilidades comunes. clean_html/truncate_text reciclados casi intactos de
BitBreadRSS/utils/common.py — ya cumplían bien su función."""

import re

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


def extract_target_user(update):
    """Determina sobre qué usuario aplica un comando de moderación:
    respondiendo a un mensaje > @mención en argumentos > None.
    Devuelve (user_id, nombre_visible) o (None, None).
    """
    message = update.effective_message
    if message.reply_to_message and message.reply_to_message.from_user:
        u = message.reply_to_message.from_user
        return u.id, u.full_name
    if message.entities:
        for ent in message.entities:
            if ent.type == "text_mention" and ent.user:
                return ent.user.id, ent.user.full_name
    return None, None
