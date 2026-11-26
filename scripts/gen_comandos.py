"""Genera docs/COMANDOS.md desde el registro de comandos (core/registry.py).

    python -m scripts.gen_comandos           # reescribe el archivo
    python -m scripts.gen_comandos --check   # sale con 1 si está desactualizado

El texto sale de los COMMANDS/TOPIC de cada módulo, igual que /help y el menú "/".
No se edita COMANDOS.md a mano: se cambia el módulo y se regenera
(tests/test_comandos_doc.py falla si se olvida).
"""

import importlib
import pathlib
import re
import sys

from core import registry
from core.loader import _module_names, _recoger

RAIZ = pathlib.Path(__file__).resolve().parent.parent
DESTINO = RAIZ / "docs" / "COMANDOS.md"

CABECERA = """\
# Comandos de taso-gcg

> Archivo generado por `python -m scripts.gen_comandos` desde el registro de comandos.
> No lo edites a mano: cambia `COMMANDS`/`TOPIC` en el módulo y vuelve a generarlo.

Convención: 🔒 = requiere ser admin del chat · 👑 = solo SUDO_USERS (equipo TASALO) · sin marca = cualquiera.

Nota: todo comando marcado "(respondiendo)" también acepta `@usuario` como alternativa
(ej. `/ban @fulano`), siempre que esa persona ya haya escrito al menos un mensaje en algún
chat donde esté el bot - Telegram no deja resolver un @usuario al que el bot nunca le haya
visto un mensaje, así que si no funciona no es un bug, es que el bot todavía no lo conoce.
"""


def recoger() -> tuple[list, list, dict[str, str]]:
    """(cmds, temas, archivo_de_cada_tema) leyendo los módulos como lo hace el loader."""
    cmds, temas, archivo = [], [], {}
    for nombre in [*_module_names(), "rss.handlers"]:
        mod = importlib.import_module(f"modules.{nombre}")
        antes = len(temas)
        _recoger(mod, cmds, temas)
        for t in temas[antes:]:
            archivo[t.key] = nombre.replace(".", "/") + ".py"
    return cmds, temas, archivo


def _celda(texto: str) -> str:
    return texto.replace("|", "\\|")


def _fila(c: registry.Cmd) -> str:
    uso = f" {c.uso}" if c.uso else ""
    alias = "".join(f" / `/{a}`" for a in c.alias)
    marca = registry._MARCA[c.level]
    return f"| {marca}`/{c.name}{_celda(uso)}`{alias} | {_celda(c.desc)} |"


def _titulo(t: registry.Topic) -> str:
    return re.sub(r"^[^\w]+", "", t.title)  # sin el emoji del botón de /help


def generar() -> str:
    from modules.start import _ordenados  # mismo orden que /help

    cmds, temas, archivo = recoger()
    registry.validar(cmds, temas)
    partes = [CABECERA]
    for t in _ordenados(temas):
        filas = [_fila(c) for c in cmds if c.topic == t.key]
        partes.append(f"\n## {_titulo(t)} (`{archivo[t.key]}`)\n| Comando | Descripción |\n|---|---|\n" + "\n".join(filas) + "\n")
        if t.nota:
            partes.append(f"\n{t.nota}\n")
    return "".join(partes)


def main(argv: list[str]) -> int:
    texto = generar()
    if "--check" in argv:
        actual = DESTINO.read_text(encoding="utf-8") if DESTINO.exists() else ""
        if actual != texto:
            print("docs/COMANDOS.md está desactualizado: ejecuta python -m scripts.gen_comandos")
            return 1
        return 0
    DESTINO.write_text(texto, encoding="utf-8", newline="\n")
    print(f"escrito {DESTINO.relative_to(RAIZ)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
