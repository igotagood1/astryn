"""Tests for POST /chat and DELETE /chat/{session_id}."""

from contextlib import ExitStack
from unittest.mock import AsyncMock, patch

import pytest

from llm.agent import AgentResult, PendingConfirmation
from store.domain import CommunicationPreferences, SessionState
from tools.registry import COORDINATOR_TOOLS


@pytest.fixture(autouse=True)
def _clear_chat_state():
    """Clear caches and locks between tests."""
    from api.routes.chat import _availability_cache, _session_locks

    _availability_cache.clear()
    _session_locks.clear()
    yield
    _availability_cache.clear()
    _session_locks.clear()


def _standard_patches(mock_coordinator, mock_specialist, agent_result):
    """Context managers for the standard set of patches needed for chat tests."""
    return [
        patch("api.routes.chat.get_coordinator_provider", return_value=mock_coordinator),
        patch("api.routes.chat.get_specialist_provider", return_value=mock_specialist),
        patch("api.routes.chat.run_agent", new_callable=AsyncMock, return_value=agent_result),
        patch(
            "services.session.ensure_session",
            new_callable=AsyncMock,
            return_value=SessionState(),
        ),
        patch("services.session.add_user_message", new_callable=AsyncMock),
        patch("services.session.get_history_for_llm", new_callable=AsyncMock, return_value=[]),
        patch("services.session.persist_agent_messages", new_callable=AsyncMock),
        patch("services.session.update_state", new_callable=AsyncMock),
        patch(
            "services.preferences.get_preferences",
            new_callable=AsyncMock,
            return_value=CommunicationPreferences(),
        ),
    ]


class TestChatEndpoint:
    async def test_chat_requires_auth(self, client):
        resp = await client.post("/chat", json={"message": "hello"})
        assert resp.status_code == 422  # missing header

    async def test_chat_rejects_bad_key(self, client):
        resp = await client.post(
            "/chat",
            json={"message": "hello"},
            headers={"X-Api-Key": "wrong-key"},
        )
        assert resp.status_code == 401

    async def test_chat_rejects_empty_message(self, client, auth_headers):
        resp = await client.post(
            "/chat",
            json={"message": ""},
            headers=auth_headers,
        )
        assert resp.status_code == 422

    async def test_chat_rejects_oversized_message(self, client, auth_headers):
        resp = await client.post(
            "/chat",
            json={"message": "a" * 32_001},
            headers=auth_headers,
        )
        assert resp.status_code == 422

    async def test_chat_returns_reply(self, client, auth_headers, mock_provider):
        agent_result = AgentResult(
            reply="Hello from LLM",
            model="ollama/test-model",
            messages=[
                {"role": "user", "content": "hello"},
                {"role": "assistant", "content": "Hello from LLM"},
            ],
        )

        with ExitStack() as stack:
            for cm in _standard_patches(mock_provider, mock_provider, agent_result):
                stack.enter_context(cm)
            resp = await client.post(
                "/chat",
                json={"message": "hello"},
                headers=auth_headers,
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["reply"] == "Hello from LLM"
        assert data["model"] == "ollama/test-model"
        assert data["action"] is None

    async def test_chat_returns_confirmation(self, client, auth_headers, mock_provider):
        pending = PendingConfirmation(
            id="confirm-123",
            session_id="default",
            tool_name="write_file",
            tool_args={"path": "test.py", "content": "print('hi')"},
            tool_call_id="call-1",
            preview="Write to test.py",
            system="system prompt",
            messages=[],
            session_state=SessionState(),
        )
        agent_result = AgentResult(
            reply="",
            model="ollama/test-model",
            messages=[],
            pending=pending,
        )

        with ExitStack() as stack:
            for cm in _standard_patches(mock_provider, mock_provider, agent_result):
                stack.enter_context(cm)
            resp = await client.post(
                "/chat",
                json={"message": "write a file"},
                headers=auth_headers,
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["action"] is not None
        assert data["action"]["type"] == "confirmation"
        assert data["action"]["id"] == "confirm-123"
        assert data["action"]["preview"] == "Write to test.py"

    async def test_chat_503_when_provider_down(self, client, auth_headers, mock_provider):
        mock_provider.is_available = AsyncMock(return_value=False)

        with (
            patch("api.routes.chat.get_coordinator_provider", return_value=mock_provider),
            patch("api.routes.chat.get_fallback_provider", return_value=mock_provider),
            patch(
                "services.session.ensure_session",
                new_callable=AsyncMock,
                return_value=SessionState(),
            ),
            patch("services.session.add_user_message", new_callable=AsyncMock),
        ):
            resp = await client.post(
                "/chat",
                json={"message": "hello"},
                headers=auth_headers,
            )

        assert resp.status_code == 503

    async def test_delete_clears_session(self, client, auth_headers):
        with patch("services.session.clear", new_callable=AsyncMock):
            resp = await client.delete("/chat/test-session", headers=auth_headers)

        assert resp.status_code == 200
        assert resp.json()["cleared"] == "test-session"

    async def test_delete_requires_auth(self, client):
        resp = await client.delete("/chat/test-session")
        assert resp.status_code == 422

    async def test_chat_uses_coordinator_tools(self, client, auth_headers, mock_provider):
        """Verify that run_agent is called with COORDINATOR_TOOLS."""
        agent_result = AgentResult(
            reply="Hi there",
            model="ollama/test-model",
            messages=[],
        )

        mock_run_agent = AsyncMock(return_value=agent_result)

        with (
            patch("api.routes.chat.get_coordinator_provider", return_value=mock_provider),
            patch("api.routes.chat.get_specialist_provider", return_value=mock_provider),
            patch("api.routes.chat.run_agent", mock_run_agent),
            patch(
                "services.session.ensure_session",
                new_callable=AsyncMock,
                return_value=SessionState(),
            ),
            patch("services.session.add_user_message", new_callable=AsyncMock),
            patch("services.session.get_history_for_llm", new_callable=AsyncMock, return_value=[]),
            patch("services.session.persist_agent_messages", new_callable=AsyncMock),
            patch("services.session.update_state", new_callable=AsyncMock),
            patch(
                "services.preferences.get_preferences",
                new_callable=AsyncMock,
                return_value=CommunicationPreferences(),
            ),
        ):
            await client.post(
                "/chat",
                json={"message": "hello"},
                headers=auth_headers,
            )

        call_kwargs = mock_run_agent.call_args
        assert call_kwargs.kwargs.get("tools") is COORDINATOR_TOOLS

    async def test_chat_passes_specialist_provider(self, client, auth_headers, mock_provider):
        """Verify that run_agent is called with specialist_provider."""
        agent_result = AgentResult(
            reply="Hi there",
            model="ollama/test-model",
            messages=[],
        )

        mock_run_agent = AsyncMock(return_value=agent_result)
        mock_specialist = AsyncMock()
        mock_specialist.model_name = "ollama/specialist-model"

        with (
            patch("api.routes.chat.get_coordinator_provider", return_value=mock_provider),
            patch("api.routes.chat.get_specialist_provider", return_value=mock_specialist),
            patch("api.routes.chat.run_agent", mock_run_agent),
            patch(
                "services.session.ensure_session",
                new_callable=AsyncMock,
                return_value=SessionState(),
            ),
            patch("services.session.add_user_message", new_callable=AsyncMock),
            patch("services.session.get_history_for_llm", new_callable=AsyncMock, return_value=[]),
            patch("services.session.persist_agent_messages", new_callable=AsyncMock),
            patch("services.session.update_state", new_callable=AsyncMock),
            patch(
                "services.preferences.get_preferences",
                new_callable=AsyncMock,
                return_value=CommunicationPreferences(),
            ),
        ):
            await client.post(
                "/chat",
                json={"message": "hello"},
                headers=auth_headers,
            )

        call_kwargs = mock_run_agent.call_args
        assert call_kwargs.kwargs.get("specialist_provider") is mock_specialist

    async def test_chat_uses_coordinator_prompt(self, client, auth_headers, mock_provider):
        """Verify that run_agent is called with coordinator prompt (not system.md)."""
        agent_result = AgentResult(
            reply="Hi there",
            model="ollama/test-model",
            messages=[],
        )

        mock_run_agent = AsyncMock(return_value=agent_result)

        with (
            patch("api.routes.chat.get_coordinator_provider", return_value=mock_provider),
            patch("api.routes.chat.get_specialist_provider", return_value=mock_provider),
            patch("api.routes.chat.run_agent", mock_run_agent),
            patch(
                "services.session.ensure_session",
                new_callable=AsyncMock,
                return_value=SessionState(),
            ),
            patch("services.session.add_user_message", new_callable=AsyncMock),
            patch("services.session.get_history_for_llm", new_callable=AsyncMock, return_value=[]),
            patch("services.session.persist_agent_messages", new_callable=AsyncMock),
            patch("services.session.update_state", new_callable=AsyncMock),
            patch(
                "services.preferences.get_preferences",
                new_callable=AsyncMock,
                return_value=CommunicationPreferences(),
            ),
        ):
            await client.post(
                "/chat",
                json={"message": "hello"},
                headers=auth_headers,
            )

        call_kwargs = mock_run_agent.call_args
        system_prompt = call_kwargs.kwargs.get("system") or call_kwargs.args[2]
        # Coordinator prompt should contain delegation instructions
        assert "delegate" in system_prompt.lower()
        assert "specialist" in system_prompt.lower()
