from fastapi import APIRouter

from llm.providers.ollama import OllamaProvider
from llm.config import settings
from llm.router import get_active_model

router = APIRouter()


@router.get("/health")
async def health():
    active = get_active_model()
    ollama = OllamaProvider(base_url=settings.ollama_base_url, model=active)
    ollama_up = await ollama.is_available()
    return {
        "status": "ok",
        "ollama": "up" if ollama_up else "down",
        "model": active,
    }
