"""Registro de comandos ante Telegram vía setMyCommands, generado desde el registro.

El menú "/" ya no se mantiene a mano: sale de `Cmd(menu=True)` de cada módulo
(core/registry.py). Los comandos SIGUEN funcionando si se escriben a mano aunque
no estén en el menú; esto solo controla las sugerencias.

Cada scope de Telegram SUSTITUYE al anterior (no se suman), por eso cada lista se
arma completa. Precedencia de Telegram (de más a menos específico):
- BotCommandScopeChat (un SUDO en su privado: ve además lo de gestión TASALO)
- BotCommandScopeAllChatAdministrators / BotCommandScopeAllPrivateChats
- BotCommandScopeDefault (cualquiera en cualquier chat)
"""

from telegram import (
    BotCommand,
    BotCommandScopeAllChatAdministrators,
    BotCommandScopeAllPrivateChats,
    BotCommandScopeChat,
    BotCommandScopeDefault,
)

from core import registry
from core.config import SUDO_USERS
from utils.logger import log

_SCOPES_GENERALES = (
    ("default", BotCommandScopeDefault),
    ("private", BotCommandScopeAllPrivateChats),
    ("admins", BotCommandScopeAllChatAdministrators),
)


def _botcommands(cmds, scope: str) -> list[BotCommand]:
    return [BotCommand(nombre, desc) for nombre, desc in registry.menu_para(cmds, scope)]


async def registrar_comandos(bot, cmds, sudo_users=SUDO_USERS):
    """Publica los cuatro menús. Un SUDO que nunca abrió el bot da error de Telegram:
    se anota y se sigue con el resto (no debe tumbar el arranque ni a los demás)."""
    for scope, tg_scope in _SCOPES_GENERALES:
        await bot.set_my_commands(_botcommands(cmds, scope), scope=tg_scope())

    menu_sudo = _botcommands(cmds, "sudo")
    for uid in sudo_users:
        try:
            await bot.set_my_commands(menu_sudo, scope=BotCommandScopeChat(chat_id=uid))
        except Exception as e:
            log(f"Menú SUDO no publicado para {uid} (¿nunca abrió el bot?): {e}", "warning")
