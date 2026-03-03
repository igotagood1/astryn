from fastapi import FastAPI

from api.routes.chat import router as chat_router
from api.routes.health import router as health_router
from api.routes.models import router as models_router
from api.routes.tools import router as tools_router

app = FastAPI(title="Astryn Core", version="0.2.0")

app.include_router(health_router)
app.include_router(chat_router)
app.include_router(tools_router)
app.include_router(models_router)
