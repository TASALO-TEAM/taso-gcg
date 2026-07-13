"""Logger con rotación — misma convención que utils/logger.py de BitBreadRSS."""

import logging
import os
from logging.handlers import RotatingFileHandler

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
BASE_DIR = os.path.dirname(CURRENT_DIR)
LOGS_DIR = os.path.join(BASE_DIR, "data", "logs")
LOG_FILE_PATH = os.path.join(LOGS_DIR, "taso_gcg.log")

os.makedirs(LOGS_DIR, exist_ok=True)

logger = logging.getLogger("taso_gcg")
logger.setLevel(logging.INFO)
logger.propagate = False

if not logger.handlers:
    handler = RotatingFileHandler(LOG_FILE_PATH, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8")
    formatter = logging.Formatter("[%(asctime)s] | %(levelname)s | %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
    handler.setFormatter(formatter)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)

    logger.addHandler(handler)
    logger.addHandler(console_handler)


def log(msg, level="info"):
    if level == "error":
        logger.error(msg)
    elif level == "warning":
        logger.warning(msg)
    elif level == "debug":
        logger.debug(msg)
    else:
        logger.info(msg)
