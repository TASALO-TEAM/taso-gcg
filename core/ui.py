"""Piezas comunes de la interfaz por botones.

- cb()/parse(): callback_data v2 `ns:arg:arg` (≤64 bytes). Los prefijos actuales
  (`help:`, `conn:`, `rss:`, `joinreq:`) ya son v2 y siguen funcionando.
- guard_callback: UN solo sitio para permisos de botones. Responde la query ANTES
  de ejecutar el panel (en vez de al final, tras llamadas de red), comprueba los
  permisos de quien PULSA sobre el chat OBJETIVO (no sobre quien abrió el menú),
  descarta el doble toque, avisa si el botón caducó e ignora "message is not modified".
- fila_nav/paginar/fila_paginas/mostrar: lo mínimo para pantallas navegables.

Regla: un handler decorado con guard_callback NO llama a query.answer(): ya lo hizo la guardia.
"""

import functools
import re
import time

from telegram import InaccessibleMessage, InlineKeyboardButton
from telegram.constants import ParseMode
from telegram.error import BadRequest

from core.config import SUDO_USERS
from utils.decorators import is_user_admin

SEP = ":"
MAX_BYTES = 64  # límite de Telegram para callback_data
_NS = re.compile(r"[a-z0-9]+")
ANTIREBOTE_S = 1.0
_ultimo: dict[tuple[int, str], float] = {}


def cb(ns: str, *args) -> str:
    """Arma un callback v2. ValueError si no es válido o pasa de 64 bytes."""
    if not _NS.fullmatch(ns):
        raise ValueError(f"namespace inválido: {ns!r}")
    partes = [str(a) for a in args]
    if any(SEP in p for p in partes):
        raise ValueError("un argumento no puede contener ':'")
    data = SEP.join((ns, *partes))
    if len(data.encode()) > MAX_BYTES:
        raise ValueError(f"callback_data de {len(data.encode())} bytes (máximo {MAX_BYTES})")
    return data


def parse(data: str) -> tuple[str, tuple[str, ...]] | None:
    """(namespace, args) o None si `data` no tiene forma v2."""
    ns, sep, resto = data.partition(SEP)
    if not _NS.fullmatch(ns):
        return None
    return ns, (tuple(resto.split(SEP)) if sep else ())


def _ahora() -> float:
    return time.monotonic()


def _es_rebote(user_id: int, data: str) -> bool:
    ahora = _ahora()
    if len(_ultimo) > 1000:  # poda: solo se conserva lo reciente
        for k in [k for k, t in _ultimo.items() if ahora - t > ANTIREBOTE_S]:
            del _ultimo[k]
    previo = _ultimo.get((user_id, data))
    _ultimo[(user_id, data)] = ahora
    return previo is not None and ahora - previo < ANTIREBOTE_S


def guard_callback(nivel: str = "todos", objetivo=None):
    """Decorador de handlers de CallbackQuery.

    nivel: "todos" | "admin" | "sudo".
    objetivo: `async (update, context) -> tg_chat_id | None` con el chat sobre el que se
    actúa (p.ej. el conectado, o el dueño de un feed). Por defecto, el chat del mensaje.
    Devolver None = no hay objetivo válido → se rechaza.
    """
    def deco(func):
        @functools.wraps(func)
        async def wrapper(update, context, *args, **kwargs):
            q = update.callback_query
            if q is None:
                return
            if q.message is None or isinstance(q.message, InaccessibleMessage):
                await q.answer("Este botón caducó. Vuelve a abrir el menú.", show_alert=True)
                return
            if _es_rebote(q.from_user.id, q.data or ""):
                await q.answer()
                return

            permitido = True
            if nivel == "sudo":
                permitido = q.from_user.id in SUDO_USERS
            elif nivel == "admin":
                chat_id = await objetivo(update, context) if objetivo else q.message.chat.id
                permitido = chat_id is not None and await is_user_admin(context, chat_id, q.from_user.id)
            if not permitido:
                await q.answer("🚫 Solo para administradores.", show_alert=True)
                return

            await q.answer()
            try:
                return await func(update, context, *args, **kwargs)
            except BadRequest as e:
                if "message is not modified" in str(e).lower():
                    return
                raise
        return wrapper
    return deco


# --- Navegación y paginación -------------------------------------------------

def fila_nav(atras: str | None = None, inicio: str | None = "menu:home") -> list[InlineKeyboardButton]:
    """Fila inferior de toda pantalla: ⬅️ Atrás (si hay) y 🏠 Inicio (si hay)."""
    fila = []
    if atras:
        fila.append(InlineKeyboardButton("⬅️ Atrás", callback_data=atras))
    if inicio:
        fila.append(InlineKeyboardButton("🏠 Inicio", callback_data=inicio))
    return fila


def paginar(items, pagina: int, por_pagina: int = 5):
    """(items de la página, página normalizada, total de páginas). Siempre ≥1 página."""
    items = list(items)
    total = max(1, -(-len(items) // por_pagina))
    pagina = min(max(pagina, 0), total - 1)
    return items[pagina * por_pagina:(pagina + 1) * por_pagina], pagina, total


def fila_paginas(ns: str, pagina: int, total: int, *args) -> list[InlineKeyboardButton]:
    """◀ 2/5 ▶ ; vacía si solo hay una página. El callback es `ns:<args>:<página>`."""
    if total <= 1:
        return []
    fila = []
    if pagina > 0:
        fila.append(InlineKeyboardButton("◀", callback_data=cb(ns, *args, pagina - 1)))
    fila.append(InlineKeyboardButton(f"{pagina + 1}/{total}", callback_data=cb(ns, *args, pagina)))
    if pagina < total - 1:
        fila.append(InlineKeyboardButton("▶", callback_data=cb(ns, *args, pagina + 1)))
    return fila


async def mostrar(update, texto: str, teclado=None, parse_mode: str = ParseMode.HTML):
    """Edita el mensaje del botón; si no se puede (borrado, muy viejo), manda uno nuevo."""
    q = update.callback_query
    if q is not None:
        try:
            await q.edit_message_text(texto, parse_mode=parse_mode, reply_markup=teclado)
            return
        except BadRequest as e:
            if "message is not modified" in str(e).lower():
                return
    await update.effective_chat.send_message(texto, parse_mode=parse_mode, reply_markup=teclado)
