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
