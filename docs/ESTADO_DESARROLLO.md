# Estado de desarrollo — taso-gcg

> Este archivo existe para que, si el desarrollo se interrumpe (se acaban los tokens de una
> sesión, cambio de conversación, etc.), cualquiera —Claude en una sesión nueva o Ersus—
> pueda entender YA MISMO qué está hecho, qué falta y qué decisiones ya se tomaron,
> sin tener que releer todo el código desde cero.
>
> Regla de oro para continuar: **actualiza este archivo cada vez que termines un módulo.**

Referencia: `docs/plan-taso-gcg.md` tiene el plan original completo (arquitectura, roadmap en 6 fases).

---

## Decisiones ya tomadas (no re-discutir, solo ejecutar)

1. **Un solo proceso**, RSS + moderación en el mismo bot (`bot.py`).
2. **Base de datos: SQLite local** (`data/taso_gcg.db`, modo WAL), vía `aiosqlite`. No Supabase,
   no Postgres — decisión justificada con Ersus: los datos de este bot son pequeños
   (config de chats, warns, notas, feeds) y necesitan chequeos instantáneos
   (locks/antiflood se evalúan en cada mensaje). Supabase se queda reservado para taso-api.
3. **python-telegram-bot 22.x** (async, Bot API 10.0).
4. **APScheduler (AsyncIOScheduler)** para el monitor RSS, no un `while True: sleep()`.
5. **Carga dinámica de módulos**: cada archivo en `modules/` expone una función
   `def register(application, sudo_users) -> None` que añade sus propios handlers.
   `core/loader.py` recorre el paquete e importa todo (con soporte `LOAD`/`NO_LOAD` por env).
6. **Permisos**: decoradores async en `utils/decorators.py` — `@user_admin`, `@bot_admin`,
   `@sudo_only`. Igual concepto que Rose-Bot pero reescrito para PTB async, con caché de
   admins en tabla `admins_cache` (TTL configurable) para no golpear `getChatAdministrators`
   en cada comando.
7. **Chats "oficiales TASALO"** (`chats.es_oficial_tasalo=1`): solo los `SUDO_USERS` pueden
   tocar su config crítica (broadcast, RSS oficial, baja del sistema).
8. **Convención de callbacks inline**: namespaced por módulo (`adm:`, `bans:`, `warn:`,
   `rss:`, `note:`, etc.) para que no choquen entre módulos — mismo criterio que usas en
   taso-bot.
9. **Nomenclatura de columnas y tablas en español**, igual que el resto del código que
   Ersus ya tiene (BitBreadRSS, DataLab).

---

## Estructura del proyecto (ver árbol real con `find . -type f`)

```
taso-gcg/
├── bot.py
├── core/
│   ├── config.py
│   ├── database.py
│   └── loader.py
├── modules/
│   ├── admin.py
│   ├── bans.py
│   ├── warns.py
│   ├── antiflood.py
│   ├── locks.py
│   ├── blacklist.py
│   ├── filters.py
│   ├── notes.py
│   ├── welcome.py
│   ├── rules.py
│   ├── reporting.py
│   ├── connection.py
│   ├── broadcast.py
│   ├── approvals.py
│   ├── federation.py
│   ├── log_channel.py
│   ├── disabling.py
│   ├── join_requests.py
│   ├── stats.py
│   ├── chat_tracker.py
│   └── rss/
│       ├── parser.py
│       ├── resolver.py
│       ├── iv_generator.py
│       ├── monitor.py
│       └── handlers.py
├── utils/
│   ├── logger.py
│   ├── decorators.py
│   └── common.py
├── data/ (vacío en el repo, se crea el .db en runtime)
├── tests/
├── docs/
│   ├── plan-taso-gcg.md
│   ├── README.md
│   └── COMANDOS.md
├── requirements.txt
├── .env.example
├── .gitignore
└── taso-gcg.service
```

## Fuentes adicionales consultadas durante el desarrollo

- **https://missrose.org/docs/** (documentación oficial y actualizada de Rose, no el
  fork MRK-YT que se revisó primero) — de aquí salieron 4 módulos que no estaban en el
  plan original: `approvals`, `federation`, `log_channel`, `disabling`. Ver detalle abajo.

## Progreso por fase (ver plan original)

- [x] **Fase 0 — Cimientos**: config, database (schema completo), logger, decorators, loader, bot.py
- [x] **Fase 1 — Núcleo de moderación**: admin, bans, warns, antiflood, locks, blacklist, filters, notes, welcome, rules, reporting
- [x] **Fase 1.5 — Añadido tras revisar missrose.org/docs**:
  - `approvals.py`: usuarios de confianza inmunes a antiflood/blacklist/locks (no a bans manuales)
  - `federation.py`: **"federación TASALO" simplificada** — en vez del sistema genérico
    multi-federación de Rose (pensado para miles de comunidades independientes), se
    implementó una única federación implícita = todos los chats `es_oficial_tasalo=1`.
    `/fban` sincroniza el ban en todos esos chats a la vez; tabla `fed_bans` + enforcement
    automático si el usuario intenta reentrar a un chat oficial.
  - `log_channel.py`: canal de auditoría de acciones, flujo `/setlog` + reenvío (igual a Rose)
  - `disabling.py`: `/disable /enable /disabled /disableable /disabledel /disableadmin`,
    intercepta comandos en `group=-3` con `ApplicationHandlerStop`
- [x] **Fase 2 — Multi-chat TASALO**: chat_tracker (registro automático + detección de oficiales), connection, broadcast
- [x] **Fase 3 — RSS**: parser/resolver/iv_generator portados de BitBreadRSS (iv_generator adaptado
  para usar la tabla `iv_templates` en vez del JSON externo), monitor reescrito sobre SQLite +
  APScheduler, handlers con ConversationHandler para `/addfeed`
- [x] **Fase 4 — Features Telegram 2026**: join_requests (screening), stats, federación, log de
  admin, deshabilitar comandos. Command scopes vía BotFather documentados como pendiente manual
  (no se puede automatizar desde el propio bot).
- [x] **Fase 5 — Endurecimiento (primera vuelta)**: 23 tests pasando (`pytest tests/ -v`), los 21
  módulos + bot.py importan y arrancan sin errores (verificado con `ApplicationBuilder` real +
  `load_all()` dentro de un event loop, igual que ocurre en producción). docs/README/COMANDOS.md
  escritos.
- [x] **Fase 6 — IA vía Groq (traducción RSS + contexto de moderación)**: ver sección dedicada
  más abajo, "Sesión: IA con Groq".

## Verificación real hecha en esta sesión (no solo "se ve bien", se corrió)

```
pytest tests/ -v          -> 23 passed
python -c "import <cada módulo>"  -> 0 errores en los 21 módulos + bot.py
ApplicationBuilder().build() + load_all(app) dentro de asyncio.run()
  -> 21 módulos cargados, 90 handlers registrados, scheduler RSS arrancado
```

Bug real encontrado y corregido gracias a los tests: `get_or_create_chat` actualizaba el
título en la DB pero devolvía la fila vieja (sin el título nuevo) — quedó corregido y
cubierto por `test_ensure_chat_actualiza_titulo_si_cambia`.

## Qué falta / próximos pasos si se retoma

1. **Probar contra un bot real de Telegram** (con token de verdad) — todo lo de arriba
   verifica que el código es correcto y arranca, pero nadie ha mandado un `/ban` real
   todavía. Recomendado: crear un bot de pruebas con @BotFather antes de tocar los
   chats oficiales de TASALO.
2. Ampliar la suite de tests más allá de database/common/decorators — faltan tests de
   integración de los módulos de moderación en sí (warns.py, antiflood.py, etc.), que
   requieren mockear más profundamente la API de Telegram.
3. ~~Aplicar los **command scopes** vía BotFather~~ — **[RESUELTO]**, ver punto 7 más
   abajo: se automatizó por completo con `setMyCommands` + scopes, no hacía falta
   tocar BotFather a mano como se pensó originalmente.
4. Command `/help` todavía no existe como tal — no se portó el patrón
   `HELP_TOPICS`/`TOPIC_ALIASES` de taso-bot. Cada módulo responde con su propio
   mensaje de uso cuando faltan argumentos, pero no hay un `/help` centralizado.

   **[RESUELTO]** — Ersus reportó que `/start` no hacía nada (cierto: nunca se
   implementó, con 21 módulos de funcionalidad se pasó por alto el más básico de
   todos). Se añadió `modules/start.py` con `/start` (bienvenida distinta en PM
   vs grupo) y `/help` completo con el patrón `HELP_TOPICS`/`TOPIC_ALIASES` igual
   que taso-bot — resumen con botones inline + `/help <tema>` directo. Ahora son
   22 módulos, 93 handlers. Tests siguen en 23/23.

7. **[RESUELTO]** Ersus reportó "el comando /help no funciona" ya con `/start`
   arreglado. `help_cmd` en sí funcionaba perfecto en aislamiento (se probó
   directamente con un update simulado, cero excepciones). La causa real: **nunca
   se llamó a `setMyCommands`**, así que ningún comando aparecía en el menú "/"
   del cliente de Telegram — se podían escribir a mano y funcionaban, pero no
   había autocompletado, que es lo primero que la gente prueba. Se añadió
   `core/commands_menu.py` con dos listas (`COMANDOS_PUBLICOS` / `COMANDOS_ADMIN`)
   y `registrar_comandos(bot)`, llamado desde `post_init` en `bot.py`. Usa
   `BotCommandScopeDefault` + `BotCommandScopeAllChatAdministrators` — esto es,
   de hecho, la implementación real de los "command scopes" que el plan original
   había documentado por error como "paso manual en BotFather"; sí se puede
   automatizar por completo desde la API, como quedó demostrado aquí.
   Verificado con `set_my_commands` real (mock) → 2 llamadas, 9 comandos en
   default y 30 en el scope de admins, todos dentro de los límites de Telegram
   (32 car. nombre / 256 car. descripción / 100 comandos por scope).

8. **[RESUELTO]** Ersus reportó que al reiniciar el bot "pierde de manera visual"
   los canales conectados (los feeds RSS seguían funcionando bien, pero
   `/connection` se comportaba como si nunca te hubieras conectado). Causa: la
   conexión se guardaba en `context.user_data`, que vive solo en memoria y PTB
   la borra por completo en cada reinicio del proceso — nunca se configuró
   ninguna capa de persistencia para eso. Se movió a SQLite (tabla `connections`,
   `user_id` -> `tg_chat_id`), consistente con el resto del proyecto (un solo
   punto de persistencia, nada de introducir `PicklePersistence` como capa
   aparte). De paso, se aprovechó para resolver el segundo pedido: `/connect`
   ahora acepta `@usuario` del canal/grupo además del ID numérico (solo hace
   falta el ID si el chat es privado sin username público). Se añadieron 3 tests
   nuevos de la persistencia (incluyendo uno que simula explícitamente el
   "reinicio" al no depender de nada en memoria). Total: 26 tests pasando.
5. Del catálogo de MissRose que se dejó fuera a propósito (ver más abajo): AntiRaid,
   captcha con imagen/matemática, exportar/importar configuración, topics/foros.
6. `taso-gcg.service` no se ha probado en el VPS real — es una plantilla basada en el
   patrón que ya usas en otros servicios TASALO, ajustar `User=`/rutas antes de activarlo.

## Del catálogo de MissRose (missrose.org/docs) que se dejó fuera a propósito

- Blocklist modes avanzados (Rose separa "blocklist" de "blacklist" con más matices de
  acción) — nuestro `blacklist.py` ya cubre delete/warn/ban, que es lo esencial.
- **AntiRaid** (ban temporal masivo ante entradas sospechosas en ráfaga) — no implementado,
  buen candidato para una v2 si TASALO empieza a sufrir raids de spam.
- **CAPTCHA "de verdad"** (imagen/matemática) — `join_requests.py` ya cubre el caso de
  solicitudes de ingreso con botón de confirmación; un captcha más robusto (para grupos
  sin "solicitud para unirse" activada) quedaría como mejora futura.
- Exportar/importar configuración entre chats — útil si se crean chats TASALO nuevos
  seguido, no urgente con el número de chats actual.
- Topics (foros) y Bot-to-Bot — nicho, no aplican al caso de uso actual de TASALO.

## Cómo correrlo localmente para probar

```bash
cd taso-gcg
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # editar TOKEN, SUDO_USERS
python bot.py
```

## Sesión: IA con Groq (traducción RSS + contexto de moderación)

Origen: Ersus preguntó si valía la pena "llevar el bot al siguiente nivel" con IA,
inspirado en Groq de bbchat (**no** de taso-bot — se verificó el repo de taso-bot y no
usa Groq para nada, solo pandas/tradingview-ta para /ta /graf /p; esa confusión quedó
aclarada con él). Se hizo primero un análisis de viabilidad antes de tocar código:

- **Traducción de RSS**: viable y de bajo riesgo — aprobado e implementado.
- **IA decidiendo bans en tiempo real**: **rechazado** — rompería "robusto/seguro"
  (latencia en el camino crítico de moderación, riesgo de prompt injection vía texto
  de usuarios, dependencia externa en una ruta de seguridad).
- **IA explicando después de una acción ya tomada** (asíncrono, fire-and-forget, nunca
  bloquea ni decide) — aprobado e implementado como término medio.

### Piezas nuevas

- `core/ai_client.py`: cliente Groq genérico y compartido (`ask_groq`), httpx + tenacity,
  degradación controlada — si `GROQ_API_KEY` no está, devuelve `None` y quien llama decide
  el fallback. Nunca propaga excepciones hacia arriba.
- `modules/rss/translator.py`: traduce `title`/`description` de un feed marcado con
  `traducir=1`. No detecta idioma por entrada (el idioma de un feed no cambia) — flag
  estático por feed vía `/settranslate <id> <on|off>`. Fallback silencioso: si Groq falla,
  se publica el entry original sin traducir.
- `modules/moderation_context.py`: `explicar_en_log(context, tg_chat_id, categoria, evento)`.
  Se llama DESPUÉS de que antiflood/blacklist/warns ya aplicaron su acción determinística de
  siempre. Agenda una `asyncio.Task` (con referencia guardada en un `set` para que el GC no
  se la coma a medias) que le pide a Groq una frase corta y la manda al log — todo esto nunca
  bloquea la acción de moderación real. `evento` solo lleva métricas/etiquetas ya controladas
  (conteos, nombre de acción, palabra que un ADMIN puso en la blacklist) — nunca texto libre
  de un usuario cualquiera, precisamente para no abrir una puerta de prompt injection.
- `core/database.py`: columna `feeds.traducir` + método `_migrate()` (ALTER TABLE seguro e
  idempotente, corre en cada arranque, no rompe la DB ya desplegada en el VPS).

### Módulos existentes conectados a `log_channel.enviar_log` (antes nadie lo llamaba)

Se descubrió que `log_channel.py` (el flujo `/setlog`, categorías `settings/admin/user/
automated/reports/other`) estaba completo pero **ningún módulo lo usaba** — el canal de log
no recibía nada aún. Se conectó:

- `antiflood.py`: log + contexto IA (categoría `automated`) en cada acción automática.
- `blacklist.py`: log siempre; contexto IA solo si la acción fue `warn`/`ban` (un simple
  `delete` no lo amerita). Categoría `automated`.
- `warns.py`: si el aviso llega al límite y dispara la sanción automática → log + contexto
  IA (`automated`). Si es solo un `/warn` manual con motivo del admin → log plano sin IA
  (`user`), porque el admin ya explicó el motivo él mismo.
- `bans.py`: log plano (sin IA) en ban/tban/kick/mute/tmute/unban/unmute, categoría `admin`
  — son comandos manuales, el admin ya sabe por qué los usó, la IA no aporta nada ahí.

### Verificación real hecha en esta sesión

```
pytest tests/ -q                          -> 26 passed (los mismos de antes, nada roto)
Migración de DB probada contra una DB "vieja" simulada (sin la columna nueva)
  -> columna agregada, feed existente preservado, segundo init() no la duplica
translator.py probado con 3 casos: Groq caído / JSON inválido / éxito
  -> los 3 caen bien, nunca rompe el envío del RSS
moderation_context.py probado con 3 casos: éxito / Groq caído / Groq lanza excepción
  -> explicar_en_log() retorna en <1ms en los 3 (fire-and-forget real, no bloquea)
```

### Qué falta / próximos pasos si se retoma

1. Probar en el VPS real con `GROQ_API_KEY` puesto — todo lo de arriba es correcto en
   aislamiento, pero nadie ha visto un mensaje real de "🤖 ..." aparecer en un canal de
   log de verdad todavía.
2. Posible mejora futura (no pedida, no implementada): un comando `/analizar` (respondiendo
   a un mensaje) para que un admin pida la opinión de la IA en un caso gris puntual —
   síncrono porque lo dispara un humano a propósito, la decisión la sigue tomando el admin.

---

## Sesión: fix /setlog (no vinculaba canales), @usuario en menciones, /id "pro"

Origen: Ersus reportó tres problemas relacionados con identificar usuarios/chats:

1. **`/setlog` no dejaba añadir canales.** Causa real: `_detectar_reenvio_setlog` exigía
   `message.reply_to_message` en el mensaje reenviado — algo que un reenvío normal de
   Telegram NUNCA trae (reenviar y responder son dos acciones distintas e incompatibles en
   el cliente), así que la condición jamás se cumplía. El dato correcto ya venía disponible
   en `message.forward_origin` (`MessageOriginChannel.chat` + `.message_id`), que además
   permite validar que el reenvío viene del mismo canal que pidió el `/setlog` (antes no
   había ningún chequeo de eso). Fix en `modules/log_channel.py`.

2. **`@usuario` en menciones no funcionaba para nada.** `extract_target_user` solo miraba
   entidades `text_mention` (mención por nombre visible, sin @username — ahí Telegram sí
   manda el `user_id` embebido). Una mención `@usuario` en texto plano es una entidad
   `mention` distinta, donde Telegram NO manda ningún `user_id`, solo el texto — y ese caso
   ni se intentaba resolver. Como la Bot API no deja buscar un usuario cualquiera por
   username salvo que el bot ya lo "conozca" de antes (restricción real de la plataforma,
   no un bug nuestro), se agregó una tabla `users` (caché local: id/username/nombre/
   is_premium/language_code) que se alimenta en `chat_tracker.py` con cada mensaje que pasa
   por el bot. `extract_target_user` (ahora async) y la nueva `resolve_username` resuelven
   primero contra esa caché y, si no está, intentan `get_chat("@usuario")` como último
   recurso. Afecta a `/ban /tban /unban /kick /mute /tmute /warn /resetwarns /promote
   /demote /fban /funban /approve /unapprove` — todos ahora aceptan `@usuario` además de
   responder al mensaje, siempre que esa persona ya haya escrito antes en algún chat con
   el bot presente.

3. **`/id` en canales no servía y el formato era muy básico.** Antes asumía
   `reply_to_message.from_user` siempre presente — en un post de canal no hay usuario real
   detrás (solo `sender_chat`), así que reventaba en silencio. Reescrito en
   `modules/admin.py` con salida en bloques 👤/💬 (formato pedido por Ersus):
   - Sin argumento ni reply: tu info (`👤 You`) + el chat actual (`💬 Origin chat`).
   - Respondiendo a un mensaje: info de quien lo mandó (usuario o canal-como-remitente), y
     si ese mensaje a su vez es un reenvío, un segundo bloque con el origen real —
     así es como se saca el ID de un canal: reenviar un post suyo al grupo y responder
     `/id` a ese reenvío.
   - `/id @usuario` o `/id <id>`: resuelve usuario o chat/canal directamente.
   - `created: ~ M/AAAA (?)`: estimado de fecha de creación de cuenta a partir del
     user_id, por interpolación entre puntos de referencia conocidos
     (`utils/common.py::estimate_account_creation`). Técnica estándar de este tipo de
     bots (igual que "Creation Date"/"GetIDs Bot") — Telegram no expone esto por API,
     así que **siempre** es aproximado, nunca un dato oficial (de ahí el "(?)" fijo).
     Los checkpoints se pueden ajustar en esa misma tabla si Ersus junta datos propios
     más precisos más adelante.

### Verificación real hecha en esta sesión

```
pytest tests/ -q               -> 48 passed (26 previos + 22 nuevos, nada roto)
ApplicationBuilder + load_all() dentro de un event loop real
  -> 22 módulos, 94 handlers (igual que antes del cambio, comparado contra el zip original)
Import de todos los modules/*.py uno por uno -> sin errores
```

Tests nuevos: `test_database.py` (caché de usuarios), `test_common.py` (extract_target_user
con los 3 casos — reply/text_mention/mention resuelto por caché o API —, y
estimate_account_creation), `test_log_channel.py` (el fix del reenvío, incluyendo el caso
de seguridad de canal-distinto-al-esperado), `test_admin_id.py` (formato de los bloques y
el caso base de `/id`).

### Qué falta / próximos pasos si se retoma

1. El estimado de fecha de creación es una aproximación basada en checkpoints públicos de
   crecimiento de Telegram, no en datos verificados uno por uno — si en algún momento Ersus
   junta ejemplos reales (cuenta con fecha de creación conocida + su ID), vale la pena
   afinar `_CHECKPOINTS_CREACION` en `utils/common.py`.
2. La caché de `users` solo se llena desde grupos (`chat_tracker.py` está filtrado a
   `ChatType.GROUPS`) — si en algún momento hace falta resolver @usuario también a partir
   de mensajes en privado con el bot, habría que ampliar ese filtro.

---

## Sesión: numeración de feeds por chat + `/connection` con lista de conectados

Origen: Ersus reportó dos fricciones de uso para admins:

1. **Numeración de feeds sin límite.** `feeds.id` es un PK global `AUTOINCREMENT`
   compartido por todos los chats; al borrar un feed, ese id quedaba "quemado" para
   siempre (SQLite no reutiliza autoincrement), así que en un chat con rotación de feeds
   los números en `/myfeeds` crecían sin control (#1, #2... #47) aunque solo hubiera 3
   feeds activos. Decisión tomada con Ersus: numeración **por chat**, no global — se
   añadió `feeds.numero_local` (nueva columna, `UNIQUE(chat_id, numero_local)`,
   migración con backfill para feeds ya existentes) y un helper
   `db.siguiente_numero_local(chat_id)` que rellena el primer hueco libre de ese chat al
   crear un feed. El id interno real (PK, usado en FKs de `feed_historial`/`feed_stats`)
   no se tocó. `/myfeeds`, `/setinterval`, `/setstyle`, `/settranslate`, `/setrhash`,
   `/rmfeed`, `/testfeed` pasan a recibir ese `#numero_local` (no el id crudo) y lo
   traducen resolviendo primero el chat actual/conectado — de paso cierra un permiso
   implícito demasiado amplio que tenían: antes aceptaban cualquier id de cualquier chat
   sin verificar que fuera el suyo.
2. **`/connection` no listaba nada, solo mostraba el chat activo.** Si Ersus administra
   varios chats, tenía que recordar o volver a teclear el id/@usuario cada vez que
   quería cambiar de uno a otro. Se añadió tabla `connection_history`
   (`user_id`, `tg_chat_id`, `titulo`, `ultimo_uso`), que `/connect` llena en cada
   conexión exitosa. `/connection` sin argumentos ahora lista esos chats ordenados por
   uso reciente con botones, marca "✅" el activo y lo destaca arriba; `/connection <n>`
   o el botón selecciona esa posición, fija la conexión y muestra el mismo detalle de
   siempre (extraído a `_render_detalle_conexion` para no duplicarlo).

Plan completo: `C:\Users\ernes\Documents\tasalo\docs\plans\2026-07-21-admin-ux-feeds-connection.md`.

### Verificación real hecha en esta sesión

```
py -3 -m py_compile core/database.py modules/connection.py modules/rss/handlers.py
  -> OK, sin errores
pytest local no corre (falta aiosqlite en el venv de Windows, limitación conocida) —
  pendiente correrlo en el VPS tras el deploy
```

### Qué falta / próximos pasos si se retoma

1. Pruebas manuales en el chat de pruebas: crear/borrar varios feeds y confirmar que
   rellena huecos; conectar 2-3 chats con `/connect` y revisar que `/connection` los
   liste bien con el indicador correcto.
2. `git push` + deploy en el VPS (`git pull` + restart) — ahí sí correr `pytest` completo.
3. Commiteado en local: `86ceec7` (feature) y `bdd6773` (mover el plan al directorio
   compartido). `version.txt` pasó de `0.1.8` a `0.1.9`.

### Bugfix post-deploy (mismo día): `/connection` no mostraba nada

Ersus reportó que tras desplegar v0.1.9, `/connection` no respondía (ni error ni lista) y
el log no mostraba nada raro. Dos bugs reales encontrados al revisar:

1. **`connection_history` nueva quedaba vacía** para quien ya estaba conectado antes del
   deploy (tabla vieja `connections` no se migró). Corregido: `Database.init()` ahora
   corre `_backfill_connection_history()` en cada arranque (INSERT OR IGNORE, así no pisa
   historial ya poblado) — copia lo que haya en `connections` (con el título vía JOIN a
   `chats`) hacia `connection_history` si aún no está ahí.
2. **HTML sin escapar**: `_render_detalle_conexion`, `_render_lista_conexiones` y el
   mensaje de `/connect` interpolaban el título del chat directo en un texto con
   `parse_mode=HTML` — si el título tenía `<`, `>` o `&`, Telegram rechazaba el mensaje
   completo (`Can't parse entities`) y el usuario no veía nada, sin traceback en el log de
   archivo (el error de Telegram no pasaba por el logger custom). Mismo patrón de bug ya
   corregido antes en `/help`/`/warns`. Corregido con `html.escape()` en las 4 interpolaciones.

`version.txt`: `0.1.9` → `0.1.10`. Verificado con `py -3 -m py_compile` sobre
`core/database.py` y `modules/connection.py`. Pendiente: push + deploy, y confirmar con
Ersus que `/connection` ya funciona (sobre todo si su conexión venía de antes del deploy).

### Bugfix post-deploy #2 (mismo día): seguía sin responder tras v0.1.10

Ersus confirmó que probaba `/connection` en el PM del bot y seguía sin pasar nada — ni
siquiera el mensaje de "no estás conectado". El log del bot mostraba que la migración de
`connection_history` sí había corrido bien, así que el problema no era ese.

Causa raíz encontrada al revisar `bot.py`: **nunca se registró un
`application.add_error_handler()`**. Sin eso, si un handler revienta con una excepción,
python-telegram-bot la atrapa internamente y la loguea con SU PROPIO logger estándar
(`telegram.ext._application`) — que no pasa por nuestro logger custom
(`utils/logger.py` usa un logger separado `taso_gcg` con `propagate = False`) y termina
solo en stderr/journal del servicio, invisible en `logs/taso-gcg.log`. Por eso el comando
fallaba "en silencio" y el log de archivo no mostraba nada raro: probablemente sí estaba
reventando, solo que en un canal que nadie estaba mirando.

Corregido: `bot.py` ahora registra `on_error()` vía `add_error_handler`, que loguea el
traceback completo con nuestro `log(..., "error")` (así sí llega a
`logs/taso-gcg-errors.log`) y además manda un aviso corto a `LOG_CHAT_ID` si está
configurado. Esto no arregla el bug original de `/connection` en sí — sirve para que la
*próxima* vez que algo falle dentro de un handler, se pueda ver el traceback real en vez
de tener que adivinar.

`version.txt`: `0.1.10` → `0.1.11`.

**Pendiente crítico**: esta sesión se cortó por una desconexión del conector de ejecución
de comandos (Desktop Commander) — el cambio de `bot.py` y el bump de versión quedaron
escritos en disco pero SIN compilar, SIN commitear y SIN pushear/desplegar. Antes de
seguir, hace falta:
1. `py -3 -m py_compile bot.py`
2. `git add bot.py version.txt docs/ESTADO_DESARROLLO.md && git commit` (mensaje sugerido:
   `fix(bot): registrar error handler global para no perder tracebacks silenciosos`)
3. `git push`
4. Deploy en el VPS (`git pull` + restart del servicio)
5. Reproducir `/connection` de nuevo en el PM y mandar el log fresco — con el error
   handler puesto, si sigue sin responder, esta vez el traceback real va a estar en
   `logs/taso-gcg-errors.log`.

### Bugfix post-deploy #3: encontrado el bug real gracias al error handler

Con `on_error` ya desplegado, la traza completa apareció en el log:
`modules/connection.py`, línea 172, `connection_cmd` → `telegram.error.BadRequest:
Can't parse entities: unsupported start tag "n" at byte offset 124`.

Causa: bug tonto en el texto literal de `_render_lista_conexiones` —
`"...Toca uno o usa /connection <n>."` — con `parse_mode=HTML`, Telegram intenta
parsear `<n>` como una etiqueta HTML inexistente y rechaza el mensaje COMPLETO (no
solo esa parte). No tenía nada que ver con el escape de títulos que se había arreglado
antes (ese fix seguía siendo válido y necesario, solo que este otro bug pegaba primero
en el flujo más común: `/connection` sin argumentos). Corregido: se reescribió esa
frase sin ángulos ("...usa /connection seguido del número (ej. /connection 1).").

De paso, se aplicó `html.escape()` también a los títulos de feeds RSS (externos, vienen
del feed original) en `modules/rss/handlers.py` (`addfeed_url`, `addfeed_style`,
`myfeeds_cmd`) — mismo patrón de riesgo latente: un feed con `<` en el título habría
roto esos mensajes exactamente igual, y con el error handler ahora si eso pasa al menos
va a quedar registrado en vez de fallar en silencio.

`version.txt`: `0.1.11` → `0.1.12`.

**Pendiente crítico (igual que la sesión anterior)**: el conector de ejecución de
comandos volvió a caerse a media tarea. Cambios escritos en disco, SIN compilar, SIN
commitear, SIN pushear/desplegar. Antes de seguir:
1. `py -3 -m py_compile modules\connection.py modules\rss\handlers.py`
2. `git add modules/connection.py modules/rss/handlers.py version.txt docs/ESTADO_DESARROLLO.md`
3. `git commit -m "fix(connection,rss): escapar <n> literal en /connection y titulos externos en HTML"`
4. `git push`
5. Deploy en el VPS (`git pull` + restart) y probar `/connection` de nuevo — esta vez sí
   debería mostrar la lista sin reventar.

### Ajuste de alcance (mismo día): `/connection` solo mostraba el historial de /connect

Ersus probó y el mensaje ya no revienta, pero solo le mostraba el chat activo — él
administra varios chats y esperaba verlos todos, no solo los que había usado antes con
`/connect` desde el PM (que es un flujo aparte, pensado para gestionar un chat sin
escribir ahí; la mayoría de sus chats los administra directamente en el grupo, sin pasar
por `/connect` nunca).

Corregido: nuevo método `db.get_chats_administrados(user_id)` que junta dos fuentes —
todos los chats donde aparece en `admins_cache` (la misma caché que ya usan los comandos
de moderación, se llena sola la primera vez que se corre un comando admin en ese chat) más
lo que haya en `connection_history`. `_render_lista_conexiones` y la selección por
posición (`/connection <n>`) pasan a usar esta lista completa en vez de solo el historial.

**Limitación conocida, documentada en el docstring del método**: un chat recién añadido
donde nunca corrió un comando de moderación (admins_cache vacía ahí) y que tampoco se usó
con `/connect` no va a aparecer hasta que ocurra una de esas dos cosas una vez. Si a Ersus
le falta algún chat en la lista, el atajo es correr cualquier comando de admin ahí una vez
(o `/connect <id>` una sola vez) y ya queda registrado para siempre.

`version.txt`: `0.1.12` → `0.1.13`.

**Pendiente crítico (tercera vez, mismo motivo)**: el conector de ejecución de comandos
sigue caído. Compilar/commitear/pushear pendiente:
1. `py -3 -m py_compile core\database.py modules\connection.py`
2. `git add core/database.py modules/connection.py version.txt docs/ESTADO_DESARROLLO.md`
3. `git commit -m "feat(connection): listar todos los chats administrados, no solo el historial de /connect"`
4. `git push`
5. Deploy en el VPS (`git pull` + restart) y probar `/connection` — debería listar todos
   los chats donde Ersus es admin.
