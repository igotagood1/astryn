"""Provider routing — factory functions for coordinator and specialist providers.

get_coordinator_provider() returns Claude or Ollama based on config.
get_specialist_provider() always returns Ollama (optionally with a specific model).
get_fallback_provider() always returns Ollama with the default specialist model.
"""

import logging

from llm.base import LLMProvider
from llm.config import settings
from llm.providers.ollama import OllamaProvider

logger = logging.getLogger(__name__)

# Global active model. Switched via POST /models/active. Resets on restart.
_active_model: str = settings.astryn_default_model


def get_active_model() -> str:
    return _active_model


def set_active_model(model: str) -> None:
    global _active_model
    _active_model = model


def get_coordinator_provider() -> LLMProvider:
    """Return the provider for the coordinator agent.

    Uses Anthropic if configured, otherwise Ollama with the active model.
    """
    if (
        settings.astryn_coordinator_provider == "anthropic"
        and settings.anthropic_api_key is not None
    ):
        from llm.providers.anthropic import AnthropicProvider

        logger.info("Coordinator: Anthropic (%s)", settings.astryn_coordinator_model)
        return AnthropicProvider(
            api_key=settings.anthropic_api_key.get_secret_value(),
            model=settings.astryn_coordinator_model,
        )

    logger.info("Coordinator: Ollama (%s)", _active_model)
    return OllamaProvider(base_url=settings.ollama_base_url, model=_active_model)


def get_specialist_provider(model: str | None = None) -> LLMProvider:
    """Return the provider for specialist agents. Always Ollama.

    Args:
        model: Optional model override (e.g. from skill metadata).
               Falls back to the configured specialist model.
    """
    effective_model = model or settings.astryn_specialist_model
    return OllamaProvider(base_url=settings.ollama_base_url, model=effective_model)


def get_fallback_provider() -> LLMProvider:
    """Return the Ollama fallback provider (for when Anthropic is unavailable)."""
    return OllamaProvider(base_url=settings.ollama_base_url, model=_active_model)


async def list_available_models() -> list[str]:
    """Return all model names available in the local Ollama instance."""
    provider = OllamaProvider(base_url=settings.ollama_base_url, model=_active_model)
    return await provider.list_models()
