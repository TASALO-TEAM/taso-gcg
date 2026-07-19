"""# Plan: Integrar taso-gcg al sistema de logs (/log de taso-bot)

Fecha: 2026-07-18

## Contexto / viabilidad (confirmado por análisis directo del código)

taso-bot expone `/log` para inspeccionar logs de bot/api/web sin SSH, vía
`src/services/log_manager.py` + `src/handlers/logs.py`. Ese módulo asume que
cada servicio hermano escribe sus logs con el contrato:

    <logs_dir>/<display_name>.log
    <logs_dir>/<display_name>-errors.log
    <logs_dir>/archive/<display_name>_<timestamp>.log

Ese contrato lo implementa `DatedRotatingFileHandler`, duplicado hoy en
taso-bot (`src/logger.py`), taso-api (`src/logging_config.py`) y taso-app
(mismo patrón, según sus tests). taso-gcg todavía NO lo tiene: usa
`utils/logger.py` con un `RotatingFileHandler` plano, sin archive/, sin log
de errores separado, con logs en `data/logs/taso_gcg.log`.

Hallazgo clave: taso-gcg centraliza TODO su logging a través de una sola
función `log(msg, level="info")`, usada en ~15 archivos (`modules/`,
`core/`, `utils/`, `scripts/`) — no hay loggers por módulo como en el bug
que se arregló en taso-bot. Por tanto, migrar el motor interno NO requiere
tocar esos call sites: `log()` se mantiene como wrapper delgado.

taso-gcg.service confirma despliegue en `/home/tasalo/taso-gcg`, sibling de
los demás repos en el VPS — la misma suposición de rutas relativas que ya
usa `config.py` de taso-bot para taso-api/taso-app aplica igual aquí.

## Decisiones ya tomadas con Ernesto
- Los logs de taso-gcg se mudan a `<repo>/logs/` (antes `data/logs/`), para
  quedar 100% consistente con bot/api/app.
- Alias en `/log`: solo `gcg` (sin sinónimos).
- Se incluye el interceptor de crashes no controlados (`sys.excepthook`) en
  esta misma tarea, por paridad con `BotLogger` de taso-bot.
"""

## Fase 1 — taso-gcg

1. **Mover logs**: `data/logs/` -> `logs/` en la raíz del repo.
   - Actualizar `.gitignore` si referencia `data/logs/`.
   - `DB_PATH` (en `core/config.py`) no se toca, sigue en `data/`.

2. **Reescribir `utils/logger.py`** tomando `taso-api/src/logging_config.py`
   como plantilla canónica (la copia más limpia de las 3 existentes):
   - Clase `DatedRotatingFileHandler` (idéntica a las otras 3 copias; se
     mantiene el comentario "se duplica en N repos, mantener en sync").
   - `SERVICE_NAME = "taso-gcg"` (con guion, no `taso_gcg`, para que el
     archivo activo se llame `taso-gcg.log` — coherente con el resto).
   - `logs/taso-gcg.log` (DEBUG+) y `logs/taso-gcg-errors.log` (ERROR+).
   - `logs/archive/` para rotados, `MAX_BYTES` y `BACKUP_COUNT` iguales a
     los otros repos (8 MB / 10 backups, ajustable).
   - Guard de pytest (`PYTEST_CURRENT_TEST` en entorno -> no crear archivos),
     igual que taso-api/taso-app.
   - Logger destino: se mantiene el logger nombrado `"taso_gcg"` que ya usa
     todo el proyecto vía `log()` (no hace falta root logger aquí, porque
     no hay problema de propagación que resolver).

3. **Mantener la función pública `log(msg, level="info")`** con la misma
   firma — internamente ahora despacha a los métodos del logger reconfigurado.
   Cero cambios en los ~15 call sites (`modules/*.py`, `core/loader.py`,
   `utils/decorators.py`, `scripts/migrar_historial_rss.py`, etc.).

4. **Interceptor de crashes**: añadir `sys.excepthook` en `utils/logger.py`
   (o en `bot.py` al arrancar) que loguee como ERROR cualquier excepción no
   controlada antes de que el proceso muera, igual que `BotLogger` en
   taso-bot. No debe interceptar `KeyboardInterrupt`.

5. Revisar `tests/conftest.py` y `tests/test_log_channel.py` (ojo: ese test
   es sobre `modules/log_channel.py`, el canal de Telegram para logs de
   moderación — un feature totalmente distinto, no tocar) para confirmar
   que ningún test asume el `RotatingFileHandler` viejo o la ruta
   `data/logs/`.

## Fase 2 — taso-bot

1. `src/config.py`: nuevo campo
   `taso_gcg_log_dir: str = Field(default="../taso-gcg/logs", ...)`.

2. `src/services/log_manager.py`:
   - `SERVICE_DISPLAY_NAMES`: añadir `"gcg": "taso-gcg"`.
   - `SERVICE_ALIASES`: añadir `"gcg": "gcg"`.
   - `_service_logs_dir()`: nueva rama
     `if service == "gcg": return os.path.normpath(os.path.join(BOT_BASE_DIR, settings.taso_gcg_log_dir))`.
   - El resto de funciones (`get_service_log_info`, `list_all_services`,
     `find_archive_by_date`, `clear_archives`) ya son genéricas por diseño
     y no necesitan cambios.

3. `src/handlers/logs.py`: actualizar `USAGE_HINT` para mencionar
   `/log gcg`. `_send_summary` ya itera `services.values()` dinámicamente,
   no requiere cambios.

4. Tests: extender `tests/test_log_manager.py` y `tests/test_log_handler.py`
   con casos para `"gcg"` (mismo patrón que los casos existentes de
   `bot`/`api`/`web`).

## Fase 3 — Verificación end-to-end

1. `py_compile` en Windows para ambos repos (sintaxis).
2. Deploy en VPS: `git pull` en taso-gcg y taso-bot, `systemctl restart`
   de ambos servicios (taso-gcg primero, para que genere logs con el
   formato nuevo antes de que taso-bot intente leerlos).
3. Provocar actividad real en taso-gcg (cualquier comando) y confirmar
   `/log gcg` desde Telegram: resumen, log activo, y — tras forzar una
   rotación o esperar una — `/log gcg <fecha>` para un archivo archivado.
4. `pytest` en el VPS (nunca local) para taso-gcg y taso-bot.

## Orden de commits
taso-gcg (Fase 1) -> taso-bot (Fase 2), como manda la convención del
proyecto (repo que expone el dato antes que el que lo consume).
