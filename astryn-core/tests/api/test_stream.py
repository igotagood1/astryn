"""Tests for POST /chat/stream SSE endpoint.

Verifies:
- Auth requirements (missing key, bad key)
- Response content type is text/event-stream
- SSE event formatting for all event types (text_delta, tool_start, etc.)
- Provider unavailability returns 503
- Fallback_from metadata when coordinator falls back
"""

import json
from contextlib import ExitStack
from unittest.mock import AsyncMock, patch

import pytest

from llm.agent import AgentResult
from llm.events import StatusUpdate, TextDelta, ToolResult, ToolStart
from store.domain import CommunicationPreferences, SessionState


@pytest.fixture(autouse=True)
def _clear_availability_cache():
    """Clear the availability cache between tests so stale entries don't leak."""
    from api.routes.chat import _availability_cache

    _availability_cache.clear()
    yield
    _availability_cache.clear()


def _make_agent_result(reply="Hello", model="ollama/test-model"):
    """Build a minimal AgentResult for tests."""
    return AgentResult(
        reply=reply,
        model=model,
        messages=[
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": reply},
        ],
    )


def _mock_run_agent(result, pre_events=None):
    """Create an AsyncMock for run_agent that pushes events to the queue.

    The stream route calls run_agent(..., event_queue=queue) and then
    pushes AgentDone itself after run_agent returns. So the mock only
    needs to push intermediate events (TextDelta, ToolStart, etc.)
    and return the AgentResult.
    """

    async def _side_effect(**kwargs):
        queue = kwargs.get("event_queue")
        if queue and pre_events:
            for event in pre_events:
                await queue.put(event)
        return result

    return AsyncMock(side_effect=_side_effect)


def _standard_patches(mock_coordinator, mock_specialist, run_agent_mock):
    """Context managers for the standard set of patches needed for stream tests."""
    return [
        patch("api.routes.stream.get_coordinator_provider", return_value=mock_coordinator),
        patch("api.routes.stream.get_specialist_provider", return_value=mock_specialist),
        patch("api.routes.stream.run_agent", run_agent_mock),
        patch("api.routes.stream._is_available_cached", new_callable=AsyncMock, return_value=True),
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


def _parse_sse_events(body: str) -> list[dict]:
    """Parse SSE text into a list of {event, data} dicts."""
    events = []
    for block in body.strip().split("\n\n"):
        if not block.strip():
            continue
        event_type = None
        data = None
        for line in block.strip().split("\n"):
            if line.startswith("event: "):
                event_type = line[len("event: ") :]
            elif line.startswith("data: "):
                data = json.loads(line[len("data: ") :])
        if event_type is not None:
            events.append({"event": event_type, "data": data})
    return events


class TestStreamEndpoint:
    async def test_stream_requires_auth(self, client):
        """POST /chat/stream without X-Api-Key header returns 422."""
        resp = await client.post("/chat/stream", json={"message": "hello"})
        assert resp.status_code == 422

    async def test_stream_rejects_bad_key(self, client):
        """POST /chat/stream with wrong API key returns 401."""
        resp = await client.post(
            "/chat/stream",
            json={"message": "hello"},
            headers={"X-Api-Key": "wrong-key"},
        )
        assert resp.status_code == 401

    async def test_stream_returns_sse_content_type(self, client, auth_headers, mock_provider):
        """Response Content-Type is text/event-stream."""
        result = _make_agent_result()
        run_mock = _mock_run_agent(result)

        with ExitStack() as stack:
            for cm in _standard_patches(mock_provider, mock_provider, run_mock):
                stack.enter_context(cm)
            resp = await client.post(
                "/chat/stream",
                json={"message": "hello"},
                headers=auth_headers,
            )

        assert resp.status_code == 200
        assert "text/event-stream" in resp.headers["content-type"]

    async def test_stream_emits_done_event(self, client, auth_headers, mock_provider):
        """A completed agent run emits an event: done with the reply and model."""
        result = _make_agent_result(reply="Done reply", model="ollama/test-model")
        run_mock = _mock_run_agent(result)

        with ExitStack() as stack:
            for cm in _standard_patches(mock_provider, mock_provider, run_mock):
                stack.enter_context(cm)
            resp = await client.post(
                "/chat/stream",
                json={"message": "hello"},
                headers=auth_headers,
            )

        events = _parse_sse_events(resp.text)
        done_events = [e for e in events if e["event"] == "done"]
        assert len(done_events) == 1
        assert done_events[0]["data"]["reply"] == "Done reply"
        assert done_events[0]["data"]["model"] == "ollama/test-model"

    async def test_stream_emits_text_delta(self, client, auth_headers, mock_provider):
        """TextDelta events from run_agent appear as event: text_delta in the SSE stream."""
        result = _make_agent_result()
        run_mock = _mock_run_agent(result, pre_events=[TextDelta(text="Hello ")])

        with ExitStack() as stack:
            for cm in _standard_patches(mock_provider, mock_provider, run_mock):
                stack.enter_context(cm)
            resp = await client.post(
                "/chat/stream",
                json={"message": "hello"},
                headers=auth_headers,
            )

        events = _parse_sse_events(resp.text)
        text_events = [e for e in events if e["event"] == "text_delta"]
        assert len(text_events) == 1
        assert text_events[0]["data"]["text"] == "Hello "

        # done should still be the last event
        assert events[-1]["event"] == "done"

    async def test_stream_emits_tool_events(self, client, auth_headers, mock_provider):
        """ToolStart and ToolResult events appear in the SSE stream."""
        result = _make_agent_result()
        pre_events = [
            ToolStart(tool_name="read_file", tool_args={"path": "/tmp/x.py"}),
            ToolResult(tool_name="read_file", summary="Read 42 lines"),
        ]
        run_mock = _mock_run_agent(result, pre_events=pre_events)

        with ExitStack() as stack:
            for cm in _standard_patches(mock_provider, mock_provider, run_mock):
                stack.enter_context(cm)
            resp = await client.post(
                "/chat/stream",
                json={"message": "read a file"},
                headers=auth_headers,
            )

        events = _parse_sse_events(resp.text)
        tool_start_events = [e for e in events if e["event"] == "tool_start"]
        tool_result_events = [e for e in events if e["event"] == "tool_result"]

        assert len(tool_start_events) == 1
        assert tool_start_events[0]["data"]["tool"] == "read_file"
        assert tool_start_events[0]["data"]["args"] == {"path": "/tmp/x.py"}

        assert len(tool_result_events) == 1
        assert tool_result_events[0]["data"]["tool"] == "read_file"
        assert tool_result_events[0]["data"]["summary"] == "Read 42 lines"

    async def test_stream_emits_status_event(self, client, auth_headers, mock_provider):
        """StatusUpdate events appear as event: status in the SSE stream."""
        result = _make_agent_result()
        run_mock = _mock_run_agent(
            result, pre_events=[StatusUpdate(message="Delegating to code-writer...")]
        )

        with ExitStack() as stack:
            for cm in _standard_patches(mock_provider, mock_provider, run_mock):
                stack.enter_context(cm)
            resp = await client.post(
                "/chat/stream",
                json={"message": "write code"},
                headers=auth_headers,
            )

        events = _parse_sse_events(resp.text)
        status_events = [e for e in events if e["event"] == "status"]
        assert len(status_events) == 1
        assert status_events[0]["data"]["message"] == "Delegating to code-writer..."

    async def test_stream_emits_error_on_failure(self, client, auth_headers, mock_provider):
        """When run_agent raises, the stream emits an event: error."""

        async def _raise(**kwargs):
            raise RuntimeError("Something broke")

        run_mock = AsyncMock(side_effect=_raise)

        with ExitStack() as stack:
            for cm in _standard_patches(mock_provider, mock_provider, run_mock):
                stack.enter_context(cm)
            resp = await client.post(
                "/chat/stream",
                json={"message": "hello"},
                headers=auth_headers,
            )

        assert resp.status_code == 200  # SSE stream still starts; error is in the event
        events = _parse_sse_events(resp.text)
        error_events = [e for e in events if e["event"] == "error"]
        assert len(error_events) == 1
        assert "Something broke" in error_events[0]["data"]["error"]

    async def test_stream_503_when_provider_down(self, client, auth_headers, mock_provider):
        """When the coordinator and fallback are both unavailable, returns 503."""
        mock_provider.is_available = AsyncMock(return_value=False)

        with (
            patch("api.routes.stream.get_coordinator_provider", return_value=mock_provider),
            patch("api.routes.stream.get_fallback_provider", return_value=mock_provider),
            patch(
                "api.routes.stream._is_available_cached",
                new_callable=AsyncMock,
                return_value=False,
            ),
            patch(
                "services.session.ensure_session",
                new_callable=AsyncMock,
                return_value=SessionState(),
            ),
            patch("services.session.add_user_message", new_callable=AsyncMock),
        ):
            resp = await client.post(
                "/chat/stream",
                json={"message": "hello"},
                headers=auth_headers,
            )

        assert resp.status_code == 503

    async def test_stream_includes_fallback_from(self, client, auth_headers):
        """When the coordinator falls back due to unavailability, done event has fallback_from."""
        unavailable_provider = AsyncMock()
        unavailable_provider.model_name = "ollama/primary-model"

        fallback_provider = AsyncMock()
        fallback_provider.model_name = "ollama/test-model"
        fallback_provider.is_available = AsyncMock(return_value=True)

        result = _make_agent_result(model="ollama/test-model")
        run_mock = _mock_run_agent(result)

        with (
            patch("api.routes.stream.get_coordinator_provider", return_value=unavailable_provider),
            patch("api.routes.stream.get_specialist_provider", return_value=fallback_provider),
            patch("api.routes.stream.get_fallback_provider", return_value=fallback_provider),
            patch(
                "api.routes.stream._is_available_cached",
                new_callable=AsyncMock,
                side_effect=[False, True],
            ),
            patch("api.routes.stream.run_agent", run_mock),
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
            resp = await client.post(
                "/chat/stream",
                json={"message": "hello"},
                headers=auth_headers,
            )

        events = _parse_sse_events(resp.text)
        done_events = [e for e in events if e["event"] == "done"]
        assert len(done_events) == 1
        assert done_events[0]["data"]["fallback_from"] == "ollama/primary-model"
