from fastapi import APIRouter
from llm.providers.ollama import OllamaProvider
from llm.config import settings

router = APIRouter()


@router.get('/health')
async def health():
    ollama = OllamaProvider(
        base_url=settings.ollama_base_url,
        model=settings.astryn_default_model,
    )
    ollama_up = await ollama.is_available()
    return {
        'status': 'ok',
        'ollama': 'up' if ollama_up else 'down',
        'model': settings.astryn_default_model,
    }