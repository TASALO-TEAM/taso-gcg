"""RSSMonitor — misma lógica de negocio que BitBreadRSS/services/monitor.py
(backoff exponencial, auto-reparación de feeds caídos vía RSSResolver, estilo
'bitbread' con foto/video + fallback a texto), pero con la capa de datos
reescrita sobre SQLite en vez de un JSON completo cargado/guardado en memoria.

Se integra con APScheduler: en vez de `while True: sleep(60)`, se registra
como job periódico (ver core del bot.py / register_scheduler abajo).
"""

import asyncio
import time

from telegram.constants import ParseMode

from core.database import db
from modules.rss.parser import RSSParser
from modules.rss.resolver import RSSResolver
from modules.rss.iv_generator import create_instant_view_link
from utils.common import truncate_text
from utils.logger import log

DEFAULT_TEMPLATE = (
    "<b>#title#</b>\n\n"
    "<i>#description#</i>\n\n"
    "<i><b>🔗 Fuente:</b><a href='#link#'> #source#</a></i>"
)


class RSSMonitor:
    def __init__(self, bot):
        self.bot = bot
        self.semaphore = asyncio.Semaphore(3)  # máx 3 peticiones HTTP a la vez

    async def check_feeds(self):
        """Un ciclo completo: revisa todos los feeds activos que ya les toque
        chequearse según su intervalo (con backoff si vienen fallando)."""
        feeds = await db.fetchall(
            "SELECT feeds.*, chats.tg_chat_id as chat_tg_id, chats.activo as chat_activo "
            "FROM feeds JOIN chats ON feeds.chat_id = chats.id "
            "WHERE feeds.activo = 1"
        )
        for feed in feeds:
            if not feed["chat_activo"]:
                continue
            try:
                await self._procesar_feed(feed)
            except Exception as e:
                log(f"❌ Error CRÍTICO procesando feed {feed.get('url', 'desconocido')}: {e}", "error")
                await self._registrar_error(feed["id"], str(e))
            await asyncio.sleep(0.5)  # pausa breve para no saturar CPU entre feeds

    async def _procesar_feed(self, feed: dict):
        ahora = time.time()
        stats = await db.fetchone("SELECT * FROM feed_stats WHERE feed_id = ?", (feed["id"],))
        errores_consecutivos = stats["errores"] if stats else 0

        intervalo_base = feed["intervalo_min"] * 60
        multiplicador = min(errores_consecutivos + 1, 4) if errores_consecutivos else 1
        intervalo_real = intervalo_base * multiplicador

        if ahora - feed["ultimo_check"] < intervalo_real:
            return

        async with self.semaphore:
            parsed, error = await RSSParser.parse(feed["url"])

            # --- Auto-reparación: si Nitter cae o hay bloqueo WAF, rotar instancia ---
            is_nitter = "nitter" in feed["url"]
            is_waf_block = any(k in str(error) for k in ("403", "429", "Cloudflare"))
            needs_repair = bool(error) and (is_nitter or is_waf_block)

            if needs_repair:
                err_type = "Instancia Caída" if is_nitter else "WAF Bloqueo"
                log(f"🛡️ {err_type} en {feed['url']}. Iniciando rotación...", "warning")
                target_url = feed["url_original"] or feed["url"]
                new_url, new_title, res_err = await RSSResolver.find_best_feed(target_url)
                if new_url and new_url != feed["url"]:
                    log(f"✅ Feed reparado: {feed['url']} -> {new_url}")
                    await db.execute("UPDATE feeds SET url = ? WHERE id = ?", (new_url, feed["id"]))
                    feed["url"] = new_url
                    parsed, error = await RSSParser.parse(new_url)
                else:
                    log(f"❌ Falló reparación: {res_err}", "error")

        if error:
            log(f"⚠️ Fallo en {feed['url']}: {error}", "warning")
            await self._registrar_error(feed["id"], error)
            await db.execute("UPDATE feeds SET ultimo_check = ? WHERE id = ?", (ahora, feed["id"]))
            return

        # Éxito: resetear contador de errores y marcar el check
        await db.execute(
            "INSERT INTO feed_stats(feed_id, errores) VALUES (?, 0) "
            "ON CONFLICT(feed_id) DO UPDATE SET errores = 0",
            (feed["id"],),
        )
        await db.execute("UPDATE feeds SET ultimo_check = ? WHERE id = ?", (ahora, feed["id"]))

        historial = await db.fetchall(
            "SELECT entry_hash FROM feed_historial WHERE feed_id = ?", (feed["id"],)
        )
        vistos = {h["entry_hash"] for h in historial}
        nuevas = [e for e in reversed(parsed["entries"]) if e["hash"] not in vistos]

        enviados = 0
        for entry in nuevas:
            ok = await self._send_entry(feed, entry)
            if ok:
                await db.execute(
                    "INSERT OR IGNORE INTO feed_historial(feed_id, entry_hash) VALUES (?,?)",
                    (feed["id"], entry["hash"]),
                )
                await db.execute(
                    "INSERT INTO feed_stats(feed_id, enviados) VALUES (?, 1) "
                    "ON CONFLICT(feed_id) DO UPDATE SET enviados = enviados + 1",
                    (feed["id"],),
                )
                enviados += 1
                await asyncio.sleep(2.0)  # pausa entre envíos, cortesía con los límites de Telegram

        if enviados:
            log(f"✅ {enviados} noticias enviadas de {feed['titulo'] or feed['url']}")
            # Limpieza periódica del historial: no tiene sentido acumular hashes de
            # entradas que ya no aparecerán nunca más en el feed (los feeds típicos
            # traen 10-20 entradas). Nos quedamos con los últimos 200 por feed.
            await db.execute(
                "DELETE FROM feed_historial WHERE feed_id = ? AND entry_hash NOT IN ("
                "  SELECT entry_hash FROM feed_historial WHERE feed_id = ? "
                "  ORDER BY enviado_en DESC LIMIT 200)",
                (feed["id"], feed["id"]),
            )

    async def _registrar_error(self, feed_id: int, error_msg: str):
        await db.execute(
            "INSERT INTO feed_stats(feed_id, errores, ultimo_error) VALUES (?, 1, ?) "
            "ON CONFLICT(feed_id) DO UPDATE SET errores = errores + 1, ultimo_error = excluded.ultimo_error",
            (feed_id, error_msg),
        )

    async def _send_entry(self, feed: dict, entry: dict) -> bool:
        template = feed["plantilla"] or DEFAULT_TEMPLATE
        style = feed["estilo"] or "bitbread"
        user_rhash = feed["rhash"]

        iv_link = await create_instant_view_link(entry["link"], user_rhash)

        text = (
            template.replace("#title#", entry["title"])
            .replace("#description#", entry["description"])
            .replace("#link#", entry["link"])
            .replace("#source#", entry["source"])
            .replace("#sourceiv#", iv_link)
        )

        offset = len(iv_link) - len(entry["link"]) if user_rhash else 0
        limit_caption = 1024 - max(0, offset)
        limit_text = 4090 - max(0, offset)
        chat_tg_id = feed["chat_tg_id"]

        if style == "bitbread":
            try:
                safe_caption = truncate_text(text, limit=int(limit_caption))
                if entry.get("video"):
                    await self.bot.send_video(
                        chat_id=chat_tg_id, video=entry["video"], caption=safe_caption,
                        parse_mode=ParseMode.HTML, read_timeout=30, write_timeout=30,
                    )
                    return True
                elif entry.get("image"):
                    await self.bot.send_photo(
                        chat_id=chat_tg_id, photo=entry["image"], caption=safe_caption,
                        parse_mode=ParseMode.HTML,
                    )
                    return True
            except Exception as e:
                log(f"⚠️ Falló multimedia en {chat_tg_id} (intentando texto). Err: {e}", "warning")

        try:
            safe_text = truncate_text(text, limit=int(limit_text))
            await self.bot.send_message(
                chat_id=chat_tg_id, text=safe_text, parse_mode=ParseMode.HTML,
                disable_web_page_preview=False,
            )
            return True
        except Exception as e:
            log(f"❌ Error fatal enviando a {chat_tg_id}: {e}", "error")
            return False

    async def force_check(self, feed_id: int):
        """Usado por /testfeed: manda la entrada más reciente sin esperar al intervalo."""
        feed = await db.fetchone(
            "SELECT feeds.*, chats.tg_chat_id as chat_tg_id "
            "FROM feeds JOIN chats ON feeds.chat_id = chats.id WHERE feeds.id = ?",
            (feed_id,),
        )
        if not feed:
            return False, "Feed no encontrado."
        parsed, error = await RSSParser.parse(feed["url"])
        if error or not parsed["entries"]:
            return False, "No se pudo leer el feed."
        ok = await self._send_entry(feed, parsed["entries"][0])
        return ok, "Noticia de prueba enviada." if ok else "Error enviando al canal."
