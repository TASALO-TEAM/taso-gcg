"""Registro de comandos ante Telegram vía setMyCommands.

Esto es justo lo que faltaba para que /help (y el resto) aparezcan en el menú
"/" del cliente de Telegram. Importante: los comandos SIGUEN funcionando si
se escriben a mano aunque no estén registrados aquí — esto solo controla el
menú de sugerencias. Pero es la pieza que le da al bot esa sensación
"profesional" de autocompletado, y create dudas del tipo "no me funciona"
cuando en realidad el comando sí respondía, solo que no aparecía sugerido.

Se usan dos scopes (esto es lo que en el plan original se llamó "command
scopes" — resulta que SÍ se puede automatizar desde la API, no hace falta
tocar BotFather a mano como se documentó por error en una primera versión
del plan):
- BotCommandScopeDefault: lo que ve cualquier persona en cualquier chat.
- BotCommandScopeAllChatAdministrators: lo mismo + los comandos de moderación,
  visible solo para quienes Telegram ya sabe que son admins de un chat.
"""

from telegram import BotCommand, BotCommandScopeAllChatAdministrators, BotCommandScopeDefault

COMANDOS_PUBLICOS = [
    BotCommand("start", "Iniciar / info del bot"),
    BotCommand("help", "Menú de ayuda por temas"),
    BotCommand("rules", "Ver las reglas del grupo"),
    BotCommand("id", "ID del chat, o de un usuario si respondes a su mensaje"),
    BotCommand("admins", "Ver administradores del chat"),
    BotCommand("report", "Reportar un mensaje a los admins"),
    BotCommand("myfeeds", "Ver los feeds RSS configurados aquí"),
    BotCommand("notes", "Ver notas guardadas"),
    BotCommand("warns", "Ver tus avisos"),
]

COMANDOS_ADMIN = COMANDOS_PUBLICOS + [
    BotCommand("ban", "Banear (respondiendo a un mensaje)"),
    BotCommand("tban", "Ban temporal: /tban 1h"),
    BotCommand("kick", "Expulsar"),
    BotCommand("mute", "Silenciar"),
    BotCommand("tmute", "Silencio temporal: /tmute 30m"),
    BotCommand("unban", "Desbanear"),
    BotCommand("unmute", "Quitar silencio"),
    BotCommand("warn", "Dar un aviso"),
    BotCommand("promote", "Dar administrador"),
    BotCommand("demote", "Quitar administrador"),
    BotCommand("pin", "Fijar mensaje"),
    BotCommand("unpin", "Desfijar"),
    BotCommand("purge", "Borrar varios mensajes de una vez"),
    BotCommand("lock", "Bloquear tipo de contenido"),
    BotCommand("unlock", "Desbloquear"),
    BotCommand("setrules", "Configurar las reglas"),
    BotCommand("setwelcome", "Configurar la bienvenida"),
    BotCommand("addfeed", "Añadir un feed RSS"),
    BotCommand("approve", "Aprobar usuario (inmunidad)"),
    BotCommand("fban", "Ban federado en todos los chats oficiales TASALO"),
    BotCommand("connect", "Conectarse a un chat desde el PM"),
]


async def registrar_comandos(bot):
    await bot.set_my_commands(COMANDOS_PUBLICOS, scope=BotCommandScopeDefault())
    await bot.set_my_commands(COMANDOS_ADMIN, scope=BotCommandScopeAllChatAdministrators())
