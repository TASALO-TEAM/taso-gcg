"""T0.7 — nitter_watch solo avisa en cambios de estado confirmados del pool."""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import modules.rss.nitter_watch as nw  # noqa: E402


@pytest.fixture(autouse=True)
def _reset():
    nw._estado_confirmado = None
    nw._estado_pendiente = None
    nw._contador = 0


def _pasadas(*estados):
    return [nw._registrar_pasada(e) for e in estados]


def test_arranque_solo_fija_base_sin_avisar():
    assert _pasadas("caido", "caido", "caido") == [None, None, None]


def test_sano_tras_caido_avisa_una_vez_al_confirmar():
    assert _pasadas("caido", "caido", "sano", "sano", "sano") == [None, None, None, "sano", None]


def test_parpadeo_de_una_pasada_no_avisa():
    assert _pasadas("sano", "sano", "caido", "sano", "caido", "sano") == [None] * 6


def test_pool_caido_se_avisa_al_confirmar():
    assert _pasadas("sano", "sano", "caido", "caido") == [None, None, None, "caido"]
