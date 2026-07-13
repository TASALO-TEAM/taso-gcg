# Plan de creación — TASALO GCG (Gestión de Canales y Grupos)

**Repo propuesto:** `TASALO-TEAM/taso-gcg`
**Fecha del plan:** 12 de julio de 2026
**Autor del análisis:** Claude, a partir de BitBreadRSS, Rose-Bot y documentación oficial de Telegram

---

## 0. Resumen de lo que se analizó

Antes de proponer nada, clonco y leí código real, no solo los READMEs:

| Fuente | Qué es realmente | Qué se aprovecha |
|---|---|---|
| `BitBreadRSS` (tuyo) | Bot RSS ya bastante maduro: PTB v20+ async, `curl_cffi` para bypass de WAF/Cloudflare, resolver de Nitter con rotación de instancias, generador de Instant View, monitor con backoff exponencial, menús inline con `ConversationHandler`. **No** está "a medias" en lógica — lo que le falta es una base de datos de verdad (usa un único JSON con lock) | Todo el `services/` (parser, resolver, monitor, iv_generator) se recicla casi intacto. Se sustituye solo la capa de persistencia. |
| `Rose-Bot` (MRK-YT) | Fork del viejo *Rose* / *Marie* — arquitectura modular por archivos en `modules/`, con SQLAlchemy 1.3 + Postgres y **PTB v11 síncrono** (2019-2020, ya obsoleto). Trae 28 módulos: admin, bans, warns, antiflood, locks, blacklist, filtros, notas, welcome, reglas, reporting, conexión, RSS propio, global bans, log de canal, etc. | Se copia el **catálogo de funciones y el modelo de permisos** (decoradores `user_admin`/`bot_admin`), no el código en sí — está en una versión de PTB que ya no existe. |
| `core.telegram.org/bots/features` | Guía oficial 2026: command scopes, `KeyboardButtonRequestChat`, deep linking (`start`/`startgroup`), rich messages (HTML/Markdown enriquecido, hasta 32.768 caracteres), privacy mode, entorno de pruebas dedicado, alertas de BotFather por bajo *response rate* | Reemplaza trucos manuales (reenviar mensajes para obtener el ID de un canal) por mecanismos nativos y más profesionales. |
| Blog Telegram — *"AI Editor, Mighty Polls..."* (31 mar 2026) y *"Smartwatch Apps..."* (11 jun 2026) | Confirman: bots pueden mandar **rich text** (tablas, colapsables, hasta 32.768 caracteres), y ahora existe el mecanismo nativo de **screening de solicitudes de ingreso** (`chat_join_request`) usado por los "AI Guardians" | Estos dos features son justo lo que necesita un bot de administración de grupos serio en 2026. |

Con eso como base, aquí va el plan.

---

## 1. Arquitectura general

**Un solo proceso, un solo bot**, no dos bots separados para RSS y administración. Motivo: menos RAM, menos overhead de systemd, menos tokens de BotFather que gestionar, y el `Application` de PTB ya soporta correr el monitor de RSS como tarea de fondo (`post_init` + `asyncio.create_task`, tal como ya hace tu `bbalert.py`).

```
taso-gcg/
├── bot.py                     # Entry point único
├── core/
│   ├── config.py              # Env vars, TOKEN, SUDO_USERS, TASALO_CHATS
│   ├── database.py            # aiosqlite + migraciones versionadas
│   └── loader.py              # Carga dinámica de módulos (LOAD/NO_LOAD)
├── modules/
│   ├── admin.py                # promote/demote/pin/purge/title/id
│   ├── bans.py                  # ban/kick/unban, tban/tmute con duración
│   ├── warns.py                 # sistema de avisos con límite configurable
│   ├── antiflood.py
│   ├── locks.py                 # restringir stickers/links/foros/etc
│   ├── blacklist.py
│   ├── filters.py                # respuestas automáticas por palabra clave
│   ├── notes.py
│   ├── welcome.py
│   ├── rules.py
│   ├── reporting.py              # botón "reportar a admins"
│   ├── join_requests.py          # screening de solicitudes de ingreso
│   ├── connection.py              # gestionar un grupo desde el PM del bot
│   ├── broadcast.py               # difusión cruzada a todos los canales TASALO
│   ├── rss/
│   │   ├── monitor.py             # heredado de BitBreadRSS/services/monitor.py
│   │   ├── parser.py              # heredado casi intacto (curl_cffi + feedparser)
│   │   ├── resolver.py            # rotación de instancias Nitter
│   │   ├── iv_generator.py
│   │   └── handlers.py            # /addfeed /myfeeds /interval etc.
│   └── stats.py                   # /stats con tablas de rich text
├── utils/
│   ├── logger.py                  # reciclado de BitBreadRSS (RotatingFileHandler)
│   ├── decorators.py               # user_admin/bot_admin/sudo_only (async)
│   └── common.py
├── data/                            # taso_gcg.db (SQLite WAL) + logs/
├── tests/                            # suite ~34+ tests, convención TASALO
├── docs/
│   ├── COMANDOS.md
│   └── ARQUITECTURA.md
├── requirements.txt
├── .env.example
└── taso-gcg.service                  # unit de systemd
```

### Stack técnico

| Pieza | Elección | Por qué |
|---|---|---|
| Framework | `python-telegram-bot` **22.x** (async, Bot API 10.0) | Ya lo usas en BitBreadRSS y en NetSeek confías en asyncio; PTB 22 soporta ya command scopes, rich text y los objetos de solicitud de chat/usuario. |
| Base de datos | **SQLite + WAL** vía `aiosqlite`, mismo patrón que NetSeek (FTS5 para búsquedas si hace falta en notas/filtros) | Cero infraestructura extra en el VPS (nada de Postgres como Rose-Bot), consumo mínimo de RAM, backups triviales (`sqlite3 .backup`). |
| Programador de tareas | `APScheduler` (AsyncIOScheduler) en vez del `while True: sleep(60)` actual | Mismo resultado, pero se integra con el resto de tareas (backups, limpieza de historial) sin *loops* manuales duplicados. |
| Requests con bypass WAF | `curl_cffi` (ya en BitBreadRSS) | Se mantiene, funciona bien. |
| Despliegue | systemd, mismo patrón que taso-bot/bbalert (`Restart=on-failure`, límite de memoria) | Consistencia con el resto del ecosistema TASALO. |
| Logs | `RotatingFileHandler` reciclado de `utils/logger.py` | Ya cumple lo que se necesita, no hay que reinventarlo. |

---

## 2. Módulo RSS — migración de BitBreadRSS

Se conserva casi todo el `services/` tal cual (parser, resolver, iv_generator son sólidos), y se cambia únicamente la capa de datos:

**Esquema SQLite propuesto:**

```sql
CREATE TABLE chats (
    id INTEGER PRIMARY KEY,
    tg_chat_id INTEGER UNIQUE NOT NULL,
    tipo TEXT CHECK(tipo IN ('group','supergroup','channel','private')),
    titulo TEXT,
    es_oficial_tasalo BOOLEAN DEFAULT 0,   -- protección extra, ver sección 4
    activo BOOLEAN DEFAULT 1,
    creado_en TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE feeds (
    id INTEGER PRIMARY KEY,
    chat_id INTEGER REFERENCES chats(id),
    url TEXT NOT NULL,               -- URL técnica resuelta
    url_original TEXT,
    titulo TEXT,
    estilo TEXT DEFAULT 'bitbread',  -- 'bitbread' | 'texto'
    plantilla TEXT,
    rhash TEXT,                      -- Instant View
    intervalo_min INTEGER DEFAULT 10,
    ultimo_check REAL DEFAULT 0,
    activo BOOLEAN DEFAULT 1,
    creado_en TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE feed_historial (
    feed_id INTEGER REFERENCES feeds(id),
    entry_hash TEXT NOT NULL,
    enviado_en TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (feed_id, entry_hash)
);

CREATE TABLE feed_stats (
    feed_id INTEGER PRIMARY KEY REFERENCES feeds(id),
    enviados INTEGER DEFAULT 0,
    errores INTEGER DEFAULT 0,
    ultimo_error TEXT
);
```

Ventajas frente al JSON actual:
- Nada de reescribir el archivo entero (`json.dump`) cada vez que se envía una noticia — solo un `INSERT`/`UPDATE` puntual, mucho más barato en I/O.
- El historial de hashes deja de vivir como lista dentro del JSON (con el límite artificial de 50 elementos) y pasa a tabla propia, con limpieza periódica vía `DELETE ... WHERE enviado_en < datetime('now','-30 days')`.
- Bloqueo real de concurrencia lo da SQLite en modo WAL, no hace falta el `asyncio.Lock` manual.

**Lo que se mantiene sin tocar (o casi):**
- `RSSParser` completo (perfiles de navegador, detección de bloqueo Cloudflare/WAF, extracción de imagen/video).
- `RSSResolver` con rotación de instancias Nitter.
- `iv_generator.py` para Instant View.
- Backoff exponencial del monitor ante errores consecutivos.

**Mejora aprovechando features nuevas de Telegram:** los mensajes de RSS pueden usar ahora **rich text** (tablas, bloques colapsables, hasta 32.768 caracteres) para plantillas más elaboradas — por ejemplo, un resumen con tabla de "fuente / hora / categoría" en vez de solo HTML plano. Se deja como plantilla opcional (`estilo = 'rich'`), sin obligar a reescribir las existentes.

---

## 3. Módulo de administración y moderación

Este es el catálogo que se saca de Rose-Bot, adaptado a async y a las necesidades reales de TASALO (no todo lo de Rose-Bot aplica — por ejemplo, *global bans* entre bots de terceros no tiene sentido si solo administras tus propios chats).

| Módulo | Comandos clave | Notas |
|---|---|---|
| **admin** | `/promote`, `/demote`, `/pin`, `/unpin`, `/purge`, `/title` | Decorador `@bot_admin` / `@user_admin` async, igual concepto que Rose-Bot pero reescrito para PTB 22. |
| **bans** | `/ban`, `/kick`, `/unban`, `/tban 1h`, `/tmute 30m` | Duración parseada con regex simple (`\d+[smhd]`). |
| **warns** | `/warn`, `/warns`, `/resetwarns`, límite configurable por chat | Guardado en tabla `warns(chat_id, user_id, cantidad, motivos)`. |
| **antiflood** | `/setflood 5` | Cuenta mensajes por usuario en ventana deslizante, mutea automático. |
| **locks** | `/lock stickers`, `/lock links`, `/locks` | Tabla `locks(chat_id, tipo, activo)`. |
| **blacklist** | `/addblacklist`, `/blacklist` | Palabra + acción (borrar / advertir / banear). |
| **filters** | `/filter`, `/filters`, `/stop` | Respuestas automáticas por palabra clave, útil para FAQ de TASALO (ej. "cómo uso el bot de tasas"). |
| **notes** | `/save`, `#nombre`, `/notes` | Snippets guardados por chat. |
| **welcome** | `/setwelcome`, `/setgoodbye` | Con botón de verificación opcional para nuevos miembros. |
| **rules** | `/rules`, `/setrules` | Reglas fijadas del grupo. |
| **reporting** | `/report`, botón "Reportar" | Notifica a admins vía mención o mensaje privado. |
| **connection** | `/connect <chat_id>` | Permite administrar un grupo/canal desde el PM del bot sin escribir en el grupo — clave para gestionar varios canales TASALO desde un solo lugar. |
| **broadcast** | `/broadcast` | Difusión cruzada a **todos** los canales/grupos TASALO marcados como oficiales de una sola vez (para anuncios del ecosistema). |

### Selección de chat sin trucos manuales

En vez de "reenvía un mensaje del canal al bot" (como pide BitBreadRSS hoy), se usa el mecanismo nativo `KeyboardButtonRequestChat` / `chat_shared`: el admin toca un botón, Telegram le muestra sus chats que cumplen el criterio (ej. "canales donde soy admin"), y el bot recibe el ID directo. Mucho más pulido y menos propenso a error.

### Screening de solicitudes de ingreso (join requests)

Telegram introdujo en junio de 2026 los "AI Guardians" — bots admin que procesan `chat_join_request` para filtrar quién entra a un grupo. No hace falta IA para aprovechar el mecanismo: se implementa un módulo `join_requests.py` que:
1. Escucha `ChatJoinRequestHandler`.
2. Opcionalmente exige responder una pregunta simple (anti-bot) antes de aprobar.
3. Aprueba/rechaza con `approve_chat_join_request` / `decline_chat_join_request`.

Esto es genuinamente nuevo y le da un plus profesional al bot frente a lo que ofrecía Rose-Bot en su época.

---

## 4. Particularidades del ecosistema TASALO

- **Chats oficiales protegidos:** los grupos/canales marcados `es_oficial_tasalo=1` solo pueden ser dados de baja del sistema o tener sus ajustes críticos (broadcast, RSS oficial) tocados por los `SUDO_USERS` (tú), no por admins normales del chat — evita que alguien con admin en un canal TASALO desconfigure algo por accidente.
- **Broadcast cruzado:** un solo comando para anunciar en todos los canales TASALO a la vez (útil para avisos de mantenimiento del `taso-api`, nuevas versiones de `taso-app`/`taso-ext`, etc.).
- **Estética Liquid Glass:** los mensajes de bienvenida, reglas y stats siguen la misma línea visual que ya usas (emojis como separadores, `JetBrains Mono` implícito en el uso de `<code>`, HTML consistente).
- **Convenciones que ya usas y se mantienen:** diccionario tipo `HELP_TOPICS`/`TOPIC_ALIASES` para el `/help`, callbacks de teclado inline con namespace (`adm_`, `rss_`, `warn_`, etc. — para no chocar entre módulos), suite de pruebas con el estándar de ~34 tests que ya manejas en taso-bot.

---

## 5. Aprovechando lo nuevo de Telegram (2026)

| Feature | Uso concreto en TASALO GCG |
|---|---|
| **Command scopes** (`BotCommandScope`) | Los comandos de administración (`/ban`, `/lock`, etc.) solo aparecen sugeridos a quienes son admin del chat; el resto ve solo comandos públicos (`/rules`, `/start`). |
| **Rich text para bots** (hasta 32.768 caracteres, tablas, colapsables) | `/stats` y `/help` con tablas reales en vez de texto plano forzado con monoespaciado. |
| **Chat/user selection nativo** | Reemplaza el flujo de "reenvía un mensaje" para vincular canales. |
| **Join request screening** | Módulo `join_requests.py`, sección 3. |
| **Deep linking (`startgroup`)** | Botón "Añadir a tu grupo" que ya preselecciona parámetros, útil si algún día se ofrece el bot a otras comunidades. |
| **Menu button personalizado** | Configurado vía BotFather para mostrar accesos directos a `/help`, `/rules`, `/stats`. |
| **Entorno de pruebas dedicado** | Se recomienda crear un bot de test aparte (con su propio token) para probar cambios sin afectar los canales TASALO reales — barato y evita sustos en producción. |
| **Alertas de BotFather (status alerts)** | Vigilar que el bot no empiece a bajar su tasa de respuesta — señal temprana de que algo se colgó en el VPS. |

---

## 6. Roadmap por fases

1. **Fase 0 — Cimientos:** repo `taso-gcg`, `config.py`, esquema SQLite + migraciones, `logger.py` reciclado, unit de systemd base.
2. **Fase 1 — Núcleo de moderación (MVP):** admin, bans, warns, locks, blacklist, filters, notes, welcome, rules, reporting. Esto ya deja el bot usable en un grupo real.
3. **Fase 2 — Multi-chat TASALO:** `connection`, selección de chat nativa (`chat_shared`), `broadcast`, marcado de chats oficiales y sus protecciones.
4. **Fase 3 — Migración RSS:** portar `parser/resolver/iv_generator/monitor` de BitBreadRSS a SQLite + APScheduler, comandos `/addfeed /myfeeds /interval /style`.
5. **Fase 4 — Features avanzadas Telegram:** command scopes por rol, `join_requests`, rich text en `/stats` y `/help`, menu button, bot de pruebas separado.
6. **Fase 5 — Endurecimiento y entrega:** suite de tests (~34+, convención TASALO), `docs/COMANDOS.md`, `docs/ARQUITECTURA.md`, despliegue final en el VPS con systemd, monitoreo de recursos (reusar el patrón de `BotCleaner` que ya tienes de otro proyecto).

---

## 7. Consumo de recursos — decisiones concretas

- Un solo proceso Python para todo (RSS + moderación), no dos bots.
- SQLite en modo WAL en vez de Postgres — cero demonio extra corriendo en el VPS.
- APScheduler con un único job de monitoreo RSS (en vez de *loops* infinitos por feed).
- Caché en memoria de la lista de admins por chat (`admins_cache`, TTL de unos minutos) para no golpear `getChatAdministrators` en cada comando de moderación.
- Logging rotativo con tamaño máximo fijo (ya está resuelto en tu `utils/logger.py`).
- `systemd` con `MemoryMax` y `Restart=on-failure`, igual que tus otros servicios.

---

## 8. Siguiente paso

Si te parece bien esta estructura, lo lógico es arrancar por la **Fase 0 + Fase 1** (cimientos + moderación básica), que es lo que te da un bot funcional y demostrable más rápido, y dejar la migración de RSS (Fase 3) para cuando el núcleo de administración ya esté probado en un grupo real.
