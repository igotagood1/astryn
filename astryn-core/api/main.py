import asyncio
import logging
import logging.config
from contextlib import asynccontextmanager
from pathlib import Path

from alembic.config import Config
from fastapi import FastAPI
from sqlalchemy import text

from alembic import command
from api.routes.chat import router as chat_router
from api.routes.health import router as health_router
from api.routes.models import router as models_router
from api.routes.preferences import router as preferences_router
from api.routes.projects import router as projects_router
from api.routes.tools import router as tools_router
from db.engine import engine

# Logging config applied at import AND again in lifespan (after uvicorn's
# configure_logging, which can silently override basicConfig).
_LOGGING_CONFIG = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "app": {
            "format": "%(asctime)s %(levelname)s %(name)s — %(message)s",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "app",
            "stream": "ext://sys.stderr",
        },
    },
    "root": {
        "handlers": ["console"],
        "level": "INFO",
    },
}

logging.config.dictConfig(_LOGGING_CONFIG)

logger = logging.getLogger(__name__)

_CORE_DIR = Path(__file__).resolve().parent.parent


def _run_migrations() -> None:
    """Run Alembic migrations to ensure the schema is up to date.

    Sets script_location and prepend_sys_path explicitly so migrations
    work regardless of the current working directory (local dev, Docker,
    or any other launch context).
    """
    alembic_cfg = Config(str(_CORE_DIR / "alembic.ini"))
    alembic_cfg.set_main_option("script_location", str(_CORE_DIR / "alembic"))
    alembic_cfg.set_main_option("prepend_sys_path", str(_CORE_DIR))
    command.upgrade(alembic_cfg, "head")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Re-apply logging config after uvicorn's configure_logging() has run.
    # Without this, uvicorn can silently override the root logger setup,
    # causing all request-level logs to vanish.
    logging.config.dictConfig(_LOGGING_CONFIG)

    # Startup: verify DB connectivity
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        logger.info("Database connection verified")
    except Exception as e:
        logger.error("Failed to connect to database: %s", e)
        raise

    # Run migrations in a separate thread because env.py calls asyncio.run(),
    # which cannot be invoked from within an already-running event loop.
    logger.info("Running database migrations…")
    await asyncio.to_thread(_run_migrations)
    logger.info("Database migrations complete")

    # Log configured provider so it's visible at startup
    from llm.config import settings

    provider = settings.astryn_coordinator_provider
    model = (
        settings.astryn_coordinator_model
        if provider == "anthropic"
        else settings.astryn_default_model
    )
    has_key = bool(settings.anthropic_api_key)
    print(f"[DIAG] Coordinator provider: {provider} (model: {model})", flush=True)
    print(f"[DIAG] Anthropic API key set: {has_key}", flush=True)
    logger.info("Coordinator provider: %s (model: %s)", provider, model)

    yield
    # Shutdown: dispose engine
    await engine.dispose()
    logger.info("Database engine disposed")


app = FastAPI(title="Astryn Core", version="0.3.0", lifespan=lifespan)

app.include_router(health_router)
app.include_router(chat_router)
app.include_router(tools_router)
app.include_router(models_router)
app.include_router(projects_router)
app.include_router(preferences_router)
