# Plan: mejoras UX admin — numeración de feeds por chat + lista de conexiones

Fecha: 2026-07-21
Repo: taso-gcg
Objetivo: simplificar el manejo del bot para admins, filosofía "tan simple
como sea posible" sin perder funciones. Dos mejoras independientes, mismo plan.

## Parte 1 — Numeración de feeds por chat (rellenar huecos)

### Problema actual
`feeds.id` es un PK global `AUTOINCREMENT` compartido por todos los chats.
Al borrar un feed su id queda "quemado" para siempre (SQLite no reutiliza
autoincrement), así que en un chat con mucha rotación de feeds los números
visibles en `/myfeeds` crecen sin límite (#1, #2, #3... #47) aunque solo
haya 3 feeds activos. Además ese mismo id es FK de `feed_historial` y
`feed_stats`, así que no se puede simplemente "renumerar" sin romper esas
relaciones.

### Decisión (confirmada con Ernesto)
Numeración **por chat**, no global. Cada grupo/canal tiene su propio
contador visible 1,2,3... independiente de los demás chats. El id interno
(PK real, usado en FKs) no se toca — se añade una columna nueva puramente
para mostrar/referenciar desde los comandos.

### Cambios de esquema (`core/database.py`)
- Nueva columna `feeds.numero_local INTEGER` + `UNIQUE(chat_id, numero_local)`.
- Migración en `_migrate()` (mismo patrón ya usado para `feeds.traducir`):
  agregar la columna, y luego backfill: por cada `chat_id`, asignar
  `numero_local` 1,2,3... a los feeds existentes ordenados por `id` asc.
  Es un solo `UPDATE` con `ROW_NUMBER()` (SQLite moderno lo soporta) o un
  loop en Python si preferimos no depender de window functions.

### Lógica de "primer hueco libre" (al crear un feed)
Nuevo helper en `core/database.py`, p.ej. `siguiente_numero_local(chat_id)`:
```sql
SELECT MIN(t1.numero_local + 1) AS libre
FROM feeds t1
WHERE t1.chat_id = ?
  AND NOT EXISTS (
    SELECT 1 FROM feeds t2
    WHERE t2.chat_id = t1.chat_id AND t2.numero_local = t1.numero_local + 1
  )
```
Si no hay filas para ese chat, devuelve 1. Se usa en `addfeed_style()` al
hacer el INSERT, y se guarda junto al resto de columnas.

### Comandos a actualizar (`modules/rss/handlers.py`)
Todos estos hoy reciben el id "en crudo" por texto y afectan cualquier
feed de cualquier chat sin verificar que sea el suyo — eso también se
corrige de paso (hoy es un permiso implícito demasiado amplio: un admin
de un chat podría, sin querer, modificar un feed de otro chat con el
número correcto adivinado):
- `/setinterval <n> <min>`, `/setstyle <n> <estilo>`, `/setrhash <n> <rhash>`,
  `/rmfeed <n>`, `/testfeed <n>` — pasan a resolver primero el chat con
  `_resolver_chat_destino()` (igual que `/addfeed`/`/myfeeds`) y luego
  traducir `numero_local` → id interno con
  `SELECT id FROM feeds WHERE chat_id = ? AND numero_local = ?`.
  Si no existe ese número en ese chat → mensaje de error claro.
- `/myfeeds`: mostrar `numero_local` en vez de `id` en el texto (`#{n}`).
  Los botones inline (toggle/estilo/eliminar) siguen usando el id interno
  en `callback_data` — no hace falta traducir ahí porque no lo escribe el
  usuario, solo lo pulsa.
- `testfeed`/monitor (`modules/rss/monitor.py`, `force_check`) sigue
  operando con el id interno sin cambios; solo cambia qué recibe el
  comando desde el usuario.

### No afecta
`feed_historial`, `feed_stats`, el scheduler y el resto del sistema RSS
siguen usando el id interno tal cual — cero cambios ahí.

## Parte 2 — `/connection` como lista de conectados + indicador de activo

### Problema actual
Hoy solo existe una conexión "viva" por usuario (tabla `connections`,
`user_id` PK). `/connect <id|@usuario>` sobrescribe la anterior sin dejar
rastro, y `/connection` (sin args) únicamente muestra el detalle del chat
conectado en ese momento — si administras varios chats, hay que recordar
o volver a teclear el id/username cada vez que quieres cambiar.

### Cambios de esquema
Nueva tabla `connection_history`:
```sql
CREATE TABLE IF NOT EXISTS connection_history (
    user_id INTEGER NOT NULL,
    tg_chat_id INTEGER NOT NULL,
    titulo TEXT,
    ultimo_uso TEXT DEFAULT (datetime('now')),
    PRIMARY KEY (user_id, tg_chat_id)
);
```
Se llena/actualiza (`INSERT ... ON CONFLICT DO UPDATE ultimo_uso`) cada vez
que `/connect` conecta con éxito — así queda un historial de chats a los
que el usuario ya se conectó antes, ordenable por uso reciente.

### Comportamiento nuevo de `/connection`
- **Sin argumentos**: lista los chats del historial del usuario, ordenados
  por `ultimo_uso` desc, cada uno con un botón inline. El chat conectado
  actualmente (tabla `connections`) se marca con "✅" al inicio de su línea
  y además se muestra arriba del todo como "Conectado ahora: <título>".
- **Al pulsar un botón, o con `/connection <n>`**: `<n>` es la posición en
  esa lista (1, 2, 3... calculada al vuelo en cada consulta, no un id
  guardado — así nunca hay huecos que gestionar aquí, es solo el orden de
  la lista de ese momento). Seleccionar una entrada:
  1. La fija como conexión activa (`db.set_connection`, igual que hace
     `/connect` hoy).
  2. Muestra el mismo detalle que ya renderiza `connection_cmd` hoy
     (título, id, oficial TASALO, feeds activos, límite de avisos,
     antiflood, bloqueos) — se extrae a un helper
     `_render_detalle_conexion(chat_row)` reusado en ambos casos para no
     duplicar ese bloque de texto.
- Si el historial está vacío, mismo mensaje que hoy: invita a usar
  `/connect <@usuario|id>`.

### No afecta
`/connect` y `/disconnect` mantienen su firma y comportamiento actual
(`/connect` además ahora también escribe en `connection_history`);
`get_connected_chat_id()` (usado por RSS y otros módulos para resolver el
chat activo en PM) no cambia.

## Orden de implementación sugerido
1. Parte 1 (feeds): migración de esquema + helper + los 5 comandos + `/myfeeds`.
2. Parte 2 (connection): tabla nueva + `/connect` guarda historial +
   `/connection` con lista/detalle + callback de selección.
3. `py_compile` de ambos módulos tocados; pruebas manuales en el chat de
   pruebas; deploy en VPS al final de ambas partes (no dos deploys sueltos).

Sin tocar nada más hasta aprobación.
