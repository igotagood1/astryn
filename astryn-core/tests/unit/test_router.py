"""Tests for llm/router.py — active model management and multi-provider routing."""

from unittest.mock import patch

from llm.router import (
    get_active_model,
    get_coordinator_provider,
    get_fallback_provider,
    get_specialist_provider,
    set_active_model,
)


class TestActiveModel:
    def test_get_active_model_default(self):
        assert get_active_model() == "test-model"

    def test_set_and_get_active_model(self):
        set_active_model("new-model")
        assert get_active_model() == "new-model"


class TestCoordinatorProvider:
    def test_ollama_coordinator_by_default(self):
        """When coordinator_provider is 'ollama', returns OllamaProvider."""
        provider = get_coordinator_provider()
        assert "ollama" in provider.model_name

    def test_anthropic_coordinator_when_configured(self):
        """When coordinator is 'anthropic' with API key, returns AnthropicProvider."""
        from pydantic import SecretStr

        with (
            patch("llm.router.settings") as mock_settings,
        ):
            mock_settings.astryn_coordinator_provider = "anthropic"
            mock_settings.anthropic_api_key = SecretStr("sk-test-key")
            mock_settings.astryn_coordinator_model = "claude-sonnet-4-6"
            mock_settings.ollama_base_url = "http://localhost:11434"

            provider = get_coordinator_provider()
            assert "anthropic" in provider.model_name

    def test_falls_back_to_ollama_without_api_key(self):
        """When coordinator_provider is 'anthropic' but no API key, returns Ollama."""
        with patch("llm.router.settings") as mock_settings:
            mock_settings.astryn_coordinator_provider = "anthropic"
            mock_settings.anthropic_api_key = None
            mock_settings.ollama_base_url = "http://localhost:11434"
            mock_settings._active_model = "test-model"

            provider = get_coordinator_provider()
            assert "ollama" in provider.model_name


class TestSpecialistProvider:
    def test_default_specialist_model(self):
        provider = get_specialist_provider()
        assert "ollama" in provider.model_name

    def test_custom_model_override(self):
        provider = get_specialist_provider(model="deepseek-r1:7b")
        assert "deepseek-r1:7b" in provider.model_name

    def test_always_ollama(self):
        """Specialist provider is always Ollama, even when coordinator is Anthropic."""
        provider = get_specialist_provider()
        assert "ollama" in provider.model_name


class TestFallbackProvider:
    def test_returns_ollama(self):
        provider = get_fallback_provider()
        assert "ollama" in provider.model_name

    def test_uses_active_model(self):
        set_active_model("custom-model")
        provider = get_fallback_provider()
        assert "custom-model" in provider.model_name
