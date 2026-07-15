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


async def traducir_entry(entry: dict) -> dict:
    """Devuelve una copia de `entry` con title/description traducidos.

    Si Groq no está configurado, falla, o responde algo no parseable,
    devuelve el `entry` original intacto (fallback silencioso).
    """
    user_prompt = json.dumps(
        {"title": entry.get("title", ""), "description": entry.get("description", "")},
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
