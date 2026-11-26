"""Diagnóstico EN VIVO de NostrClient (análogo a diagnostico_bluesky.py) y spike
para elegir los relays por defecto: mide cada relay candidato (tiempo, eventos
recibidos, eventos con firma válida) y luego resuelve + parsea la cuenta con
los relays configurados en NOSTR_RELAYS.

Uso (desde la raíz del proyecto, con el venv activado):
    python -m scripts.diagnostico_nostr
    python -m scripts.diagnostico_nostr --cuenta npub1... --relays wss://a,wss://b
"""

import argparse
import asyncio
import time

from core.config import NOSTR_RELAYS
from modules.rss import nostr
from modules.rss.nostr import NostrClient

# Cuenta pública y activa de ejemplo (fiatjaf). Cambia con --cuenta.
CUENTA = "3bf0c63fcb93463407af97a5e5ee64fa883d107ef9e558472c4eb9aaaefa459d"
CANDIDATOS = [
    "wss://relay.damus.io", "wss://nos.lol", "wss://relay.primal.net", "wss://relay.nostr.band",
    "wss://offchain.pub", "wss://relay.snort.social", "wss://nostr.wine", "wss://purplepag.es",
]


async def probar_relay(relay: str, clave: str):
    t0 = time.monotonic()
    eventos, ok = await nostr._query_relay(
        relay, [{"authors": [clave], "kinds": [1, 30023], "limit": nostr.REQ_LIMIT}])
    validos = sum(nostr.verify_event(e, clave) for e in eventos)
    estado = "EOSE" if ok else ("parcial" if eventos else "sin respuesta")
    print(f"   {relay:<30} {time.monotonic() - t0:5.1f}s  {estado:<14} eventos={len(eventos):<3} firma válida={validos}")


async def main(cuenta: str, relays: list[str]):
    clave, _ = await NostrClient._clave(cuenta)
    print(f"🔍 Diagnóstico Nostr para {nostr.hex_to_npub(clave)}\n")

    print("1) Relays candidatos (en paralelo, como en producción):")
    await asyncio.gather(*(probar_relay(r, clave) for r in relays))

    print(f"\n2) Resolviendo (NostrClient.resolve) con NOSTR_RELAYS={NOSTR_RELAYS}...")
    url, titulo, error = await NostrClient.resolve(cuenta)
    if error:
        print(f"   ❌ {error}")
        return
    print(f"   ✅ {titulo}\n   URL a guardar en feeds.url: {url}")

    print("\n3) Trayendo notas (NostrClient.parse)...")
    t0 = time.monotonic()
    parsed, error = await NostrClient.parse(url)
    if error:
        print(f"   ❌ {error}")
        return
    entradas = parsed["entries"]
    print(f"   ✅ {len(entradas)} entradas en {time.monotonic() - t0:.1f}s (feed: {parsed['title']})")
    if entradas:
        e = entradas[0]
        print("\n   Primera entrada ya normalizada:")
        for k in ("title", "link", "image", "video", "external_link", "hash", "source"):
            print(f"     {k:<14} {e[k]}")
        print(f"     description    {e['description'][:200]}")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--cuenta", default=CUENTA)
    p.add_argument("--relays", default=",".join(CANDIDATOS), help="lista separada por comas")
    a = p.parse_args()
    asyncio.run(main(a.cuenta, [r.strip() for r in a.relays.split(",") if r.strip()]))
