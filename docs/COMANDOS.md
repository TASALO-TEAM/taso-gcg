# Comandos de taso-gcg

> Archivo generado por `python -m scripts.gen_comandos` desde el registro de comandos.
> No lo edites a mano: cambia `COMMANDS`/`TOPIC` en el módulo y vuelve a generarlo.

Convención: 🔒 = requiere ser admin del chat · 👑 = solo SUDO_USERS (equipo TASALO) · sin marca = cualquiera.

Nota: todo comando marcado "(respondiendo)" también acepta `@usuario` como alternativa
(ej. `/ban @fulano`), siempre que esa persona ya haya escrito al menos un mensaje en algún
chat donde esté el bot - Telegram no deja resolver un @usuario al que el bot nunca le haya
visto un mensaje, así que si no funciona no es un bug, es que el bot todavía no lo conoce.

## Inicio (`start.py`)
| Comando | Descripción |
|---|---|
| `/menu` | Menú con botones |
| `/start` | Iniciar / info del bot |
| `/help [tema]` | Menú de ayuda por temas |

## Administración (`admin.py`)
| Comando | Descripción |
|---|---|
| 🔒 `/promote` | Dar administrador (respondiendo) |
| 🔒 `/demote` | Quitar administrador (respondiendo) |
| 🔒 `/pin [silent]` | Fijar mensaje (respondiendo) |
| 🔒 `/unpin` | Desfijar (todos si no respondes a nada) |
| 🔒 `/purge` | Borra desde el mensaje respondido hasta ahora |
| `/title` | Nombre, ID y tipo del chat |
| `/id [@usuario\|id]` | ID del chat, o de un usuario si respondes a su mensaje |
| `/admins` | Ver administradores del chat |

## Bans y silencios (`bans.py`)
| Comando | Descripción |
|---|---|
| 🔒 `/ban [motivo]` | Banear (respondiendo a un mensaje) |
| 🔒 `/tban <1h\|30m\|1d> [motivo]` | Ban temporal |
| 🔒 `/unban` | Desbanear |
| 🔒 `/kick` | Expulsar (puede volver a entrar) |
| 🔒 `/mute` | Silenciar |
| 🔒 `/tmute <1h\|30m\|1d>` | Silencio temporal |
| 🔒 `/unmute` | Quitar silencio |

## Avisos (`warns.py`)
| Comando | Descripción |
|---|---|
| 🔒 `/warn [motivo]` | Dar un aviso |
| `/warns` | Ver tus avisos (o los de quien respondes) |
| 🔒 `/resetwarns` | Limpiar los avisos de un usuario |
| 🔒 `/setwarnlimit <n>` | Límite de avisos antes de sancionar |

## AntiFlood (`antiflood.py`)
| Comando | Descripción |
|---|---|
| 🔒 `/setflood <n>` | Más de n mensajes en 10s dispara la acción (0 = off) |
| 🔒 `/setfloodaction <mute\|kick\|ban>` | Acción al detectar flood |

## Bloqueos de contenido (`locks.py`)
| Comando | Descripción |
|---|---|
| 🔒 `/lock <tipo>` | Bloquear tipo de contenido |
| 🔒 `/unlock <tipo>` | Desbloquear tipo de contenido |
| `/locks` | Ver bloqueos activos |

Tipos: stickers, links, forwards, photos, videos, documents, voice, polls, games, inlinebots

## Lista negra (`blacklist.py`)
| Comando | Descripción |
|---|---|
| 🔒 `/addblacklist <palabra> [delete\|warn\|ban]` | Añadir palabra prohibida |
| 🔒 `/rmblacklist <palabra>` | Quitar palabra de la lista negra |
| `/blacklist` | Ver la lista negra del chat |

## Filtros (auto-respuestas) (`filters.py`)
| Comando | Descripción |
|---|---|
| 🔒 `/filter <palabra> <respuesta>` | Respuesta automática a una palabra |
| 🔒 `/stop <palabra>` | Eliminar un filtro |
| `/filters` | Ver filtros activos |

## Notas (`notes.py`)
| Comando | Descripción |
|---|---|
| 🔒 `/save <nombre> <contenido>` | Guardar una nota (o respondiendo) |
| `/get <nombre>` | Mostrar una nota (también #nombre) |
| 🔒 `/clear <nombre>` | Eliminar una nota |
| `/notes` | Ver notas guardadas |

## Bienvenida (`welcome.py`)
| Comando | Descripción |
|---|---|
| 🔒 `/setwelcome <texto>` | Configurar la bienvenida |
| 🔒 `/setgoodbye <texto>` | Configurar la despedida |
| 🔒 `/welcome on\|off` | Activar o desactivar la bienvenida |

Placeholders: {mencion} {nombre} {chat}

## Reglas (`rules.py`)
| Comando | Descripción |
|---|---|
| `/rules` | Ver las reglas del grupo |
| 🔒 `/setrules <texto>` | Configurar las reglas |

## Reportes (`reporting.py`)
| Comando | Descripción |
|---|---|
| `/report` / `/reportar` | Reportar un mensaje a los admins (respondiendo) |

## Aprobaciones (`approvals.py`)
| Comando | Descripción |
|---|---|
| 🔒 `/approve [motivo]` | Aprobar usuario (inmunidad) |
| `/approval` | Consultar si un usuario está aprobado |
| `/approved` | Listar usuarios aprobados |
| 🔒 `/unapprove` | Quitar la aprobación |
| 👑 `/unapproveall` | Quitar todas las aprobaciones del chat |

Un usuario aprobado es inmune a antiflood, lista negra y locks.

## Federación TASALO (`federation.py`)
| Comando | Descripción |
|---|---|
| 🔒 `/fban [motivo]` | Ban federado en todos los chats oficiales TASALO |
| 🔒 `/funban` | Revertir el ban federado |
| 👑 `/fbanlist` | Lista de baneados de la federación |

## Log de administración (`log_channel.py`)
| Comando | Descripción |
|---|---|
| 👑 `/setlog` | Vincular el canal de log (enviar en el canal) |
| 🔒 `/unsetlog` | Desvincular el canal de log |
| `/logchannel` | Ver el canal de log y sus categorías |
| 🔒 `/log <categorías>` | Activar categorías de log |
| 🔒 `/nolog <categorías>` | Desactivar categorías de log |

Categorías: settings, admin, user, automated, reports, other.
• admin: tus /ban /mute /kick manuales, etc.
• automated: acciones que el bot aplica solo (antiflood, lista negra, límite de avisos).
Si ves un mensaje con 🤖, es una frase corta generada con IA (Groq) que explica el motivo de una acción automática: nunca decide nada, solo la explica después de aplicada. Sin GROQ_API_KEY esos mensajes no aparecen (el log normal sí).

## Deshabilitar comandos (`disabling.py`)
| Comando | Descripción |
|---|---|
| 🔒 `/disable <cmd>` | Desactivar un comando para usuarios normales |
| 🔒 `/enable <cmd>` | Reactivar un comando |
| `/disabled` | Ver comandos desactivados |
| `/disableable` | Ver qué comandos se pueden desactivar |
| 🔒 `/disabledel on\|off` | Borrar el mensaje del comando desactivado |
| 🔒 `/disableadmin on\|off` | Aplicar la desactivación también a admins |

## Solicitudes de ingreso (`join_requests.py`)
| Comando | Descripción |
|---|---|
| 🔒 `/joincaptcha on\|off` | Exigir botón de confirmación al ingresar |

## Conexión remota (`connection.py`)
| Comando | Descripción |
|---|---|
| `/connect <@usuario\|id_chat>` | Gestionar un chat desde el privado |
| `/connection [n]` | Ver y cambiar tus chats conectados |
| `/disconnect` | Cerrar la conexión activa |

## Difusión TASALO (`broadcast.py`)
| Comando | Descripción |
|---|---|
| 👑 `/broadcast <texto>` | Difundir a todos los chats oficiales (o respondiendo) |
| 👑 `/marcaroficial [id]` | Marcar un chat como oficial |
| 👑 `/desmarcaroficial [id]` | Desmarcar un chat como oficial |
| 👑 `/oficiales` | Listar los chats oficiales |

## Estadísticas (`stats.py`)
| Comando | Descripción |
|---|---|
| 👑 `/stats` | Estado del bot: memoria, chats, feeds |

## Publicación automática (`pub.py`)
| Comando | Descripción |
|---|---|
| 👑 `/pub` | Panel de publicación automática (horas, destinos, pruebas) |
| 👑 `/pubdest <id_trabajo> <@canal\|id>` | Añadir un canal de Telegram como destino de un trabajo |

Solo para el equipo TASALO y por privado. Empieza en modo prueba: arma lo que publicaría sin enviar nada hasta que lo desactives en el panel.

## RSS (`rss/handlers.py`)
| Comando | Descripción |
|---|---|
| 🔒 `/addfeed` | Añadir un feed RSS |
| 🔒 `/myfeeds` | Ver y gestionar los feeds de este chat |
| 🔒 `/setinterval <#feed> <min>` | Cada cuántos minutos se revisa un feed |
| 🔒 `/setstyle <#feed> <bitbread\|texto\|social>` | Formato de publicación |
| 🔒 `/setrhash <#feed> <rhash\|none>` | Plantilla de Instant View |
| 🔒 `/settranslate <#feed> <on\|off>` | Traducir con IA antes de publicar (requiere Groq) |
| 🔒 `/rmfeed <#feed>` | Eliminar un feed |
| 🔒 `/testfeed <#feed>` | Enviar ahora la noticia más reciente |

Acepta RSS genérico, perfiles de X/Twitter, de Bluesky y cuentas de Nostr (npub, nombre@dominio). El #n de cada feed es propio del chat.
