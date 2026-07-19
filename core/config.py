"""Configuración central de taso-gcg.

Sigue la misma convención que core/config.py de BitBreadRSS: carga desde .env,
expone constantes simples que el resto del proyecto importa directamente.
"""

import os
from dotenv import load_dotenv

load_dotenv()

# --- Credenciales y control de acceso ---
TOKEN = os.getenv("TELEGRAM_TOKEN")

def _parse_id_list(env_value: str | None) -> set[int]:
    """Convierte '123,456 789' en {123, 456, 789}. Acepta comas y/o espacios."""
    if not env_value:
        return set()
    raw = env_value.replace(",", " ").split()
    result = set()
    for item in raw:
        try:
            result.add(int(item))
        except ValueError:
            continue
    return result

# Dueños del bot: control total, incluida config de chats oficiales TASALO
SUDO_USERS: set[int] = _parse_id_list(os.getenv("SUDO_USERS"))

# Chat/canal donde el bot manda logs de arranque, errores críticos, etc.
LOG_CHAT_ID = os.getenv("LOG_CHAT_ID")

def _parse_key_list(env_value: str | None) -> list[str]:
    """Convierte 'key1,key2' en ['key1', 'key2']. Acepta solo comas (las keys
    no llevan espacios como separador válido, a diferencia de _parse_id_list)."""
    if not env_value:
        return []
    return [k.strip() for k in env_value.split(",") if k.strip()]

# --- IA (Groq) — traducción de RSS y contexto de moderación ---
# Opcional: si no se configura, las funciones de IA se desactivan solas
# (se publica el RSS en el idioma original, no hay contexto de moderación),
# el resto del bot sigue funcionando exactamente igual.
# Soporta una o varias keys separadas por coma (rotación round-robin en
# core/ai_client.py: si una cuenta pega el límite de rate, se prueba la
# siguiente antes de rendirse). Con 1 sola key, comportamiento idéntico.
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
GROQ_API_KEYS: list[str] = _parse_key_list(GROQ_API_KEY)
GROQ_MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")

# --- Rutas ---
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")
DB_PATH = os.path.join(DATA_DIR, "taso_gcg.db")
# Los logs viven en <repo>/logs/ (ver utils/logger.py), no en data/ — ese
# módulo gestiona su propio directorio y rotación.

os.makedirs(DATA_DIR, exist_ok=True)

# --- Carga de módulos ---
# Si LOAD está vacío, se cargan todos los módulos de modules/ excepto los de NO_LOAD.
LOAD = [m for m in os.getenv("LOAD", "").split(",") if m]
NO_LOAD = [m for m in os.getenv("NO_LOAD", "").split(",") if m]

# --- Comportamiento por defecto (se puede sobreescribir por chat en chat_settings) ---
DEFAULT_WARN_LIMIT = int(os.getenv("DEFAULT_WARN_LIMIT", "3"))
DEFAULT_FLOOD_LIMIT = int(os.getenv("DEFAULT_FLOOD_LIMIT", "0"))  # 0 = desactivado
ADMIN_CACHE_TTL_SECONDS = int(os.getenv("ADMIN_CACHE_TTL_SECONDS", "300"))

# --- Versión ---
try:
    with open(os.path.join(BASE_DIR, "version.txt"), "r") as f:
        BOT_VERSION = f.read().strip()
except FileNotFoundError:
    BOT_VERSION = "0.1.0"

if not TOKEN:
    print("⚠️  TELEGRAM_TOKEN no configurado — revisa tu archivo .env")
