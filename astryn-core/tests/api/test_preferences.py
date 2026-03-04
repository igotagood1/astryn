"""Tests for GET/POST /preferences/{session_id}."""

from unittest.mock import AsyncMock, patch

from store.domain import CommunicationPreferences


class TestGetPreferences:
    async def test_returns_defaults(self, client, auth_headers):
        with patch(
            "services.preferences.get_preferences",
            new_callable=AsyncMock,
            return_value=CommunicationPreferences(),
        ):
            resp = await client.get("/preferences/test-session", headers=auth_headers)

        assert resp.status_code == 200
        data = resp.json()
        assert data["verbosity"] == "balanced"
        assert data["tone"] == "casual"
        assert data["code_explanation"] == "explain"
        assert data["proactive_suggestions"] is True

    async def test_requires_auth(self, client):
        resp = await client.get("/preferences/test-session")
        assert resp.status_code == 422


class TestUpdatePreference:
    async def test_update_verbosity(self, client, auth_headers):
        updated = CommunicationPreferences(verbosity="concise")
        with patch(
            "services.preferences.update_preference",
            new_callable=AsyncMock,
            return_value=updated,
        ):
            resp = await client.post(
                "/preferences/test-session",
                json={"field": "verbosity", "value": "concise"},
                headers=auth_headers,
            )

        assert resp.status_code == 200
        assert resp.json()["verbosity"] == "concise"

    async def test_update_proactive_suggestions(self, client, auth_headers):
        updated = CommunicationPreferences(proactive_suggestions=False)
        with patch(
            "services.preferences.update_preference",
            new_callable=AsyncMock,
            return_value=updated,
        ):
            resp = await client.post(
                "/preferences/test-session",
                json={"field": "proactive_suggestions", "value": False},
                headers=auth_headers,
            )

        assert resp.status_code == 200
        assert resp.json()["proactive_suggestions"] is False

    async def test_invalid_field(self, client, auth_headers):
        with patch(
            "services.preferences.update_preference",
            new_callable=AsyncMock,
            side_effect=ValueError("Unknown preference field: 'bad_field'"),
        ):
            resp = await client.post(
                "/preferences/test-session",
                json={"field": "bad_field", "value": "x"},
                headers=auth_headers,
            )

        assert resp.status_code == 400
        assert "Unknown preference field" in resp.json()["detail"]

    async def test_invalid_value(self, client, auth_headers):
        with patch(
            "services.preferences.update_preference",
            new_callable=AsyncMock,
            side_effect=ValueError("Invalid value for verbosity: 'verbose'"),
        ):
            resp = await client.post(
                "/preferences/test-session",
                json={"field": "verbosity", "value": "verbose"},
                headers=auth_headers,
            )

        assert resp.status_code == 400
        assert "Invalid value" in resp.json()["detail"]

    async def test_requires_auth(self, client):
        resp = await client.post(
            "/preferences/test-session",
            json={"field": "verbosity", "value": "concise"},
        )
        assert resp.status_code == 422
