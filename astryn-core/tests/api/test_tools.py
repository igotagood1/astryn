"""Tests for POST /confirm/{confirmation_id}."""

from unittest.mock import AsyncMock, patch

from llm.agent import AgentResult, PendingConfirmation
from store.domain import SessionState, pending_confirmations


class TestConfirmEndpoint:
    def _make_pending(self, confirmation_id="conf-1"):
        return PendingConfirmation(
            id=confirmation_id,
            session_id="default",
            tool_name="write_file",
            tool_args={"path": "test.py", "content": "hello"},
            tool_call_id="call-1",
            preview="Write to test.py",
            system="system prompt",
            messages=[{"role": "user", "content": "write test.py"}],
            session_state=SessionState(),
        )

    async def test_approve_tool(self, client, auth_headers, mock_provider):
        pending = self._make_pending()
        pending_confirmations[pending.id] = pending

        agent_result = AgentResult(
            reply="Done, wrote file.",
            model="ollama/test-model",
            messages=[],
        )

        with (
            patch("api.routes.tools.get_provider", return_value=mock_provider),
            patch(
                "api.routes.tools.resume_agent",
                new_callable=AsyncMock,
                return_value=agent_result,
            ),
            patch("services.session.persist_agent_messages", new_callable=AsyncMock),
            patch("services.session.update_state", new_callable=AsyncMock),
        ):
            resp = await client.post(
                f"/confirm/{pending.id}",
                json={"action": "approve"},
                headers=auth_headers,
            )

        assert resp.status_code == 200
        assert resp.json()["reply"] == "Done, wrote file."
        assert pending.id not in pending_confirmations

    async def test_reject_tool(self, client, auth_headers, mock_provider):
        pending = self._make_pending()
        pending_confirmations[pending.id] = pending

        agent_result = AgentResult(
            reply="Okay, cancelled.",
            model="ollama/test-model",
            messages=[],
        )

        with (
            patch("api.routes.tools.get_provider", return_value=mock_provider),
            patch(
                "api.routes.tools.resume_agent",
                new_callable=AsyncMock,
                return_value=agent_result,
            ),
            patch("services.session.persist_agent_messages", new_callable=AsyncMock),
            patch("services.session.update_state", new_callable=AsyncMock),
        ):
            resp = await client.post(
                f"/confirm/{pending.id}",
                json={"action": "reject"},
                headers=auth_headers,
            )

        assert resp.status_code == 200

    async def test_unknown_confirmation_404(self, client, auth_headers):
        resp = await client.post(
            "/confirm/nonexistent",
            json={"action": "approve"},
            headers=auth_headers,
        )
        assert resp.status_code == 404

    async def test_invalid_action_422(self, client, auth_headers):
        resp = await client.post(
            "/confirm/any-id",
            json={"action": "maybe"},
            headers=auth_headers,
        )
        assert resp.status_code == 422

    async def test_confirm_requires_auth(self, client):
        resp = await client.post("/confirm/abc", json={"action": "approve"})
        assert resp.status_code == 422
