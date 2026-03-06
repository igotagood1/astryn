"""Tests for GET /models, POST /models/active, and POST /models/pull."""

from unittest.mock import AsyncMock, patch


class TestModelsEndpoint:
    async def test_list_models(self, client, auth_headers):
        with patch(
            "api.routes.models.list_available_models",
            new_callable=AsyncMock,
            return_value=["model-a", "model-b"],
        ):
            resp = await client.get("/models", headers=auth_headers)

        assert resp.status_code == 200
        data = resp.json()
        assert "model-a" in data["models"]
        assert "active" in data

    async def test_list_models_requires_auth(self, client):
        resp = await client.get("/models")
        assert resp.status_code == 422

    async def test_set_model(self, client, auth_headers):
        with patch(
            "api.routes.models.list_available_models",
            new_callable=AsyncMock,
            return_value=["model-a", "model-b"],
        ):
            resp = await client.post(
                "/models/active",
                json={"model": "model-a"},
                headers=auth_headers,
            )

        assert resp.status_code == 200
        assert resp.json()["active"] == "model-a"

    async def test_set_unknown_model_404(self, client, auth_headers):
        with patch(
            "api.routes.models.list_available_models",
            new_callable=AsyncMock,
            return_value=["model-a"],
        ):
            resp = await client.post(
                "/models/active",
                json={"model": "nonexistent"},
                headers=auth_headers,
            )

        assert resp.status_code == 404

    async def test_set_model_requires_auth(self, client):
        resp = await client.post("/models/active", json={"model": "x"})
        assert resp.status_code == 422

    async def test_pull_model_error_does_not_leak_details(self, client, auth_headers):
        """When pull_model raises, the error detail must not expose internal info."""
        mock_provider = AsyncMock()
        mock_provider.is_available = AsyncMock(return_value=True)
        mock_provider.pull_model = AsyncMock(
            side_effect=RuntimeError("connection to /internal/socket failed")
        )

        with patch("api.routes.models.OllamaProvider", return_value=mock_provider):
            resp = await client.post(
                "/models/pull",
                json={"model": "bad-model"},
                headers=auth_headers,
            )

        assert resp.status_code == 500
        assert "/internal/socket" not in resp.json()["detail"]
        assert "failed" in resp.json()["detail"].lower()
