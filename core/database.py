"""Capa de persistencia de taso-gcg.

SQLite local en modo WAL vía aiosqlite. Un solo módulo con todas las tablas:
para el tamaño de datos de este bot (config de chats, warns, notas, feeds)
no hace falta separar por dominio ni meter un ORM completo.

Patrón de uso:
    from core.database import db
    await db.init()
    rows = await db.fetchall("SELECT * FROM chats WHERE activo = 1")
"""

import asyncio
import time
import aiosqlite

from core.config import DB_PATH
from utils.logger import log

SCHEMA_VERSION = 1

SCHEMA_SQL = """
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS meta (
    clave TEXT PRIMARY KEY,
    valor TEXT
);

CREATE TABLE IF NOT EXISTS chats (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tg_chat_id INTEGER UNIQUE NOT NULL,
    tipo TEXT NOT NULL CHECK(tipo IN ('group','supergroup','channel','private')),
    titulo TEXT,
    username TEXT,
    es_oficial_tasalo INTEGER NOT NULL DEFAULT 0,
    activo INTEGER NOT NULL DEFAULT 1,
    creado_en TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS chat_settings (
    chat_id INTEGER PRIMARY KEY REFERENCES chats(id) ON DELETE CASCADE,
    flood_limit INTEGER NOT NULL DEFAULT 0,
    flood_action TEXT NOT NULL DEFAULT 'mute',
    warn_limit INTEGER NOT NULL DEFAULT 3,
    warn_action TEXT NOT NULL DEFAULT 'ban',
    welcome_enabled INTEGER NOT NULL DEFAULT 0,
    welcome_text TEXT,
    goodbye_enabled INTEGER NOT NULL DEFAULT 0,
    goodbye_text TEXT,
    rules_text TEXT,
    clean_service_msgs INTEGER NOT NULL DEFAULT 0,
    join_captcha INTEGER NOT NULL DEFAULT 0,
    disable_del INTEGER NOT NULL DEFAULT 0,
    disable_admin INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS warns (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id INTEGER NOT NULL REFERENCES chats(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL,
    razon TEXT,
    dado_por INTEGER,
    creado_en TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_warns_chat_user ON warns(chat_id, user_id);

CREATE TABLE IF NOT EXISTS locks (
    chat_id INTEGER NOT NULL REFERENCES chats(id) ON DELETE CASCADE,
    tipo TEXT NOT NULL,
    activo INTEGER NOT NULL DEFAULT 1,
    PRIMARY KEY (chat_id, tipo)
);

CREATE TABLE IF NOT EXISTS blacklist (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id INTEGER NOT NULL REFERENCES chats(id) ON DELETE CASCADE,
    palabra TEXT NOT NULL,
    accion TEXT NOT NULL DEFAULT 'delete',
    UNIQUE(chat_id, palabra)
);

CREATE TABLE IF NOT EXISTS filters (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id INTEGER NOT NULL REFERENCES chats(id) ON DELETE CASCADE,
    disparador TEXT NOT NULL,
    respuesta TEXT NOT NULL,
    tipo_respuesta TEXT NOT NULL DEFAULT 'text',
    UNIQUE(chat_id, disparador)
);

CREATE TABLE IF NOT EXISTS notes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id INTEGER NOT NULL REFERENCES chats(id) ON DELETE CASCADE,
    nombre TEXT NOT NULL,
    contenido TEXT NOT NULL,
    tipo_contenido TEXT NOT NULL DEFAULT 'text',
    creado_por INTEGER,
    UNIQUE(chat_id, nombre)
);

CREATE TABLE IF NOT EXISTS admins_cache (
    chat_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    es_creador INTEGER NOT NULL DEFAULT 0,
    cacheado_en REAL NOT NULL,
    PRIMARY KEY (chat_id, user_id)
);

CREATE TABLE IF NOT EXISTS join_requests (
    chat_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    estado TEXT NOT NULL DEFAULT 'pendiente',
    solicitado_en TEXT DEFAULT (datetime('now')),
    PRIMARY KEY (chat_id, user_id)
);

CREATE TABLE IF NOT EXISTS broadcast_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    mensaje TEXT,
    chats_alcanzados INTEGER,
    enviado_por INTEGER,
    enviado_en TEXT DEFAULT (datetime('now'))
);

-- === Approvals (inmunidad ante acciones automáticas: antiflood, blacklist, locks) ===
CREATE TABLE IF NOT EXISTS approvals (
    chat_id INTEGER NOT NULL REFERENCES chats(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL,
    razon TEXT,
    aprobado_por INTEGER,
    creado_en TEXT DEFAULT (datetime('now')),
    PRIMARY KEY (chat_id, user_id)
);

-- === Federación TASALO: bans que se sincronizan entre todos los chats oficiales ===
CREATE TABLE IF NOT EXISTS fed_bans (
    user_id INTEGER PRIMARY KEY,
    razon TEXT,
    baneado_por INTEGER,
    creado_en TEXT DEFAULT (datetime('now'))
);

-- === Log de administración (canal donde se reportan acciones de moderación) ===
CREATE TABLE IF NOT EXISTS log_channels (
    chat_id INTEGER PRIMARY KEY REFERENCES chats(id) ON DELETE CASCADE,
    log_chat_tg_id INTEGER NOT NULL,
    categorias TEXT NOT NULL DEFAULT 'settings,admin,user,automated,reports,other'
);

-- === Comandos deshabilitados por chat ===
CREATE TABLE IF NOT EXISTS disabled_commands (
    chat_id INTEGER NOT NULL REFERENCES chats(id) ON DELETE CASCADE,
    comando TEXT NOT NULL,
    PRIMARY KEY (chat_id, comando)
);

-- === RSS (migrado de BitBreadRSS) ===
CREATE TABLE IF NOT EXISTS feeds (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id INTEGER NOT NULL REFERENCES chats(id) ON DELETE CASCADE,
    numero_local INTEGER,
    url TEXT NOT NULL,
    url_original TEXT,
    titulo TEXT,
    estilo TEXT NOT NULL DEFAULT 'bitbread',
    plantilla TEXT,
    rhash TEXT,
    intervalo_min INTEGER NOT NULL DEFAULT 10,
    ultimo_check REAL NOT NULL DEFAULT 0,
    activo INTEGER NOT NULL DEFAULT 1,
    traducir INTEGER NOT NULL DEFAULT 0,
    creado_en TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_feeds_activo ON feeds(activo);
-- numero_local: contador visible propio de cada chat (1,2,3... reutilizando
-- huecos), independiente del id interno (PK real, usado en FKs de
-- feed_historial/feed_stats). El índice único se crea en _migrate(), no
-- aquí, porque en una DB ya existente la columna todavía no existe cuando
-- corre este script. Ver docs/plans/2026-07-21-admin-ux-feeds-connection.md

CREATE TABLE IF NOT EXISTS feed_historial (
    feed_id INTEGER NOT NULL REFERENCES feeds(id) ON DELETE CASCADE,
    entry_hash TEXT NOT NULL,
    titulo_normalizado TEXT,
    link_externo_normalizado TEXT,
    enviado_en TEXT DEFAULT (datetime('now')),
    PRIMARY KEY (feed_id, entry_hash)
);
CREATE INDEX IF NOT EXISTS idx_feed_historial_feed_fecha ON feed_historial(feed_id, enviado_en);

CREATE TABLE IF NOT EXISTS feed_stats (
    feed_id INTEGER PRIMARY KEY REFERENCES feeds(id) ON DELETE CASCADE,
    enviados INTEGER NOT NULL DEFAULT 0,
    errores INTEGER NOT NULL DEFAULT 0,
    ultimo_error TEXT
);

CREATE TABLE IF NOT EXISTS iv_templates (
    dominio TEXT PRIMARY KEY,   -- '_universal' para el rhash por defecto
    rhash TEXT NOT NULL
);

-- === Conexión remota (/connect): persistida en DB, no en memoria, para que
-- sobreviva a un reinicio del bot igual que todo lo demás ===
CREATE TABLE IF NOT EXISTS connections (
    user_id INTEGER PRIMARY KEY,
    tg_chat_id INTEGER NOT NULL,
    conectado_en TEXT DEFAULT (datetime('now'))
);

-- === Historial de conexiones: chats a los que el usuario ya se conectó
-- alguna vez, para poder listarlos en /connection y cambiar entre ellos
-- sin volver a teclear el id/@usuario cada vez ===
CREATE TABLE IF NOT EXISTS connection_history (
    user_id INTEGER NOT NULL,
    tg_chat_id INTEGER NOT NULL,
    titulo TEXT,
    ultimo_uso TEXT DEFAULT (datetime('now')),
    PRIMARY KEY (user_id, tg_chat_id)
);

-- === Caché local de usuarios vistos (id, username, nombre...) ===
-- Necesaria porque la Bot API de Telegram NO deja resolver un @username
-- arbitrario a su user_id salvo que el bot ya "conozca" a ese usuario por
-- algún otro medio (a diferencia de grupos/canales, que sí son resolubles
-- siempre vía get_chat porque su username es público). Se alimenta con cada
-- mensaje que el bot ve pasar (chat_tracker.py) — si alguien nunca escribió
-- en un chat donde está el bot, su @username simplemente no es resoluble
-- todavía, es una limitación real de la plataforma, no un bug del bot.
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    username TEXT,
    first_name TEXT,
    last_name TEXT,
    is_bot INTEGER NOT NULL DEFAULT 0,
    language_code TEXT,
    is_premium INTEGER NOT NULL DEFAULT 0,
    visto_en TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_users_username ON users(username COLLATE NOCASE);
"""


class Database:
    """Wrapper fino sobre aiosqlite con un pool de una sola conexión reusada.

    SQLite en modo WAL soporta bien un único writer + múltiples readers desde
    el mismo proceso, así que no hace falta un pool de verdad como con Postgres.
    """

    def __init__(self, path: str = DB_PATH):
        self.path = path
        self._conn: aiosqlite.Connection | None = None
        self._lock = asyncio.Lock()

    async def init(self):
        self._conn = await aiosqlite.connect(self.path)
        self._conn.row_factory = aiosqlite.Row
        await self._conn.executescript(SCHEMA_SQL)
        await self._conn.commit()
        await self._backfill_connection_history()
        await self._migrate()
        await self._set_schema_version()
        log(f"Base de datos lista en {self.path} (WAL)")

    async def _backfill_connection_history(self):
        """connection_history es tabla nueva (antes solo existía `connections`,
        que guarda una única conexión viva por usuario sin historial). Sin este
        backfill, un usuario que ya estaba conectado antes de este cambio vería
        /connection como si nunca se hubiera conectado — se le "perdía" su
        conexión de la vista nueva aunque siguiera viva en `connections`.
        INSERT OR IGNORE (no INSERT a secas) porque esto corre en CADA
        arranque, no solo la primera vez: si el usuario ya tiene una entrada
        en connection_history (por (user_id, tg_chat_id), su PK), esa fila no
        se toca — así no pisa un `ultimo_uso` más reciente que ya tenga ahí."""
        await self._conn.execute(
            """
            INSERT OR IGNORE INTO connection_history(user_id, tg_chat_id, titulo, ultimo_uso)
            SELECT c.user_id, c.tg_chat_id, ch.titulo, c.conectado_en
            FROM connections c
            LEFT JOIN chats ch ON ch.tg_chat_id = c.tg_chat_id
            """
        )
        await self._conn.commit()
        cur = await self._conn.execute("SELECT changes()")
        n = (await cur.fetchone())[0]
        if n:
            log(f"🔧 Migración: connection_history poblada con {n} conexión(es) existente(s)")

    async def _migrate(self):
        """Agrega columnas nuevas a tablas que ya existían antes de que se
        introdujeran (CREATE TABLE IF NOT EXISTS no toca tablas existentes).
        Cada entrada se salta sola si la columna ya está — así esto es seguro
        de correr en cada arranque, tanto en una DB nueva como en la del VPS."""
        migraciones = [
            ("feeds", "traducir", "INTEGER NOT NULL DEFAULT 0"),
            ("feeds", "numero_local", "INTEGER"),
            ("feed_historial", "titulo_normalizado", "TEXT"),
            ("feed_historial", "link_externo_normalizado", "TEXT"),
        ]
        columnas_por_tabla = {}
        for tabla in {t for t, _, _ in migraciones}:
            cur = await self._conn.execute(f"PRAGMA table_info({tabla})")
            columnas_por_tabla[tabla] = {row[1] for row in await cur.fetchall()}
        for tabla, columna, tipo in migraciones:
            if columna in columnas_por_tabla.get(tabla, set()):
                continue
            try:
                await self._conn.execute(f"ALTER TABLE {tabla} ADD COLUMN {columna} {tipo}")
                log(f"🔧 Migración: agregada columna {tabla}.{columna}")
                if tabla == "feeds" and columna == "numero_local":
                    await self._backfill_numero_local()
            except aiosqlite.OperationalError:
                pass  # ya existía (carrera improbable, pero por si acaso)
        # El índice único va aquí (no en SCHEMA_SQL) porque en una DB vieja
        # la columna numero_local recién se acaba de agregar arriba.
        await self._conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_feeds_chat_numero "
            "ON feeds(chat_id, numero_local)"
        )
        await self._conn.commit()

    async def _backfill_numero_local(self):
        """Asigna numero_local 1,2,3... a los feeds ya existentes, por chat,
        respetando el orden actual (id asc). Solo corre una vez, justo al
        agregar la columna en una DB que no la tenía."""
        cur = await self._conn.execute(
            "SELECT id, chat_id FROM feeds ORDER BY chat_id, id"
        )
        filas = await cur.fetchall()
        contador_por_chat = {}
        for feed_id, chat_id in filas:
            contador_por_chat[chat_id] = contador_por_chat.get(chat_id, 0) + 1
            await self._conn.execute(
                "UPDATE feeds SET numero_local = ? WHERE id = ?",
                (contador_por_chat[chat_id], feed_id),
            )
        if filas:
            log(f"🔧 Migración: numero_local asignado a {len(filas)} feed(s) existentes")

    async def _set_schema_version(self):
        await self._conn.execute(
            "INSERT INTO meta(clave, valor) VALUES('schema_version', ?) "
            "ON CONFLICT(clave) DO UPDATE SET valor=excluded.valor",
            (str(SCHEMA_VERSION),),
        )
        await self._conn.commit()

    async def close(self):
        if self._conn:
            await self._conn.close()

    # --- Helpers genéricos ---
    async def execute(self, query: str, params: tuple = ()):
        async with self._lock:
            cur = await self._conn.execute(query, params)
            await self._conn.commit()
            return cur.lastrowid

    async def executemany(self, query: str, seq_of_params):
        async with self._lock:
            await self._conn.executemany(query, seq_of_params)
            await self._conn.commit()

    async def fetchone(self, query: str, params: tuple = ()):
        cur = await self._conn.execute(query, params)
        row = await cur.fetchone()
        await cur.close()
        return dict(row) if row else None

    async def fetchall(self, query: str, params: tuple = ()):
        cur = await self._conn.execute(query, params)
        rows = await cur.fetchall()
        await cur.close()
        return [dict(r) for r in rows]

    # --- Operaciones de dominio: chats ---
    async def ensure_chat(self, chat) -> dict:
        """Recibe un objeto telegram.Chat y garantiza que exista en la tabla chats.
        Devuelve la fila (incluye el id interno usado como FK en el resto de tablas)."""
        titulo = chat.title or getattr(chat, "full_name", None) or getattr(chat, "first_name", None)
        return await self.get_or_create_chat(chat.id, chat.type, titulo, chat.username)

    async def get_or_create_chat(self, tg_chat_id: int, tipo: str, titulo: str = None,
                                  username: str = None) -> dict:
        row = await self.fetchone("SELECT * FROM chats WHERE tg_chat_id = ?", (tg_chat_id,))
        if row:
            # Mantener título/username actualizados sin costar una escritura extra si no cambió
            if titulo and (row["titulo"] != titulo or row["username"] != username):
                await self.execute(
                    "UPDATE chats SET titulo = ?, username = ? WHERE tg_chat_id = ?",
                    (titulo, username, tg_chat_id),
                )
                row = await self.fetchone("SELECT * FROM chats WHERE tg_chat_id = ?", (tg_chat_id,))
            return row
        chat_id = await self.execute(
            "INSERT INTO chats(tg_chat_id, tipo, titulo, username) VALUES (?,?,?,?)",
            (tg_chat_id, tipo, titulo, username),
        )
        await self.execute(
            "INSERT INTO chat_settings(chat_id) VALUES (?)", (chat_id,)
        )
        log(f"Nuevo chat registrado: {titulo or tg_chat_id} ({tipo})")
        return await self.fetchone("SELECT * FROM chats WHERE id = ?", (chat_id,))

    async def get_chat_settings(self, chat_id: int) -> dict:
        row = await self.fetchone("SELECT * FROM chat_settings WHERE chat_id = ?", (chat_id,))
        if not row:
            await self.execute("INSERT INTO chat_settings(chat_id) VALUES (?)", (chat_id,))
            row = await self.fetchone("SELECT * FROM chat_settings WHERE chat_id = ?", (chat_id,))
        return row

    async def update_chat_settings(self, chat_id: int, **campos):
        if not campos:
            return
        set_clause = ", ".join(f"{k} = ?" for k in campos)
        await self.execute(
            f"UPDATE chat_settings SET {set_clause} WHERE chat_id = ?",
            (*campos.values(), chat_id),
        )

    async def set_oficial_tasalo(self, tg_chat_id: int, valor: bool):
        await self.execute(
            "UPDATE chats SET es_oficial_tasalo = ? WHERE tg_chat_id = ?",
            (1 if valor else 0, tg_chat_id),
        )

    async def chats_oficiales(self) -> list[dict]:
        return await self.fetchall(
            "SELECT * FROM chats WHERE es_oficial_tasalo = 1 AND activo = 1"
        )

    # --- admins_cache ---
    async def cache_admins(self, tg_chat_id: int, admin_ids: list[tuple[int, bool]]):
        """admin_ids: lista de (user_id, es_creador)"""
        now = time.time()
        await self.execute("DELETE FROM admins_cache WHERE chat_id = ?", (tg_chat_id,))
        await self.executemany(
            "INSERT INTO admins_cache(chat_id, user_id, es_creador, cacheado_en) VALUES (?,?,?,?)",
            [(tg_chat_id, uid, 1 if creador else 0, now) for uid, creador in admin_ids],
        )

    async def get_cached_admins(self, tg_chat_id: int, ttl_seconds: int) -> list[dict] | None:
        rows = await self.fetchall(
            "SELECT * FROM admins_cache WHERE chat_id = ?", (tg_chat_id,)
        )
        if not rows:
            return None
        if time.time() - rows[0]["cacheado_en"] > ttl_seconds:
            return None
        return rows

    # --- Approvals ---
    async def is_approved(self, chat_id: int, user_id: int) -> bool:
        row = await self.fetchone(
            "SELECT 1 FROM approvals WHERE chat_id = ? AND user_id = ?", (chat_id, user_id)
        )
        return row is not None

    # --- Federación TASALO ---
    async def is_fed_banned(self, user_id: int) -> dict | None:
        return await self.fetchone("SELECT * FROM fed_bans WHERE user_id = ?", (user_id,))

    # --- Comandos deshabilitados ---
    async def is_command_disabled(self, chat_id: int, comando: str) -> bool:
        row = await self.fetchone(
            "SELECT 1 FROM disabled_commands WHERE chat_id = ? AND comando = ?", (chat_id, comando)
        )
        return row is not None

    # --- Instant View templates ---
    async def find_iv_rhash(self, url: str) -> str | None:
        from urllib.parse import urlparse
        dominio = urlparse(url).netloc.lower().replace("www.", "")
        fila = await self.fetchone("SELECT rhash FROM iv_templates WHERE dominio = ?", (dominio,))
        if fila:
            return fila["rhash"]
        todas = await self.fetchall("SELECT dominio, rhash FROM iv_templates WHERE dominio != '_universal'")
        for t in todas:
            if dominio.endswith(t["dominio"]):
                return t["rhash"]
        universal = await self.fetchone("SELECT rhash FROM iv_templates WHERE dominio = '_universal'")
        return universal["rhash"] if universal else None

    # --- RSS: numero_local (numeración de feeds por chat, rellenando huecos) ---
    async def siguiente_numero_local(self, chat_id: int) -> int:
        """Primer numero_local libre para este chat (rellena huecos dejados
        por feeds eliminados en vez de crecer sin límite)."""
        row = await self.fetchone(
            """
            SELECT MIN(t1.numero_local + 1) AS libre
            FROM feeds t1
            WHERE t1.chat_id = ?
              AND NOT EXISTS (
                  SELECT 1 FROM feeds t2
                  WHERE t2.chat_id = t1.chat_id AND t2.numero_local = t1.numero_local + 1
              )
            """,
            (chat_id,),
        )
        if row and row["libre"] is not None:
            return row["libre"]
        return 1  # no hay feeds todavía en este chat

    async def get_feed_by_numero_local(self, chat_id: int, numero_local: int) -> dict | None:
        return await self.fetchone(
            "SELECT * FROM feeds WHERE chat_id = ? AND numero_local = ?",
            (chat_id, numero_local),
        )

    # --- Conexión remota (/connect) ---
    async def set_connection(self, user_id: int, tg_chat_id: int):
        await self.execute(
            "INSERT INTO connections(user_id, tg_chat_id) VALUES (?,?) "
            "ON CONFLICT(user_id) DO UPDATE SET tg_chat_id = excluded.tg_chat_id, "
            "conectado_en = datetime('now')",
            (user_id, tg_chat_id),
        )

    async def get_connection(self, user_id: int) -> int | None:
        row = await self.fetchone("SELECT tg_chat_id FROM connections WHERE user_id = ?", (user_id,))
        return row["tg_chat_id"] if row else None

    async def clear_connection(self, user_id: int):
        await self.execute("DELETE FROM connections WHERE user_id = ?", (user_id,))

    # --- Historial de conexiones (/connection: lista de chats ya usados) ---
    async def record_connection_history(self, user_id: int, tg_chat_id: int, titulo: str = None):
        await self.execute(
            "INSERT INTO connection_history(user_id, tg_chat_id, titulo) VALUES (?,?,?) "
            "ON CONFLICT(user_id, tg_chat_id) DO UPDATE SET "
            "titulo = excluded.titulo, ultimo_uso = datetime('now')",
            (user_id, tg_chat_id, titulo),
        )

    async def get_connection_history(self, user_id: int) -> list[dict]:
        return await self.fetchall(
            "SELECT * FROM connection_history WHERE user_id = ? ORDER BY ultimo_uso DESC",
            (user_id,),
        )

    async def get_chats_administrados(self, user_id: int) -> list[dict]:
        """Todos los chats donde este usuario es admin (según admins_cache,
        la misma caché que usan los comandos de moderación) O a los que ya se
        conectó antes por /connect — la unión de ambos, para que /connection
        muestre TODOS sus chats y no solo los que conectó manualmente por PM.
        Limitación conocida: un chat nuevo donde nunca corrió un comando de
        moderación (admins_cache vacía ahí) y que tampoco usó con /connect no
        va a aparecer hasta que ocurra una de esas dos cosas una vez.
        Ordena primero por uso más reciente en connection_history, y después
        alfabéticamente el resto."""
        return await self.fetchall(
            """
            SELECT tg_chat_id, titulo FROM (
                SELECT c.tg_chat_id AS tg_chat_id, c.titulo AS titulo,
                       ch.ultimo_uso AS ultimo_uso
                FROM chats c
                JOIN admins_cache a ON a.chat_id = c.tg_chat_id
                LEFT JOIN connection_history ch
                    ON ch.tg_chat_id = c.tg_chat_id AND ch.user_id = a.user_id
                WHERE a.user_id = ? AND c.activo = 1
                UNION
                SELECT tg_chat_id, titulo, ultimo_uso
                FROM connection_history WHERE user_id = ?
            )
            ORDER BY (ultimo_uso IS NULL), ultimo_uso DESC, titulo COLLATE NOCASE
            """,
            (user_id, user_id),
        )

    # --- Caché de usuarios (resolución de @username -> user_id) ---
    async def upsert_user(self, user) -> None:
        """Guarda o actualiza los datos vistos de un usuario. Se llama en cada
        mensaje que pasa por el bot (ver chat_tracker.py) para que /id y los
        comandos de moderación puedan resolver @username más adelante."""
        if not user:
            return
        await self.execute(
            "INSERT INTO users(user_id, username, first_name, last_name, is_bot, "
            "language_code, is_premium, visto_en) VALUES (?,?,?,?,?,?,?, datetime('now')) "
            "ON CONFLICT(user_id) DO UPDATE SET username=excluded.username, "
            "first_name=excluded.first_name, last_name=excluded.last_name, "
            "is_bot=excluded.is_bot, language_code=excluded.language_code, "
            "is_premium=excluded.is_premium, visto_en=excluded.visto_en",
            (
                user.id,
                getattr(user, "username", None),
                getattr(user, "first_name", None),
                getattr(user, "last_name", None),
                1 if getattr(user, "is_bot", False) else 0,
                getattr(user, "language_code", None),
                1 if getattr(user, "is_premium", False) else 0,
            ),
        )

    async def find_user_by_username(self, username: str) -> dict | None:
        """Busca en la caché local. Solo encuentra a quien ya haya escrito
        al menos un mensaje en algún chat donde el bot esté presente."""
        username = username.lstrip("@")
        return await self.fetchone(
            "SELECT * FROM users WHERE username = ? COLLATE NOCASE", (username,)
        )

    async def get_user(self, user_id: int) -> dict | None:
        return await self.fetchone("SELECT * FROM users WHERE user_id = ?", (user_id,))


db = Database()
