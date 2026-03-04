"""Tests for GET /models and POST /models/active."""

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
