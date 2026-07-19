"""Tests para modules/rss/translator.py: capado defensivo del tamaño de la
entrada antes de traducir, y el fallback silencioso existente (no romperlo)."""

import json
import os
import sys
from unittest.mock import AsyncMock, patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from modules.rss.translator import traducir_entry, MAX_CHARS_A_TRADUCIR  # noqa: E402


@pytest.mark.asyncio
async def test_traducir_entry_capa_descripcion_larga_antes_de_llamar_a_groq():
    entry = {
        "title": "Titulo corto",
        "description": "x" * (MAX_CHARS_A_TRADUCIR + 500),
        "hash": "abc",
    }
    mock_ask = AsyncMock(return_value=json.dumps({"title": "T", "description": "D"}))
    with patch("modules.rss.translator.ask_groq", mock_ask):
        await traducir_entry(entry)

    user_prompt_enviado = mock_ask.call_args.args[1]
    enviado = json.loads(user_prompt_enviado)
    assert len(enviado["description"]) <= MAX_CHARS_A_TRADUCIR + 3  # +"..."


@pytest.mark.asyncio
async def test_traducir_entry_no_capa_si_ya_es_corta():
    entry = {"title": "Titulo", "description": "Descripcion normal y corta", "hash": "abc"}
    mock_ask = AsyncMock(return_value=json.dumps({"title": "T", "description": "D"}))
    with patch("modules.rss.translator.ask_groq", mock_ask):
        await traducir_entry(entry)

    user_prompt_enviado = mock_ask.call_args.args[1]
    enviado = json.loads(user_prompt_enviado)
    assert enviado["description"] == "Descripcion normal y corta"


@pytest.mark.asyncio
async def test_traducir_entry_devuelve_original_si_groq_falla():
    """Fallback silencioso existente — no debe romperse con el capado nuevo."""
    entry = {"title": "Original", "description": "Desc original", "hash": "abc"}
    with patch("modules.rss.translator.ask_groq", AsyncMock(return_value=None)):
        resultado = await traducir_entry(entry)

    assert resultado == entry


@pytest.mark.asyncio
async def test_traducir_entry_reemplaza_title_y_description_si_groq_responde_ok():
    entry = {"title": "Original", "description": "Desc original", "hash": "abc"}
    mock_ask = AsyncMock(return_value=json.dumps({"title": "Traducido", "description": "Desc traducida"}))
    with patch("modules.rss.translator.ask_groq", mock_ask):
        resultado = await traducir_entry(entry)

    assert resultado["title"] == "Traducido"
    assert resultado["description"] == "Desc traducida"
    assert resultado["hash"] == "abc"  # el resto del entry se preserva
