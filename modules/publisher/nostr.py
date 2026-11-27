"""Publicar en Nostr: clave privada, evento firmado (NIP-01, kind 1) y envío a relays.

La clave llega como `nsec1…` o 64 caracteres hex. Ningún mensaje de error repite lo que el dueño escribió.
La verificación de firmas ajenas y la codificación bech32 viven en `modules/rss/nostr.py` (solo lectura).
"""

import asyncio
import hashlib
import json
import re
import time

from coincurve import PrivateKey
from websockets.asyncio.client import connect

from modules.rss.nostr import bech32_decode, bech32_encode, hex_to_npub
from utils.logger import log

OPEN_TIMEOUT = 8          # s para abrir cada relay
TOTAL_TIMEOUT = 12        # s máximos por relay (conexión + OK)
MAX_MSG = 65_536          # bytes por respuesta del relay
_HEX = re.compile(r"[0-9a-fA-F]{64}")


class NostrError(ValueError):
    """Mensaje seguro para mostrar: nunca incluye la clave."""


def parsear_clave(texto: str) -> bytes:
    t = (texto or "").strip()
    if t.lower().startswith(("npub1", "nprofile1")):
        raise NostrError("Eso es una clave pública. Necesito la privada (nsec1… o 64 caracteres hex).")
    try:
        if _HEX.fullmatch(t):
            raw = bytes.fromhex(t)
        else:
            hrp, raw = bech32_decode(t)
            if hrp != "nsec":
                raise ValueError
        PrivateKey(raw)                      # valida el rango de la curva
    except Exception:
        raise NostrError("No es una clave privada de Nostr válida (nsec1… o 64 caracteres hex).") from None
    return raw


def _pub_hex(sk: bytes) -> str:
    return PrivateKey(sk).public_key.format()[1:].hex()


def npub_de(sk: bytes) -> str:
    return hex_to_npub(_pub_hex(sk))


def nsec_de(sk: bytes) -> str:
    return bech32_encode("nsec", sk)


def evento(sk: bytes, contenido: str, tags=(), kind: int = 1, t: int | None = None) -> dict:
    pub = _pub_hex(sk)
    t = int(time.time()) if t is None else t
    tags = [list(x) for x in tags]
    ser = json.dumps([0, pub, t, kind, tags, contenido], separators=(",", ":"), ensure_ascii=False)
    eid = hashlib.sha256(ser.encode()).digest()
    sig = PrivateKey(sk).sign_schnorr(eid).hex()
    return {"id": eid.hex(), "pubkey": pub, "created_at": t, "kind": kind, "tags": tags, "content": contenido, "sig": sig}


def nota_url(eid: str) -> str:
    return "https://njump.me/" + bech32_encode("note", bytes.fromhex(eid))


async def _enviar(relay: str, ev: dict) -> bool:
    async def correr() -> bool:
        async with connect(relay, open_timeout=OPEN_TIMEOUT, close_timeout=2, max_size=MAX_MSG) as ws:
            await ws.send(json.dumps(["EVENT", ev]))
            async for crudo in ws:
                try:
                    msg = json.loads(crudo)
                except ValueError:
                    continue
                if isinstance(msg, list) and len(msg) >= 3 and msg[0] == "OK" and msg[1] == ev["id"]:
                    return msg[2] is True
        return False

    try:
        return await asyncio.wait_for(correr(), TOTAL_TIMEOUT)
    except Exception as e:
        log(f"Nostr: {relay} no confirmó ({type(e).__name__})", "debug")
        return False


async def publicar(ev: dict, relays: list[str]) -> tuple[list[str], list[str]]:
    """(relays que aceptaron, relays que no). Nunca lanza."""
    res = await asyncio.gather(*(_enviar(r, ev) for r in relays))
    return [r for r, ok in zip(relays, res) if ok], [r for r, ok in zip(relays, res) if not ok]
