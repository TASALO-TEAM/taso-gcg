import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.common import parse_duration, humanize_seconds, clean_html, truncate_text


def test_parse_duration_valida():
    assert parse_duration("30s") == 30
    assert parse_duration("5m") == 300
    assert parse_duration("2h") == 7200
    assert parse_duration("1d") == 86400


def test_parse_duration_invalida():
    assert parse_duration("") is None
    assert parse_duration("abc") is None
    assert parse_duration("10") is None  # falta la unidad
    assert parse_duration("10x") is None  # unidad inválida


def test_humanize_seconds():
    assert humanize_seconds(30) == "30s"
    assert humanize_seconds(60) == "1m"
    assert humanize_seconds(3600) == "1h"
    assert humanize_seconds(86400) == "1d"
    assert humanize_seconds(90) == "90s"  # no es múltiplo exacto de una unidad mayor


def test_clean_html_quita_etiquetas_no_soportadas():
    resultado = clean_html("<div><script>alert(1)</script><p>Hola <b>mundo</b></p></div>")
    assert "script" not in resultado
    assert "<b>mundo</b>" in resultado
    assert "<div>" not in resultado


def test_clean_html_vacio():
    assert clean_html("") == ""
    assert clean_html(None) == ""


def test_truncate_text_no_corta_si_cabe():
    texto = "Hola mundo"
    assert truncate_text(texto, limit=100) == texto


def test_truncate_text_corta_y_cierra_enlace():
    texto = "a" * 50 + "<a href='x'>enlace</a>"
    resultado = truncate_text(texto, limit=40)
    assert len(resultado) <= 44  # 40 + "</a>" si hizo falta cerrar
    assert resultado.count("<a") <= resultado.count("</a>")
