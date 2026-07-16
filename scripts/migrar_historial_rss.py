"""Script de un solo uso: correr DESPUÉS de desplegar el fix de deduplicación
de RSS (nuevo _get_hash con guid + normalización) y ANTES de reiniciar el
servicio systemd del bot (o justo después, da igual, mientras corra una
vez antes de que RSSMonitor.check_feeds haga su primer ciclo real).

Por qué hace falta:
El hash viejo era md5(link_crudo + titulo_crudo). El nuevo prioriza el guid
y normaliza link/título. Son fórmulas distintas, así que TODOS los hashes
guardados en feed_historial dejan de coincidir con lo que el bot va a
calcular de aquí en adelante. Sin este script, el primer chequeo después
del despliegue va a ver las 10-20 entradas actuales de cada feed como
"nuevas" y las reenvía una vez — molesto pero no catastrófico, y es
justo el bug que se está arreglando, así que vale la pena evitarlo.

Qué hace:
Para cada feed activo, vuelve a parsear la URL (mismo RSSParser que usa el
bot en producción, así que el hash calculado es exactamente el que el
monitor va a ver luego) e inserta esas entradas en feed_historial como ya
"vistas", SIN enviarlas a Telegram.

Uso (desde la raíz del proyecto, con el venv activado):
    python -m scripts.migrar_historial_rss
"""

import asyncio

from core.database import db
from modules.rss.parser import RSSParser
from utils.logger import log


async def main():
    await db.init()

    feeds = await db.fetchall("SELECT * FROM feeds WHERE activo = 1")
    if not feeds:
        log("No hay feeds activos, nada que migrar.")
        await db.close()
        return

    total_marcadas = 0
    for feed in feeds:
        parsed, error = await RSSParser.parse(feed["url"])
        if error or not parsed:
            log(f"⚠️ No se pudo leer {feed['url']} durante la migración: {error}", "warning")
            continue

        for entry in parsed["entries"]:
            titulo_norm = RSSParser.normalize_title(entry["title"])
            await db.execute(
                "INSERT OR IGNORE INTO feed_historial(feed_id, entry_hash, titulo_normalizado) "
                "VALUES (?,?,?)",
                (feed["id"], entry["hash"], titulo_norm),
            )
            total_marcadas += 1

        log(f"✅ {feed['titulo'] or feed['url']}: {len(parsed['entries'])} entradas marcadas como vistas")

    log(f"🏁 Migración completa: {total_marcadas} entradas marcadas en {len(feeds)} feeds.")
    await db.close()


if __name__ == "__main__":
    asyncio.run(main())
