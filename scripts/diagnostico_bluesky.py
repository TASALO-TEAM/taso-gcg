"""Script de diagnóstico puntual para BlueskyClient — prueba EN VIVO, contra
este VPS, el flujo completo que usa /addfeed + el monitor: resolver el
perfil (BlueskyClient.resolve) y traer sus posts (BlueskyClient.parse).

A diferencia de diagnostico_nitter.py no hace falta probar un pool de
instancias (Bluesky expone una sola API pública oficial), así que esto es
más bien una prueba de humo end-to-end antes de confiar el feed al
monitor: confirma que la cuenta existe, que la API responde desde este VPS
concreto (por si hay algún bloqueo de red/firewall de salida) y muestra el
primer post ya normalizado al formato de entry que usa monitor.py.

Uso (desde la raíz del proyecto, con el venv activado):
    python -m scripts.diagnostico_bluesky
    python -m scripts.diagnostico_bluesky --perfil https://bsky.app/profile/watcher.guru
"""

import argparse
import asyncio

from modules.rss.bluesky import BlueskyClient


async def main(perfil: str):
    print(f"🔬 Diagnóstico Bluesky para {perfil}\n")

    print("1) Resolviendo perfil (BlueskyClient.resolve)...")
    url_canonica, titulo, error = await BlueskyClient.resolve(perfil)
    if error:
        print(f"   ❌ {error}")
        return
    print(f"   ✅ {titulo}")
    print(f"   URL canónica a guardar en feeds.url: {url_canonica}")

    print("\n2) Trayendo posts (BlueskyClient.parse)...")
    parsed, error = await BlueskyClient.parse(url_canonica)
    if error:
        print(f"   ❌ {error}")
        return
    entries = parsed["entries"]
    print(f"   ✅ {len(entries)} posts obtenidos (feed: {parsed['title']})")

    if not entries:
        print("   ⚠️ La cuenta existe pero no devolvió posts (¿cuenta nueva o solo respuestas?).")
        return

    primero = entries[0]
    print("\n3) Primer post normalizado (esto es lo que enviaría /testfeed):")
    for llave in ("title", "link", "image", "video", "external_link", "source", "hash"):
        valor = primero.get(llave)
        texto = (valor[:80] + "…") if isinstance(valor, str) and len(valor) > 80 else valor
        print(f"   {llave:<14}: {texto}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--perfil", default="https://bsky.app/profile/watcher.guru",
        help="Link de perfil de Bluesky a probar",
    )
    args = parser.parse_args()
    asyncio.run(main(args.perfil))
