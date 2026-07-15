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

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from core.config import GROQ_API_KEY, GROQ_MODEL
from utils.logger import log

GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
DEFAULT_TIMEOUT = 15
MAX_RETRIES = 3


@retry(
    reraise=True,
    stop=stop_after_attempt(MAX_RETRIES),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_exception_type((httpx.TimeoutException, httpx.NetworkError, httpx.HTTPStatusError)),
)
async def _call_groq_async(payload: dict, timeout: int = DEFAULT_TIMEOUT) -> dict:
    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
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
    falló tras los reintentos. Quien llama SIEMPRE debe manejar el caso None
    con un fallback razonable — nunca asumir que hay respuesta.
    """
    if not GROQ_API_KEY:
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

    try:
        data = await _call_groq_async(payload)
    except httpx.HTTPStatusError as e:
        status = e.response.status_code if e.response else "??"
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

    choices = data.get("choices", [])
    if not choices:
        log("Groq devolvió 'choices' vacío", "warning")
        return None

    content = choices[0].get("message", {}).get("content", "").strip()
    return content or None
