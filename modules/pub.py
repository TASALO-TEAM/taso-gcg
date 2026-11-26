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
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes

from core.config import PUB_DRY_RUN
from core.registry import Cmd, Topic
from core.ui import cb, fila_nav, guard_callback, mostrar, parse
from modules.publisher import destinos as _destinos  # noqa: F401  (registra los destinos)
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
PASO_MIN = 15
ICONO_ESTADO = {"ok": "✅", "simulado": "🧪", "error": "❌", "reservado": "⏳"}
FUENTE_NOMBRE = {"year": "Estado del año", "tspl": "Blog TSPL"}


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
    extra = d["params"].get("chat", "")
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
    if not any(j["fuente"] == "year" for j in jobs):
        filas.append([B("➕ Estado del año → @tasalospl", callback_data=cb(NS, "new", "year"))])
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
    return pantalla_job(job, await store.listar_destinos(job_id), await store.historial(job_id, 3),
                        await store.modo_prueba(PUB_DRY_RUN), aviso)


async def _previa(job: dict) -> str:
    """Vista previa del texto que armaría la fuente (para que se vea el formato antes de publicar)."""
    from modules.publisher.base import FUENTES
    try:
        c = await FUENTES[job["fuente"]]()
    except Exception as e:
        return f"⚠️ La fuente falló: {_e(type(e).__name__)}: {_e(str(e)[:150])}"
    return f"<b>Vista previa</b>\n<pre>{_e(c.texto_corto[:900])}</pre>"


async def _despachar(accion: str, a: tuple, context) -> tuple[str, InlineKeyboardMarkup]:
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
    if accion == "new" and a and a[0] == "year":
        job_id = await store.crear_job("Estado del año", "year", 8, 30)
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


def register(application: Application, sudo_users):
    application.add_handler(CommandHandler("pub", pub_cmd))
    application.add_handler(CommandHandler("pubdest", pubdest_cmd))
    application.add_handler(CallbackQueryHandler(_on_pub, pattern=f"^{NS}:"))
