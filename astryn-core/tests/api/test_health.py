"""Tests for GET /health — no auth required."""

from unittest.mock import AsyncMock, patch


class TestHealthEndpoint:
    async def test_health_ollama_up(self, client):
        with patch("api.routes.health.OllamaProvider") as MockProvider:
            instance = AsyncMock()
            instance.is_available = AsyncMock(return_value=True)
            MockProvider.return_value = instance

            resp = await client.get("/health")

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["ollama"] == "up"
        assert "model" in data

    async def test_health_ollama_down(self, client):
        with patch("api.routes.health.OllamaProvider") as MockProvider:
            instance = AsyncMock()
            instance.is_available = AsyncMock(return_value=False)
            MockProvider.return_value = instance

            resp = await client.get("/health")

        assert resp.status_code == 200
        data = resp.json()
        assert data["ollama"] == "down"

    async def test_health_no_auth_required(self, client):
        """Health endpoint should be accessible without an API key."""
        with patch("api.routes.health.OllamaProvider") as MockProvider:
            instance = AsyncMock()
            instance.is_available = AsyncMock(return_value=True)
            MockProvider.return_value = instance

            resp = await client.get("/health")

        assert resp.status_code == 200
