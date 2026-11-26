import pytest
from telegram import (
    BotCommandScopeAllChatAdministrators,
    BotCommandScopeAllPrivateChats,
    BotCommandScopeChat,
    BotCommandScopeDefault,
)

from core import registry
from core.commands_menu import registrar_comandos
from core.registry import Cmd

CMDS = (
    Cmd("start", "Inicio", menu=True),
    Cmd("ban", "Banea", level="admin", ambito="grupo", menu=True),
    Cmd("connect", "Conectar", ambito="privado", menu=True),
    Cmd("stats", "Estado", level="sudo", menu=True),
)


class FakeBot:
    def __init__(self, falla_en=()):
        self.llamadas = []
        self.falla_en = set(falla_en)

    async def set_my_commands(self, commands, scope=None):
        if isinstance(scope, BotCommandScopeChat) and scope.chat_id in self.falla_en:
            raise RuntimeError("Chat not found")
        self.llamadas.append((scope, [(c.command, c.description) for c in commands]))


def _lista(bot, tipo, chat_id=None):
    for scope, comandos in bot.llamadas:
        if type(scope) is tipo and (chat_id is None or scope.chat_id == chat_id):
            return comandos
    raise AssertionError(f"no se registró {tipo.__name__}")


@pytest.mark.asyncio
async def test_registra_cada_scope_con_su_lista_completa():
    bot = FakeBot()
    await registrar_comandos(bot, CMDS, sudo_users=[111])
    assert _lista(bot, BotCommandScopeDefault) == registry.menu_para(CMDS, "default")
    assert _lista(bot, BotCommandScopeAllPrivateChats) == registry.menu_para(CMDS, "private")
    assert _lista(bot, BotCommandScopeAllChatAdministrators) == registry.menu_para(CMDS, "admins")
    assert _lista(bot, BotCommandScopeChat, 111) == registry.menu_para(CMDS, "sudo")


@pytest.mark.asyncio
async def test_un_sudo_que_falla_no_tumba_a_los_demas():
    bot = FakeBot(falla_en={111})
    await registrar_comandos(bot, CMDS, sudo_users=[111, 222])  # no debe lanzar
    assert _lista(bot, BotCommandScopeChat, 222)
    with pytest.raises(AssertionError):
        _lista(bot, BotCommandScopeChat, 111)


@pytest.mark.asyncio
async def test_sin_sudo_solo_hay_tres_scopes_generales():
    bot = FakeBot()
    await registrar_comandos(bot, CMDS, sudo_users=[])
    assert len(bot.llamadas) == 3
