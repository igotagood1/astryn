import asyncio
import logging
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

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)

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
