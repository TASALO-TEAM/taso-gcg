"""Carga dinámica de módulos.

Cada archivo en modules/ (que no empiece con _) debe exponer:
    def register(application, sudo_users) -> None

register() es responsable de añadir sus propios handlers al Application.
Esto reemplaza el `dispatcher.add_handler()` global de Rose-Bot por algo
más explícito y fácil de testear módulo por módulo.

Convención LOAD/NO_LOAD igual que Rose-Bot:
- Si LOAD está vacío, se cargan todos los módulos encontrados.
- NO_LOAD siempre tiene prioridad (si un módulo está en ambas listas, no se carga).
"""

import importlib
import pkgutil

import modules
from core.config import LOAD, NO_LOAD, SUDO_USERS
from utils.logger import log

# Submódulos que no son "módulos de comandos" per se (paquete rss/ se carga aparte)
_SKIP = {"rss"}


def _module_names() -> list[str]:
    nombres = []
    for _, name, is_pkg in pkgutil.iter_modules(modules.__path__):
        if name.startswith("_") or name in _SKIP:
            continue
        nombres.append(name)
    return sorted(nombres)


def load_all(application):
    disponibles = _module_names()
    a_cargar = LOAD if LOAD else disponibles

    cargados = []
    for name in a_cargar:
        if name in NO_LOAD:
            log(f"Módulo '{name}' omitido (NO_LOAD)")
            continue
        if name not in disponibles:
            log(f"Módulo '{name}' listado en LOAD pero no existe en modules/", "warning")
            continue
        try:
            mod = importlib.import_module(f"modules.{name}")
            if not hasattr(mod, "register"):
                log(f"Módulo '{name}' no expone register(), se omite", "warning")
                continue
            mod.register(application, SUDO_USERS)
            cargados.append(name)
        except Exception as e:
            log(f"Error cargando módulo '{name}': {e}", "error")

    # RSS se carga como paquete propio (tiene su propio ciclo: handlers + monitor)
    if "rss" not in NO_LOAD:
        try:
            from modules.rss import handlers as rss_handlers
            rss_handlers.register(application, SUDO_USERS)
            cargados.append("rss")
        except Exception as e:
            log(f"Error cargando módulo RSS: {e}", "error")

    log(f"Módulos cargados ({len(cargados)}): {', '.join(cargados)}")
    return cargados
