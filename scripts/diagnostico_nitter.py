"""Script de diagnóstico puntual (no de un solo uso, se puede correr las
veces que haga falta): prueba EN VIVO, contra este VPS específico, cada
instancia de RSSParser.NITTER_INSTANCES con un usuario real.

Por qué hace falta:
NITTER_RSS_CONFIRMADAS se armó a partir de https://status.d420.de/, que
monitorea las instancias desde OTRA IP/fingerprint. Que una instancia esté
"sana" ahí no dice nada sobre si le responde a este VPS en particular — de
hecho ese es justo el problema que estamos viendo con nitter.net, que era
la única instancia con éxito confirmado en el log local y ahora devuelve
403 de forma persistente. Este script contesta la pregunta directamente,
sin esperar a que el ciclo normal de RSSMonitor (que puede tardar minutos
por feed) llegue a probar cada instancia.

Qué hace:
Para --usuario (default: philosway, uno de los que está fallando ahora
mismo según el log), llama a RSSParser.fetch_content() -- el mismo cliente,
mismos headers/perfiles TLS que usa el bot en producción -- contra
"{instancia}/{usuario}/rss" en CADA instancia de NITTER_INSTANCES, una por
una (sin concurrencia, para no gastar de golpe el rate-limit de cada una),
y reporta si dio contenido RSS válido, qué código HTTP devolvió, o qué
excepción de red saltó.

Uso (desde la raíz del proyecto, con el venv activado):
    python -m scripts.diagnostico_nitter
    python -m scripts.diagnostico_nitter --usuario wordsnwisdom26
"""

import argparse
import asyncio

from modules.rss.parser import RSSParser
from utils.logger import log


async def main(usuario: str):
    log(f"🔬 Diagnóstico Nitter para @{usuario} — {len(RSSParser.NITTER_INSTANCES)} instancias\n")

    resultados = []
    for instancia in RSSParser.NITTER_INSTANCES:
        confirmada = instancia in RSSParser.NITTER_RSS_CONFIRMADAS
        url = f"{instancia}/{usuario}/rss"
        content, error = await RSSParser.fetch_content(url)

        if not error and RSSParser.is_valid_xml(content):
            estado = "✅ OK"
        elif error:
            estado = f"❌ {error}"
        else:
            estado = "⚠️ Respondió pero no es XML válido (posible página de bloqueo)"

        marca = "(confirmada)" if confirmada else "(resto del pool)"
        print(f"{instancia:<40} {marca:<18} {estado}")
        resultados.append((instancia, confirmada, estado.startswith("✅")))

        await asyncio.sleep(1)  # no golpear todas las instancias de una vez

    exitosas = [r for r in resultados if r[2]]
    print(f"\nResumen: {len(exitosas)}/{len(resultados)} instancias respondieron OK a este VPS.")
    if not exitosas:
        print(
            "Ninguna instancia del pool le respondió a este VPS. Esto ya no es un "
            "problema de instancias muertas/rotas — apunta a bloqueo por IP de "
            "datacenter/fingerprint a nivel de VPS, el ítem que el plan había "
            "dejado fuera de alcance."
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--usuario", default="philosway", help="Usuario de X/Twitter a probar (sin @)")
    args = parser.parse_args()
    asyncio.run(main(args.usuario))
