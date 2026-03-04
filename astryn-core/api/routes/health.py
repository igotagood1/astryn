import logging

from fastapi import APIRouter

from llm.config import settings
from llm.providers.ollama import OllamaProvider
from llm.router import get_active_model

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/health")
async def health():
    active = get_active_model()
    ollama = OllamaProvider(base_url=settings.ollama_base_url, model=active)
    ollama_up = await ollama.is_available()
    status = "up" if ollama_up else "down"
    logger.debug("Health check: ollama=%s model=%s", status, active)
    return {"status": "ok", "ollama": status, "model": active}
