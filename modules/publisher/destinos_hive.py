"""Destinos Hive: `hive_wave` (Waves de Ecency), `hive_snap` (Snaps de PeakD) y `hive_blog`.

La cuenta (`pub_cuentas`, red hive) trae la clave de posting cifrada y, en `params`, los valores
por defecto: `comunidad` (hive-XXXXX), `tags` y `beneficiarios` ([{"account": "x", "weight": 500}],
10000 = 100 %). Los `params` del destino los sobrescriben campo a campo; `max_chars` (opcional)
recorta el microblog si una plataforma limita el largo.

Wave y snap son un comentario que responde al post contenedor vigente (sin comment_options).
El blog es un post raíz con tags, comunidad y beneficiarios.
"""

from datetime import datetime, timezone

from modules.publisher import hive
from modules.publisher.base import Contenido, Resultado, destino

# Cuentas cuyo último post es el contenedor vigente, y tag base de cada microblog.
CONTENEDORES = {"hive_wave": ("ecency.waves", "waves"), "hive_snap": ("peak.snaps", "snaps")}
APP = "taso-gcg"
MAX_TAGS = 10


def _ajustes(cuenta: dict | None, d: dict) -> dict:
    if not cuenta:
        raise ValueError("el destino de Hive necesita una cuenta")
    return {**(cuenta.get("params") or {}), **(d.get("params") or {})}


def _tags(base: tuple[str, ...], *grupos) -> list[str]:
    vistos: list[str] = []
    for t in (*base, *(x for g in grupos for x in g)):
        t = hive.slug(str(t).lstrip("#"), 24)
        if t not in vistos:
            vistos.append(t)
    return vistos[:MAX_TAGS]


def _permlink(base: str) -> str:
    return f"{base}-{datetime.now(timezone.utc).strftime('%Y%m%dt%H%M%S')}"


def _url(autor: str, permlink: str) -> str:
    return f"https://peakd.com/@{autor}/{permlink}"


async def _microblog(tipo: str, contenido: Contenido, d: dict, cuenta, secreto, simular: bool) -> Resultado:
    aj = _ajustes(cuenta, d)
    texto = contenido.texto_corto
    tope = aj.get("max_chars")
    if isinstance(tope, int) and tope > 1 and len(texto) > tope:
        texto = texto[: tope - 1].rstrip() + "…"
    if simular:
        return Resultado(True, simulado=True)
    if not secreto:
        raise RuntimeError("la cuenta no tiene clave de posting guardada")
    contenedor_de, tag = CONTENEDORES[tipo]
    cont = await hive.contenedor_vigente(contenedor_de)
    autor = cuenta["nombre"]
    permlink = _permlink(f"re-{hive.slug(cont['author'], 20)}")
    meta = {"app": APP, "format": "markdown", "tags": _tags((tag,), contenido.tags, aj.get("tags") or ())}
    await hive.transmitir([hive.op_comentario(autor, permlink, texto, cont["author"], cont["permlink"], meta=meta)], secreto)
    return Resultado(True, url=_url(autor, permlink))


@destino("hive_wave")
async def destino_wave(contenido, d, cuenta, secreto, simular):
    return await _microblog("hive_wave", contenido, d, cuenta, secreto, simular)


@destino("hive_snap")
async def destino_snap(contenido, d, cuenta, secreto, simular):
    return await _microblog("hive_snap", contenido, d, cuenta, secreto, simular)


@destino("hive_blog")
async def destino_blog(contenido: Contenido, d: dict, cuenta, secreto, simular: bool) -> Resultado:
    aj = _ajustes(cuenta, d)
    if not contenido.titulo or not contenido.cuerpo_md:
        raise ValueError("el contenido no trae título y cuerpo para un post de blog")
    comunidad = (aj.get("comunidad") or "").strip()
    tags = _tags((), contenido.tags, aj.get("tags") or ())
    principal = comunidad or (tags[0] if tags else "")
    if not principal:
        raise ValueError("el blog necesita una comunidad o al menos una tag")
    if simular:
        return Resultado(True, simulado=True)
    if not secreto:
        raise RuntimeError("la cuenta no tiene clave de posting guardada")
    autor = cuenta["nombre"]
    permlink = _permlink(hive.slug(contenido.titulo))
    meta = {"app": APP, "format": "markdown", "tags": ([principal] + [t for t in tags if t != principal])[:MAX_TAGS]}
    ops = [hive.op_comentario(autor, permlink, contenido.cuerpo_md, "", principal, contenido.titulo[:255], meta)]
    ops.append(hive.op_opciones(autor, permlink, aj.get("beneficiarios") or []))
    await hive.transmitir(ops, secreto)
    return Resultado(True, url=_url(autor, permlink))
