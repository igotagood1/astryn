from llm.base import LLMProvider
from llm.config import settings
from llm.providers.ollama import OllamaProvider

# Global active model. Switched via POST /models/active. Resets on restart.
# Phase 3 will persist this to the database.
_active_model: str = settings.astryn_default_model


def get_active_model() -> str:
    return _active_model


def set_active_model(model: str) -> None:
    global _active_model
    _active_model = model


def get_provider() -> LLMProvider:
    """Return an LLMProvider for the currently active model."""
    return OllamaProvider(base_url=settings.ollama_base_url, model=_active_model)


async def list_available_models() -> list[str]:
    """Return all model names available in the local Ollama instance."""
    provider = OllamaProvider(base_url=settings.ollama_base_url, model=_active_model)
    return await provider.list_models()
