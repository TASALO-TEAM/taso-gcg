"""Cliente Groq compartido para taso-gcg.

Mismo patrón que usa bbchat para hablar con Groq: httpx async + reintentos
con tenacity + degradación controlada (taso-bot NO usa Groq — no hay nada
que replicar de ahí, solo pandas/tradingview-ta para /ta, /graf y /p).
Aquí la función es genérica (`ask_groq`) porque taso-gcg tiene dos
consumidores distintos (traducción de RSS y contexto de moderación) que
comparten toda la lógica de llamada/reintento/errores y solo cambian el
prompt.

Regla de oro: esto NUNCA debe poder tumbar el flujo principal del bot (ni el
de RSS ni el de moderación). Si Groq no está configurado o falla, se devuelve
None y quien llama decide el fallback (publicar el original, omitir el
contexto, etc.) — nunca se propaga una excepción hacia arriba.
"""

import itertools

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from core.config import GROQ_API_KEYS, GROQ_MODEL
from utils.logger import log

GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
DEFAULT_TIMEOUT = 15
MAX_RETRIES = 3

# Rotación round-robin de keys (mismo patrón que CoinGeckoClient en taso-bot).
# Con 0 o 1 key, _next_key() se comporta como antes (None fijo, o siempre la
# misma key).
_key_cycle = itertools.cycle(GROQ_API_KEYS) if GROQ_API_KEYS else None


def _next_key() -> str | None:
    """Devuelve la siguiente API key en la rotación, o None si no hay ninguna
    configurada. Síncrono y sin `await`, así que es seguro con corrutinas
    concurrentes usando el mismo ciclo."""
    return next(_key_cycle) if _key_cycle else None


@retry(
    reraise=True,
    stop=stop_after_attempt(MAX_RETRIES),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_exception_type((httpx.TimeoutException, httpx.NetworkError)),
)
async def _call_groq_async(payload: dict, api_key: str, timeout: int = DEFAULT_TIMEOUT) -> dict:
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.post(GROQ_API_URL, headers=headers, json=payload)
        response.raise_for_status()
        return response.json()


async def ask_groq(
    system_prompt: str,
    user_prompt: str,
    *,
    temperature: float = 0.4,
    max_tokens: int = 512,
    json_mode: bool = False,
) -> str | None:
    """Llamada genérica a Groq (modelo GROQ_MODEL, por defecto openai/gpt-oss-120b).

    Devuelve el texto de la respuesta, o None si Groq no está configurado o
    falló tras los reintentos (agotando todas las keys disponibles). Quien
    llama SIEMPRE debe manejar el caso None con un fallback razonable —
    nunca asumir que hay respuesta.
    """
    if not GROQ_API_KEYS:
        return None

    payload = {
        "model": GROQ_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if json_mode:
        payload["response_format"] = {"type": "json_object"}

    # Rotación: si una key da 429 (rate limit), se prueba la siguiente antes
    # de rendirse. Cualquier otro error (red, timeout, HTTP no-429, JSON
    # vacío) devuelve None de inmediato — rotar de key no arregla un 400,
    # 401 o 500.
    attempts = max(len(GROQ_API_KEYS), 1)
    data = None
    for attempt in range(attempts):
        api_key = _next_key()
        try:
            data = await _call_groq_async(payload, api_key)
            break
        except httpx.HTTPStatusError as e:
            status = e.response.status_code if e.response else None
            if status == 429 and attempt < attempts - 1:
                log(
                    f"Groq 429 (rate limit) con key ...{api_key[-4:]}, "
                    f"probando siguiente key (intento {attempt + 2}/{attempts})",
                    "warning",
                )
                continue
            log(f"Groq HTTP error {status}: {e}", "warning")
            return None
        except httpx.TimeoutException:
            log("Groq: tiempo de espera agotado", "warning")
            return None
        except httpx.NetworkError as e:
            log(f"Groq: error de red: {e}", "warning")
            return None
        except Exception as e:
            log(f"Groq: error inesperado: {e}", "error")
            return None

    if data is None:
        return None

    choices = data.get("choices", [])
    if not choices:
        log("Groq devolvió 'choices' vacío", "warning")
        return None

    content = choices[0].get("message", {}).get("content", "").strip()
    return content or None
