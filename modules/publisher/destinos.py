"""Destinos de la publicación automática.

`telegram`: manda `texto_corto` a un canal o grupo. Va en texto plano salvo que la fuente pida
`extra["parse_mode"]` (el digest TSPL va en Markdown); si Telegram rechaza el formato se
reenvía en texto plano, como hace taso-bot, para que una frase rara nunca cuele un fallo. `params = {"chat": "@tasalospl"}` o un id numérico.
El bot debe ser administrador del canal con permiso de publicar.
"""

from telegram.error import BadRequest

from modules.publisher.base import CTX, Contenido, Resultado, destino

LIMITE_TELEGRAM = 4096


def _chat(params: dict) -> str | int:
    chat = params.get("chat")
    if isinstance(chat, str):
        chat = chat.strip()
        if chat.lstrip("-").isdigit():
            return int(chat)
        if chat.startswith("@") and len(chat) > 1:
            return chat
    if isinstance(chat, int) and chat != 0:
        return chat
    raise ValueError("destino telegram sin 'chat' válido (@canal o id numérico)")


@destino("telegram")
async def destino_telegram(contenido: Contenido, d: dict, cuenta, secreto, simular: bool) -> Resultado:
    chat = _chat(d.get("params") or {})
    texto = contenido.texto_corto
    if len(texto) > LIMITE_TELEGRAM:
        texto = texto[: LIMITE_TELEGRAM - 1] + "…"
    if simular:
        return Resultado(True, simulado=True)
    bot = CTX.get("bot")
    if bot is None:
        raise RuntimeError("el bot de Telegram no está disponible")
    modo = contenido.extra.get("parse_mode")
    try:
        msg = await bot.send_message(chat, texto, **({"parse_mode": modo} if modo else {}))
    except BadRequest:
        if not modo:
            raise
        msg = await bot.send_message(chat, texto)
    url = f"https://t.me/{chat[1:]}/{msg.message_id}" if isinstance(chat, str) else None
    return Resultado(True, url=url)
