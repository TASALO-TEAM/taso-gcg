"""Tests para core/ai_client.py: logging del cuerpo de la respuesta de Groq
en errores no-429, y que la rotación de keys siga comportándose igual que
antes (retry en 429, sin retry en 400/401/500)."""

import os
import sys
from unittest.mock import MagicMock, patch

import httpx
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import core.ai_client as ai_client  # noqa: E402


def _mock_response(json_data, status_code=200, text=""):
    resp = MagicMock()
    resp.json.return_value = json_data
    resp.status_code = status_code
    resp.text = text
    if status_code >= 400:
        def _raise(_resp=resp):
            raise httpx.HTTPStatusError("error", request=MagicMock(), response=_resp)
        resp.raise_for_status = MagicMock(side_effect=_raise)
    else:
        resp.raise_for_status = MagicMock()
    return resp


class _FakeAsyncClient:
    def __init__(self, responses):
        self._responses = iter(responses)
        self.post_calls = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def post(self, url, headers=None, json=None):
        self.post_calls.append(headers)
        return next(self._responses)


def _patch_client(responses):
    fake = _FakeAsyncClient(responses)
    return patch("core.ai_client.httpx.AsyncClient", return_value=fake), fake


def _patch_keys(keys):
    """Sustituye GROQ_API_KEYS y reconstruye _key_cycle (normalmente se
    arma una sola vez al importar el módulo, con las keys reales del
    .env — hay que rehacerlo por test para poder controlar el escenario)."""
    import itertools
    return (
        patch("core.ai_client.GROQ_API_KEYS", keys),
        patch("core.ai_client._key_cycle", itertools.cycle(keys) if keys else None),
    )


@pytest.mark.asyncio
async def test_ask_groq_returns_none_without_keys():
    p1, p2 = _patch_keys([])
    with p1, p2:
        assert await ask_groq_wrapper() is None


async def ask_groq_wrapper(**kwargs):
    return await ai_client.ask_groq("system", "user", **kwargs)


@pytest.mark.asyncio
async def test_ask_groq_logs_response_body_on_400():
    """El bug que motivó este cambio: antes solo se logueaba el status
    code, nunca el cuerpo real de la respuesta de Groq — sin eso no se
    podía diagnosticar la causa (context_length_exceeded, etc.)."""
    p1, p2 = _patch_keys(["key1", "key2"])
    patcher, fake_client = _patch_client([
        _mock_response({}, status_code=400, text='{"error": {"message": "context_length_exceeded"}}'),
    ])
    with p1, p2, patcher, patch("core.ai_client.log") as mock_log:
        resultado = await ask_groq_wrapper()

    assert resultado is None
    assert len(fake_client.post_calls) == 1  # no reintenta con key2 ante un 400
    logged_text = " ".join(str(c) for c in mock_log.call_args_list)
    assert "context_length_exceeded" in logged_text


@pytest.mark.asyncio
async def test_ask_groq_falls_back_to_next_key_on_429():
    p1, p2 = _patch_keys(["key1", "key2"])
    patcher, fake_client = _patch_client([
        _mock_response({}, status_code=429),
        _mock_response({"choices": [{"message": {"content": "traducido"}}]}),
    ])
    with p1, p2, patcher:
        resultado = await ask_groq_wrapper()

    assert resultado == "traducido"
    assert len(fake_client.post_calls) == 2


@pytest.mark.asyncio
async def test_ask_groq_does_not_retry_on_400_even_with_multiple_keys():
    p1, p2 = _patch_keys(["key1", "key2"])
    patcher, fake_client = _patch_client([
        _mock_response({}, status_code=400, text="bad request"),
    ])
    with p1, p2, patcher:
        resultado = await ask_groq_wrapper()

    assert resultado is None
    assert len(fake_client.post_calls) == 1
