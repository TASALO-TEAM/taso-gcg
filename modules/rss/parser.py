"""RSSParser — portado casi intacto de BitBreadRSS/services/parser.py.

Se quitó el método find_best_feed() de esta clase (en el original quedó a medio
escribir y sin uso real — el descubrimiento de feeds lo hace por completo
RSSResolver.find_best_feed en resolver.py, que sí está completo).
"""

import feedparser
import re
import asyncio
import hashlib
import random
from urllib.parse import urlparse, parse_qsl, urlencode
from curl_cffi.requests import AsyncSession
from bs4 import BeautifulSoup

from utils.logger import log


class RSSParser:
    # --- Deduplicación robusta (ver ESTADO_DESARROLLO.md / análisis del bug de
    # reenvíos): el hash original era md5(link_crudo + titulo_crudo), lo cual
    # se rompe apenas la fuente le pega un parámetro de tracking al link o
    # edita un espacio del título. Estas listas y umbrales son los únicos
    # puntos que hay que tocar si en el futuro aparece una fuente con un
    # patrón de tracking nuevo que no cubran los prefijos de abajo.
    TRACKING_PARAM_PATTERNS = (
        "utm_", "fbclid", "gclid", "msclkid", "ref_src", "_ga", "_gl",
        "spm", "cmpid", "campaign", "mc_cid", "mc_eid", "igshid", "vero_",
        "session", "sid", "token", "cache", "_t", "timestamp", "rand", "nocache",
    )
    _EMOJI_PATTERN = re.compile(
        "[\U0001F300-\U0001FAFF\U00002600-\U000027BF\U0001F1E6-\U0001F1FF\u2B00-\u2BFF]+",
        flags=re.UNICODE,
    )

    PROFILES = ["chrome120", "safari17_0", "safari15_5", "chrome110"]
    HEADERS = {
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9,es;q=0.8",
        "Accept-Encoding": "gzip, deflate, br",
        "Referer": "https://www.google.com/",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "cross-site",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    }

    NITTER_INSTANCES = [
        "https://nitter.privacyredirect.com",
        "https://nitter.net",
        "https://xcancel.com",
        "https://nitter.poast.org",
        "https://nitter.privacydev.net",
        "https://nitter.soopy.moe",
        "https://nitter.lucabased.xyz",
        "https://lightbrd.com",
        "https://nitter.space",
        "https://nitter.tiekoetter.com",
        "https://nuku.trabun.org",
        "https://nitter.catsarch.com",
        "https://nitter.kavin.rocks",
        "https://nitter.koyu.space",
        "https://nitter.nixnet.services",
        "https://nitter.kavin.app",
        "https://twiiit.com/",
    ]

    @staticmethod
    def is_valid_xml(content):
        """Verifica si el contenido es XML válido y NO una página de bloqueo."""
        if not content:
            return False
        try:
            text = content.decode("utf-8", errors="ignore") if isinstance(content, bytes) else content
            block_keywords = [
                "<!DOCTYPE html>", "<html", "Cloudflare", "Rate limit",
                "Just a moment", "Access denied", "403 Forbidden",
            ]
            is_html = text.strip().startswith(("<!DOCTYPE html>", "<html"))
            has_rss_tags = ("<rss" in text or "<feed" in text or "<?xml" in text)
            if is_html and not has_rss_tags:
                return False
            if any(k in text for k in ["Rate limit exceeded", "Instance has been rate limited"]):
                return False
            return has_rss_tags
        except Exception:
            return False

    @classmethod
    def _get_twitter_username(cls, url):
        match = re.search(r"(?:twitter\.com|x\.com|nitter\.[a-z\.]+)/([a-zA-Z0-9_]+)", url)
        if not match and "nitter" in url:
            parts = url.rstrip("/").split("/")
            if len(parts) > 0:
                return parts[-1]
        return match.group(1) if match else None

    # --- Fuentes tipo "post" (X/Twitter vía espejo Nitter): en estas el título
    # que trae el feed casi siempre ES el cuerpo del tuit (a veces truncado),
    # igual que la descripción — de ahí el texto duplicado al usar la plantilla
    # normal (título + descripción). Este método reutiliza la misma detección
    # de _get_twitter_username para sugerir/activar el estilo "social" (ver
    # monitor.py) en vez de repetir el texto dos veces.
    _NITTER_MIRROR_HOSTS = (
        "xcancel.com", "twiiit.com", "lightbrd.com", "nuku.trabun.org",
    )

    @classmethod
    def is_social_source(cls, url: str) -> bool:
        """True si la URL es de X/Twitter directo o de un espejo Nitter
        (instancia con 'nitter' en el host, o uno de los alias conocidos sin
        ese nombre). Se usa en /addfeed para sugerir el estilo 'social'."""
        if not url:
            return False
        host = urlparse(url).netloc.lower()
        if not host:
            return False
        if "twitter.com" in host or "x.com" in host or "nitter" in host:
            return True
        return any(alias in host for alias in cls._NITTER_MIRROR_HOSTS)

    @staticmethod
    def _clean_html(raw_html):
        if not raw_html:
            return ""
        text = raw_html.replace("<br>", "\n").replace("<p>", "").replace("</p>", "\n\n")
        text = re.sub(r"<(?!\/?(b|strong|i|em|u|s|a|code|pre)\b)[^>]*>", "", text, flags=re.IGNORECASE)
        return text.strip()

    @staticmethod
    def _extract_image(entry):
        """Reconstruye URLs relativas de Nitter y otros sitios."""
        if "media_content" in entry:
            for m in entry.media_content:
                if "image" in m.get("type", "") or m.get("medium") == "image":
                    return m["url"]
        if "links" in entry:
            for l in entry.links:
                if l.get("rel") == "enclosure" and "image" in l.get("type", ""):
                    return l["href"]

        content = entry.get("summary", "") or entry.get("description", "") or ""
        if "content" in entry:
            for c in entry.content:
                content += c.value

        base_url = ""
        if entry.get("link"):
            parsed = urlparse(entry["link"])
            base_url = f"{parsed.scheme}://{parsed.netloc}"

        if content:
            try:
                soup = BeautifulSoup(content, "lxml")
                for img in soup.find_all("img"):
                    src = img.get("src")
                    if not src:
                        continue
                    if src.startswith("/"):
                        src = base_url + src
                    if any(x in src.lower() for x in ("emoji", "pixel", "tracking", "avatar", "icon")):
                        continue
                    if "pbs.twimg" in src or "/pic/" in src or "media" in src:
                        return src
                    if src.startswith("http"):
                        return src
            except Exception:
                pass
        return None

    @staticmethod
    def _extract_video(entry):
        base_url = ""
        if entry.get("link"):
            parsed = urlparse(entry["link"])
            base_url = f"{parsed.scheme}://{parsed.netloc}"

        if "media_content" in entry:
            for m in entry.media_content:
                t = m.get("type", "")
                if "video" in t or "mp4" in t:
                    url = m["url"]
                    return base_url + url if url.startswith("/") else url

        if "links" in entry:
            for l in entry.links:
                if l.get("rel") == "enclosure":
                    t = l.get("type", "")
                    if "video" in t or "mp4" in t:
                        url = l["href"]
                        return base_url + url if url.startswith("/") else url

        content = entry.get("summary", "") or entry.get("description", "")
        if content and "<video" in content:
            try:
                soup = BeautifulSoup(content, "lxml")
                video = soup.find("video")
                if video:
                    src = video.get("src")
                    if not src:
                        source = video.find("source")
                        if source:
                            src = source.get("src")
                    if src:
                        return base_url + src if src.startswith("/") else src
            except Exception:
                pass
        return None

    @classmethod
    def _normalize_link(cls, link: str) -> str:
        """Quita querystring/fragment volátiles (tracking, cache-busters) sin
        tocar parámetros que algunas fuentes SÍ usan como identificador real
        del artículo (ej. ?id=1234). Solo se filtran los patrones conocidos
        de tracking listados en TRACKING_PARAM_PATTERNS."""
        if not link:
            return ""
        parsed = urlparse(link.strip())
        netloc = parsed.netloc.lower()
        path = parsed.path.rstrip("/") or "/"
        pares = parse_qsl(parsed.query, keep_blank_values=True)
        conservados = [
            (k, v) for k, v in pares
            if not any(pat in k.lower() for pat in cls.TRACKING_PARAM_PATTERNS)
        ]
        normalizado = f"{parsed.scheme}://{netloc}{path}"
        if conservados:
            normalizado += f"?{urlencode(conservados)}"
        return normalizado

    @classmethod
    def normalize_title(cls, title: str) -> str:
        """Título en minúsculas, sin emojis y con espacios colapsados.
        Público (sin guion bajo) porque monitor.py también lo usa para la
        capa de fuzzy-match (fase 2 de la deduplicación)."""
        if not title:
            return ""
        limpio = cls._EMOJI_PATTERN.sub("", title)
        limpio = re.sub(r"\s+", " ", limpio).strip().lower()
        return limpio

    @classmethod
    def _get_hash(cls, entry) -> str:
        """Identidad estable de la entrada. Prioridad:
        1. GUID/ID nativo del feed (entry.id — el <guid> de RSS o <id> de
           Atom), que el estándar diseñó justo para esto. Si el guid es en sí
           una URL, se normaliza igual que un link.
        2. Fallback: link normalizado + título normalizado, para feeds que no
           traen guid (bastante comunes en scrapers/espejos tipo Nitter).

        Importante: cuando hay guid, NO se mezcla con el título. Si se
        mezclara, una fuente que edita el titular de un artículo ya publicado
        (algo normal en medios) rompería el hash otra vez y reintroduciría el
        mismo bug que estamos arreglando."""
        guid = (entry.get("id") or "").strip()
        if guid:
            identidad = cls._normalize_link(guid) if guid.startswith("http") else guid
        else:
            identidad = cls._normalize_link(entry.get("link", "")) + "|" + cls.normalize_title(entry.get("title", ""))
        return hashlib.md5(identidad.encode()).hexdigest()

    @classmethod
    async def fetch_content(cls, url):
        profiles = list(cls.PROFILES)
        random.shuffle(profiles)
        for profile in profiles[:2]:
            try:
                async with AsyncSession(impersonate=profile, headers=cls.HEADERS) as session:
                    response = await session.get(url, timeout=15)
                    if response.status_code == 200:
                        return response.content, None
                    if response.status_code in (403, 429, 503):
                        await asyncio.sleep(1)
                        continue
            except Exception as e:
                log(f"Error conexión ({profile}) en {url}: {e}", "debug")
                continue
        return None, "Error de conexión o Bloqueo WAF persistente"

    @classmethod
    async def parse(cls, url):
        content, error = await cls.fetch_content(url)
        if error:
            log(f"Error fetching {url}: {error}", "warning")
            return None, error
        try:
            feed = feedparser.parse(content)
            if feed.bozo and not feed.entries:
                if b"Cloudflare" in content or b"Just a moment" in content:
                    return None, "Bloqueo Cloudflare JS"
                return None, "XML inválido o bloqueado"

            entries = []
            for entry in feed.entries[:10]:
                entries.append({
                    "title": cls._clean_html(entry.get("title", "Sin título")),
                    "link": entry.get("link", ""),
                    "description": cls._clean_html(entry.get("summary", entry.get("description", ""))),
                    "image": cls._extract_image(entry),
                    "video": cls._extract_video(entry),
                    "hash": cls._get_hash(entry),
                    "source": feed.feed.get("title", "RSS Source"),
                })
            return {"title": feed.feed.get("title", "Feed"), "entries": entries}, None
        except Exception as e:
            log(f"Error parsing logic {url}: {e}", "error")
            return None, f"Excepción interna: {str(e)}"
