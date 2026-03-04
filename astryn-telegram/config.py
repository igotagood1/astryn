import os

from dotenv import load_dotenv

# Load .env before reading any values. Safe to call multiple times — dotenv is idempotent.
load_dotenv()

# ── Required ─────────────────────────────────────────────────────────────────
# The bot will not start if these are missing. Fail fast with a clear message
# rather than a cryptic crash inside the telegram library.

TELEGRAM_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
if not TELEGRAM_BOT_TOKEN:
    raise RuntimeError("TELEGRAM_BOT_TOKEN environment variable is not set")

ASTRYN_CORE_API_KEY: str = os.getenv("ASTRYN_CORE_API_KEY", "")
if not ASTRYN_CORE_API_KEY:
    raise RuntimeError("ASTRYN_CORE_API_KEY environment variable is not set")

# ── Optional with defaults ────────────────────────────────────────────────────

ASTRYN_CORE_URL: str = os.getenv("ASTRYN_CORE_URL", "http://localhost:8000")

# Only this Telegram user ID is allowed to interact with the bot.
# Defaults to 0 (no one) so the bot is locked down unless explicitly set.
ALLOWED_USER_ID: int = int(os.getenv("ALLOWED_USER_ID", "0"))
