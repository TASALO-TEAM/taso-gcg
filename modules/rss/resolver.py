"""RSSResolver — portado casi intacto de BitBreadRSS/services/resolver.py."""

import asyncio
import random
import json
import urllib.parse
from urllib.parse import urljoin, urlparse
import feedparser
from bs4 import BeautifulSoup

from modules.rss.parser import RSSParser
from utils.logger import log


class RSSResolver:
    """Descubre la URL real del RSS a partir de un dominio/URL cualquiera,
    con contingencias ante bloqueos WAF/Cloudflare."""

    COMMON_PATHS = [
        "feed", "feed/", "rss", "rss.xml", "atom.xml", "feed.xml",
        "index.xml", "feeds/posts/default", "?feed=rss2", "rss/",
    ]

    @classmethod
    async def find_best_feed(cls, url):
        """Retorna: (resolved_url, title, error_msg)"""
        url = url.strip().rstrip("/")
        if not url.startswith("http"):
            url = f"https://{url}"

        log(f"🔍 Resolviendo feed para: {url}")
        candidates = []
        domain_error = None

        if "twitter.com" in url or "x.com" in url or "nitter" in url:
            username = RSSParser._get_twitter_username(url)
            if username:
                log(f"🐦 Buscando feed para @{username}...")
                instances = RSSParser.NITTER_INSTANCES.copy()
                random.shuffle(instances)
                for nitter_base in instances:
                    nitter_url = f"{nitter_base}/{username}/rss"
                    content, error = await RSSParser.fetch_content(nitter_url)
                    if not error and RSSParser.is_valid_xml(content):
                        log(f"   ✅ ¡Nitter encontrado en {nitter_base}!")
                        return nitter_url, f"Twitter: @{username}", None

                log("   ⚠️ Nitter falló. Probando RSSHub (Bridge)...")
                rsshub_url = f"https://rsshub.app/twitter/user/{username}"
                content, error = await RSSParser.fetch_content(rsshub_url)
                if not error and RSSParser.is_valid_xml(content):
                    return rsshub_url, f"Twitter: @{username}", None
                return None, None, "No se pudo obtener el feed de Twitter (Nitter y RSSHub bloqueados)."

        content, error = await RSSParser.fetch_content(url)
        if not error:
            d = feedparser.parse(content)
            if not d.bozo and len(d.entries) > 0:
                return url, d.feed.get("title", "Feed"), None
            try:
                soup = BeautifulSoup(content, "lxml")
                links = soup.find_all("link", rel=["alternate", "service.feed"])
                for link in links:
                    t = link.get("type", "").lower()
                    href = link.get("href")
                    if href and ("rss" in t or "atom" in t or "xml" in t):
                        candidates.append(urljoin(url, href))
                if not candidates:
                    for a in soup.find_all("a", href=True):
                        href = a.get("href")
                        if any(x in href.lower() for x in ("/rss", "/feed", ".xml")):
                            candidates.append(urljoin(url, href))
            except Exception as e:
                log(f"Error parseando HTML: {e}", "warning")
        else:
            domain_error = error
            log(f"⚠️ Falló acceso a home ({error}), intentando fuerza bruta...", "warning")

        if not candidates:
            base = f"{urlparse(url).scheme}://{urlparse(url).netloc}"
            if url != base and url != base + "/":
                candidates.append(url)
            for path in cls.COMMON_PATHS:
                candidates.append(urljoin(base + "/", path))

        unique_candidates = list(set(candidates))
        await asyncio.sleep(2)

        for cand in unique_candidates[:6]:
            log(f"   👉 Probando candidato: {cand}")
            c_content, c_err = await RSSParser.fetch_content(cand)
            if not c_err:
                d_cand = feedparser.parse(c_content)
                if not d_cand.bozo and len(d_cand.entries) > 0:
                    return cand, d_cand.feed.get("title", "Feed Detectado"), None
            elif "403" in str(c_err) or "429" in str(c_err):
                log(f"   🚫 Bloqueo WAF en {cand}", "warning")

        log("⚠️ Falló descubrimiento local. Activando Nivel 2 (API Externa)...")
        ext_url, ext_title, ext_err = await cls.fetch_from_feedly(url)
        if ext_url:
            return ext_url, ext_title, None

        fail_msg = (
            f"No se pudo detectar el feed. Error inicial: {domain_error}"
            if domain_error else "No se encontraron feeds válidos."
        )
        return None, None, fail_msg

    @classmethod
    async def fetch_from_feedly(cls, domain_url):
        clean_url = urllib.parse.quote(domain_url)
        search_url = f"https://cloud.feedly.com/v3/search/feeds?query={clean_url}"
        log(f"🌍 Consultando inteligencia externa (Feedly) para: {domain_url}")
        content, err = await RSSParser.fetch_content(search_url)
        if not err and content:
            try:
                data = json.loads(content)
                if data.get("results"):
                    best_match = data["results"][0]
                    found_url = best_match["feedId"].replace("feed/", "")
                    return found_url, best_match.get("title", "Feed Externo"), None
            except Exception as e:
                log(f"Error parseando respuesta de Feedly: {e}", "warning")
        return None, None, "No encontrado en índices externos"
