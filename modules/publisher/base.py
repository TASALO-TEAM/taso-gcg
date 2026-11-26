"""Tipos comunes y registros de fuentes y destinos de la publicación automática."""

from dataclasses import dataclass, field
from typing import Awaitable, Callable

TIPOS_DESTINO = ("telegram", "hive_blog", "hive_wave", "hive_snap", "nostr")
FUENTES_VALIDAS = ("year", "tspl")


@dataclass(frozen=True)
class Contenido:
    """Lo que produce una fuente, ya listo para que cada destino elija formato."""
    titulo: str
    cuerpo_md: str                 # versión larga (blog)
    texto_corto: str               # versión corta (microblog, Telegram)
    tags: tuple[str, ...] = ()
    imagen: str | None = None
    extra: dict = field(default_factory=dict)


@dataclass(frozen=True)
class Resultado:
    ok: bool
    url: str | None = None
    error: str | None = None
    simulado: bool = False         # dry-run: se armó pero no se envió


# Una fuente es `async () -> Contenido`.
# Un destino es `async (contenido, destino: dict, cuenta: dict | None, secreto: str | None, simular: bool) -> Resultado`.
Fuente = Callable[[], Awaitable[Contenido]]
Destino = Callable[..., Awaitable[Resultado]]

CTX: dict = {}   # recursos compartidos que pone register(): {"bot": telegram.Bot}
FUENTES: dict[str, Fuente] = {}
DESTINOS: dict[str, Destino] = {}


def fuente(nombre: str):
    def deco(fn: Fuente) -> Fuente:
        FUENTES[nombre] = fn
        return fn
    return deco


def destino(tipo: str):
    def deco(fn: Destino) -> Destino:
        DESTINOS[tipo] = fn
        return fn
    return deco
