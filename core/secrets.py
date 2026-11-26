"""Cifrado de secretos guardados en la base de datos (claves de posting de Hive,
nsec de Nostr...).

Diseño:
- AES-256-GCM (autenticado). Formato guardado: "v1." + base64url(nonce12 + cifrado).
- La clave maestra vive SOLO en el entorno (.env): PUBLISHER_MASTER_KEY. Una
  copia de la base de datos sola no revela nada.
- El *nombre* del secreto se usa como dato asociado (AAD): un valor cifrado
  copiado a otra fila ya no descifra.
- Rotación: PUBLISHER_MASTER_KEY_OLD admite una clave anterior solo para
  descifrar; `recifrar()` devuelve el valor con la clave actual.
- Nunca se registra ni se muestra el valor; usa `enmascarar()` para mostrar algo.

Generar una clave:  python -m core.secrets
"""

import base64
import os
import secrets as _secrets

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

VERSION = "v1"
ENV_ACTUAL = "PUBLISHER_MASTER_KEY"
ENV_ANTERIOR = "PUBLISHER_MASTER_KEY_OLD"


class SecretoError(Exception):
    """Fallo de cifrado/descifrado. El mensaje nunca incluye valores secretos."""


def generar_clave() -> str:
    return base64.urlsafe_b64encode(_secrets.token_bytes(32)).decode()


def _leer_clave(var: str) -> bytes | None:
    crudo = os.getenv(var, "").strip()
    if not crudo:
        return None
    try:
        clave = base64.urlsafe_b64decode(crudo + "=" * (-len(crudo) % 4))
    except Exception as e:  # noqa: BLE001
        raise SecretoError(f"{var} no es base64 válido") from e
    if len(clave) != 32:
        raise SecretoError(f"{var} debe decodificar a 32 bytes (usa `python -m core.secrets`)")
    return clave


def disponible() -> bool:
    """True si hay clave maestra configurada (sin ella no se guardan secretos)."""
    try:
        return _leer_clave(ENV_ACTUAL) is not None
    except SecretoError:
        return False


def cifrar(nombre: str, valor: str) -> str:
    clave = _leer_clave(ENV_ACTUAL)
    if clave is None:
        raise SecretoError(f"Falta {ENV_ACTUAL} en el entorno: no se pueden guardar secretos")
    nonce = _secrets.token_bytes(12)
    cifrado = AESGCM(clave).encrypt(nonce, valor.encode("utf-8"), nombre.encode("utf-8"))
    return f"{VERSION}." + base64.urlsafe_b64encode(nonce + cifrado).decode()


def descifrar(nombre: str, token: str) -> str:
    if not token or not token.startswith(VERSION + "."):
        raise SecretoError("Formato de secreto no reconocido")
    carga = token[len(VERSION) + 1:]
    try:
        datos = base64.urlsafe_b64decode(carga + "=" * (-len(carga) % 4))
    except Exception as e:  # noqa: BLE001
        raise SecretoError("Secreto corrupto") from e
    if len(datos) < 12 + 16:
        raise SecretoError("Secreto corrupto")
    nonce, cifrado = datos[:12], datos[12:]
    claves = [k for k in (_leer_clave(ENV_ACTUAL), _leer_clave(ENV_ANTERIOR)) if k]
    if not claves:
        raise SecretoError(f"Falta {ENV_ACTUAL} en el entorno")
    for clave in claves:
        try:
            return AESGCM(clave).decrypt(nonce, cifrado, nombre.encode("utf-8")).decode("utf-8")
        except InvalidTag:
            continue
    raise SecretoError("No se pudo descifrar (¿clave maestra distinta o secreto movido?)")


def recifrar(nombre: str, token: str) -> str:
    """Descifra con la clave actual o la anterior y vuelve a cifrar con la actual."""
    return cifrar(nombre, descifrar(nombre, token))


def enmascarar(valor: str) -> str:
    """Solo para mostrar: últimos 4 caracteres. Nunca el valor completo."""
    return "…" + valor[-4:] if len(valor) > 8 else "…"


if __name__ == "__main__":
    print(f"{ENV_ACTUAL}={generar_clave()}")
