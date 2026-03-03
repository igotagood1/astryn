from llm.base import LLMProvider, LLMResponse
from llm.config import settings
from llm.providers.ollama import OllamaProvider


def get_provider() -> LLMProvider:
    return OllamaProvider(
        base_url=settings.ollama_base_url,
        model=settings.astryn_default_model,
    )


async def chat_with_fallback(
    messages: list[dict],
    system: str,
) -> tuple[LLMResponse, bool]:
    """Phase 1: no fallback - raises if Ollama is down."""
    provider = get_provider()
    if not await provider.is_available():
        raise RuntimeError("Ollama is not available. Is it running? Try: ollama serve")
    response = await provider.chat(messages, system)
    return response, False
