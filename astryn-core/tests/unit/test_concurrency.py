"""Tests for per-session locking, orphaned confirmation cleanup, and domain state management.

Locks in these behaviors:
- Only one chat request per session at a time (409 on concurrent access)
- Different sessions can process in parallel
- Locks are released after request completion
- Orphaned confirmations for the current session are auto-rejected on new messages
- Confirmations for other sessions are not affected
- Expired confirmations are cleaned up by TTL
- Cancel events are created during processing and cleaned up afterward
"""

import asyncio
import time
from contextlib import ExitStack
from unittest.mock import AsyncMock, patch

import pytest

from llm.agent import AgentResult, PendingConfirmation
from store.domain import (
    _CONFIRMATION_TTL,
    SessionState,
    cancel_events,
    cleanup_expired_confirmations,
    pending_confirmations,
)


@pytest.fixture(autouse=True)
def _clear_chat_state():
    """Clear caches and locks between tests."""
    from api.routes.chat import _availability_cache, _session_locks

    _availability_cache.clear()
    _session_locks.clear()
    yield
    _availability_cache.clear()
    _session_locks.clear()


def _make_pending(session_id: str, confirmation_id: str = "c-1", **kwargs) -> PendingConfirmation:
    """Helper to build a PendingConfirmation with sensible defaults."""
    defaults = dict(
        id=confirmation_id,
        session_id=session_id,
        tool_name="write_file",
        tool_args={"path": "test.py", "content": "x"},
        tool_call_id="call-1",
        preview="Write to test.py",
        system="system prompt",
        messages=[],
        session_state=SessionState(),
    )
    defaults.update(kwargs)
    return PendingConfirmation(**defaults)


def _standard_patches(mock_provider, agent_result, run_agent_side_effect=None):
    """Return context managers for the standard set of patches needed for chat tests."""
    run_agent_kwargs = {"return_value": agent_result}
    if run_agent_side_effect is not None:
        run_agent_kwargs = {"side_effect": run_agent_side_effect}

    from store.domain import CommunicationPreferences

    return [
        patch("api.routes.chat.get_coordinator_provider", return_value=mock_provider),
        patch("api.routes.chat.get_specialist_provider", return_value=mock_provider),
        patch("api.routes.chat.run_agent", new_callable=AsyncMock, **run_agent_kwargs),
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


class TestSessionLocking:
    """Verify that per-session locks prevent concurrent processing."""

    async def test_409_when_session_busy(self, client, auth_headers, mock_provider):
        """A second request to the same session while the first is processing gets 409."""
        # Gate that holds run_agent until we release it
        gate = asyncio.Event()

        async def slow_agent(**kwargs):
            await gate.wait()
            return AgentResult(reply="done", model="ollama/test-model", messages=[])

        with ExitStack() as stack:
            for cm in _standard_patches(mock_provider, None, run_agent_side_effect=slow_agent):
                stack.enter_context(cm)

            # Start first request (will block in run_agent)
            task1 = asyncio.create_task(
                client.post("/chat", json={"message": "first"}, headers=auth_headers)
            )
            # Give the event loop a chance to enter run_agent and acquire the lock
            await asyncio.sleep(0.05)

            # Second request should be rejected immediately
            resp2 = await client.post("/chat", json={"message": "second"}, headers=auth_headers)
            assert resp2.status_code == 409
            assert "already processing" in resp2.json()["detail"]

            # Release first request so it can finish
            gate.set()
            resp1 = await task1
            assert resp1.status_code == 200

    async def test_different_sessions_not_blocked(self, client, auth_headers, mock_provider):
        """Requests to different sessions should both succeed concurrently."""
        gate = asyncio.Event()

        async def slow_agent(**kwargs):
            await gate.wait()
            return AgentResult(reply="done", model="ollama/test-model", messages=[])

        with ExitStack() as stack:
            for cm in _standard_patches(mock_provider, None, run_agent_side_effect=slow_agent):
                stack.enter_context(cm)

            # Start request for session A
            task_a = asyncio.create_task(
                client.post(
                    "/chat",
                    json={"message": "hello", "session_id": "session-a"},
                    headers=auth_headers,
                )
            )
            await asyncio.sleep(0.05)

            # Start request for session B -- should NOT get 409
            task_b = asyncio.create_task(
                client.post(
                    "/chat",
                    json={"message": "hello", "session_id": "session-b"},
                    headers=auth_headers,
                )
            )
            await asyncio.sleep(0.05)

            # Release both
            gate.set()
            resp_a = await task_a
            resp_b = await task_b

            assert resp_a.status_code == 200
            assert resp_b.status_code == 200

    async def test_lock_released_after_request(self, client, auth_headers, mock_provider):
        """After a request completes, the same session can process another."""
        agent_result = AgentResult(reply="ok", model="ollama/test-model", messages=[])

        with ExitStack() as stack:
            for cm in _standard_patches(mock_provider, agent_result):
                stack.enter_context(cm)

            resp1 = await client.post("/chat", json={"message": "first"}, headers=auth_headers)
            assert resp1.status_code == 200

            # Second request to the same session should succeed
            resp2 = await client.post("/chat", json={"message": "second"}, headers=auth_headers)
            assert resp2.status_code == 200


class TestOrphanedConfirmations:
    """Verify that stale confirmations are cleaned up when a new message arrives."""

    async def test_orphaned_confirmations_cleared_on_new_message(
        self, client, auth_headers, mock_provider
    ):
        """Pending confirmations for the current session are removed when a new chat arrives."""
        pending = _make_pending("default", confirmation_id="orphan-1")
        pending_confirmations["orphan-1"] = pending

        agent_result = AgentResult(reply="fresh reply", model="ollama/test-model", messages=[])

        with ExitStack() as stack:
            for cm in _standard_patches(mock_provider, agent_result):
                stack.enter_context(cm)

            resp = await client.post("/chat", json={"message": "new message"}, headers=auth_headers)

        assert resp.status_code == 200
        assert "orphan-1" not in pending_confirmations

    async def test_other_session_confirmations_untouched(self, client, auth_headers, mock_provider):
        """Confirmations for a different session are not removed."""
        other_pending = _make_pending("other-session", confirmation_id="other-1")
        pending_confirmations["other-1"] = other_pending

        agent_result = AgentResult(reply="ok", model="ollama/test-model", messages=[])

        with ExitStack() as stack:
            for cm in _standard_patches(mock_provider, agent_result):
                stack.enter_context(cm)

            resp = await client.post(
                "/chat",
                json={"message": "hello", "session_id": "default"},
                headers=auth_headers,
            )

        assert resp.status_code == 200
        assert "other-1" in pending_confirmations
        assert pending_confirmations["other-1"].session_id == "other-session"


class TestConfirmationTTL:
    """Verify TTL-based cleanup of expired confirmations."""

    def test_expired_confirmations_cleaned_up(self):
        """Confirmations older than _CONFIRMATION_TTL are removed by cleanup."""
        old = _make_pending("s1", confirmation_id="expired-1")
        # Simulate creation far in the past
        old.created_at = time.monotonic() - _CONFIRMATION_TTL - 1
        pending_confirmations["expired-1"] = old

        result = cleanup_expired_confirmations()

        assert "expired-1" in result
        assert "expired-1" not in pending_confirmations

    def test_fresh_confirmations_not_cleaned(self):
        """Confirmations within the TTL window survive cleanup."""
        fresh = _make_pending("s1", confirmation_id="fresh-1")
        # created_at defaults to time.monotonic(), which is recent
        pending_confirmations["fresh-1"] = fresh

        result = cleanup_expired_confirmations()

        assert "fresh-1" not in result
        assert "fresh-1" in pending_confirmations

    def test_cleanup_returns_expired_ids(self):
        """cleanup_expired_confirmations returns the list of expired confirmation IDs."""
        old_1 = _make_pending("s1", confirmation_id="exp-1")
        old_1.created_at = time.monotonic() - _CONFIRMATION_TTL - 100
        old_2 = _make_pending("s2", confirmation_id="exp-2")
        old_2.created_at = time.monotonic() - _CONFIRMATION_TTL - 200

        fresh = _make_pending("s3", confirmation_id="keep-1")

        pending_confirmations["exp-1"] = old_1
        pending_confirmations["exp-2"] = old_2
        pending_confirmations["keep-1"] = fresh

        result = cleanup_expired_confirmations()

        assert set(result) == {"exp-1", "exp-2"}
        assert "keep-1" in pending_confirmations
        assert "exp-1" not in pending_confirmations
        assert "exp-2" not in pending_confirmations


class TestCancelEvents:
    """Verify cancel event lifecycle during chat processing."""

    async def test_cancel_event_created_during_request(self, client, auth_headers, mock_provider):
        """While run_agent is executing, cancel_events[session_id] should exist."""
        observed_cancel_event = {}

        async def spy_agent(**kwargs):
            session_id = kwargs.get("session_id", "default")
            # Capture whether the cancel event exists during processing
            observed_cancel_event["exists"] = session_id in cancel_events
            observed_cancel_event["is_event"] = isinstance(
                cancel_events.get(session_id), asyncio.Event
            )
            return AgentResult(reply="ok", model="ollama/test-model", messages=[])

        with ExitStack() as stack:
            for cm in _standard_patches(mock_provider, None, run_agent_side_effect=spy_agent):
                stack.enter_context(cm)

            resp = await client.post("/chat", json={"message": "hello"}, headers=auth_headers)

        assert resp.status_code == 200
        assert observed_cancel_event["exists"] is True
        assert observed_cancel_event["is_event"] is True
        # After completion, cancel event should be cleaned up
        assert "default" not in cancel_events

    async def test_cancel_event_cleaned_up_on_error(self, client, auth_headers, mock_provider):
        """Even when run_agent raises, the cancel event is cleaned up (finally block)."""
        event_existed = {}

        async def failing_agent(**kwargs):
            session_id = kwargs.get("session_id", "default")
            # Capture that the cancel event exists before we explode
            event_existed["before_error"] = session_id in cancel_events
            raise RuntimeError("agent exploded")

        with ExitStack() as stack:
            for cm in _standard_patches(mock_provider, None, run_agent_side_effect=failing_agent):
                stack.enter_context(cm)

            # The RuntimeError is unhandled by the route (only SQLAlchemyError is caught),
            # so it propagates through the ASGI transport. We catch it here.
            with pytest.raises(RuntimeError, match="agent exploded"):
                await client.post("/chat", json={"message": "hello"}, headers=auth_headers)

        # The cancel event was present during processing...
        assert event_existed["before_error"] is True
        # ...but cleaned up by the finally block despite the error
        assert "default" not in cancel_events
