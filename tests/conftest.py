import os
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.database import Database  # noqa: E402


@pytest.fixture
async def test_db():
    """Base de datos SQLite temporal y aislada, con el esquema completo aplicado,
    para que cada test corra contra datos limpios sin tocar taso_gcg.db real."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    database = Database(path=path)
    await database.init()
    yield database
    await database.close()
    os.remove(path)
    for extra in (path + "-wal", path + "-shm"):
        if os.path.exists(extra):
            os.remove(extra)
