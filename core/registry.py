"""Registro único de comandos (dato puro, sin Telegram).

Cada módulo declara junto a su `register()`:

    TOPIC = Topic("bans", "🔨 Bans y silencios", aliases=("ban", "baneos"))
    COMMANDS = (
        Cmd("ban", "Banea permanentemente", level="admin", ambito="grupo",
            topic="bans", uso="[motivo]", menu=True),
        ...
    )

`core/loader.py` los recoge en `application.bot_data["cmds"|"topics"]` y de ahí
salen las tres cosas que antes se mantenían a mano: el menú "/" de Telegram,
`/help` y `docs/COMANDOS.md`. Los módulos siguen creando sus CommandHandler;
`tests/test_registry.py` impide que un comando exista en un lado y no en el otro.
"""

import re
from dataclasses import dataclass

NIVELES = ("todos", "admin", "sudo")
AMBITOS = ("grupo", "privado", "ambos")
# Cada scope de Telegram sustituye al anterior (no se suman): por eso cada lista
# se arma completa. "default" = grupos/canales para quien no es admin.
SCOPES = ("default", "private", "admins", "sudo")
MAX_MENU = 100  # límite de Telegram por scope
PRIMEROS = ("start", "help", "menu", "settings")  # van arriba en la lista "/"

_NOMBRE = re.compile(r"[a-z0-9_]{1,32}")


@dataclass(frozen=True)
class Cmd:
    name: str
    desc: str                 # 1-256 caracteres (límite de Telegram)
    level: str = "todos"      # quién puede usarlo
    ambito: str = "ambos"     # dónde tiene sentido
    topic: str = ""           # clave del Topic de /help
    uso: str = ""             # argumentos para /help, p.ej. "<1h|30m|1d> [motivo]"
    menu: bool = False        # ¿sale en la lista "/"? solo los ~25 imprescindibles
    alias: tuple[str, ...] = ()


@dataclass(frozen=True)
class Topic:
    key: str
    title: str
    aliases: tuple[str, ...] = ()
    nota: str = ""            # texto libre extra que se añade al final del tema


def validar(cmds, topics=()) -> None:
    """ValueError si el registro no es coherente. Se llama al arrancar y en tests."""
    claves = {t.key for t in topics}
    vistos: dict[str, str] = {}
    for c in cmds:
        for nombre in (c.name, *c.alias):
            if not _NOMBRE.fullmatch(nombre):
                raise ValueError(f"nombre de comando inválido: {nombre!r}")
            if nombre in vistos:
                raise ValueError(f"comando repetido: /{nombre} ({vistos[nombre]} y {c.name})")
            vistos[nombre] = c.name
        if not 1 <= len(c.desc) <= 256:
            raise ValueError(f"/{c.name}: la descripción debe tener 1-256 caracteres")
        if c.level not in NIVELES:
            raise ValueError(f"/{c.name}: level inválido {c.level!r}")
        if c.ambito not in AMBITOS:
            raise ValueError(f"/{c.name}: ambito inválido {c.ambito!r}")
        if topics and c.topic not in claves:
            raise ValueError(f"/{c.name}: topic {c.topic!r} no existe")
    for scope in SCOPES:
        if len(menu_para(cmds, scope)) > MAX_MENU:
            raise ValueError(f"el menú '{scope}' pasa de {MAX_MENU} comandos")


def _visible(c: Cmd, scope: str) -> bool:
    if scope == "default":
        return c.level == "todos" and c.ambito != "privado"
    if scope == "private":
        return c.level == "todos" and c.ambito != "grupo"
    if scope == "admins":
        return c.level in ("todos", "admin") and c.ambito != "privado"
    if scope == "sudo":
        return c.ambito != "grupo"
    raise ValueError(f"scope desconocido: {scope!r}")


def menu_para(cmds, scope: str) -> list[tuple[str, str]]:
    """[(nombre, descripción)] para setMyCommands del scope dado."""
    elegidos = [c for c in cmds if c.menu and _visible(c, scope)]
    elegidos.sort(key=lambda c: c.name not in PRIMEROS)  # estable: el resto conserva el orden
    return [(c.name, c.desc) for c in elegidos]


def temas(cmds, topics) -> list[tuple[Topic, list[Cmd]]]:
    """Los temas de /help en orden, cada uno con sus comandos."""
    return [(t, [c for c in cmds if c.topic == t.key]) for t in topics]


def resolver_tema(topics, clave: str) -> Topic | None:
    clave = clave.lower()
    for t in topics:
        if clave == t.key or clave in t.aliases:
            return t
    return None


_MARCA = {"todos": "", "admin": "🔒 ", "sudo": "👑 "}


def linea_ayuda(c: Cmd) -> str:
    """'🔒 /tban <1h|30m|1d> — Ban temporal' (texto plano; quien lo muestre escapa)."""
    uso = f" {c.uso}" if c.uso else ""
    return f"{_MARCA[c.level]}/{c.name}{uso} — {c.desc}"
