# Rotación de API keys de Groq — traducción de RSS y contexto de moderación

## Diagnóstico

`GROQ_API_KEY` en `.env` acepta hoy una sola key. Cuando esa cuenta pega el
límite de rate (429) durante una racha de traducciones de RSS, `ask_groq()`
recibe el 429 como `HTTPStatusError`, lo captura y devuelve `None` — el
comportamiento correcto (nunca bloquear el envío), pero deja esa entrada sin
traducir aunque quedara margen en otra cuenta Groq disponible.

Patrón de referencia ya usado en `taso-bot` (`CoinGeckoClient`): varias API
keys separadas por coma, rotación round-robin con `itertools.cycle`, y en un
429 se reintenta con la siguiente key antes de rendirse.

## Diseño

Mismo comportamiento externo de `ask_groq()` y `traducir_entry()`: si todas
las keys fallan o no hay ninguna configurada, se devuelve `None`/el entry
original sin traducir, exactamente como ahora. Lo único que cambia es que,
de fondo, un 429 en la key actual pasa a la siguiente en vez de rendirse
directamente.

### `core/config.py`
- Nuevo parser `_parse_key_list(env_value)` (mismo estilo que
  `_parse_id_list`, pero preservando el string tal cual, solo separando por
  comas y quitando espacios) → devuelve `list[str]`.
- `GROQ_API_KEYS: list[str] = _parse_key_list(os.getenv("GROQ_API_KEY"))`.
- Se mantiene `GROQ_API_KEY` tal cual (primera key o cadena vacía) por si
  algo más lo importa, para no romper nada existente.

### `core/ai_client.py`
- `itertools.cycle` a nivel de módulo sobre `GROQ_API_KEYS` (si la lista
  está vacía, no se crea ciclo — mismo caso "Groq no configurado" de hoy).
- `_call_groq_async` pasa a recibir la `api_key` como parámetro explícito
  (hoy la toma directo de `GROQ_API_KEY` importado) y arma el header
  `Authorization` con esa key.
- Se saca `httpx.HTTPStatusError` del `retry_if_exception_type` de tenacity
  (ese decorador reintenta con la MISMA key — no tiene sentido para rotar).
  Tenacity se queda solo para `TimeoutException`/`NetworkError` (fallos de
  red transitorios, misma key, igual que ahora).
- `ask_groq()` envuelve la llamada en un loop manual de hasta
  `len(GROQ_API_KEYS)` intentos (mínimo 1): cada intento toma la siguiente
  key del ciclo; si el resultado es un 429, se loguea con los últimos 4
  caracteres de la key y se prueba la siguiente; cualquier otro error
  (network, timeout, HTTP no-429, JSON vacío) devuelve `None` de inmediato
  igual que hoy — no tiene sentido rotar keys por un 400/401/500, esos no
  se arreglan cambiando de cuenta.
- Con 1 sola key (o ninguna) el comportamiento es idéntico al actual.

### `.env` / `.env.example`
- Documentar que `GROQ_API_KEY` acepta varias keys separadas por coma,
  igual que ya está documentado `coingecko_api_key` en taso-bot.

## Sin cambios

- `modules/rss/translator.py` no se toca — sigue llamando a `ask_groq()`
  igual que ahora, la rotación es transparente para quien la usa.
- El consumidor de contexto de moderación (el otro caller de `ask_groq()`)
  tampoco cambia.
- No se toca la lógica de fallback "se publica sin traducir" — sigue siendo
  el mismo camino cuando se agotan todas las keys.

## Validación

- `py -3 -m py_compile core/ai_client.py core/config.py` en Windows.
- Prueba manual: con 2 keys en `.env`, forzar un 429 en la primera (o
  simularlo) y confirmar en logs que rota a la segunda y la traducción
  sale bien; con 0 keys, confirmar que sigue publicando sin traducir como
  hoy.

## Fuera de alcance

- No se añaden proveedores de IA distintos a Groq (eso sería otro cambio
  más grande, no una rotación de keys).
- No se toca `traducir_entry()` ni el prompt de traducción.
