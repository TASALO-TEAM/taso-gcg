"""Paridad entre los CommandHandler de cada módulo y su COMMANDS (core/registry.py).

Si añades un CommandHandler sin declararlo en COMMANDS (o al revés), este test falla:
es lo que evita que el menú "/", /help y COMANDOS.md se desincronicen otra vez.
"""

import ast
import importlib
import pathlib

import pytest

from core import registry

RAIZ = pathlib.Path(__file__).resolve().parent.parent
# Handlers internos que no son comandos "de usuario" (fallback de una conversación).
INTERNOS = {"cancel"}


def _modulos() -> list[str]:
    nombres = [p.stem for p in (RAIZ / "modules").glob("*.py") if not p.stem.startswith("_")]
    return sorted(nombres) + ["rss.handlers"]


def _ruta(nombre: str) -> pathlib.Path:
    return RAIZ / "modules" / (nombre.replace(".", "/") + ".py")


def _nombres_en_codigo(nombre: str) -> set[str]:
    """Nombres de comando pasados a CommandHandler(...), leídos con ast (sin ejecutar register)."""
    encontrados: set[str] = set()
    for n in ast.walk(ast.parse(_ruta(nombre).read_text(encoding="utf-8"))):
        if not (isinstance(n, ast.Call) and getattr(n.func, "id", getattr(n.func, "attr", "")) == "CommandHandler"):
            continue
        arg = n.args[0]
        if isinstance(arg, ast.Constant):
            encontrados.add(arg.value)
        elif isinstance(arg, (ast.List, ast.Tuple)):
            encontrados.update(e.value for e in arg.elts)
        else:
            pytest.fail(f"{nombre}: CommandHandler con nombre dinámico ({ast.unparse(arg)}); usa literales")
    return encontrados - INTERNOS


def _declarados(nombre: str) -> set[str]:
    mod = importlib.import_module(f"modules.{nombre}")
    return {n for c in getattr(mod, "COMMANDS", ()) for n in (c.name, *c.alias)}


@pytest.mark.parametrize("nombre", _modulos())
def test_commandhandlers_y_commands_coinciden(nombre):
    assert _nombres_en_codigo(nombre) == _declarados(nombre)


def _registro_completo():
    cmds, topics = [], []
    for nombre in _modulos():
        mod = importlib.import_module(f"modules.{nombre}")
        cmds.extend(getattr(mod, "COMMANDS", ()))
        if getattr(mod, "TOPIC", None) is not None:
            topics.append(mod.TOPIC)
    return cmds, topics


def test_registro_completo_es_valido():
    cmds, topics = _registro_completo()
    registry.validar(cmds, topics)


def test_temas_unicos_y_sin_alias_repetidos():
    _, topics = _registro_completo()
    claves = [t.key for t in topics]
    assert len(claves) == len(set(claves)), "clave de tema repetida"
    entradas = claves + [a for t in topics for a in t.aliases]
    repetidas = {e for e in entradas if entradas.count(e) > 1}
    assert not repetidas, f"alias que apuntan a dos temas: {repetidas}"


def test_menu_basico_en_todos_los_scopes_de_chat():
    cmds, _ = _registro_completo()
    for scope in registry.SCOPES:
        nombres = [n for n, _ in registry.menu_para(cmds, scope)]
        assert {"start", "help"} <= set(nombres), scope
    # Un usuario normal en un grupo no debe ver comandos de moderación en su menú.
    default = {n for n, _ in registry.menu_para(cmds, "default")}
    assert not default & {"ban", "mute", "addfeed", "myfeeds", "fban"}
