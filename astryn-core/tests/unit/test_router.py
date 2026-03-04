"""Tests for llm/router.py — active model management."""

from llm.router import get_active_model, get_provider, set_active_model


class TestRouter:
    def test_get_active_model_default(self):
        assert get_active_model() == "test-model"

    def test_set_and_get_active_model(self):
        set_active_model("new-model")
        assert get_active_model() == "new-model"

    def test_get_provider_returns_ollama(self):
        provider = get_provider()
        assert provider.model_name == "ollama/test-model"

    def test_provider_uses_active_model(self):
        set_active_model("custom-model")
        provider = get_provider()
        assert "custom-model" in provider.model_name
