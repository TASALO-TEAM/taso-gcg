# Rediseño de /setlog — vinculación por @username en vez de reenvío desde el canal

## Diagnóstico

`/setlog` está roto por diseño, no por un typo. El comando está decorado con
`@sudo_only`, que depende de `update.effective_user`. Cuando un mensaje se
publica **como post de canal**, Telegram no manda el campo `from` — el post
aparece como del canal, no de un usuario — así que `effective_user` es
siempre `None` ahí. `sudo_only` nunca puede pasar dentro de un canal,
sin importar quién lo mande. El flujo actual (mandar `/setlog` en el canal,
luego reenviar la confirmación al grupo) es estructuralmente inviable.

## Diseño nuevo

`/setlog @canalusername`, mandado por un sudo en el **grupo** que se quiere
vincular, o en **privado** con el bot (en este último caso, indicando
también el grupo — ver "Casos y validaciones").

Elimina por completo:
- `_pendientes_setlog` (dict en memoria)
- `_detectar_reenvio_setlog` (el MessageHandler de FORWARDED)
- El MessageOriginChannel y todo el flujo de reenvío

## Flujo

1. Sudo manda `/setlog @canalusername` en el grupo a vincular.
2. El bot resuelve el canal con `context.bot.get_chat("@canalusername")`.
   - Si falla (no existe / no es canal / bot no tiene acceso): error claro.
3. El bot verifica que **él mismo** sea admin en ese canal
   (`get_chat_member(canal.id, bot.id)`).
   - Si no lo es: "Necesito ser admin en @canalusername para usarlo como log."
4. Si todo OK: guarda `log_channels(chat_id=grupo, log_chat_tg_id=canal.id)`
   igual que ahora (mismo INSERT ... ON CONFLICT).
5. Confirma en el grupo: "✅ Este grupo ahora reporta a @canalusername."

### Caso privado con el bot
`/setlog @canalusername` en privado no tiene un "grupo actual" implícito.
Opciones para decidir en la implementación (a confirmar contigo si hace
falta, si no, se toma la más simple):
- Requerir un segundo argumento: `/setlog @canalusername @o_id_del_grupo`.
- O no soportar privado en la v1 y dejarlo solo para el grupo (más simple,
  cambia lo mínimo respecto a lo que pediste). **Propuesta: empezar con
  esto y añadir el caso privado después si hace falta.**

## Cambios de código (taso-gcg)

`modules/log_channel.py`:
- Reescribir `setlog_cmd`: quitar el chequeo `chat.type != "channel"`,
  leer `context.args[0]` como username del canal, resolver con
  `get_chat`, verificar admin del bot, hacer el INSERT/UPDATE directo.
- Borrar `_pendientes_setlog`, `_detectar_reenvio_setlog`.
- `register()`: quitar el `MessageHandler(filters.FORWARDED & ...)`.
- Actualizar el docstring del módulo (ya no es el flujo estilo Rose).

Sin cambios en `taso-api` — la tabla `log_channels` no cambia de forma.

## Validación

- `py -3 -m py_compile modules/log_channel.py` en Windows.
- Prueba manual: `/setlog @canaldeejemplo` en un grupo de prueba, con el
  bot admin y sin ser admin en el canal (para ver los dos mensajes de
  error) y luego con todo correcto.

## Fuera de alcance

- No se toca `unsetlog`, `logchannel`, `log`/`nolog` (categorías) —
  siguen funcionando igual, ya que dependen de `user_admin`, no de
  `sudo_only`, y no del chat siendo canal.
