import pytest

from core.registry import Cmd, Topic, linea_ayuda, menu_para, resolver_tema, temas, validar

TOPICS = (Topic("bans", "Bans", aliases=("ban",)), Topic("inicio", "Inicio"))
CMDS = (
    Cmd("ban", "Banea", level="admin", ambito="grupo", topic="bans", uso="[motivo]", menu=True),
    Cmd("rules", "Reglas", topic="inicio", menu=True),
    Cmd("connect", "Conectar", ambito="privado", topic="inicio", menu=True),
    Cmd("stats", "Estado", level="sudo", topic="inicio", menu=True),
    Cmd("help", "Ayuda", topic="inicio", menu=True, alias=("ayuda",)),
    Cmd("oculto", "No sale en el menú", topic="inicio"),
)


def nombres(scope):
    return [n for n, _ in menu_para(CMDS, scope)]


def test_validar_acepta_registro_correcto():
    validar(CMDS, TOPICS)


@pytest.mark.parametrize("malo", [
    Cmd("Mayus", "x"),
    Cmd("a" * 33, "x"),
    Cmd("ok", ""),
    Cmd("ok", "x" * 257),
    Cmd("ok", "x", level="dios"),
    Cmd("ok", "x", ambito="luna"),
])
def test_validar_rechaza_comandos_invalidos(malo):
    with pytest.raises(ValueError):
        validar((malo,))


def test_validar_rechaza_repetidos_incluso_por_alias():
    with pytest.raises(ValueError):
        validar((Cmd("a", "x"), Cmd("b", "x", alias=("a",))))


def test_validar_rechaza_topic_inexistente():
    with pytest.raises(ValueError):
        validar((Cmd("a", "x", topic="nada"),), TOPICS)


def test_validar_rechaza_menu_de_mas_de_100():
    muchos = tuple(Cmd(f"c{i}", "x", menu=True) for i in range(101))
    with pytest.raises(ValueError):
        validar(muchos)


def test_scopes_se_arman_completos():
    assert nombres("default") == ["help", "rules"]
    assert nombres("private") == ["help", "rules", "connect"]
    assert nombres("admins") == ["help", "ban", "rules"]
    assert nombres("sudo") == ["help", "rules", "connect", "stats"]


def test_scope_desconocido():
    with pytest.raises(ValueError):
        menu_para(CMDS, "otro")


def test_temas_y_resolucion_por_alias():
    por_tema = {t.key: [c.name for c in cs] for t, cs in temas(CMDS, TOPICS)}
    assert por_tema["bans"] == ["ban"]
    assert resolver_tema(TOPICS, "BAN").key == "bans"
    assert resolver_tema(TOPICS, "zzz") is None


def test_linea_ayuda():
    assert linea_ayuda(CMDS[0]) == "🔒 /ban [motivo] — Banea"
    assert linea_ayuda(CMDS[3]) == "👑 /stats — Estado"
    assert linea_ayuda(CMDS[1]) == "/rules — Reglas"
