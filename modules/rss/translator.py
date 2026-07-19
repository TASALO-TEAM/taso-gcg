"""Traduce entradas de feeds marcados como 'traducir' antes de publicarlas.

Diseño deliberadamente simple: el idioma de un feed no cambia entrada a
entrada, así que no se detecta idioma por entrada (gasto innecesario) — se
traduce todo lo que venga de un feed marcado, punto. Si Groq no responde o
devuelve algo inválido, se publica el entry original sin traducir: esto
nunca debe bloquear el envío de una noticia.
"""

import json

from core.ai_client import ask_groq
from utils.logger import log

SYSTEM_PROMPT = (
    "Eres un traductor profesional de noticias de criptomonedas, del idioma "
    "original al español latino, con tono periodístico y natural. No "
    "traduzcas literalmente los términos que el gremio cripto usa siempre en "
    "inglés (Bitcoin, wallet, staking, DeFi, HODL, ETF, stablecoin, etc.) si "
    "así aparecen en el original. Responde EXCLUSIVAMENTE con un JSON válido "
    'de la forma {"title": "...", "description": "..."}, sin texto, '
    "explicación ni markdown adicional antes o después."
)


# Tope defensivo antes de mandar a traducir: los hilos de Twitter/Nitter son
# la fuente más probable de descripciones desproporcionadamente largas (un
# hilo completo o una cita repetida), que podrían empujar la petición fuera
# del límite de contexto de Groq (o simplemente son más texto del que tiene
# sentido traducir para un post). No afecta el texto que se envía al canal
# (eso lo trunca aparte utils.common.truncate_text sobre el mensaje final).
MAX_CHARS_A_TRADUCIR = 3000


def _cap(texto: str, limite: int = MAX_CHARS_A_TRADUCIR) -> str:
    if not texto or len(texto) <= limite:
        return texto
    return texto[:limite].rstrip() + "..."


async def traducir_entry(entry: dict) -> dict:
    """Devuelve una copia de `entry` con title/description traducidos.

    Si Groq no está configurado, falla, o responde algo no parseable,
    devuelve el `entry` original intacto (fallback silencioso).
    """
    user_prompt = json.dumps(
        {
            "title": _cap(entry.get("title", "")),
            "description": _cap(entry.get("description", "")),
        },
        ensure_ascii=False,
    )

    respuesta = await ask_groq(
        SYSTEM_PROMPT, user_prompt, temperature=0.3, max_tokens=700, json_mode=True
    )
    if not respuesta:
        return entry

    try:
        traducido = json.loads(respuesta)
    except json.JSONDecodeError:
        log("Groq devolvió un JSON inválido al traducir, se publica el original", "warning")
        return entry

    nuevo = dict(entry)
    if traducido.get("title"):
        nuevo["title"] = traducido["title"]
    if traducido.get("description"):
        nuevo["description"] = traducido["description"]
    return nuevo
