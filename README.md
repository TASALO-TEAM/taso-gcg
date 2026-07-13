# taso-gcg — Gestión de Canales y Grupos TASALO

Bot de Telegram que unifica dos cosas en un solo proceso: administración/moderación
de todos los grupos y canales de TASALO, y distribución de noticias RSS
(migrado y modernizado desde [BitBreadRSS](https://github.com/ersus93/BitBreadRSS)).

Ver `ESTADO_DESARROLLO.md` para el estado exacto del desarrollo, decisiones tomadas
y qué falta. Ver `docs/plan-taso-gcg.md` para el plan de arquitectura completo.
Ver `docs/COMANDOS.md` para el listado de todos los comandos.

## Stack

- Python 3.11+, [python-telegram-bot](https://github.com/python-telegram-bot/python-telegram-bot) 22.x (async)
- SQLite local en modo WAL (`aiosqlite`) — sin Postgres, sin Supabase, sin infraestructura extra
- APScheduler para el monitor de RSS
- `curl_cffi` + `feedparser` + `BeautifulSoup` para el parseo/bypass WAF de feeds

## Arranque rápido (desarrollo local)

```bash
python -m venv venv
# Linux/Mac:
source venv/bin/activate
# Windows:
venv\Scripts\activate

pip install -r requirements.txt
cp .env.example .env
# Edita .env: TELEGRAM_TOKEN y SUDO_USERS son obligatorios

python bot.py
```

## Correr los tests

```bash
pip install -r requirements.txt  # ya incluye pytest y pytest-asyncio
pytest -v
```

## Despliegue en VPS (systemd)

1. Clona el repo en el VPS, crea el venv e instala dependencias igual que arriba.
2. Copia `taso-gcg.service` a `/etc/systemd/system/`, ajusta `User=` y las rutas.
3. `sudo systemctl daemon-reload && sudo systemctl enable --now taso-gcg`
4. Logs: `journalctl -u taso-gcg -f` o directamente `data/logs/taso_gcg.log`.

## Primeros pasos con el bot ya corriendo

1. Añade el bot a un grupo/canal y hazlo administrador.
2. En ese chat, marca tu propio Telegram ID en `SUDO_USERS` del `.env` para tener
   acceso a `/broadcast`, `/marcaroficial`, `/fban`, `/stats`, etc.
3. `/marcaroficial` en cada chat oficial de TASALO para que entren en la
   federación (bans sincronizados) y en la lista de difusión.
4. `/addfeed` para empezar a recibir noticias RSS en ese chat.
