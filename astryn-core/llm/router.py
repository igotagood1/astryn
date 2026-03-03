from llm.base import LLMProvider, LLMResponse
from llm.config import settings
from llm.providers.ollama import OllamaProvider

# Global active model. Switched via POST /models/active. Resets on restart.
_active_model: str = settings.astryn_default_model


def get_active_model() -> str:
    return _active_model


def set_active_model(model: str) -> None:
    global _active_model
    _active_model = model


def get_provider() -> LLMProvider:
    return OllamaProvider(base_url=settings.ollama_base_url, model=_active_model)


async def list_available_models() -> list[str]:
    provider = OllamaProvider(base_url=settings.ollama_base_url, model=_active_model)
    return await provider.list_models()


async def chat_with_fallback(
    messages: list[dict],
    system: str,
) -> tuple[LLMResponse, bool]:
    """Phase 1 helper. The agent loop (Phase 2+) calls the provider directly."""
    provider = get_provider()
    if not await provider.is_available():
        raise RuntimeError("Ollama is not available. Is it running? Try: ollama serve")
    response = await provider.chat(messages, system)
    return response, False
