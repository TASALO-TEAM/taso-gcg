"""Destino `nostr`: publica el texto corto como nota (kind 1) firmada con la clave de la cuenta.

La cuenta (`pub_cuentas`, red nostr) trae el nsec cifrado y, en `params`, `relays` (lista wss://). Los
`params` del destino los sobrescriben; sin ninguno se usan `NOSTR_RELAYS`. `max_chars` (opcional) recorta.
Basta con que UN relay confirme; si ninguno lo hace, el planificador reintenta.
"""

import re

from core.config import NOSTR_RELAYS
from modules.publisher import nostr
from modules.publisher.base import Contenido, Resultado, destino

MAX_TAGS = 5


def _tags(contenido: Contenido) -> list[list[str]]:
    vistos: list[str] = []
    for t in contenido.tags:
        t = re.sub(r"\W", "", str(t).lower())[:30]
        if t and t not in vistos:
            vistos.append(t)
    return [["t", t] for t in vistos[:MAX_TAGS]]


@destino("nostr")
async def destino_nostr(contenido: Contenido, d: dict, cuenta, secreto, simular: bool) -> Resultado:
    if not cuenta:
        raise ValueError("el destino de Nostr necesita una cuenta")
    aj = {**(cuenta.get("params") or {}), **(d.get("params") or {})}
    texto = contenido.texto_corto
    tope = aj.get("max_chars")
    if isinstance(tope, int) and tope > 1 and len(texto) > tope:
        texto = texto[: tope - 1].rstrip() + "…"
    if simular:
        return Resultado(True, simulado=True)
    if not secreto:
        raise RuntimeError("la cuenta no tiene clave guardada")
    ev = nostr.evento(nostr.parsear_clave(secreto), texto, _tags(contenido))
    relays = [r for r in (aj.get("relays") or NOSTR_RELAYS) if isinstance(r, str)]
    ok, mal = await nostr.publicar(ev, relays)
    if not ok:
        raise RuntimeError(f"ningún relay aceptó la nota ({len(mal)} probados)")
    return Resultado(True, url=nostr.nota_url(ev["id"]))
