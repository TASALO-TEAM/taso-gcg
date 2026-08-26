"""BlueskyClient — integra cuentas de Bluesky (AT Protocol) como fuente de
feed, con la misma interfaz que RSSResolver.find_best_feed() y RSSParser.parse()
usan para X/Twitter, para que monitor.py, handlers.py y el resto del pipeline
(dedup, estilos, traducción, Instant View) no necesiten saber que existe.

Diferencia clave con X: Bluesky expone una API pública oficial y SIN
autenticación para lectura (perfiles y posts) directamente contra el AppView
de Bluesky, https://public.api.bsky.app — no hace falta espejo tipo Nitter,
rotación de instancias ni bypass de WAF con curl_cffi (ver
https://docs.bsky.app/docs/advanced-guides/api-directory, sección "Public
Bluesky app requests"). Por eso este módulo usa httpx directo (ya en
requirements.txt para core/ai_client.py) en vez de RSSParser.fetch_content().

Entrada soportada en /addfeed: enlaces de perfil
https://bsky.app/profile/<handle-o-did>[/lo-que-sea]. El feed se guarda en la
tabla `feeds` con esa misma URL de perfil como valor de `url` (no una URL de
API) — igual que un feed de X se guarda con la URL del espejo Nitter. Es este
módulo el que la reconoce en tiempo de fetch por el host/path, mismo patrón
que RSSParser usa para reconocer Nitter/X por substring, sin columna aparte
en la tabla feeds.
"""

import hashlib
from urllib.parse import urlparse

import httpx

from utils.logger import log

API_BASE = "https://public.api.bsky.app/xrpc"

# 'posts_no_replies' para que el feed se comporte como se esperaría de un
# RSS de cuenta (solo publicaciones propias, sin hilos de respuesta a
# terceros). Los reposts se filtran aparte en parse() (vienen marcados con
# 'reason' en el item del feed) porque son contenido ajeno, no de la cuenta
# seguida — igual criterio que un RSS normal, que tampoco reenvía retweets.
DEFAULT_FILTER = "posts_no_replies"
FETCH_LIMIT = 20
HTTP_TIMEOUT = 15


class BlueskyClient:

    @staticmethod
    def is_bluesky_url(url: str) -> bool:
        """True si `url` es un link de perfil de Bluesky (bsky.app/profile/...).
        Acepta URLs sin esquema (se asume https) porque handlers.py a veces
        llama esto con el texto crudo que escribió el admin, antes de que
        RSSResolver normalice el esquema."""
        if not url:
            return False
        try:
            parsed = urlparse(url if "://" in url else f"https://{url}")
        except Exception:
            return False
        host = parsed.netloc.lower()
        return host in ("bsky.app", "www.bsky.app") and parsed.path.startswith("/profile/")

    @staticmethod
    def _extract_actor(url: str) -> str | None:
        """Extrae el handle o DID del path /profile/<actor>[/...]. Si pegan el
        link a un post puntual (.../profile/<actor>/post/<rkey>) igual se
        queda solo con la cuenta — mismo criterio que _get_twitter_username
        en parser.py, que extrae el @usuario sin importar qué tan específico
        sea el link original."""
        try:
            parsed = urlparse(url if "://" in url else f"https://{url}")
            partes = [p for p in parsed.path.split("/") if p]
            if len(partes) >= 2 and partes[0] == "profile":
                return partes[1]
        except Exception:
            pass
        return None

    @classmethod
    async def resolve(cls, url: str):
        """Equivalente a RSSResolver.find_best_feed() pero para Bluesky: no
        hace falta descubrir nada (a diferencia de un RSS genérico, la URL de
        perfil YA es la fuente), solo confirmar que la cuenta existe y
        normalizar a su handle real (por si pegaron un DID). Retorna
        (url_canonica, titulo, error) — mismo contrato que find_best_feed."""
        actor = cls._extract_actor(url)
        if not actor:
            return None, None, "No reconocí el handle/DID en el link de Bluesky (¿es un link de perfil?)."

        profile, error = await cls._get_profile(actor)
        if error:
            return None, None, error

        handle = profile.get("handle", actor)
        display = profile.get("displayName") or handle
        canonical = f"https://bsky.app/profile/{handle}"
        return canonical, f"Bluesky: {display} (@{handle})", None

    @classmethod
    async def _get_profile(cls, actor: str):
        try:
            async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
                resp = await client.get(f"{API_BASE}/app.bsky.actor.getProfile", params={"actor": actor})
            if resp.status_code == 400:
                return None, f"No existe ninguna cuenta de Bluesky «{actor}» (revisa el handle)."
            resp.raise_for_status()
            return resp.json(), None
        except httpx.HTTPStatusError as e:
            return None, f"Bluesky respondió con error HTTP {e.response.status_code}."
        except httpx.TimeoutException:
            return None, "Tiempo de espera agotado consultando la API de Bluesky."
        except Exception as e:
            return None, f"Error consultando el perfil de Bluesky: {e}"

    @classmethod
    async def parse(cls, url: str):
        """Interfaz compatible con RSSParser.parse(): retorna
        ({"title": ..., "entries": [...]}, None) o (None, error_msg). Cada
        entrada trae las mismas llaves que arma RSSParser (title, link,
        description, image, video, external_link, hash, source) para que
        monitor.py no necesite ninguna rama especial."""
        actor = cls._extract_actor(url)
        if not actor:
            return None, "URL de Bluesky inválida (esperaba .../profile/<handle>)."

        try:
            async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
                resp = await client.get(
                    f"{API_BASE}/app.bsky.feed.getAuthorFeed",
                    params={"actor": actor, "filter": DEFAULT_FILTER, "limit": FETCH_LIMIT},
                )
            if resp.status_code == 400:
                return None, f"Cuenta de Bluesky «{actor}» no encontrada."
            resp.raise_for_status()
            data = resp.json()
        except httpx.TimeoutException:
            return None, "Timeout consultando la API de Bluesky."
        except httpx.HTTPStatusError as e:
            return None, f"HTTP {e.response.status_code} consultando Bluesky."
        except Exception as e:
            log(f"Error consultando Bluesky ({actor}): {e}", "warning")
            return None, f"Error de conexión con Bluesky: {e}"

        entries = []
        for item in data.get("feed", []):
            if "reason" in item:
                continue  # repost ajeno, no es contenido propio de la cuenta
            entry = cls._post_to_entry(item.get("post", {}))
            if entry:
                entries.append(entry)

        return {"title": f"Bluesky: @{actor}", "entries": entries}, None

    @classmethod
    def _post_to_entry(cls, post: dict) -> dict | None:
        try:
            uri = post.get("uri", "")
            handle = post.get("author", {}).get("handle", "?")
            texto = (post.get("record", {}).get("text") or "").strip() or "(post sin texto)"

            rkey = uri.rsplit("/", 1)[-1] if uri else ""
            link = f"https://bsky.app/profile/{handle}/post/{rkey}" if rkey else f"https://bsky.app/profile/{handle}"

            image, external_link = cls._extract_media(post.get("embed"))
            identidad = uri or f"{handle}|{texto}"

            return {
                "title": texto,
                "link": link,
                "description": texto,
                "image": image,
                # Bluesky sirve el video como HLS (m3u8 + segmentos), no como
                # mp4 directo — bot.send_video necesita una URL de archivo
                # reproducible de una, así que no se manda (se usa su
                # miniatura como imagen, ver _extract_media). Posible mejora
                # futura: transcodificar server-side si hace falta.
                "video": None,
                "external_link": external_link,
                "hash": hashlib.md5(identidad.encode()).hexdigest(),
                "source": f"Bluesky / @{handle}",
            }
        except Exception as e:
            log(f"Error normalizando post de Bluesky: {e}", "warning")
            return None

    @staticmethod
    def _extract_media(embed: dict | None):
        """Retorna (image_url, external_link) según el tipo de embed del
        post. Cubre los casos más comunes: imágenes propias, tarjeta de link
        externo (se usa como external_link para el dedup cruzado de
        monitor.py, igual que RSSParser._extract_external_link) y video
        (se usa su miniatura como imagen de reemplazo, ver nota en
        _post_to_entry)."""
        if not embed:
            return None, None
        tipo = embed.get("$type", "")

        if tipo == "app.bsky.embed.images#view":
            imagenes = embed.get("images") or []
            if imagenes:
                return imagenes[0].get("fullsize"), None
            return None, None

        if tipo == "app.bsky.embed.external#view":
            externo = embed.get("external") or {}
            return externo.get("thumb"), externo.get("uri")

        if tipo == "app.bsky.embed.video#view":
            return embed.get("thumbnail"), None

        if tipo == "app.bsky.embed.recordWithMedia#view":
            return BlueskyClient._extract_media(embed.get("media"))

        return None, None
