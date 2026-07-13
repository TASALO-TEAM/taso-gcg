"""Tests de core/database.py contra una DB SQLite temporal (ver conftest.py)."""

import pytest


class ChatFalso:
    """Sustituto mínimo de telegram.Chat para no depender de la librería en los tests."""
    def __init__(self, id, type="supergroup", title="Chat de prueba", username=None):
        self.id = id
        self.type = type
        self.title = title
        self.username = username
        self.full_name = None
        self.first_name = None


@pytest.mark.asyncio
async def test_ensure_chat_crea_y_reutiliza(test_db):
    chat = ChatFalso(id=-100123)
    fila1 = await test_db.ensure_chat(chat)
    assert fila1["tg_chat_id"] == -100123
    assert fila1["titulo"] == "Chat de prueba"

    # Llamar de nuevo con el mismo tg_chat_id no debe crear una fila duplicada
    fila2 = await test_db.ensure_chat(chat)
    assert fila1["id"] == fila2["id"]

    todos = await test_db.fetchall("SELECT * FROM chats")
    assert len(todos) == 1


@pytest.mark.asyncio
async def test_ensure_chat_actualiza_titulo_si_cambia(test_db):
    chat = ChatFalso(id=-100456, title="Nombre viejo")
    await test_db.ensure_chat(chat)

    chat.title = "Nombre nuevo"
    fila = await test_db.ensure_chat(chat)
    assert fila["titulo"] == "Nombre nuevo"


@pytest.mark.asyncio
async def test_chat_settings_se_crean_con_defaults(test_db):
    chat = ChatFalso(id=-100789)
    chat_row = await test_db.ensure_chat(chat)
    settings = await test_db.get_chat_settings(chat_row["id"])
    assert settings["warn_limit"] == 3
    assert settings["flood_limit"] == 0
    assert settings["join_captcha"] == 0


@pytest.mark.asyncio
async def test_update_chat_settings(test_db):
    chat_row = await test_db.ensure_chat(ChatFalso(id=-100111))
    await test_db.update_chat_settings(chat_row["id"], warn_limit=5, flood_limit=10)
    settings = await test_db.get_chat_settings(chat_row["id"])
    assert settings["warn_limit"] == 5
    assert settings["flood_limit"] == 10


@pytest.mark.asyncio
async def test_warns_se_acumulan_por_usuario(test_db):
    chat_row = await test_db.ensure_chat(ChatFalso(id=-100222))
    await test_db.execute(
        "INSERT INTO warns(chat_id, user_id, razon, dado_por) VALUES (?,?,?,?)",
        (chat_row["id"], 555, "spam", 1),
    )
    await test_db.execute(
        "INSERT INTO warns(chat_id, user_id, razon, dado_por) VALUES (?,?,?,?)",
        (chat_row["id"], 555, "spam otra vez", 1),
    )
    total = await test_db.fetchone(
        "SELECT COUNT(*) as n FROM warns WHERE chat_id = ? AND user_id = ?", (chat_row["id"], 555)
    )
    assert total["n"] == 2


@pytest.mark.asyncio
async def test_approvals_inmunidad(test_db):
    chat_row = await test_db.ensure_chat(ChatFalso(id=-100333))
    assert await test_db.is_approved(chat_row["id"], 999) is False

    await test_db.execute(
        "INSERT INTO approvals(chat_id, user_id, razon, aprobado_por) VALUES (?,?,?,?)",
        (chat_row["id"], 999, "confianza", 1),
    )
    assert await test_db.is_approved(chat_row["id"], 999) is True


@pytest.mark.asyncio
async def test_fed_bans(test_db):
    assert await test_db.is_fed_banned(42) is None
    await test_db.execute(
        "INSERT INTO fed_bans(user_id, razon, baneado_por) VALUES (?,?,?)", (42, "spam", 1)
    )
    fila = await test_db.is_fed_banned(42)
    assert fila is not None
    assert fila["razon"] == "spam"


@pytest.mark.asyncio
async def test_disabled_commands(test_db):
    chat_row = await test_db.ensure_chat(ChatFalso(id=-100444))
    assert await test_db.is_command_disabled(chat_row["id"], "notes") is False
    await test_db.execute(
        "INSERT INTO disabled_commands(chat_id, comando) VALUES (?,?)", (chat_row["id"], "notes")
    )
    assert await test_db.is_command_disabled(chat_row["id"], "notes") is True


@pytest.mark.asyncio
async def test_chats_oficiales(test_db):
    chat1 = await test_db.ensure_chat(ChatFalso(id=-100555, title="Oficial"))
    await test_db.ensure_chat(ChatFalso(id=-100666, title="No oficial"))
    await test_db.set_oficial_tasalo(-100555, True)

    oficiales = await test_db.chats_oficiales()
    assert len(oficiales) == 1
    assert oficiales[0]["tg_chat_id"] == -100555


@pytest.mark.asyncio
async def test_iv_templates_jerarquia(test_db):
    await test_db.execute("INSERT INTO iv_templates(dominio, rhash) VALUES ('_universal', 'univ123')")
    await test_db.execute("INSERT INTO iv_templates(dominio, rhash) VALUES ('elpais.com', 'ep456')")

    # Coincidencia exacta
    assert await test_db.find_iv_rhash("https://elpais.com/nota") == "ep456"
    # Subdominio -> coincide por sufijo
    assert await test_db.find_iv_rhash("https://tecnologia.elpais.com/nota") == "ep456"
    # Dominio sin plantilla propia -> universal
    assert await test_db.find_iv_rhash("https://otrositio.com/nota") == "univ123"


@pytest.mark.asyncio
async def test_connection_persiste_y_sobrevive_reinicio_simulado(test_db):
    # "Reinicio simulado" = no depender de ningún estado en memoria (user_data),
    # solo de lo que devuelve una consulta fresca a la DB.
    assert await test_db.get_connection(555) is None

    await test_db.set_connection(555, -100999)
    assert await test_db.get_connection(555) == -100999


@pytest.mark.asyncio
async def test_connection_se_puede_reemplazar(test_db):
    await test_db.set_connection(555, -100111)
    await test_db.set_connection(555, -100222)  # el usuario se conecta a otro chat
    assert await test_db.get_connection(555) == -100222


@pytest.mark.asyncio
async def test_connection_clear(test_db):
    await test_db.set_connection(555, -100333)
    await test_db.clear_connection(555)
    assert await test_db.get_connection(555) is None
