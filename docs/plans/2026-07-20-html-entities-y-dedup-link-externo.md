# Plan: entidades HTML sin decodificar + dedup por link externo (taso-gcg)

## Contexto

Reportado: en fuentes tipo "social" (X/Twitter vía Nitter), a veces la
misma noticia se manda dos veces: primero como un post con el texto
completo, y minutos/horas después como un segundo post que es solo
"Read the article: [link]" con la tarjeta de vista previa del artículo
(título/descripción/dominio). Además, ese segundo mensaje mostró una
entidad HTML sin decodificar (`company&apos;s` en vez de `company's`).

Son dos bugs distintos, confirmados leyendo el código (no solo por el
síntoma):

### 1. `&apos;` sin decodificar

`RSSParser._clean_html()` en `modules/rss/parser.py` nunca llama a
`html.unescape()`. Si la fuente entrega una entidad doble-escapada (algo
común en algunos espejos Nitter: `&amp;apos;` en el XML crudo),
`feedparser` decodifica un solo nivel (`&amp;apos;` → `&apos;`) y ahí se
queda — nuestro código nunca hace la segunda pasada.

### 2. El mismo artículo se manda dos veces

`RSSMonitor._es_duplicado_por_titulo()` en `modules/rss/monitor.py` es la
ÚNICA capa de dedup además del hash por guid/link (que ya falla porque
son dos tuits con permalink distinto). Compara solo **similitud de
título** con un umbral del 90%. El segundo post ("Read the article:
...") tiene un título completamente distinto al primero (texto completo
del post original) — nunca llega al 90% de parecido, así que no se
detecta como duplicado. Esto es un hueco real de diseño, no un bug de
umbral mal calibrado: subir/bajar el 90% no lo arregla, porque los dos
títulos genuinamente no se parecen.

## Archivos afectados

- `modules/rss/parser.py`
- `modules/rss/monitor.py`
- `core/database.py` (migración de columna nueva)
- `tests/test_rss_social_style.py` (o nuevo `tests/test_parser.py` /
  `tests/test_monitor_dedup.py`, según cómo esté organizada la suite)

## Cambios

### 1. `modules/rss/parser.py` — `_clean_html()` decodifica entidades

```python
import html  # nuevo import

@staticmethod
def _clean_html(raw_html):
    if not raw_html:
        return ""
    text = html.unescape(raw_html)
    text = text.replace("<br>", "\n").replace("<p>", "").replace("</p>", "\n\n")
    text = re.sub(r"<(?!\/?(b|strong|i|em|u|s|a|code|pre)\b)[^>]*>", "", text, flags=re.IGNORECASE)
    return text.strip()
```

El `unescape()` va ANTES del recorte de tags: si una fuente doble-escapó
`&amp;lt;b&amp;gt;` (por accidente) esto lo reconstruye a un tag real que
luego el filtro de whitelist trata igual que a cualquier otro — no cambia
el comportamiento para el caso normal (texto plano con `&apos;`, `&quot;`,
`&amp;`, etc., que es el 99% de los casos).

### 2. `modules/rss/parser.py` — nuevo `_extract_external_link()`

```python
@classmethod
def _extract_external_link(cls, entry) -> str | None:
    """Para fuentes 'social' (X/Twitter vía Nitter): el mismo artículo a
    veces se publica dos veces — un post con el comentario completo, y
    después un post 'tarjeta' que es solo el link desnudo al artículo. El
    título de ambos posts es tan distinto que el fuzzy-match de
    monitor.py no los detecta como duplicados (ver plan). Este método
    saca el primer link <a> que NO apunte al propio dominio del post
    (nitter/x.com/twitter.com) — el link real al artículo externo — para
    que monitor.py compare TAMBIÉN esto, no solo el título.
    """
    own_domain = urlparse(entry.get("link", "")).netloc.lower()
    content = entry.get("summary", "") or entry.get("description", "") or ""
    if "content" in entry:
        for c in entry.content:
            content += c.value
    if not content:
        return None
    try:
        soup = BeautifulSoup(content, "lxml")
        for a in soup.find_all("a", href=True):
            href_domain = urlparse(a["href"]).netloc.lower()
            if not href_domain or href_domain == own_domain:
                continue
            if "nitter" in href_domain or href_domain in ("twitter.com", "x.com"):
                continue
            return cls._normalize_link(a["href"])
    except Exception:
        pass
    return None
```

Y en `parse()`, agregar al dict de cada entrada:
```python
"external_link": cls._extract_external_link(entry),
```

Si no se encuentra ningún link externo (fuentes que no son 'social', o
posts sin link embebido), queda en `None` y el resto del flujo no cambia
— esto es aditivo, no reemplaza el hash ni el fuzzy-match existente.

### 3. `core/database.py` — migración de columna nueva

Agregar `link_externo_normalizado TEXT` a la definición de
`feed_historial` en `SCHEMA_SQL` (para instalaciones nuevas) Y a la lista
`migraciones` de `_migrate()` (para la DB ya existente en el VPS, que se
actualiza sola en el próximo arranque, mismo mecanismo que ya se usó para
`titulo_normalizado`).

### 4. `modules/rss/monitor.py` — segunda señal de duplicado (link externo)

- La consulta de `recientes` pasa a traer también
  `link_externo_normalizado`, y arma un `set` con los que no sean nulos
  (`links_externos_recientes`).
- En el loop de `candidatas`: además de `_es_duplicado_por_titulo`,
  chequear si `entry["external_link"]` (si no es `None`) ya está en
  `links_externos_recientes` — comparación EXACTA (no difusa, ya que es
  una URL normalizada), así que no hay riesgo de falsos positivos entre
  artículos distintos.
- Si cualquiera de las dos señales marca duplicado, se omite el envío
  (mismo comportamiento que hoy: se registra en `feed_historial` sin
  enviar, para no reevaluarlo en cada ciclo) y se loguea cuál de las dos
  causas fue.
- Los dos `INSERT OR IGNORE INTO feed_historial(...)` (el de duplicados
  omitidos y el de envíos exitosos) pasan a incluir
  `link_externo_normalizado` en la tupla.
- La limpieza de historial (quedarse con los últimos 200 por feed) no
  cambia.

## Fuera de alcance

- No se toca el formato/estilo del mensaje cuando un post 'tarjeta' (solo
  link) es la ÚNICA versión de una noticia (sin un post de texto completo
  antes) — en ese caso no hay nada que deduplicar y el mensaje se manda
  tal cual llega de Nitter. Si eso se ve con mal formato de forma
  recurrente, es un problema aparte (necesitaría inspeccionar el XML
  crudo de Nitter para diseñar una limpieza específica, no algo para
  adivinar sin esos datos).
- No se implementa dedup semántico/con IA entre ARTÍCULOS DE FUENTES
  DISTINTAS (ej. CoinDesk y BeInCrypto cubriendo la misma noticia) —
  sigue siendo la 'fase 3' explícitamente fuera de alcance según el
  propio código. Este plan solo cubre el caso concreto reportado: mismo
  feed, mismo artículo, dos formatos de post.
- No se cambia el umbral de `FUZZY_THRESHOLD` (90%) — no es el problema,
  como se explica en el contexto.
