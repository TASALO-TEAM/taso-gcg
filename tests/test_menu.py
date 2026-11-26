"""/menu: cada pantalla es alcanzable, cabe en Telegram y respeta permisos y tipo de chat."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from core import ui
from core.ui import parse
from modules import menu
from scripts import gen_comandos

CMDS, TOPICS, _ = gen_comandos.recoger()

SUDO = {"todos", "admin", "sudo"}
ADMIN = {"todos", "admin"}
USUARIO = {"todos"}
PERFILES = {
    "sudo en privado": (SUDO, True),
    "admin en grupo": (ADMIN, False),
    "usuario en grupo": (USUARIO, False),
    "usuario en privado": (USUARIO, True),
}


def _botones(teclado):
    return [b for fila in teclado.inline_keyboard for b in fila]


def _alcanzables(niveles, privado):
    """Recorre desde el inicio todo botón `menu:` y devuelve [(args, texto, teclado)]."""
    pendientes, vistos, salida = [("home",)], set(), []
    while pendientes:
        args = pendientes.pop()
        if args in vistos:
            continue
        vistos.add(args)
        texto, teclado = menu.pantalla(args, CMDS, TOPICS, niveles, privado)
        salida.append((args, texto, teclado))
        for b in _botones(teclado):
            p = parse(b.callback_data)
            if p and p[0] == menu.NS:
                pendientes.append(p[1])
    return salida


def test_todo_tema_pertenece_a_una_seccion():
    """Un módulo nuevo con tema propio debe añadirse a SECCIONES o no sería alcanzable."""
    en_secciones = {k for _, _, claves in menu.SECCIONES for k in claves}
    claves = {t.key for t in TOPICS}
    assert claves - en_secciones - menu.FUERA_DE_SECCIONES == set()
    assert en_secciones <= claves, "SECCIONES nombra un tema que ya no existe"


def test_inicio_segun_permisos():
    def titulos(niveles, privado):
        _, kb = menu.pantalla(("home",), CMDS, TOPICS, niveles, privado)
        return [b.text for b in _botones(kb)]

    # el 🌐 TASALO lo ve quien tiene algo ahí: SUDO todo, un admin de grupo solo la federación
    assert any("TASALO" in t for t in titulos(SUDO, True))
    assert any("TASALO" in t for t in titulos(ADMIN, False))
    assert not any("TASALO" in t for t in titulos(USUARIO, False))
    # un usuario normal ve algo útil (RSS/notas/reglas son de todos) y siempre la ayuda
    assert any("Ayuda" in t for t in titulos(USUARIO, False))
    assert len(titulos(USUARIO, False)) < len(titulos(ADMIN, False))


@pytest.mark.parametrize("perfil", PERFILES)
def test_cada_pantalla_valida_y_cubre_los_comandos_visibles(perfil):
    niveles, privado = PERFILES[perfil]
    paginas = _alcanzables(niveles, privado)
    todo_el_texto = "\n".join(t for _, t, _ in paginas)
    for args, texto, teclado in paginas:
        assert len(texto) < 4096, args
        for b in _botones(teclado):
            assert len(b.callback_data.encode()) <= 64, b.callback_data
    esperados = [c for c in menu.visibles(CMDS, niveles, privado) if c.topic not in menu.FUERA_DE_SECCIONES]
    assert esperados, perfil
    for c in esperados:
        assert f"/{c.name}" in todo_el_texto, f"/{c.name} no se alcanza desde /menu como {perfil}"


def test_comandos_de_otro_ambito_o_nivel_no_se_muestran():
    solo_grupo = next(c for c in CMDS if c.ambito == "grupo" and c.level == "todos")
    solo_admin = next(c for c in CMDS if c.level == "admin")
    texto_privado = "\n".join(t for _, t, _ in _alcanzables(USUARIO, True))
    texto_usuario = "\n".join(t for _, t, _ in _alcanzables(USUARIO, False))
    assert f"/{solo_grupo.name} " not in texto_privado + " "
    assert f"/{solo_admin.name} " not in texto_usuario + " "


def test_pantalla_desconocida_o_no_visible_cae_al_inicio():
    inicio = menu.pantalla(("home",), CMDS, TOPICS, USUARIO, False)[0]
    assert menu.pantalla(("zzz",), CMDS, TOPICS, USUARIO, False)[0] == inicio
    assert menu.pantalla((), CMDS, TOPICS, USUARIO, False)[0] == inicio
    # un botón viejo que apunta a algo que este usuario ya no puede ver
    assert menu.pantalla(("t", "federation", "tasalo"), CMDS, TOPICS, USUARIO, False)[0] == inicio
    assert menu.pantalla(("s", "tasalo"), CMDS, TOPICS, USUARIO, False)[0] == inicio


def _consulta(data, user_id=5, chat_type="group"):
    chat = SimpleNamespace(id=-100, type=chat_type)
    q = SimpleNamespace(
        data=data, from_user=SimpleNamespace(id=user_id), message=SimpleNamespace(chat=chat),
        answer=AsyncMock(), edit_message_text=AsyncMock(),
    )
    return SimpleNamespace(
        callback_query=q, effective_chat=chat, effective_user=q.from_user,
        effective_message=SimpleNamespace(reply_text=AsyncMock()),
    ), q


def _contexto():
    return SimpleNamespace(application=SimpleNamespace(bot_data={"cmds": CMDS, "topics": TOPICS}), args=[])


@pytest.mark.asyncio
async def test_boton_responde_una_vez_y_edita(monkeypatch):
    ui._ultimo.clear()
    monkeypatch.setattr(menu, "is_user_admin", AsyncMock(return_value=False))
    update, q = _consulta("menu:t:rules:cont")  # /rules es de todos: un usuario normal lo ve
    await menu._on_menu_button(update, _contexto())
    q.answer.assert_awaited_once_with()
    assert "/rules" in q.edit_message_text.call_args.args[0]


@pytest.mark.asyncio
async def test_comando_menu_responde_con_botones_y_admin_ve_mas(monkeypatch):
    ui._ultimo.clear()
    monkeypatch.setattr(menu, "is_user_admin", AsyncMock(return_value=True))
    update, _ = _consulta("x", user_id=6)
    await menu.menu_cmd(update, _contexto())
    teclado = update.effective_message.reply_text.call_args.kwargs["reply_markup"]
    assert any("Moderación" in b.text for b in _botones(teclado))
    # admin del chat, pero no SUDO: lo exclusivo del equipo no llega a su menú
    solo_sudo = next(c for c in CMDS if c.level == "sudo" and c.ambito != "grupo")
    assert f"/{solo_sudo.name} " not in "\n".join(t for _, t, _ in _alcanzables(ADMIN, True)) + " "


def test_menu_declara_su_comando_y_el_atajo_de_start_existe():
    assert [c.name for c in menu.COMMANDS] == ["menu"]
    from modules import start
    assert "menu:home" in open(start.__file__, encoding="utf-8").read()
