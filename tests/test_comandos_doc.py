"""docs/COMANDOS.md se genera desde el registro: no puede quedarse atrás.

Si falla: `python -m scripts.gen_comandos` y commitea el resultado.
"""

from core import registry
from scripts import gen_comandos


def test_comandos_md_esta_al_dia():
    actual = gen_comandos.DESTINO.read_text(encoding="utf-8")
    assert actual == gen_comandos.generar(), "ejecuta: python -m scripts.gen_comandos"


def test_documenta_cada_comando_y_cada_tema():
    cmds, temas, _ = gen_comandos.recoger()
    doc = gen_comandos.DESTINO.read_text(encoding="utf-8")
    for c in cmds:
        assert f"/{c.name}" in doc, f"/{c.name} falta en COMANDOS.md"
    for t in temas:
        assert f"## {gen_comandos._titulo(t)} (" in doc, f"tema {t.key} falta en COMANDOS.md"


def test_celdas_no_rompen_la_tabla():
    """Un `|` sin escapar en uso/desc partiría la fila en más columnas."""
    cmds, _, _ = gen_comandos.recoger()
    for c in cmds:
        fila = gen_comandos._fila(c)
        assert fila.replace("\\|", "").count("|") == 3, f"/{c.name}: fila mal formada"
    assert registry._MARCA["admin"] in gen_comandos._fila(next(c for c in cmds if c.level == "admin"))
