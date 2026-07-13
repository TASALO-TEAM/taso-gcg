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
3. Aplicar los **command scopes** vía BotFather (`/setcommands` con scope de admin vs
   default) — es un paso manual de configuración, no de código.
4. Command `/help` todavía no existe como tal — no se portó el patrón
   `HELP_TOPICS`/`TOPIC_ALIASES` de taso-bot. Cada módulo responde con su propio
   mensaje de uso cuando faltan argumentos, pero no hay un `/help` centralizado.

   **[RESUELTO]** — Ersus reportó que `/start` no hacía nada (cierto: nunca se
   implementó, con 21 módulos de funcionalidad se pasó por alto el más básico de
   todos). Se añadió `modules/start.py` con `/start` (bienvenida distinta en PM
   vs grupo) y `/help` completo con el patrón `HELP_TOPICS`/`TOPIC_ALIASES` igual
   que taso-bot — resumen con botones inline + `/help <tema>` directo. Ahora son
   22 módulos, 93 handlers. Tests siguen en 23/23.
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
