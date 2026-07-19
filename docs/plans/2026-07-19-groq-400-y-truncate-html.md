# Plan: Diagnóstico de 400s de Groq + fix de truncado HTML roto (taso-gcg)

## Contexto

Del log de producción del 2026-07-19 se observan dos problemas distintos
mezclados:

1. **`Groq HTTP error 400`** — ocurren casi siempre inmediatamente antes de
   un envío de fuentes tipo Twitter/Nitter (`@intcyberdigest` la mayoría de
   las veces, una vez `@watcherguru`, una vez CriptoNoticias). `core/ai_client.py`
   ya tiene rotación de keys (ver `_next_key()`), pero un 400 no es un
   problema de rate-limit — es la API rechazando el *contenido* de la
   petición — y hoy solo se loguea el status code y el `str(exception)` de
   httpx (genérico, sin el cuerpo real de la respuesta de Groq). Sin ese
   cuerpo no se puede confirmar la causa exacta (podría ser
   `context_length_exceeded` por descripciones muy largas de hilos de
   Twitter, contenido rechazado, u otra cosa).

2. **`Falló multimedia... Err: Can't parse entities: unclosed start tag`** —
   bug confirmado (no una hipótesis): `truncate_text()` en `utils/common.py`
   corta el texto por conteo de caracteres sin verificar si el corte cae
   DENTRO de una etiqueta HTML (ej. `<a href="https://ejemplo...` sin el `>`
   de cierre), y solo rebalancea `<a>`/`</a>` — no las otras etiquetas
   permitidas (`b`, `strong`, `i`, `em`, `u`, `s`, `code`, `pre`). Esto
   produce HTML roto que Telegram rechaza.

Nota: "algunas fuentes no se traducen" (el síntoma original reportado) no es
un bug de la lógica de traducción — `translator.py` está diseñado a
propósito para publicar el original si Groq falla en esa entrada puntual
(fallback silencioso, documentado en el propio docstring del módulo). Es
consecuencia directa del punto 1: arreglarlo/mitigarlo sube la cobertura de
traducción, no requiere tocar `translator.py`.

## Archivos afectados

- `core/ai_client.py`
- `modules/rss/translator.py`
- `utils/common.py`
- `tests/` (agregar cobertura para `truncate_text` y el logging de error)

## Cambios

### 1. `core/ai_client.py` — loguear el cuerpo de la respuesta en errores no-429

En el `except httpx.HTTPStatusError` de `ask_groq()`, además del status:

```python
try:
    body = e.response.text[:500] if e.response is not None else ""
except Exception:
    body = ""
log(f"Groq HTTP error {status} (key ...{api_key[-4:]}): {body or str(e)}", "warning")
```

Esto no cambia el comportamiento (sigue devolviendo `None` en cualquier
error no-429, el fallback silencioso de `translator.py` sigue intacto) —
solo añade la información que falta para confirmar la causa real la
próxima vez que ocurra.

### 2. `modules/rss/translator.py` — capar el tamaño de la entrada antes de traducir

Defensivo, independiente de si el punto 1 confirma `context_length_exceeded`
como causa: capar `title`/`description` a un tamaño razonable (ej. 3000
caracteres cada uno) antes de armar el `user_prompt`, igual que ya se hace
en el lado de envío (`truncate_text` sobre el texto final). Los hilos de
Twitter/Nitter son la fuente más probable de descripciones inusualmente
largas.

### 3. `utils/common.py` — `truncate_text()` HTML-aware

Reescribir para que:
- Si el punto de corte cae dentro de una etiqueta sin terminar (ej.
  `...<a href="ht`), retroceda hasta justo ANTES de esa etiqueta en vez de
  dejar el fragmento roto.
- Rastree con una pila (LIFO) cuáles de las 8 etiquetas permitidas
  (`b, strong, i, em, u, s, a, code, pre`) quedaron abiertas tras el corte,
  y las cierre todas en orden inverso — no solo `<a>`.

Comportamiento para texto que ya cabe dentro del límite: sin cambios.

### 4. Tests

- `tests/test_common_truncate.py` (nuevo): casos con corte a mitad de
  `<a href="...">` sin cerrar, con `<b>` sin cerrar, con varias etiquetas
  anidadas sin cerrar, y el caso ya cubierto de solo `<a>` (no debe
  romperse).
- `tests/test_ai_client.py` (si no existe, crear): verificar que un 400 loguea
  el cuerpo de la respuesta y sigue devolviendo `None` sin reintentar con
  otra key (mismo criterio que el plan de taso-bot).
- `tests/test_translator.py`: verificar que una descripción larga se capa
  antes de construir el `user_prompt`.

## Fuera de alcance

- No se toca la lógica de fallback de `translator.py` (publicar original si
  Groq falla) — es un diseño deliberado y correcto, documentado en el propio
  módulo.
- No se ajusta el volumen/espaciado de llamadas a Groq (moderation_context +
  RSS comparten el mismo pool de keys) hasta confirmar con el log de cuerpo
  de error si el problema es realmente de tamaño de contenido o de otra
  cosa — prematuro optimizar sin ese dato.
- No se toca el problema de "Bloqueo WAF persistente" en
  criptonoticias.com/feed — es un bloqueo del origen (no relacionado con
  Groq ni con el truncado), ya cubierto por la auto-reparación/rotación de
  `RSSResolver`; si sigue sin resolverse solo, es un problema aparte de
  scraping, no de traducción/envío.
