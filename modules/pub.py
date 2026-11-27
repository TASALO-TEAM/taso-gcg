"""Módulo pub - /pub: panel de la publicación automática (solo SUDO, solo por privado).

Pantallas puras (`pantalla_*`) que reciben los datos ya leídos; los handlers solo leen la base,
llaman a una pantalla y la dibujan. Todo se edita desde aquí: pausar/activar, hora (±15 min),
destinos, modo prueba y "probar / publicar ahora". Los secretos (Hive, Nostr) llegan con sus
destinos; este panel nunca los muestra.
"""

import html
from datetime import datetime

from telegram import InlineKeyboardButton as B
from telegram import InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes, MessageHandler, filters

from core import secrets as _secretos
from core.config import PUB_DRY_RUN, SUDO_USERS
from core.registry import Cmd, Topic
from core.ui import cb, fila_nav, guard_callback, mostrar, parse
from modules.publisher import cuentas, hive
from modules.publisher import destinos as _destinos  # noqa: F401  (registra los destinos)
from modules.publisher import destinos_hive as _destinos_hive  # noqa: F401  (registra los destinos de Hive)
from modules.publisher import fuentes as _fuentes  # noqa: F401  (registra las fuentes)
from modules.publisher import store
from modules.publisher.scheduler import TZ, ejecutar_job
from utils.decorators import sudo_only

__mod_name__ = "Publicación"

TOPIC = Topic(
    "pub", "📣 Publicación automática", aliases=("publicar", "publicacion"),
    nota="Solo para el equipo TASALO y por privado. Empieza en modo prueba: arma lo que publicaría "
         "sin enviar nada hasta que lo desactives en el panel.",
)
COMMANDS = (
    Cmd("pub", "Panel de publicación automática (horas, destinos, pruebas)", level="sudo", ambito="privado", topic="pub", menu=True),
    Cmd("pubdest", "Añadir un canal de Telegram como destino de un trabajo", level="sudo", ambito="privado", topic="pub", uso="<id_trabajo> <@canal|id>"),
)

NS = "pub"
ACCIONES_CUENTA = {"cs", "c", "cn", "cx", "ce", "ca", "cd", "cdc", "cl", "cj"}
PASO_MIN = 15
ICONO_ESTADO = {"ok": "✅", "simulado": "🧪", "error": "❌", "reservado": "⏳"}
FUENTE_NOMBRE = {"year": "Estado del año", "tspl": "Resumen TSPL"}
# Trabajos que el panel sabe crear con un toque: fuente -> (nombre, etiqueta del botón). Salen a las 8:30 Cuba
# hacia @tasalospl; el estado del año va primero si coinciden (ver store.listar_jobs).
PLANTILLAS = {
    "year": ("Estado del año", "➕ Estado del año → @tasalospl"),
    "tspl": ("Resumen TSPL", "➕ Resumen TSPL → @tasalospl"),
}


def _e(x) -> str:
    return html.escape(str(x))


def hhmm(job: dict) -> str:
    return f"{job['hora']:02d}:{job['minuto']:02d}"


def desplazar(job: dict, delta: int) -> tuple[int, int]:
    """Hora y minuto tras sumar `delta` minutos (da la vuelta a las 24 h)."""
    total = (job["hora"] * 60 + job["minuto"] + delta) % 1440
    return total // 60, total % 60


def _dias(job: dict) -> str:
    if job["dias"] == "*":
        return "todos los días"
    nombres = "lun mar mié jue vie sáb dom".split()
    return ", ".join(nombres[int(d)] for d in job["dias"].split(",") if d.isdigit() and int(d) < 7)


def _destino_txt(d: dict) -> str:
    extra = d["params"].get("chat") or (f"@{d['cuenta_nombre']}" if d.get("cuenta_nombre") else "")
    return f"{d['tipo']} {extra}".strip()


def pantalla_home(jobs: list[dict], prueba: bool) -> tuple[str, InlineKeyboardMarkup]:
    lineas = ["📣 <b>Publicación automática</b>", ""]
    lineas.append("🧪 Modo prueba: <b>ACTIVADO</b> (lo programado no se envía)" if prueba
                  else "🟢 Modo real: <b>se publica de verdad</b>")
    filas = []
    if jobs:
        lineas.append("")
        for j in jobs:
            icono = "▶️" if j["activo"] else "⏸"
            lineas.append(f"{icono} <b>{_e(j['nombre'])}</b> · {hhmm(j)} (Cuba) · {_dias(j)}")
            filas.append([B(f"{icono} {j['nombre']}", callback_data=cb(NS, "j", j["id"]))])
    else:
        lineas += ["", "Aún no hay trabajos. Crea el primero:"]
    for fuente, (_, etiqueta) in PLANTILLAS.items():
        if not any(j["fuente"] == fuente for j in jobs):
            filas.append([B(etiqueta, callback_data=cb(NS, "new", fuente))])
    filas.append([B("👤 Cuentas (Hive)", callback_data=cb(NS, "cs"))])
    filas.append([B("🔄 Pasar a modo real" if prueba else "🧪 Pasar a modo prueba", callback_data=cb(NS, "pm"))])
    return "\n".join(lineas), InlineKeyboardMarkup(filas)


def pantalla_job(job: dict, destinos: list[dict], historial: list[dict], prueba: bool,
                 aviso: str = "") -> tuple[str, InlineKeyboardMarkup]:
    jid = job["id"]
    lineas = [
        f"📣 <b>{_e(job['nombre'])}</b> ({_e(FUENTE_NOMBRE.get(job['fuente'], job['fuente']))})",
        f"🕗 {hhmm(job)} hora de Cuba · {_dias(job)}",
        f"Estado: {'▶️ activo' if job['activo'] else '⏸ en pausa'}"
        + (" · 🧪 modo prueba" if prueba else ""),
        "",
        "<b>Destinos</b>" + ("" if destinos else " — ninguno. Añade uno con /pubdest"),
    ]
    filas = [
        [B("⏸ Pausar" if job["activo"] else "▶️ Activar", callback_data=cb(NS, "ja", jid))],
        [B(f"⏪ −{PASO_MIN} min", callback_data=cb(NS, "hm", jid, -PASO_MIN)),
         B(f"⏩ +{PASO_MIN} min", callback_data=cb(NS, "hm", jid, PASO_MIN))],
    ]
    for d in destinos:
        icono = "✅" if d["activo"] else "⏸"
        lineas.append(f"{icono} {_e(_destino_txt(d))}")
        filas.append([B(f"{icono} {_destino_txt(d)}", callback_data=cb(NS, "da", d["id"]))])
    if historial:
        lineas += ["", "<b>Últimas ejecuciones</b>"]
        for h in historial[:3]:
            fila = f"{ICONO_ESTADO.get(h['estado'], '•')} {_e(h['fecha'])}"
            if h.get("url"):
                fila += f" · {_e(h['url'])}"
            if h.get("error"):
                fila += f" · {_e(h['error'][:80])}"
            lineas.append(fila)
    if aviso:
        lineas += ["", aviso]
    filas.append([B("🧪 Probar (no envía)", callback_data=cb(NS, "t", jid)),
                  B("📤 Publicar ahora", callback_data=cb(NS, "n", jid))])
    filas.append(fila_nav(atras=cb(NS, "h"), inicio=None))
    return "\n".join(lineas), InlineKeyboardMarkup(filas)


def pantalla_confirmar(job: dict, destinos: list[dict]) -> tuple[str, InlineKeyboardMarkup]:
    activos = [d for d in destinos if d["activo"]]
    if not activos:
        texto = f"No hay destinos activos en <b>{_e(job['nombre'])}</b>."
        return texto, InlineKeyboardMarkup([fila_nav(atras=cb(NS, "j", job["id"]), inicio=None)])
    lista = "\n".join(f"• {_e(_destino_txt(d))}" for d in activos)
    texto = (f"📤 <b>Publicar ahora</b> «{_e(job['nombre'])}» DE VERDAD en:\n{lista}\n\n"
             "Es un envío extra: no cuenta como la publicación programada de hoy y se hace "
             "aunque el modo prueba esté activado.")
    return texto, InlineKeyboardMarkup([[B("✅ Sí, publicar", callback_data=cb(NS, "nc", job["id"])),
                                         B("↩️ Cancelar", callback_data=cb(NS, "j", job["id"]))]])


def resumen(filas: list[dict]) -> str:
    if not filas:
        return "Sin resultados (¿no había destinos activos?)."
    partes = []
    for f in filas:
        linea = f"{ICONO_ESTADO.get(f['estado'], '•')} {_e(f['tipo'])}"
        if f.get("url"):
            linea += f" · {_e(f['url'])}"
        if f.get("error"):
            linea += f" · {_e(f['error'][:120])}"
        partes.append(linea)
    return "\n".join(partes)


# ---------- handlers ----------
def _privado(update: Update) -> bool:
    return update.effective_chat.type == "private"


async def _home():
    return pantalla_home(await store.listar_jobs(), await store.modo_prueba(PUB_DRY_RUN))


async def _job(job_id: int, aviso: str = ""):
    job = await store.get_job(job_id)
    if job is None:
        return await _home()
    destinos = await store.listar_destinos(job_id)
    for d in destinos:                      # los destinos de Hive se muestran con su cuenta
        if d["cuenta_id"]:
            c = await store.get_cuenta(d["cuenta_id"])
            d["cuenta_nombre"] = c["nombre"] if c else None
    return pantalla_job(job, destinos, await store.historial(job_id, 3),
                        await store.modo_prueba(PUB_DRY_RUN), aviso)


async def _lista_cuentas(aviso: str = ""):
    return cuentas.pantalla_cuentas(await store.listar_cuentas(), _secretos.disponible(), aviso)


async def _cuenta(cuenta_id: int, aviso: str = ""):
    c = await store.get_cuenta(cuenta_id)
    if c is None:
        return await _lista_cuentas()
    return cuentas.pantalla_cuenta(c, await store.destinos_de_cuenta(cuenta_id), _secretos.disponible(), aviso)


async def _cuentas_accion(accion: str, a: tuple, context) -> tuple[str, InlineKeyboardMarkup]:
    """Acciones de cuentas (`pub:c*`). Las que piden texto dejan el estado en context.user_data."""
    sin_clave_maestra = "⚠️ Falta PUBLISHER_MASTER_KEY en el .env del servidor: no puedo guardar claves."
    if accion == "cs":
        cuentas.cancelar(context.user_data)
        return await _lista_cuentas()
    if accion == "c":
        return await _cuenta(int(a[0]))
    if accion == "cn":
        if not _secretos.disponible():
            return await _lista_cuentas(sin_clave_maestra)
        cuentas.iniciar(context.user_data, paso="nombre")
        return cuentas.pantalla_pedir("nombre")
    if accion == "cx":
        cuentas.cancelar(context.user_data)
        return await _lista_cuentas()
    cuenta = await store.get_cuenta(int(a[0]))
    if cuenta is None:
        return await _lista_cuentas()
    if accion == "ce":
        campo = a[1]
        if campo == "k":
            if not _secretos.disponible():
                return await _cuenta(cuenta["id"], sin_clave_maestra)
            cuentas.iniciar(context.user_data, paso="clave", nombre=cuenta["nombre"])
            return cuentas.pantalla_pedir("clave", nombre=cuenta["nombre"])
        if campo not in cuentas.CAMPOS:
            raise ValueError("Botón antiguo")
        cuentas.iniciar(context.user_data, paso="campo", campo=cuentas.CAMPOS[campo], cuenta_id=cuenta["id"])
        return cuentas.pantalla_pedir("campo", campo=cuentas.CAMPOS[campo])
    if accion == "ca":
        await store.editar_cuenta(cuenta["id"], activa=not cuenta["activa"])
        return await _cuenta(cuenta["id"])
    if accion == "cd":
        return cuentas.pantalla_borrar(cuenta, await store.destinos_de_cuenta(cuenta["id"]))
    if accion == "cdc":
        await store.borrar_cuenta(cuenta["id"])
        return await _lista_cuentas(f"🗑 @{_e(cuenta['nombre'])} borrada.")
    if accion == "cl":
        if a[1] not in cuentas.TIPOS:
            raise ValueError("Botón antiguo")
        return cuentas.pantalla_enlazar(cuenta, a[1], await store.listar_jobs())
    if accion == "cj":
        tipo = cuentas.TIPOS[a[1]][0]
        job_id = int(a[2])
        if any(d["tipo"] == tipo and d["cuenta_id"] == cuenta["id"] for d in await store.listar_destinos(job_id)):
            return await _cuenta(cuenta["id"], "ℹ️ Esa cuenta ya publica así en ese trabajo.")
        await store.agregar_destino(job_id, tipo, cuenta_id=cuenta["id"])
        return await _cuenta(cuenta["id"], f"✅ Añadido: {_e(tipo)}. Revísalo en el trabajo y pulsa 🧪 Probar.")
    raise ValueError("Botón antiguo")


async def _previa(job: dict) -> str:
    """Vista previa del texto que armaría la fuente (para que se vea el formato antes de publicar)."""
    from modules.publisher.base import FUENTES
    try:
        c = await FUENTES[job["fuente"]]()
    except Exception as e:
        return f"⚠️ La fuente falló: {_e(type(e).__name__)}: {_e(str(e)[:150])}"
    return f"<b>Vista previa</b>\n<pre>{_e(c.texto_corto[:900])}</pre>"


async def _despachar(accion: str, a: tuple, context) -> tuple[str, InlineKeyboardMarkup]:
    if accion in ACCIONES_CUENTA:
        return await _cuentas_accion(accion, a, context)
    if accion == "j":
        return await _job(int(a[0]))
    if accion == "ja":
        job = await store.get_job(int(a[0]))
        if job:
            await store.editar_job(job["id"], activo=0 if job["activo"] else 1)
        return await _job(int(a[0]))
    if accion == "hm":
        job = await store.get_job(int(a[0]))
        if job:
            h, m = desplazar(job, int(a[1]))
            await store.editar_job(job["id"], hora=h, minuto=m)
        return await _job(int(a[0]))
    if accion == "da":
        d = await store.get_destino(int(a[0]))
        if d is None:
            return await _home()
        await store.editar_destino(d["id"], activo=0 if d["activo"] else 1)
        return await _job(d["job_id"])
    if accion == "pm":
        await store.set_modo_prueba(not await store.modo_prueba(PUB_DRY_RUN))
        return await _home()
    if accion == "new" and a and a[0] in PLANTILLAS:
        job_id = await store.crear_job(PLANTILLAS[a[0]][0], a[0], 8, 30)
        await store.agregar_destino(job_id, "telegram", params={"chat": "@tasalospl"})
        return await _job(job_id, "Creado. Revisa la hora y pulsa 🧪 Probar antes de pasar a modo real.")
    if accion in ("t", "n", "nc"):
        job = await store.get_job(int(a[0]))
        if job is None:
            return await _home()
        ahora = datetime.now(TZ)
        if accion == "n":
            return pantalla_confirmar(job, await store.listar_destinos(job["id"]))
        simular = accion == "t"
        fecha = f"{ahora:%Y-%m-%d}~{'p' if simular else 'a'}{ahora:%H%M%S}"
        await ejecutar_job(job, fecha, context.bot, simular=simular)
        filas = await store.log_de(job["id"], fecha + ("~sim" if simular else ""))
        aviso = ("🧪 <b>Prueba</b>" if simular else "📤 <b>Publicado</b>") + "\n" + resumen(filas)
        if simular:
            aviso += "\n\n" + await _previa(job)
        return await _job(job["id"], aviso)
    return await _home()


@sudo_only
async def pub_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _privado(update):
        await update.effective_message.reply_text("🔒 Abre /pub por privado conmigo.")
        return
    texto, teclado = await _home()
    await update.effective_message.reply_text(texto, parse_mode=ParseMode.HTML, reply_markup=teclado)


@sudo_only
async def pubdest_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    if not _privado(update):
        await msg.reply_text("🔒 Usa /pubdest por privado conmigo.")
        return
    if len(context.args) != 2 or not context.args[0].isdigit():
        await msg.reply_text("Uso: /pubdest <id_trabajo> <@canal|id>\nEl id del trabajo sale en /pub.")
        return
    try:
        chat = _destinos._chat({"chat": context.args[1]})
        await store.agregar_destino(int(context.args[0]), "telegram", params={"chat": chat})
    except (ValueError, store.PubError) as e:   # PubError ya es ValueError; se deja explícito
        await msg.reply_text(f"⚠️ {_e(e)}")
        return
    aviso = ""
    try:
        miembro = await context.bot.get_chat_member(chat, context.bot.id)
        if miembro.status not in ("administrator", "creator"):
            aviso = "\n⚠️ El bot no es administrador de ese chat: hazlo admin con permiso de publicar."
    except Exception:
        aviso = "\n⚠️ No pude comprobar que el bot sea administrador de ese chat."
    await msg.reply_text(f"✅ Destino telegram {_e(chat)} añadido al trabajo {int(context.args[0])}.{aviso}",
                         parse_mode=ParseMode.HTML)


@guard_callback("sudo")  # ya responde la query: aquí no se llama a query.answer()
async def _on_pub(update: Update, context: ContextTypes.DEFAULT_TYPE):
    parsed = parse(update.callback_query.data or "")
    args = parsed[1] if parsed else ()
    try:
        texto, teclado = await _despachar(args[0] if args else "h", args[1:], context)
    except (ValueError, IndexError) as e:      # PubError, id mal formado, botón viejo
        texto, teclado = await _home()
        texto = f"⚠️ {_e(e)}\n\n{texto}"
    await mostrar(update, texto, teclado)


async def _borrar(msg) -> bool:
    """Borra el mensaje del dueño (el que lleva la clave). False si Telegram no lo permite."""
    try:
        await msg.delete()
        return True
    except Exception:
        return False


async def _on_texto(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Respuesta de texto a una pregunta del panel de cuentas. Sin pregunta abierta no hace nada."""
    msg = update.effective_message
    user = update.effective_user
    if not (msg and msg.text and user and user.id in SUDO_USERS and _privado(update)):
        return
    st = cuentas.vigente(context.user_data)
    if st is None:
        return
    borrado = True
    if st["paso"] == "clave":                  # lo primero: que la clave no quede en el chat
        borrado = await _borrar(msg)
    try:
        texto, cid = await cuentas.procesar(context.user_data, msg.text)
    except (ValueError, hive.HiveError, _secretos.SecretoError) as e:   # mensajes que nunca llevan la clave
        _, teclado = cuentas.pantalla_pedir("nombre")                    # solo se usa su botón de cancelar
        await msg.chat.send_message(f"⚠️ {_e(e)}\nInténtalo de nuevo o cancela.", parse_mode=ParseMode.HTML, reply_markup=teclado)
        return
    if not borrado:
        texto += "\n⚠️ No pude borrar tu mensaje con la clave: bórralo tú ahora."
    if cid is None:                            # el flujo sigue: `texto` es la siguiente pregunta
        _, teclado = cuentas.pantalla_pedir("nombre")
        await msg.chat.send_message(texto, parse_mode=ParseMode.HTML, reply_markup=teclado)
        return
    pantalla, teclado = await _cuenta(cid, texto)
    await msg.chat.send_message(pantalla, parse_mode=ParseMode.HTML, reply_markup=teclado)


def register(application: Application, sudo_users):
    application.add_handler(CommandHandler("pub", pub_cmd))
    application.add_handler(CommandHandler("pubdest", pubdest_cmd))
    application.add_handler(CallbackQueryHandler(_on_pub, pattern=f"^{NS}:"))
    # group=7: aparte del resto; sin pregunta abierta devuelve enseguida y no bloquea a nadie.
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND & filters.ChatType.PRIVATE, _on_texto), group=7)
