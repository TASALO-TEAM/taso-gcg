import importlib
import pathlib
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from core.registry import Cmd, Topic
from modules import start

RAIZ = pathlib.Path(__file__).resolve().parent.parent
TOPICS = (Topic("bans", "🔨 Bans", aliases=("ban",), nota="Ej: 1h < 1d"), Topic("inicio", "🏠 Inicio"))
CMDS = (
    Cmd("ban", "Banea", level="admin", topic="bans", uso="<1h|30m>"),
    Cmd("stats", "Estado", level="sudo", topic="bans"),
    Cmd("help", "Ayuda", topic="inicio"),
)


def _registro_real():
    nombres = sorted(p.stem for p in (RAIZ / "modules").glob("*.py") if not p.stem.startswith("_"))
    cmds, topics = [], []
    for n in nombres + ["rss.handlers"]:
        mod = importlib.import_module(f"modules.{n}")
        cmds += getattr(mod, "COMMANDS", ())
        if getattr(mod, "TOPIC", None) is not None:
            topics.append(mod.TOPIC)
    return tuple(cmds), tuple(topics)


def _contexto(cmds=CMDS, topics=TOPICS, args=()):
    app = SimpleNamespace(bot_data={"cmds": cmds, "topics": topics})
    return SimpleNamespace(application=app, args=list(args))


def test_orden_de_temas_inicio_primero_y_desconocidos_al_final():
    ts = [Topic("zzz", "Z"), Topic("rss", "R"), Topic("inicio", "I"), Topic("bans", "B")]
    assert [t.key for t in start._ordenados(ts)] == ["inicio", "bans", "rss", "zzz"]


def test_texto_tema_marca_niveles_escapa_html_e_incluye_nota():
    txt = start.texto_tema(TOPICS[0], CMDS)
    assert "<b>🔨 Bans</b>" in txt
    assert "🔒 /ban &lt;1h|30m&gt; — Banea" in txt
    assert "👑 /stats — Estado" in txt
    assert "Ej: 1h &lt; 1d" in txt
    assert "/help" not in txt  # otro tema


def test_help_cubre_todos_los_comandos_reales_y_cabe_en_un_mensaje():
    cmds, topics = _registro_real()
    for t in topics:
        txt = start.texto_tema(t, cmds)
        assert len(txt) < 4096, t.key
        for c in cmds:
            if c.topic == t.key:
                assert f"/{c.name}" in txt
    # todo comando pertenece a un tema que /help muestra
    assert {c.topic for c in cmds} <= {t.key for t in topics}


def test_teclado_resumen_dos_por_fila_y_prefijo_help():
    kb = start.teclado_resumen(TOPICS).inline_keyboard
    assert [b.callback_data for fila in kb for b in fila] == ["help:bans", "help:inicio"]
    assert len(kb) == 1 and len(kb[0]) == 2


@pytest.mark.asyncio
async def test_help_con_alias_muestra_el_tema():
    msg = SimpleNamespace(reply_text=AsyncMock())
    await start.help_cmd(SimpleNamespace(effective_message=msg), _contexto(args=["BAN"]))
    assert "🔨 Bans" in msg.reply_text.call_args.args[0]


@pytest.mark.asyncio
async def test_help_con_tema_desconocido_avisa():
    msg = SimpleNamespace(reply_text=AsyncMock())
    await start.help_cmd(SimpleNamespace(effective_message=msg), _contexto(args=["nada"]))
    assert "No conozco el tema" in msg.reply_text.call_args.args[0]


@pytest.mark.asyncio
async def test_help_sin_args_manda_resumen_con_botones():
    msg = SimpleNamespace(reply_text=AsyncMock())
    await start.help_cmd(SimpleNamespace(effective_message=msg), _contexto())
    assert msg.reply_text.call_args.kwargs["reply_markup"] is not None


def _update_boton(data, user_id):
    q = MagicMock()
    q.data = data
    q.from_user.id = user_id
    q.answer = AsyncMock()
    q.edit_message_text = AsyncMock()
    return SimpleNamespace(callback_query=q, effective_chat=SimpleNamespace(send_message=AsyncMock())), q


@pytest.mark.asyncio
async def test_boton_de_tema_edita_el_mensaje_y_responde_la_query_una_vez():
    update, q = _update_boton("help:bans", user_id=9001)
    await start._on_help_button(update, _contexto())
    q.answer.assert_awaited_once()
    assert "🔨 Bans" in q.edit_message_text.call_args.args[0]


@pytest.mark.asyncio
async def test_boton_volver_regresa_al_resumen():
    update, q = _update_boton("help:volver", user_id=9002)
    await start._on_help_button(update, _contexto())
    assert "Toca un tema" in q.edit_message_text.call_args.args[0]


@pytest.mark.asyncio
async def test_boton_de_tema_inexistente_no_edita_nada():
    update, q = _update_boton("help:viejo", user_id=9003)
    await start._on_help_button(update, _contexto())
    q.edit_message_text.assert_not_awaited()
