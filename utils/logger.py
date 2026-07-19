"""Sistema de logging con rotación por tamaño y archivado por fecha (TASO-GCG).

Logs activos (siempre en `logs/`):
    logs/taso-gcg.log          -> todo el log, nivel INFO+
    logs/taso-gcg-errors.log   -> solo ERROR+, retención igual pero aislado

Logs archivados (al rotar por tamaño, no se usan sufijos numéricos):
    logs/archive/taso-gcg_<YYYY-MM-DD_HH-MM-SS>.log
    logs/archive/taso-gcg-errors_<YYYY-MM-DD_HH-MM-SS>.log

El nombre del archivo archivado refleja la fecha/hora en que el archivo se CERRÓ
(momento de la rotación), no la fecha de inicio. Esto permite al comando /log del
bot pedir un log viejo por fecha sin tener que abrir cada archivo para ver su rango.

Esta clase (`DatedRotatingFileHandler`) se duplica en taso-bot, taso-api y
taso-app — si se cambia aquí, replicar el cambio en las otras 3 copias.

No se crean archivos si se detecta que corre bajo pytest
(`PYTEST_CURRENT_TEST` en el entorno), para no ensuciar el repo durante los tests.

Se mantiene la función pública `log(msg, level="info")` con la misma firma de
siempre, para no tocar los ~15 call sites existentes en modules/, core/,
utils/ y scripts/.
"""

import logging
import os
import sys
import time
from logging.handlers import RotatingFileHandler

SERVICE_NAME = "taso-gcg"

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
BASE_DIR = os.path.dirname(CURRENT_DIR)
LOGS_DIR = os.path.join(BASE_DIR, "logs")
ARCHIVE_DIR = os.path.join(LOGS_DIR, "archive")
LOG_FILE_PATH = os.path.join(LOGS_DIR, f"{SERVICE_NAME}.log")
ERROR_LOG_PATH = os.path.join(LOGS_DIR, f"{SERVICE_NAME}-errors.log")

MAX_BYTES = 8 * 1024 * 1024  # 8 MB por archivo activo antes de rotar
BACKUP_COUNT = 10  # tope de seguridad de archivos rotados por log (además de /log clear)

LOG_FORMAT = "[%(asctime)s] | %(levelname)s | %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def _running_under_pytest() -> bool:
    return "PYTEST_CURRENT_TEST" in os.environ


class DatedRotatingFileHandler(RotatingFileHandler):
    """RotatingFileHandler que archiva por fecha de cierre en vez de sufijo numérico.

    Al superar `maxBytes`, el archivo activo se cierra y se mueve a
    `<archive_dir>/<service_name>_<timestamp>.log`. Se mantiene como máximo
    `backupCount` archivos por servicio en el directorio de archivo; los más
    viejos se eliminan automáticamente.
    """

    def __init__(
        self,
        filename: str,
        service_name: str,
        archive_dir: str | None = None,
        maxBytes: int = 0,
        backupCount: int = 0,
        encoding: str | None = None,
        delay: bool = False,
    ):
        self.service_name = service_name
        base_dir = os.path.dirname(os.path.abspath(filename))
        self.archive_dir = archive_dir or os.path.join(base_dir, "archive")
        os.makedirs(self.archive_dir, exist_ok=True)
        super().__init__(
            filename,
            maxBytes=maxBytes,
            backupCount=backupCount,
            encoding=encoding,
            delay=delay,
        )

    def doRollover(self):
        if self.stream:
            self.stream.close()
            self.stream = None

        if os.path.exists(self.baseFilename):
            archive_name = self._build_archive_name()
            try:
                os.rename(self.baseFilename, archive_name)
            except OSError:
                pass

        self._cleanup_old_archives()

        if not self.delay:
            self.stream = self._open()

    def _build_archive_name(self) -> str:
        timestamp = time.strftime("%Y-%m-%d_%H-%M-%S")
        candidate = os.path.join(self.archive_dir, f"{self.service_name}_{timestamp}.log")
        counter = 1
        while os.path.exists(candidate):
            candidate = os.path.join(
                self.archive_dir, f"{self.service_name}_{timestamp}_{counter}.log"
            )
            counter += 1
        return candidate

    def _cleanup_old_archives(self):
        if self.backupCount <= 0:
            return
        try:
            prefix = f"{self.service_name}_"
            archives = sorted(
                (
                    f
                    for f in os.listdir(self.archive_dir)
                    if f.startswith(prefix) and f.endswith(".log")
                ),
                key=lambda f: os.path.getmtime(os.path.join(self.archive_dir, f)),
            )
            excess = len(archives) - self.backupCount
            for old_file in archives[: max(0, excess)]:
                os.remove(os.path.join(self.archive_dir, old_file))
        except OSError:
            pass


logger = logging.getLogger("taso_gcg")
logger.setLevel(logging.INFO)
logger.propagate = False

if not logger.handlers:
    formatter = logging.Formatter(LOG_FORMAT, datefmt=DATE_FORMAT)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    if not _running_under_pytest():
        os.makedirs(LOGS_DIR, exist_ok=True)

        file_handler = DatedRotatingFileHandler(
            LOG_FILE_PATH,
            service_name=SERVICE_NAME,
            maxBytes=MAX_BYTES,
            backupCount=BACKUP_COUNT,
            encoding="utf-8",
        )
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

        error_handler = DatedRotatingFileHandler(
            ERROR_LOG_PATH,
            service_name=f"{SERVICE_NAME}-errors",
            maxBytes=MAX_BYTES,
            backupCount=BACKUP_COUNT,
            encoding="utf-8",
        )
        error_handler.setFormatter(formatter)
        error_handler.setLevel(logging.ERROR)
        logger.addHandler(error_handler)


def log(msg, level="info"):
    if level == "error":
        logger.error(msg)
    elif level == "warning":
        logger.warning(msg)
    elif level == "debug":
        logger.debug(msg)
    else:
        logger.info(msg)


def _handle_uncaught_exception(exc_type, exc_value, exc_traceback):
    """Loguea como ERROR cualquier excepción no controlada antes de que el
    proceso muera, en vez de perderla en stderr sin dejar rastro en logs/.
    """
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc_value, exc_traceback)
        return
    logger.error(
        "Excepción no controlada, el proceso va a terminar",
        exc_info=(exc_type, exc_value, exc_traceback),
    )


sys.excepthook = _handle_uncaught_exception
