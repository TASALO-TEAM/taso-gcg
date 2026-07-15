# Comandos de taso-gcg

Convención: 🔒 = requiere ser admin del chat · 👑 = solo SUDO_USERS (equipo TASALO) · sin marca = cualquiera.

## Inicio (`start.py`)
| Comando | Descripción |
|---|---|
| `/start` | En privado: presentación del bot. En grupo: confirma que está activo |
| `/help` | Menú de ayuda por temas (con botones). `/help <tema>` va directo a un tema |

## Administración (`admin.py`)
| Comando | Descripción |
|---|---|
| `/promote` (respondiendo) | 🔒 Promueve a un usuario a admin |
| `/demote` (respondiendo) | 🔒 Quita privilegios de admin |
| `/pin` (respondiendo) | 🔒 Fija el mensaje. `/pin silent` para no notificar |
| `/unpin` | 🔒 Desfija (el mensaje respondido, o todos si no se responde a nada) |
| `/purge` (respondiendo) | 🔒 Borra desde el mensaje respondido hasta el comando |
| `/title` | Muestra nombre/ID/tipo del chat |
| `/id` | ID del chat, o del usuario si se responde a su mensaje |
| `/admins` | Lista los administradores del chat |

## Bans (`bans.py`)
| Comando | Descripción |
|---|---|
| `/ban` (respondiendo) `[motivo]` | 🔒 Banea permanentemente |
| `/tban <1h\|30m\|1d> [motivo]` | 🔒 Ban temporal |
| `/unban` (respondiendo) | 🔒 Revierte un ban |
| `/kick` (respondiendo) | 🔒 Expulsa (puede volver a entrar) |
| `/mute` / `/tmute <duración>` | 🔒 Silencia permanente / temporal |
| `/unmute` | 🔒 Restaura permisos de hablar |

## Avisos (`warns.py`)
| Comando | Descripción |
|---|---|
| `/warn` (respondiendo) `[motivo]` | 🔒 Suma un aviso; al llegar al límite aplica la acción configurada |
| `/warns` (respondiendo, opcional) | Ver avisos de un usuario (o los tuyos) |
| `/resetwarns` (respondiendo) | 🔒 Limpia los avisos de un usuario |
| `/setwarnlimit <n>` | 🔒 Cambia el límite de avisos del chat |

## AntiFlood (`antiflood.py`)
| Comando | Descripción |
|---|---|
| `/setflood <n>` | 🔒 Más de *n* mensajes en 10s dispara la acción (0 desactiva) |
| `/setfloodaction <mute\|kick\|ban>` | 🔒 Qué hacer cuando se dispara |

## Locks (`locks.py`)
| Comando | Descripción |
|---|---|
| `/lock <tipo>` / `/unlock <tipo>` | 🔒 Bloquea/desbloquea: stickers, links, forwards, photos, videos, documents, voice, polls, games, inlinebots |
| `/locks` | Ver bloqueos activos |

## Lista negra (`blacklist.py`)
| Comando | Descripción |
|---|---|
| `/addblacklist <palabra> [delete\|warn\|ban]` | 🔒 Añade palabra prohibida |
| `/rmblacklist <palabra>` | 🔒 Quita palabra |
| `/blacklist` | Ver lista negra del chat |

## Filtros (`filters.py`)
| Comando | Descripción |
|---|---|
| `/filter <disparador> <respuesta>` | 🔒 Respuesta automática cuando alguien escribe esa palabra |
| `/stop <disparador>` | 🔒 Elimina un filtro |
| `/filters` | Ver filtros activos |

## Notas (`notes.py`)
| Comando | Descripción |
|---|---|
| `/save <nombre> <contenido>` (o respondiendo) | 🔒 Guarda una nota |
| `/get <nombre>` o `#nombre` | Muestra la nota |
| `/clear <nombre>` | 🔒 Elimina una nota |
| `/notes` | Lista las notas del chat |

## Bienvenida (`welcome.py`)
| Comando | Descripción |
|---|---|
| `/setwelcome <texto>` / `/setgoodbye <texto>` | 🔒 Placeholders: `{mencion}` `{nombre}` `{chat}` |
| `/welcome on\|off` | 🔒 Activa/desactiva la bienvenida |

## Reglas (`rules.py`)
| Comando | Descripción |
|---|---|
| `/rules` | Muestra las reglas |
| `/setrules <texto>` | 🔒 Configura las reglas |

## Reportes (`reporting.py`)
| Comando | Descripción |
|---|---|
| `/report` (respondiendo) | Notifica a los admins del chat sobre ese mensaje |

## Aprobaciones (`approvals.py`)
| Comando | Descripción |
|---|---|
| `/approve` (respondiendo) `[motivo]` | 🔒 Inmuniza a un usuario ante antiflood/blacklist/locks |
| `/approval` (respondiendo) | Consulta si un usuario está aprobado |
| `/approved` | Lista los usuarios aprobados |
| `/unapprove` (respondiendo) | 🔒 Quita la aprobación |
| `/unapproveall` | 👑 Quita todas las aprobaciones del chat |

## Federación TASALO (`federation.py`)
| Comando | Descripción |
|---|---|
| `/fban` (respondiendo) `[motivo]` | 🔒 Banea en TODOS los chats oficiales TASALO a la vez |
| `/funban` (respondiendo) | 🔒 Revierte el ban en todos los chats oficiales |
| `/fbanlist` | 👑 Lista de baneados de la federación |

## Log de administración (`log_channel.py`)
| Comando | Descripción |
|---|---|
| `/setlog` (en el canal) | 👑 Vincula un canal como log; reenvía el mensaje de confirmación al grupo |
| `/unsetlog` | 🔒 Desvincula el canal de log |
| `/logchannel` | Muestra el canal de log actual y sus categorías |
| `/log <categorías>` / `/nolog <categorías>` | 🔒 Activa/desactiva categorías: settings, admin, user, automated, reports, other |

Quién manda qué a cada categoría:
- **admin** — `bans.py`: ban/tban/kick/mute/tmute/unban/unmute (comandos manuales).
- **user** — `warns.py`: un `/warn` normal que no llega al límite.
- **automated** — acciones que el bot aplica solo, sin que nadie escriba un comando:
  `antiflood.py` (flood), `blacklist.py` (palabra prohibida con `warn`/`ban`), `warns.py`
  (cuando el aviso llega al límite y dispara la sanción).

Los mensajes con 🤖 son una frase corta generada con IA (Groq) que explica el motivo de
una acción de la categoría `automated` — se manda aparte, después, y nunca decide nada;
solo aparece si el bot tiene `GROQ_API_KEY` configurada (ver `.env.example`), si no,
el log normal sigue llegando igual, solo sin esa frase extra.

## Deshabilitar comandos (`disabling.py`)
| Comando | Descripción |
|---|---|
| `/disable <cmd>` / `/enable <cmd>` | 🔒 Desactiva/reactiva un comando para usuarios normales |
| `/disabled` | Ver comandos desactivados en el chat |
| `/disableable` | Ver qué comandos se pueden desactivar |
| `/disabledel on\|off` | 🔒 Borrar el mensaje del comando desactivado |
| `/disableadmin on\|off` | 🔒 Si se activa, ni los admins pueden usar el comando desactivado |

## Solicitudes de ingreso (`join_requests.py`)
| Comando | Descripción |
|---|---|
| `/joincaptcha on\|off` | 🔒 Exige confirmar con un botón antes de aprobar el ingreso |

## Conexiones (`connection.py`)
| Comando | Descripción |
|---|---|
| `/connect <@usuario \| id_chat>` (en PM) | Gestiona un chat sin escribir ahí (requiere ser admin de ese chat). Acepta @usuario si el canal/grupo es público, o el ID si es privado |
| `/connection` | Ver info del chat conectado |
| `/disconnect` | Cierra la conexión |

## Difusión (`broadcast.py`)
| Comando | Descripción |
|---|---|
| `/broadcast <texto>` (o respondiendo) | 👑 Difunde a todos los chats oficiales TASALO |
| `/marcaroficial [id]` / `/desmarcaroficial [id]` | 👑 Marca/desmarca el chat actual (o el ID indicado) como oficial |
| `/oficiales` | 👑 Lista los chats oficiales TASALO |

## Estadísticas (`stats.py`)
| Comando | Descripción |
|---|---|
| `/stats` | 👑 Estado del bot: memoria, CPU, chats gestionados, feeds, avisos |

## RSS (`rss/handlers.py`)
| Comando | Descripción |
|---|---|
| `/addfeed` | 🔒 Inicia el asistente para añadir un feed al chat actual (o al conectado vía `/connect`) |
| `/myfeeds` | Lista los feeds del chat con botones para pausar/eliminar |
| `/setinterval <id> <min>` | 🔒 Cambia cada cuánto se revisa un feed |
| `/setstyle <id> <bitbread\|texto>` | 🔒 Cambia el formato de publicación |
| `/setrhash <id> <rhash\|none>` | 🔒 Plantilla de Instant View del feed |
| `/settranslate <id> <on\|off>` | 🔒 Traduce título/descripción con IA antes de publicar (requiere `GROQ_API_KEY`) |
| `/rmfeed <id>` | 🔒 Elimina un feed |
| `/testfeed <id>` | 🔒 Manda la noticia más reciente sin esperar el intervalo |
