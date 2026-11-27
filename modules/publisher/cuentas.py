"""Cuentas de publicación (Hive) editables desde /pub: validadores, pantallas y entrada de texto.

La clave de posting se pide UNA vez por privado, se verifica contra la cadena (que sea de verdad la de
posting de esa cuenta), se guarda cifrada y el mensaje que la contiene se borra al instante. Nunca se
muestra, ni enmascarada. Todo lo demás (comunidad, tags, beneficiarios) se edita igual que una hora o un
destino: pulsando el botón del campo y respondiendo con el valor nuevo.

Nada de este módulo escribe la clave en un log, un error o una pantalla.
"""

import html
import re
import time

from telegram import InlineKeyboardButton as B
from telegram import InlineKeyboardMarkup

from core.ui import cb, fila_nav
from modules.publisher import hive, store
from modules.publisher.store import PubError

NS = "pub"
ESPERA_S = 300                       # cuánto espera el bot la respuesta de texto antes de olvidarla
CLAVE_ESTADO = "pub_espera"
MAX_BENEF = 8                        # tope del protocolo de Hive
MAX_TAGS = 8
TIPOS = {"w": ("hive_wave", "Wave (Ecency)"), "s": ("hive_snap", "Snap (PeakD)"), "b": ("hive_blog", "Blog")}
CAMPOS = {"c": "comunidad", "t": "tags", "b": "beneficiarios"}
_RE_CUENTA = re.compile(r"[a-z][a-z0-9.-]{1,14}[a-z0-9]")           # 3-16 caracteres
_RE_COMUNIDAD = re.compile(r"hive-\d{4,7}")


def _e(x) -> str:
    return html.escape(str(x))


# ---------- validadores (lanzan PubError con un mensaje que se puede mostrar) ----------
def parsear_nombre(texto: str) -> str:
    nombre = (texto or "").strip().lstrip("@").lower()
    if not _RE_CUENTA.fullmatch(nombre):
        raise PubError("Nombre de cuenta de Hive inválido (3-16 caracteres: letras minúsculas, números, punto o guion).")
    return nombre


def parsear_comunidad(texto: str) -> str:
    """'hive-123456' (también dentro de un enlace). '-' la quita."""
    t = (texto or "").strip().lower()
    if t in ("-", ""):
        return ""
    m = _RE_COMUNIDAD.search(t)
    if not m:
        raise PubError("No encontré un código de comunidad (hive-123456). Escribe «-» para dejarla vacía.")
    return m.group(0)


def parsear_tags(texto: str) -> list[str]:
    t = (texto or "").strip()
    if t in ("-", ""):
        return []
    vistos: list[str] = []
    for crudo in re.split(r"[\s,;]+", t):
        crudo = crudo.lstrip("#")
        if not crudo:
            continue
        tag = hive.slug(crudo, 24)
        if tag not in vistos:
            vistos.append(tag)
    if len(vistos) > MAX_TAGS:
        raise PubError(f"Demasiadas tags (máximo {MAX_TAGS}).")
    return vistos


def parsear_beneficiarios(texto: str) -> list[dict]:
    """'tasalo:5 otra:2.5' → [{'account': 'tasalo', 'weight': 500}, ...] (10000 = 100 %). '-' = ninguno."""
    t = (texto or "").strip()
    if t in ("-", ""):
        return []
    salida: list[dict] = []
    for tok in re.split(r"[\s,;]+", t):
        cuenta, sep, pct = tok.partition(":")
        if not sep:
            raise PubError(f"«{tok}»: usa cuenta:porcentaje, por ejemplo tasalo:5")
        cuenta = parsear_nombre(cuenta)
        try:
            p = float(pct.rstrip("%"))
        except ValueError:
            raise PubError(f"«{tok}»: el porcentaje no es un número") from None
        peso = round(p * 100)
        if not 1 <= peso <= 10000:
            raise PubError(f"«{tok}»: el porcentaje debe estar entre 0.01 y 100")
        if any(x["account"] == cuenta for x in salida):
            raise PubError(f"@{cuenta} aparece dos veces")
        salida.append({"account": cuenta, "weight": peso})
    if len(salida) > MAX_BENEF:
        raise PubError(f"Hive admite como máximo {MAX_BENEF} beneficiarios.")
    if sum(x["weight"] for x in salida) > 10000:
        raise PubError("Los beneficiarios suman más del 100 %.")
    return salida


def _pct(peso: int) -> str:
    return f"{peso / 100:g}%"


# ---------- pantallas puras ----------
def pantalla_cuentas(cuentas: list[dict], clave_maestra: bool, aviso: str = "") -> tuple[str, InlineKeyboardMarkup]:
    lineas = ["👤 <b>Cuentas de publicación</b>", ""]
    filas = []
    if not clave_maestra:
        lineas.append("⚠️ Falta <code>PUBLISHER_MASTER_KEY</code> en el .env del servidor: sin ella no se pueden guardar claves.\n")
    if cuentas:
        for c in cuentas:
            icono = "🟢" if c["activa"] else "⏸"
            clave = "🔑 clave guardada" if c["tiene_secreto"] else "⚠️ sin clave"
            lineas.append(f"{icono} {_e(c['red'])} @{_e(c['nombre'])} · {clave}")
            filas.append([B(f"{icono} @{c['nombre']}", callback_data=cb(NS, "c", c["id"]))])
    else:
        lineas.append("Aún no hay cuentas. Añade la de Hive con la que se publicará.")
    if aviso:
        lineas += ["", aviso]
    filas.append([B("➕ Cuenta de Hive", callback_data=cb(NS, "cn"))])
    filas.append(fila_nav(atras=cb(NS, "h"), inicio=None))
    return "\n".join(lineas), InlineKeyboardMarkup(filas)


def pantalla_cuenta(cuenta: dict, usos: list[dict], clave_maestra: bool = True, aviso: str = "") -> tuple[str, InlineKeyboardMarkup]:
    cid, p = cuenta["id"], cuenta["params"]
    benef = ", ".join(f"@{_e(b['account'])} {_pct(b['weight'])}" for b in p.get("beneficiarios") or []) or "ninguno"
    lineas = [
        f"👤 <b>@{_e(cuenta['nombre'])}</b> ({_e(cuenta['red'])})",
        f"Estado: {'🟢 activa' if cuenta['activa'] else '⏸ en pausa'}",
        "🔑 Clave de posting: " + ("✅ guardada (cifrada)" if cuenta["tiene_secreto"] else "⚠️ falta"),
        f"👥 Comunidad: {_e(p.get('comunidad') or '—')}",
        f"🏷 Tags: {_e(', '.join(p.get('tags') or []) or '—')}",
        f"💸 Beneficiarios (blog): {benef}",
        "",
        "<b>Usada en</b>" + ("" if usos else " — ningún trabajo todavía"),
    ]
    for u in usos:
        lineas.append(f"{'✅' if u['activo'] else '⏸'} {_e(u['job'])} → {_e(u['tipo'])}")
    if aviso:
        lineas += ["", aviso]
    filas = [
        [B("✏️ Clave", callback_data=cb(NS, "ce", cid, "k")), B("✏️ Comunidad", callback_data=cb(NS, "ce", cid, "c"))],
        [B("✏️ Tags", callback_data=cb(NS, "ce", cid, "t")), B("✏️ Beneficiarios", callback_data=cb(NS, "ce", cid, "b"))],
        [B("⏸ Pausar" if cuenta["activa"] else "▶️ Activar", callback_data=cb(NS, "ca", cid)),
         B("🗑 Borrar", callback_data=cb(NS, "cd", cid))],
        [B(f"➕ {nombre}", callback_data=cb(NS, "cl", cid, k)) for k, (_, nombre) in TIPOS.items()],
        fila_nav(atras=cb(NS, "cs"), inicio=None),
    ]
    return "\n".join(lineas), InlineKeyboardMarkup(filas)


_PEDIR = {
    "nombre": "👤 <b>Nueva cuenta de Hive</b>\nEscribe el nombre de la cuenta (con o sin @).",
    "comunidad": "👥 Escribe el código de la comunidad (<code>hive-123456</code>) o pega su enlace.\nEscribe «-» para dejarla vacía.",
    "tags": "🏷 Escribe las tags por defecto, separadas por espacios o comas (máximo 8). «-» para ninguna.\nSe suman a las que ponga cada publicación.",
    "beneficiarios": ("💸 Escribe los beneficiarios del blog como <code>cuenta:porcentaje</code>, por ejemplo "
                      "<code>tasalo:5 otra:2.5</code> (máximo 8, hasta 100 %). «-» para ninguno.\n"
                      "Solo afectan al blog; wave y snap no admiten beneficiarios."),
}


def pantalla_pedir(paso: str, campo: str | None = None, nombre: str | None = None) -> tuple[str, InlineKeyboardMarkup]:
    if paso == "clave":
        texto = (f"🔑 Envía ahora la clave de <b>posting</b> de @{_e(nombre)} (empieza por 5, 51 caracteres).\n\n"
                 "⚠️ Solo la de posting, nunca la activa ni la owner. Borro tu mensaje en cuanto lo recibo; "
                 "la guardo cifrada y no la vuelvo a mostrar.")
    else:
        texto = _PEDIR[campo if paso == "campo" else paso]
    return texto, InlineKeyboardMarkup([[B("↩️ Cancelar", callback_data=cb(NS, "cx"))]])


def pantalla_borrar(cuenta: dict, usos: list[dict]) -> tuple[str, InlineKeyboardMarkup]:
    texto = f"🗑 ¿Borrar la cuenta <b>@{_e(cuenta['nombre'])}</b> y su clave guardada?"
    if usos:
        texto += "\n\nSe desactivan estos destinos:\n" + "\n".join(f"• {_e(u['job'])} → {_e(u['tipo'])}" for u in usos)
    return texto, InlineKeyboardMarkup([[B("✅ Sí, borrar", callback_data=cb(NS, "cdc", cuenta["id"])),
                                         B("↩️ Cancelar", callback_data=cb(NS, "c", cuenta["id"]))]])


def pantalla_enlazar(cuenta: dict, tipo: str, jobs: list[dict]) -> tuple[str, InlineKeyboardMarkup]:
    nombre = TIPOS[tipo][1]
    if not jobs:
        return "Aún no hay trabajos. Crea uno en /pub.", InlineKeyboardMarkup([fila_nav(atras=cb(NS, "c", cuenta["id"]), inicio=None)])
    filas = [[B(j["nombre"], callback_data=cb(NS, "cj", cuenta["id"], tipo, j["id"]))] for j in jobs]
    filas.append(fila_nav(atras=cb(NS, "c", cuenta["id"]), inicio=None))
    return f"➕ ¿En qué trabajo publica <b>@{_e(cuenta['nombre'])}</b> como {_e(nombre)}?", InlineKeyboardMarkup(filas)


# ---------- entrada de texto (estado en context.user_data, caduca solo) ----------
def iniciar(user_data: dict, **estado) -> None:
    user_data[CLAVE_ESTADO] = {**estado, "t": time.monotonic()}


def vigente(user_data: dict) -> dict | None:
    st = user_data.get(CLAVE_ESTADO)
    if st is not None and time.monotonic() - st["t"] > ESPERA_S:
        user_data.pop(CLAVE_ESTADO, None)
        return None
    return st


def cancelar(user_data: dict) -> None:
    user_data.pop(CLAVE_ESTADO, None)


async def procesar(user_data: dict, texto: str) -> tuple[str, int | None]:
    """Aplica la respuesta del dueño al paso en curso.

    Devuelve (mensaje, cuenta_id). cuenta_id None = el flujo sigue (el mensaje es la siguiente pregunta).
    Lanza PubError/HiveError/SecretoError con un texto seguro (nunca la clave); el paso queda abierto
    para reintentar.
    """
    st = vigente(user_data)
    if st is None:
        raise PubError("La espera caducó. Vuelve a empezar desde /pub → Cuentas.")
    paso = st["paso"]
    if paso == "nombre":
        nombre = parsear_nombre(texto)
        iniciar(user_data, paso="clave", nombre=nombre)
        return pantalla_pedir("clave", nombre=nombre)[0], None
    if paso == "clave":
        await hive.verificar_clave(st["nombre"], texto)               # lanza si no es la de posting de la cuenta
        cid = await store.guardar_cuenta("hive", st["nombre"], texto.strip())
        cancelar(user_data)
        return "✅ Clave verificada y guardada cifrada.", cid
    if paso == "campo":
        cuenta = await store.get_cuenta(st["cuenta_id"])
        if cuenta is None:
            cancelar(user_data)
            raise PubError("La cuenta ya no existe.")
        campo = st["campo"]
        valor = {"comunidad": parsear_comunidad, "tags": parsear_tags, "beneficiarios": parsear_beneficiarios}[campo](texto)
        params = dict(cuenta["params"])
        if valor:
            params[campo] = valor
        else:
            params.pop(campo, None)
        await store.editar_cuenta(cuenta["id"], params=params)
        cancelar(user_data)
        return "✅ Guardado.", cuenta["id"]
    cancelar(user_data)
    raise PubError("Paso desconocido. Vuelve a empezar desde /pub.")
