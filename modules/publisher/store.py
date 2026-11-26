"""Almacén de la publicación automática: jobs, destinos, cuentas (secretos
cifrados) y registro idempotente. Solo toca las tablas `pub_*`."""

import json

from core import secrets
from core.database import db
from modules.publisher.base import FUENTES_VALIDAS, TIPOS_DESTINO

_CAMPOS_JOB = {"nombre", "fuente", "hora", "minuto", "dias", "activo", "params_json"}
_CAMPOS_DESTINO = {"cuenta_id", "activo", "params_json"}
_REDES = ("hive", "nostr")


class PubError(ValueError):
    """Dato inválido en la configuración de publicación."""


def validar_hora(hora: int, minuto: int) -> None:
    if not (isinstance(hora, int) and 0 <= hora <= 23 and isinstance(minuto, int) and 0 <= minuto <= 59):
        raise PubError("Hora inválida (0-23) o minuto inválido (0-59)")


def validar_dias(dias: str) -> str:
    dias = (dias or "*").replace(" ", "")
    if dias == "*":
        return dias
    try:
        nums = sorted({int(x) for x in dias.split(",")})
    except ValueError as e:
        raise PubError("Días inválidos: usa * o números 0-6 separados por coma (lun=0)") from e
    if not nums or nums[0] < 0 or nums[-1] > 6:
        raise PubError("Días inválidos: usa * o números 0-6 separados por coma (lun=0)")
    return ",".join(map(str, nums))


def _params(texto: str | None) -> dict:
    try:
        v = json.loads(texto or "{}")
        return v if isinstance(v, dict) else {}
    except ValueError:
        return {}


# ---------- jobs ----------
async def crear_job(nombre: str, fuente: str, hora: int = 8, minuto: int = 30, dias: str = "*", params: dict | None = None) -> int:
    if fuente not in FUENTES_VALIDAS:
        raise PubError(f"Fuente desconocida: {fuente}")
    validar_hora(hora, minuto)
    return await db.execute(
        "INSERT INTO pub_jobs(nombre, fuente, hora, minuto, dias, params_json) VALUES(?,?,?,?,?,?)",
        (nombre.strip(), fuente, hora, minuto, validar_dias(dias), json.dumps(params or {})),
    )


async def get_job(job_id: int) -> dict | None:
    return await db.fetchone("SELECT * FROM pub_jobs WHERE id = ?", (job_id,))


async def listar_jobs(solo_activos: bool = False) -> list[dict]:
    q = "SELECT * FROM pub_jobs" + (" WHERE activo = 1" if solo_activos else "") + " ORDER BY id"
    return await db.fetchall(q)


async def editar_job(job_id: int, **campos) -> None:
    if not campos or not set(campos) <= _CAMPOS_JOB:
        raise PubError("Campo de job no editable")
    actual = await get_job(job_id)
    if not actual:
        raise PubError("Job inexistente")
    nuevo = {**actual, **campos}
    validar_hora(nuevo["hora"], nuevo["minuto"])
    if "dias" in campos:
        campos["dias"] = validar_dias(campos["dias"])
    if "fuente" in campos and campos["fuente"] not in FUENTES_VALIDAS:
        raise PubError("Fuente desconocida")
    sets = ", ".join(f"{k} = ?" for k in campos)
    await db.execute(f"UPDATE pub_jobs SET {sets} WHERE id = ?", (*campos.values(), job_id))


async def borrar_job(job_id: int) -> None:
    await db.execute("DELETE FROM pub_destinos WHERE job_id = ?", (job_id,))
    await db.execute("DELETE FROM pub_jobs WHERE id = ?", (job_id,))


# ---------- destinos ----------
async def agregar_destino(job_id: int, tipo: str, cuenta_id: int | None = None, params: dict | None = None) -> int:
    if tipo not in TIPOS_DESTINO:
        raise PubError(f"Tipo de destino desconocido: {tipo}")
    if not await get_job(job_id):
        raise PubError("Job inexistente")
    return await db.execute(
        "INSERT INTO pub_destinos(job_id, tipo, cuenta_id, params_json) VALUES(?,?,?,?)",
        (job_id, tipo, cuenta_id, json.dumps(params or {})),
    )


async def listar_destinos(job_id: int, solo_activos: bool = False) -> list[dict]:
    q = "SELECT * FROM pub_destinos WHERE job_id = ?" + (" AND activo = 1" if solo_activos else "") + " ORDER BY id"
    filas = await db.fetchall(q, (job_id,))
    for f in filas:
        f["params"] = _params(f["params_json"])
    return filas


async def editar_destino(destino_id: int, **campos) -> None:
    if not campos or not set(campos) <= _CAMPOS_DESTINO:
        raise PubError("Campo de destino no editable")
    sets = ", ".join(f"{k} = ?" for k in campos)
    await db.execute(f"UPDATE pub_destinos SET {sets} WHERE id = ?", (*campos.values(), destino_id))


async def borrar_destino(destino_id: int) -> None:
    await db.execute("DELETE FROM pub_destinos WHERE id = ?", (destino_id,))


# ---------- cuentas y secretos ----------
def _nombre_secreto(red: str, nombre: str) -> str:
    return f"{red}:{nombre}"          # va como AAD del cifrado


async def guardar_cuenta(red: str, nombre: str, secreto: str | None = None, params: dict | None = None) -> int:
    """Crea o actualiza una cuenta. El secreto (posting key / nsec) se cifra aquí;
    si es None se conserva el que ya hubiera."""
    if red not in _REDES:
        raise PubError(f"Red desconocida: {red}")
    nombre = nombre.strip().lstrip("@")
    if not nombre:
        raise PubError("Nombre de cuenta vacío")
    cifrado = secrets.cifrar(_nombre_secreto(red, nombre), secreto) if secreto else None
    existente = await db.fetchone("SELECT id FROM pub_cuentas WHERE red = ? AND nombre = ?", (red, nombre))
    if existente:
        if cifrado:
            await db.execute("UPDATE pub_cuentas SET secreto_cifrado = ? WHERE id = ?", (cifrado, existente["id"]))
        if params is not None:
            await db.execute("UPDATE pub_cuentas SET params_json = ? WHERE id = ?", (json.dumps(params), existente["id"]))
        return existente["id"]
    return await db.execute(
        "INSERT INTO pub_cuentas(red, nombre, params_json, secreto_cifrado) VALUES(?,?,?,?)",
        (red, nombre, json.dumps(params or {}), cifrado),
    )


async def get_cuenta(cuenta_id: int) -> dict | None:
    """La cuenta SIN el secreto (solo `tiene_secreto`): segura para mostrar o loguear."""
    f = await db.fetchone("SELECT * FROM pub_cuentas WHERE id = ?", (cuenta_id,))
    if not f:
        return None
    f["tiene_secreto"] = bool(f.pop("secreto_cifrado"))
    f["params"] = _params(f["params_json"])
    return f


async def listar_cuentas(red: str | None = None) -> list[dict]:
    filas = await db.fetchall("SELECT id FROM pub_cuentas" + (" WHERE red = ?" if red else "") + " ORDER BY id", (red,) if red else ())
    return [await get_cuenta(f["id"]) for f in filas]


async def editar_cuenta(cuenta_id: int, activa: bool | None = None, params: dict | None = None) -> None:
    if activa is not None:
        await db.execute("UPDATE pub_cuentas SET activa = ? WHERE id = ?", (int(activa), cuenta_id))
    if params is not None:
        await db.execute("UPDATE pub_cuentas SET params_json = ? WHERE id = ?", (json.dumps(params), cuenta_id))


async def obtener_secreto(cuenta_id: int) -> str | None:
    """Descifra el secreto SOLO para usarlo al publicar. No lo registres ni lo muestres."""
    f = await db.fetchone("SELECT red, nombre, secreto_cifrado FROM pub_cuentas WHERE id = ?", (cuenta_id,))
    if not f or not f["secreto_cifrado"]:
        return None
    return secrets.descifrar(_nombre_secreto(f["red"], f["nombre"]), f["secreto_cifrado"])


async def borrar_cuenta(cuenta_id: int) -> None:
    await db.execute("UPDATE pub_destinos SET cuenta_id = NULL, activo = 0 WHERE cuenta_id = ?", (cuenta_id,))
    await db.execute("DELETE FROM pub_cuentas WHERE id = ?", (cuenta_id,))


# ---------- registro idempotente ----------
async def reservar(job_id: int, destino_id: int, fecha: str, max_intentos: int = 3) -> bool:
    """Reserva (job, destino, día). True = esta llamada debe publicar.
    Un intento previo en 'error' se puede reintentar hasta `max_intentos`; 'ok',
    'simulado' o 'reservado' (otra ejecución en curso o caída a medias) no se repiten solos."""
    async with db._lock:
        conn = db._conn
        await conn.execute(
            "INSERT INTO pub_log(job_id, destino_id, fecha, estado, intentos) VALUES(?,?,?,'reservado',1) "
            "ON CONFLICT(job_id, destino_id, fecha) DO UPDATE SET estado='reservado', intentos=intentos+1, error=NULL "
            "WHERE pub_log.estado='error' AND pub_log.intentos < ?",
            (job_id, destino_id, fecha, max_intentos),
        )
        cur = await conn.execute("SELECT changes()")
        cambios = (await cur.fetchone())[0]
        await conn.commit()
        return cambios > 0


async def marcar(job_id: int, destino_id: int, fecha: str, estado: str, url: str | None = None, error: str | None = None) -> None:
    await db.execute(
        "UPDATE pub_log SET estado = ?, url = ?, error = ? WHERE job_id = ? AND destino_id = ? AND fecha = ?",
        (estado, url, (error or "")[:500] or None, job_id, destino_id, fecha),
    )


async def intentos(job_id: int, destino_id: int, fecha: str) -> int:
    f = await db.fetchone("SELECT intentos FROM pub_log WHERE job_id = ? AND destino_id = ? AND fecha = ?", (job_id, destino_id, fecha))
    return f["intentos"] if f else 0


async def historial(job_id: int | None = None, limite: int = 20) -> list[dict]:
    if job_id is None:
        return await db.fetchall("SELECT * FROM pub_log ORDER BY id DESC LIMIT ?", (limite,))
    return await db.fetchall("SELECT * FROM pub_log WHERE job_id = ? ORDER BY id DESC LIMIT ?", (job_id, limite))



# ---------- modo prueba (editable desde /pub; el .env solo da el valor inicial) ----------
async def modo_prueba(por_defecto: bool = True) -> bool:
    f = await db.fetchone("SELECT valor FROM meta WHERE clave = 'pub_dry_run'")
    return por_defecto if f is None else f["valor"] != "0"


async def set_modo_prueba(activo: bool) -> None:
    await db.execute(
        "INSERT INTO meta(clave, valor) VALUES('pub_dry_run', ?) ON CONFLICT(clave) DO UPDATE SET valor = excluded.valor",
        ("1" if activo else "0",),
    )


# ---------- consultas para el panel ----------
async def get_destino(destino_id: int) -> dict | None:
    f = await db.fetchone("SELECT * FROM pub_destinos WHERE id = ?", (destino_id,))
    if f:
        f["params"] = _params(f["params_json"])
    return f


async def log_de(job_id: int, fecha: str) -> list[dict]:
    """Resultado por destino de una ejecución concreta (la clave de día usada)."""
    return await db.fetchall(
        "SELECT l.estado, l.url, l.error, d.tipo FROM pub_log l JOIN pub_destinos d ON d.id = l.destino_id "
        "WHERE l.job_id = ? AND l.fecha = ? ORDER BY d.id",
        (job_id, fecha),
    )
