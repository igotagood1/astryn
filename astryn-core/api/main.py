import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy import text

from api.routes.chat import router as chat_router
from api.routes.health import router as health_router
from api.routes.models import router as models_router
from api.routes.projects import router as projects_router
from api.routes.tools import router as tools_router
from db.engine import engine

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)

logger = logging.getLogger(__name__)


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
