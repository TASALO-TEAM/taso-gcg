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
    url TEXT NOT NULL,
    url_original TEXT,
    titulo TEXT,
    estilo TEXT NOT NULL DEFAULT 'bitbread',
    plantilla TEXT,
    rhash TEXT,
    intervalo_min INTEGER NOT NULL DEFAULT 10,
    ultimo_check REAL NOT NULL DEFAULT 0,
    activo INTEGER NOT NULL DEFAULT 1,
    creado_en TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_feeds_activo ON feeds(activo);

CREATE TABLE IF NOT EXISTS feed_historial (
    feed_id INTEGER NOT NULL REFERENCES feeds(id) ON DELETE CASCADE,
    entry_hash TEXT NOT NULL,
    enviado_en TEXT DEFAULT (datetime('now')),
    PRIMARY KEY (feed_id, entry_hash)
);

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
        await self._set_schema_version()
        log(f"Base de datos lista en {self.path} (WAL)")

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


db = Database()
