"""Tests for llm/agent.py — agentic loop, confirmation pausing, resume."""

from unittest.mock import AsyncMock, patch

from llm.agent import (
    MAX_ITERATIONS,
    AgentResult,
    PendingConfirmation,
    _looks_like_failed_tool_call,
    resume_agent,
    run_agent,
)
from llm.base import LLMResponse
from store.domain import SessionState


def _patch_repo():
    """Patch DB repository calls to no-op for agent unit tests."""
    return patch(
        "llm.agent.repo",
        **{
            "log_tool_call": AsyncMock(),
        },
    )


class TestLooksLikeFailedToolCall:
    def test_valid_tool_call_json(self):
        assert _looks_like_failed_tool_call('{"name": "read_file", "arguments": {"path": "x"}}')

    def test_normal_text(self):
        assert not _looks_like_failed_tool_call("Hello, how can I help?")

    def test_json_without_name(self):
        assert not _looks_like_failed_tool_call('{"foo": "bar"}')

    def test_empty_string(self):
        assert not _looks_like_failed_tool_call("")

    def test_invalid_json(self):
        assert not _looks_like_failed_tool_call("{not json")


class TestRunAgent:
    async def test_simple_reply(self, mock_provider, mock_db):
        result = await run_agent(
            provider=mock_provider,
            messages=[{"role": "user", "content": "hello"}],
            system="system prompt",
            session_id="test-session",
            session_state=SessionState(),
            db=mock_db,
        )

        assert isinstance(result, AgentResult)
        assert result.reply == "Hello from the LLM"
        assert result.pending is None

    async def test_pauses_for_confirmation(self, mock_db):
        """When a tool requires confirmation, agent should pause."""
        provider = AsyncMock()
        provider.model_name = "ollama/test-model"

        provider.chat = AsyncMock(
            return_value=LLMResponse(
                content="",
                model="ollama/test-model",
                provider="ollama",
                tool_calls=[
                    {
                        "id": "call-1",
                        "function": {
                            "name": "write_file",
                            "arguments": {"path": "test.py", "content": "hello"},
                        },
                    }
                ],
            )
        )

        result = await run_agent(
            provider=provider,
            messages=[{"role": "user", "content": "write a file"}],
            system="system prompt",
            session_id="test-session",
            session_state=SessionState(),
            db=mock_db,
        )

        assert result.pending is not None
        assert result.pending.tool_name == "write_file"

    async def test_executes_safe_tools_immediately(self, mock_db, tmp_path):
        """Safe tools (like list_projects) should execute without pausing."""
        provider = AsyncMock()
        provider.model_name = "ollama/test-model"

        provider.chat = AsyncMock(
            side_effect=[
                LLMResponse(
                    content="",
                    model="ollama/test-model",
                    provider="ollama",
                    tool_calls=[
                        {
                            "id": "call-1",
                            "function": {"name": "list_projects", "arguments": {}},
                        }
                    ],
                ),
                LLMResponse(
                    content="Here are the projects.",
                    model="ollama/test-model",
                    provider="ollama",
                    tool_calls=[],
                ),
            ]
        )

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
            )

        assert result.reply == "Here are the projects."
        assert result.pending is None

    async def test_max_iterations(self, mock_db, tmp_path):
        """Agent should stop after MAX_ITERATIONS."""
        provider = AsyncMock()
        provider.model_name = "ollama/test-model"

        provider.chat = AsyncMock(
            return_value=LLMResponse(
                content="",
                model="ollama/test-model",
                provider="ollama",
                tool_calls=[
                    {
                        "id": "call-1",
                        "function": {"name": "list_projects", "arguments": {}},
                    }
                ],
            )
        )

        with (
            _patch_repo(),
            patch("tools.executor.REPOS_ROOT", tmp_path),
            patch("tools.safety.REPOS_ROOT", tmp_path),
        ):
            result = await run_agent(
                provider=provider,
                messages=[],
                system="system prompt",
                session_id="test-session",
                session_state=SessionState(),
                db=mock_db,
            )

        assert "max iterations" in result.reply.lower()
        assert provider.chat.call_count == MAX_ITERATIONS

    async def test_failed_tool_call_detection(self, mock_db):
        """When model outputs tool call as text, agent should detect it."""
        provider = AsyncMock()
        provider.model_name = "ollama/test-model"
        provider.chat = AsyncMock(
            return_value=LLMResponse(
                content='{"name": "read_file", "arguments": {"path": "x"}}',
                model="ollama/test-model",
                provider="ollama",
                tool_calls=[],
            )
        )

        result = await run_agent(
            provider=provider,
            messages=[{"role": "user", "content": "read a file"}],
            system="system prompt",
            session_id="test-session",
            session_state=SessionState(),
            db=mock_db,
        )

        assert "doesn't support tool use" in result.reply


class TestResumeAgent:
    async def test_resume_approved(self, mock_db, tmp_path):
        """Approved tool should execute and continue the loop."""
        provider = AsyncMock()
        provider.model_name = "ollama/test-model"
        provider.chat = AsyncMock(
            return_value=LLMResponse(
                content="File written successfully.",
                model="ollama/test-model",
                provider="ollama",
                tool_calls=[],
            )
        )

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
            )

        assert result.reply == "File written successfully."
        assert (tmp_path / "proj" / "test.py").read_text() == "hello"

    async def test_resume_rejected(self, mock_db):
        """Rejected tool should not execute; agent should continue."""
        provider = AsyncMock()
        provider.model_name = "ollama/test-model"
        provider.chat = AsyncMock(
            return_value=LLMResponse(
                content="Okay, cancelled.",
                model="ollama/test-model",
                provider="ollama",
                tool_calls=[],
            )
        )

        pending = PendingConfirmation(
            id="conf-1",
            session_id="test-session",
            tool_name="write_file",
            tool_args={"path": "test.py", "content": "hello"},
            tool_call_id="call-1",
            preview="Write to test.py",
            system="system prompt",
            messages=[{"role": "user", "content": "write test.py"}],
            session_state=SessionState(),
        )

        with _patch_repo():
            result = await resume_agent(
                provider=provider,
                pending=pending,
                approved=False,
                db=mock_db,
            )

        assert result.reply == "Okay, cancelled."
