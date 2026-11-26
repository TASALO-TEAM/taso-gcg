from types import SimpleNamespace

import pytest
from telegram import Chat, InaccessibleMessage
from telegram.error import BadRequest

from core import ui


class FakeQ:
    def __init__(self, user_id=1, data="x:1", message="ok", chat_id=-100):
        self.from_user = SimpleNamespace(id=user_id)
        self.data = data
        self.message = SimpleNamespace(chat=SimpleNamespace(id=chat_id)) if message == "ok" else message
        self.respuestas = []

    async def answer(self, text=None, show_alert=False):
        self.respuestas.append((text, show_alert))


def upd(q):
    return SimpleNamespace(callback_query=q)


@pytest.fixture(autouse=True)
def limpio(monkeypatch):
    ui._ultimo.clear()
    reloj = {"t": 100.0}
    monkeypatch.setattr(ui, "_ahora", lambda: reloj["t"])
    monkeypatch.setattr(ui, "SUDO_USERS", {99})
    return reloj


def handler_de(nivel="todos", objetivo=None):
    llamadas = []

    @ui.guard_callback(nivel, objetivo)
    async def h(update, context):
        llamadas.append(update.callback_query.data)

    return h, llamadas


# --- callback_data v2 ---

def test_cb_y_parse():
    assert ui.cb("rss", "del", 12) == "rss:del:12"
    assert ui.parse("rss:del:12") == ("rss", ("del", "12"))
    assert ui.parse("menu") == ("menu", ())
    assert ui.parse("Mal_Formato:1") is None


@pytest.mark.parametrize("ns,args", [("Mal", ()), ("a_b", ()), ("ok", ("x:y",)), ("ok", ("z" * 70,))])
def test_cb_rechaza_invalidos(ns, args):
    with pytest.raises(ValueError):
        ui.cb(ns, *args)


# --- guard_callback ---

async def test_no_admin_recibe_alerta_y_no_se_ejecuta(monkeypatch):
    async def no_admin(ctx, chat, user):
        return False
    monkeypatch.setattr(ui, "is_user_admin", no_admin)
    h, llamadas = handler_de("admin")
    q = FakeQ()
    await h(upd(q), None)
    assert llamadas == []
    assert q.respuestas == [("🚫 Solo para administradores.", True)]


async def test_admin_se_ejecuta_y_la_query_se_responde_una_vez(monkeypatch):
    async def si_admin(ctx, chat, user):
        return True
    monkeypatch.setattr(ui, "is_user_admin", si_admin)
    h, llamadas = handler_de("admin")
    q = FakeQ()
    await h(upd(q), None)
    assert llamadas == ["x:1"]
    assert q.respuestas == [(None, False)]


async def test_permisos_se_comprueban_en_el_chat_objetivo(monkeypatch):
    vistos = []

    async def admin_solo_en_77(ctx, chat, user):
        vistos.append(chat)
        return chat == 77

    async def objetivo(update, context):
        return 77

    monkeypatch.setattr(ui, "is_user_admin", admin_solo_en_77)
    h, llamadas = handler_de("admin", objetivo)
    await h(upd(FakeQ(chat_id=-100)), None)
    assert vistos == [77] and llamadas == ["x:1"]


async def test_objetivo_none_rechaza(monkeypatch):
    async def objetivo(update, context):
        return None
    h, llamadas = handler_de("admin", objetivo)
    q = FakeQ()
    await h(upd(q), None)
    assert llamadas == [] and q.respuestas[0][1] is True


async def test_nivel_sudo():
    h, llamadas = handler_de("sudo")
    await h(upd(FakeQ(user_id=5)), None)
    await h(upd(FakeQ(user_id=99, data="x:2")), None)
    assert llamadas == ["x:2"]


async def test_boton_caducado_no_revienta():
    h, llamadas = handler_de()
    muerto = InaccessibleMessage(chat=Chat(id=1, type="private"), message_id=1)
    q = FakeQ(message=muerto)
    await h(upd(q), None)
    assert llamadas == []
    assert q.respuestas[0][1] is True
    q2 = FakeQ(message=None)
    await h(upd(q2), None)
    assert llamadas == []


async def test_doble_toque_se_descarta_y_pasado_el_tiempo_se_acepta(limpio):
    h, llamadas = handler_de()
    await h(upd(FakeQ()), None)
    await h(upd(FakeQ()), None)
    assert llamadas == ["x:1"]
    limpio["t"] += 2
    await h(upd(FakeQ()), None)
    assert llamadas == ["x:1", "x:1"]


async def test_message_is_not_modified_se_ignora_y_otros_errores_suben():
    @ui.guard_callback()
    async def igual(update, context):
        raise BadRequest("Message is not modified: exactly the same")

    @ui.guard_callback()
    async def roto(update, context):
        raise BadRequest("Chat not found")

    await igual(upd(FakeQ(data="a:1")), None)
    with pytest.raises(BadRequest):
        await roto(upd(FakeQ(data="b:1")), None)


async def test_sin_callback_query_no_hace_nada():
    h, llamadas = handler_de()
    await h(SimpleNamespace(callback_query=None), None)
    assert llamadas == []


# --- paginación y navegación ---

@pytest.mark.parametrize("n,pagina,esperado", [
    (0, 0, ([], 0, 1)),
    (1, 0, ([0], 0, 1)),
    (5, 0, ([0, 1, 2, 3, 4], 0, 1)),
    (6, 1, ([5], 1, 2)),
    (6, 9, ([5], 1, 2)),
    (6, -3, ([0, 1, 2, 3, 4], 0, 2)),
])
def test_paginar(n, pagina, esperado):
    assert ui.paginar(range(n), pagina) == esperado


def test_fila_paginas():
    assert ui.fila_paginas("feeds", 0, 1) == []
    textos = [b.text for b in ui.fila_paginas("feeds", 1, 3, "x")]
    assert textos == ["◀", "2/3", "▶"]
    for b in ui.fila_paginas("feeds", 1, 3, "x"):
        assert len(b.callback_data.encode()) <= 64


def test_fila_nav():
    assert [b.text for b in ui.fila_nav("a:b")] == ["⬅️ Atrás", "🏠 Inicio"]
    assert [b.text for b in ui.fila_nav(None, None)] == []
