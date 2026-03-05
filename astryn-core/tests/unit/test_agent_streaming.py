"""Tests for streaming event emission and cancellation in the agent loop.

Locks in these behaviors:
- _chat_with_streaming dispatches to chat() or chat_stream() based on event_queue
- Text deltas from chat_stream are pushed as TextDelta events
- The final LLMResponse from the stream is returned
- A stream that yields no LLMResponse raises RuntimeError
- Tool execution emits ToolStart and ToolResult events on the queue
- Delegation emits a StatusUpdate event
- resume_agent emits tool events when approved
- cancel_event stops the agent loop early
- cancel_event=None is safely ignored
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from llm.agent import (
    PendingConfirmation,
    _chat_with_streaming,
    _emit,
    resume_agent,
    run_agent,
)
from llm.base import LLMResponse
from llm.events import StatusUpdate, TextDelta, ToolResult, ToolStart
from llm.skills import SkillDef
from store.domain import SessionState
from tools.registry import WRITER_TOOLS


def _patch_repo():
    """Patch DB repository calls to no-op for agent unit tests."""
    return patch(
        "llm.agent.repo",
        **{
            "log_tool_call": AsyncMock(),
        },
    )


def _make_stream_fn(responses: list[LLMResponse]):
    """Build a chat_stream async generator function.

    Each invocation pops the next response from the list, yields its content
    as a text chunk (if non-empty), then yields the LLMResponse itself. This
    matches the contract of LLMProvider.chat_stream.
    """
    call_index = 0

    async def stream_fn(*args, **kwargs):
        nonlocal call_index
        resp = responses[call_index]
        call_index += 1
        if resp.content:
            yield resp.content
        yield resp

    return stream_fn


def _make_provider(
    chat_return: LLMResponse | None = None,
    chat_side_effect: list | None = None,
    model_name: str = "ollama/test-model",
) -> MagicMock:
    """Build a mock LLMProvider with configurable chat and chat_stream.

    Uses MagicMock as the base so that chat_stream can be assigned as a bare
    async generator function. AsyncMock wraps side_effect generators in a
    coroutine, which breaks ``async for`` iteration.
    """
    provider = MagicMock()
    provider.model_name = model_name
    provider.is_available = AsyncMock(return_value=True)

    if chat_side_effect is not None:
        provider.chat = AsyncMock(side_effect=chat_side_effect)
        provider.chat_stream = _make_stream_fn(list(chat_side_effect))
    elif chat_return is not None:
        provider.chat = AsyncMock(return_value=chat_return)
        provider.chat_stream = _make_stream_fn([chat_return])
    else:
        default = LLMResponse(content="Hello", model=model_name, provider="ollama", tool_calls=[])
        provider.chat = AsyncMock(return_value=default)
        provider.chat_stream = _make_stream_fn([default])

    return provider


def _simple_response(content="Hello", tool_calls=None):
    return LLMResponse(
        content=content,
        model="ollama/test-model",
        provider="ollama",
        tool_calls=tool_calls or [],
    )


def _tool_response(tool_calls, content=""):
    return LLMResponse(
        content=content,
        model="ollama/test-model",
        provider="ollama",
        tool_calls=tool_calls,
    )


# ---------------------------------------------------------------------------
# TestEmit — basic helper
# ---------------------------------------------------------------------------


class TestEmit:
    async def test_emit_pushes_to_queue(self):
        queue = asyncio.Queue()
        event = TextDelta(text="hello")
        await _emit(queue, event)
        assert queue.qsize() == 1
        assert (await queue.get()) is event

    async def test_emit_does_nothing_when_queue_is_none(self):
        # Should not raise
        await _emit(None, TextDelta(text="hello"))


# ---------------------------------------------------------------------------
# TestChatWithStreaming — _chat_with_streaming behavior
# ---------------------------------------------------------------------------


class TestChatWithStreaming:
    async def test_no_streaming_without_queue(self):
        """When event_queue is None, calls provider.chat() directly (not chat_stream)."""
        response = _simple_response("direct reply")
        provider = _make_provider(chat_return=response)

        # Track whether chat_stream was called
        stream_called = False
        original_stream = provider.chat_stream

        async def tracked_stream(*args, **kwargs):
            nonlocal stream_called
            stream_called = True
            async for chunk in original_stream(*args, **kwargs):
                yield chunk

        provider.chat_stream = tracked_stream

        result = await _chat_with_streaming(
            provider=provider,
            messages=[{"role": "user", "content": "hi"}],
            system="sys",
            tools=None,
            event_queue=None,
        )

        assert result is response
        provider.chat.assert_awaited_once()
        assert not stream_called, "chat_stream should not be called when event_queue is None"

    async def test_streams_text_deltas_to_queue(self):
        """With event_queue, text chunks from chat_stream become TextDelta events."""
        final_response = _simple_response("full text")

        async def fake_stream(*args, **kwargs):
            yield "chunk1"
            yield "chunk2"
            yield final_response

        provider = _make_provider()
        provider.chat_stream = fake_stream

        queue = asyncio.Queue()
        result = await _chat_with_streaming(
            provider=provider,
            messages=[{"role": "user", "content": "hi"}],
            system="sys",
            tools=None,
            event_queue=queue,
        )

        # Two text deltas should be on the queue
        events = []
        while not queue.empty():
            events.append(await queue.get())

        assert len(events) == 2
        assert all(isinstance(e, TextDelta) for e in events)
        assert events[0].text == "chunk1"
        assert events[1].text == "chunk2"

        # The final LLMResponse is returned
        assert result is final_response

    async def test_returns_final_response(self):
        """The LLMResponse yielded last from chat_stream is returned."""
        final = _simple_response("final text")

        async def fake_stream(*args, **kwargs):
            yield "partial"
            yield final

        provider = _make_provider()
        provider.chat_stream = fake_stream

        result = await _chat_with_streaming(
            provider=provider,
            messages=[],
            system="sys",
            tools=None,
            event_queue=asyncio.Queue(),
        )

        assert result is final
        assert result.content == "final text"

    async def test_raises_if_no_response(self):
        """If chat_stream yields only strings but no LLMResponse, raises RuntimeError."""

        async def bad_stream(*args, **kwargs):
            yield "text only"
            yield "more text"

        provider = _make_provider()
        provider.chat_stream = bad_stream

        with pytest.raises(RuntimeError, match="without yielding an LLMResponse"):
            await _chat_with_streaming(
                provider=provider,
                messages=[],
                system="sys",
                tools=None,
                event_queue=asyncio.Queue(),
            )


# ---------------------------------------------------------------------------
# TestAgentEventEmission — events during run_agent
# ---------------------------------------------------------------------------


class TestAgentEventEmission:
    async def test_emits_tool_start_and_result(self, mock_db, tmp_path):
        """When agent executes a safe tool, ToolStart and ToolResult events appear on the queue."""
        provider = _make_provider(
            chat_side_effect=[
                _tool_response(
                    [
                        {
                            "id": "call-1",
                            "function": {"name": "list_projects", "arguments": {}},
                        }
                    ]
                ),
                _simple_response("Done"),
            ]
        )

        queue = asyncio.Queue()

        with (
            _patch_repo(),
            patch("tools.executor.REPOS_ROOT", tmp_path),
            patch("tools.safety.REPOS_ROOT", tmp_path),
        ):
            (tmp_path / "proj1").mkdir()
            result = await run_agent(
                provider=provider,
                messages=[{"role": "user", "content": "list projects"}],
                system="system prompt",
                session_id="test-session",
                session_state=SessionState(),
                db=mock_db,
                event_queue=queue,
            )

        assert result.reply == "Done"

        events = []
        while not queue.empty():
            events.append(await queue.get())

        # Filter to tool events (ignore TextDelta from streaming)
        tool_events = [e for e in events if isinstance(e, (ToolStart, ToolResult))]
        assert len(tool_events) == 2
        assert isinstance(tool_events[0], ToolStart)
        assert tool_events[0].tool_name == "list_projects"
        assert isinstance(tool_events[1], ToolResult)
        assert tool_events[1].tool_name == "list_projects"

    async def test_emits_status_on_delegation(self, mock_db, tmp_path):
        """When delegate tool is called, StatusUpdate 'Delegating to ...' appears on queue."""
        from llm.skills import invalidate_skill_cache

        mock_skill = SkillDef(
            name="code-writer",
            description="Write code",
            system_prompt="You are a code writer.",
            tools=WRITER_TOOLS,
        )

        # Call 1 (coordinator): delegates to code-writer
        coordinator_response = _tool_response(
            [
                {
                    "id": "call-delegate",
                    "function": {
                        "name": "delegate",
                        "arguments": {
                            "skill": "code-writer",
                            "task": "write hello.py",
                            "context": "",
                        },
                    },
                }
            ]
        )
        # Call 2 (specialist): simple reply
        specialist_response = _simple_response("Wrote hello.py")
        # Call 3 (coordinator resumes): final reply
        coordinator_final = _simple_response("The specialist wrote hello.py for you.")

        responses = [coordinator_response, specialist_response, coordinator_final]
        provider = _make_provider(chat_side_effect=responses)

        queue = asyncio.Queue()

        # Invalidate skill cache so our patch takes effect
        invalidate_skill_cache()

        with (
            _patch_repo(),
            patch("tools.executor.REPOS_ROOT", tmp_path),
            patch("tools.safety.REPOS_ROOT", tmp_path),
            patch("llm.skills.discover_skills", return_value={"code-writer": mock_skill}),
        ):
            await run_agent(
                provider=provider,
                messages=[{"role": "user", "content": "write hello.py"}],
                system="system prompt",
                session_id="test-session",
                session_state=SessionState(active_project="proj"),
                db=mock_db,
                event_queue=queue,
            )

        events = []
        while not queue.empty():
            events.append(await queue.get())

        status_events = [e for e in events if isinstance(e, StatusUpdate)]
        delegation_msgs = [e for e in status_events if "Delegating to" in e.message]
        assert len(delegation_msgs) >= 1
        assert "code-writer" in delegation_msgs[0].message

        # Clean up cache
        invalidate_skill_cache()

    async def test_resume_emits_tool_events(self, mock_db, tmp_path):
        """resume_agent with approved=True emits ToolStart and ToolResult."""
        provider = _make_provider(chat_return=_simple_response("File written."))

        (tmp_path / "proj").mkdir()

        pending = PendingConfirmation(
            id="conf-1",
            session_id="test-session",
            tool_name="write_file",
            tool_args={"path": "test.py", "content": "hello"},
            tool_call_id="call-1",
            preview="Write to test.py",
            system="system prompt",
            messages=[{"role": "user", "content": "write test.py"}],
            session_state=SessionState(active_project="proj"),
        )

        queue = asyncio.Queue()

        with (
            _patch_repo(),
            patch("tools.executor.REPOS_ROOT", tmp_path),
            patch("tools.safety.REPOS_ROOT", tmp_path),
        ):
            result = await resume_agent(
                provider=provider,
                pending=pending,
                approved=True,
                db=mock_db,
                event_queue=queue,
            )

        assert result.reply == "File written."

        events = []
        while not queue.empty():
            events.append(await queue.get())

        tool_events = [e for e in events if isinstance(e, (ToolStart, ToolResult))]
        assert len(tool_events) >= 2
        # First event is ToolStart for write_file
        start_events = [e for e in tool_events if isinstance(e, ToolStart)]
        assert any(e.tool_name == "write_file" for e in start_events)
        # Should also have a ToolResult for write_file
        result_events = [e for e in tool_events if isinstance(e, ToolResult)]
        assert any(e.tool_name == "write_file" for e in result_events)


# ---------------------------------------------------------------------------
# TestCancellation — cancel_event behavior
# ---------------------------------------------------------------------------


class TestCancellation:
    async def test_cancel_event_stops_agent(self, mock_db):
        """When cancel_event is set before first iteration, returns 'Request cancelled.'."""
        provider = _make_provider()
        cancel = asyncio.Event()
        cancel.set()  # already cancelled

        result = await run_agent(
            provider=provider,
            messages=[{"role": "user", "content": "hello"}],
            system="system prompt",
            session_id="test-session",
            session_state=SessionState(),
            db=mock_db,
            cancel_event=cancel,
        )

        assert result.reply == "Request cancelled."
        # Provider should never be called
        provider.chat.assert_not_awaited()

    async def test_cancel_event_mid_loop(self, mock_db, tmp_path):
        """Set cancel_event after first iteration; agent stops early."""
        cancel = asyncio.Event()

        call_count = 0

        async def chat_with_cancel(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                # First call returns a tool call to force another iteration
                cancel.set()  # cancel before next iteration
                return _tool_response(
                    [
                        {
                            "id": "call-1",
                            "function": {"name": "list_projects", "arguments": {}},
                        }
                    ]
                )
            # Should not reach here since cancel was set
            return _simple_response("Should not see this")

        provider = _make_provider()
        provider.chat = AsyncMock(side_effect=chat_with_cancel)

        with (
            _patch_repo(),
            patch("tools.executor.REPOS_ROOT", tmp_path),
            patch("tools.safety.REPOS_ROOT", tmp_path),
        ):
            result = await run_agent(
                provider=provider,
                messages=[{"role": "user", "content": "hello"}],
                system="system prompt",
                session_id="test-session",
                session_state=SessionState(),
                db=mock_db,
                cancel_event=cancel,
            )

        assert result.reply == "Request cancelled."
        # chat was called once (the first iteration), then cancel kicked in
        assert call_count == 1

    async def test_cancel_event_none_is_ignored(self, mock_db):
        """When cancel_event is None, agent runs normally."""
        provider = _make_provider(chat_return=_simple_response("All good"))

        result = await run_agent(
            provider=provider,
            messages=[{"role": "user", "content": "hello"}],
            system="system prompt",
            session_id="test-session",
            session_state=SessionState(),
            db=mock_db,
            cancel_event=None,
        )

        assert result.reply == "All good"
        provider.chat.assert_awaited_once()
