"""Tests for delegation engine in llm/agent.py."""

from unittest.mock import AsyncMock, patch

import pytest

from llm.agent import PendingConfirmation, resume_agent, run_agent
from llm.base import LLMResponse
from store.domain import SessionState
from tools.registry import COORDINATOR_TOOLS, READ_WRITE_TOOLS


def _patch_repo():
    return patch(
        "llm.agent.repo",
        **{"log_tool_call": AsyncMock()},
    )


def _coordinator_delegate_response(skill="explore", task="list files", context=""):
    """LLM response that calls the delegate tool."""
    return LLMResponse(
        content="",
        model="ollama/test-model",
        provider="ollama",
        tool_calls=[
            {
                "id": "call-delegate-1",
                "function": {
                    "name": "delegate",
                    "arguments": {
                        "skill": skill,
                        "task": task,
                        "context": context,
                    },
                },
            }
        ],
    )


def _text_response(text="Done."):
    return LLMResponse(
        content=text,
        model="ollama/test-model",
        provider="ollama",
        tool_calls=[],
    )


def _tool_call_response(tool_name, tool_args, tool_call_id="call-1"):
    return LLMResponse(
        content="",
        model="ollama/test-model",
        provider="ollama",
        tool_calls=[
            {
                "id": tool_call_id,
                "function": {"name": tool_name, "arguments": tool_args},
            }
        ],
    )


class TestDelegateCallsSpecialist:
    async def test_delegate_triggers_specialist(self, mock_db, tmp_path):
        """Coordinator calls delegate → specialist runs → coordinator formats."""
        provider = AsyncMock()
        provider.model_name = "ollama/test-model"
        provider.chat = AsyncMock(
            side_effect=[
                # Coordinator calls delegate
                _coordinator_delegate_response("explore", "list available projects"),
                # Specialist runs list_projects, then replies
                _tool_call_response("list_projects", {}),
                _text_response("Projects: proj1, proj2"),
                # Coordinator formats specialist output
                _text_response("Here are your projects: proj1, proj2"),
            ]
        )

        with (
            _patch_repo(),
            patch("tools.executor.REPOS_ROOT", tmp_path),
            patch("tools.safety.REPOS_ROOT", tmp_path),
        ):
            (tmp_path / "proj1").mkdir()
            (tmp_path / "proj2").mkdir()

            result = await run_agent(
                provider=provider,
                messages=[{"role": "user", "content": "what projects are available?"}],
                system="coordinator prompt",
                session_id="test-session",
                session_state=SessionState(),
                db=mock_db,
                tools=COORDINATOR_TOOLS,
            )

        assert result.reply == "Here are your projects: proj1, proj2"
        assert result.pending is None

    async def test_delegate_returns_result_to_coordinator(self, mock_db, tmp_path):
        """Specialist reply becomes tool response for coordinator."""
        provider = AsyncMock()
        provider.model_name = "ollama/test-model"
        provider.chat = AsyncMock(
            side_effect=[
                _coordinator_delegate_response("explore", "what is in the project?"),
                # Specialist replies directly (no tools)
                _text_response("The project has 3 files: main.py, utils.py, tests.py"),
                # Coordinator formats
                _text_response("Your project contains 3 files: main.py, utils.py, and tests.py."),
            ]
        )

        with _patch_repo():
            result = await run_agent(
                provider=provider,
                messages=[{"role": "user", "content": "what's in my project?"}],
                system="coordinator prompt",
                session_id="test-session",
                session_state=SessionState(),
                db=mock_db,
                tools=COORDINATOR_TOOLS,
            )

        assert result.reply == "Your project contains 3 files: main.py, utils.py, and tests.py."

    async def test_delegate_unknown_specialist(self, mock_db):
        """Unknown specialist name returns error as tool result."""
        provider = AsyncMock()
        provider.model_name = "ollama/test-model"
        provider.chat = AsyncMock(
            side_effect=[
                _coordinator_delegate_response("nonexistent", "do something"),
                # Coordinator gets error and responds
                _text_response("I can't do that — unknown specialist."),
            ]
        )

        with _patch_repo():
            result = await run_agent(
                provider=provider,
                messages=[{"role": "user", "content": "delegate to unknown"}],
                system="coordinator prompt",
                session_id="test-session",
                session_state=SessionState(),
                db=mock_db,
                tools=COORDINATOR_TOOLS,
            )

        assert result.reply == "I can't do that — unknown specialist."


class TestSpecialistConfirmation:
    async def test_specialist_confirmation_bubbles_up(self, mock_db):
        """When specialist needs confirmation, it bubbles up to the user."""
        provider = AsyncMock()
        provider.model_name = "ollama/test-model"
        provider.chat = AsyncMock(
            side_effect=[
                # Coordinator delegates to code specialist
                _coordinator_delegate_response("code", "write hello.py"),
                # Specialist calls write_file (needs confirmation)
                _tool_call_response(
                    "write_file",
                    {"path": "hello.py", "content": "print('hello')"},
                    "call-write-1",
                ),
            ]
        )

        with _patch_repo():
            result = await run_agent(
                provider=provider,
                messages=[{"role": "user", "content": "create hello.py"}],
                system="coordinator prompt",
                session_id="test-session",
                session_state=SessionState(active_project="myproj"),
                db=mock_db,
                tools=COORDINATOR_TOOLS,
            )

        assert result.pending is not None
        assert result.pending.tool_name == "write_file"

    async def test_confirmation_has_coordinator_state(self, mock_db):
        """PendingConfirmation includes coordinator state for resume."""
        provider = AsyncMock()
        provider.model_name = "ollama/test-model"
        provider.chat = AsyncMock(
            side_effect=[
                _coordinator_delegate_response("code", "edit file"),
                _tool_call_response(
                    "write_file",
                    {"path": "x.py", "content": "x"},
                    "call-w",
                ),
            ]
        )

        with _patch_repo():
            result = await run_agent(
                provider=provider,
                messages=[{"role": "user", "content": "edit a file"}],
                system="coordinator prompt",
                session_id="test-session",
                session_state=SessionState(active_project="proj"),
                db=mock_db,
                tools=COORDINATOR_TOOLS,
            )

        pending = result.pending
        assert pending is not None
        assert pending.coordinator_messages is not None
        assert pending.coordinator_system == "coordinator prompt"
        assert pending.delegate_tool_call_id is not None


class TestResumeDelegated:
    async def test_resume_delegated_approved(self, mock_db, tmp_path):
        """Resume specialist → specialist finishes → coordinator formats."""
        provider = AsyncMock()
        provider.model_name = "ollama/test-model"
        provider.chat = AsyncMock(
            side_effect=[
                # Specialist continues after approval
                _text_response("File written: hello.py"),
                # Coordinator formats
                _text_response("Done — I wrote hello.py for you."),
            ]
        )

        (tmp_path / "proj").mkdir()

        # Build a PendingConfirmation with coordinator state (as if created by delegation)
        pending = PendingConfirmation(
            id="conf-1",
            session_id="test-session",
            tool_name="write_file",
            tool_args={"path": "hello.py", "content": "print('hello')"},
            tool_call_id="call-w",
            preview="Write hello.py",
            system="specialist prompt",
            messages=[{"role": "user", "content": "Task: write hello.py"}],
            session_state=SessionState(active_project="proj"),
            coordinator_messages=[
                {"role": "user", "content": "create hello.py"},
                {"role": "assistant", "content": "", "tool_calls": [{"id": "call-d"}]},
            ],
            coordinator_system="coordinator prompt",
            delegate_tool_call_id="call-d",
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

        assert result.reply == "Done — I wrote hello.py for you."

    async def test_resume_delegated_rejected(self, mock_db):
        """Rejection propagates: specialist sees rejection, coordinator formats."""
        provider = AsyncMock()
        provider.model_name = "ollama/test-model"
        provider.chat = AsyncMock(
            side_effect=[
                # Specialist after rejection
                _text_response("User rejected the write."),
                # Coordinator formats
                _text_response("Okay, I won't create that file."),
            ]
        )

        pending = PendingConfirmation(
            id="conf-1",
            session_id="test-session",
            tool_name="write_file",
            tool_args={"path": "x.py", "content": "x"},
            tool_call_id="call-w",
            preview="Write x.py",
            system="specialist prompt",
            messages=[{"role": "user", "content": "Task: write x.py"}],
            session_state=SessionState(),
            coordinator_messages=[
                {"role": "user", "content": "write x.py"},
                {"role": "assistant", "content": "", "tool_calls": [{"id": "call-d"}]},
            ],
            coordinator_system="coordinator prompt",
            delegate_tool_call_id="call-d",
        )

        with _patch_repo():
            result = await resume_agent(
                provider=provider,
                pending=pending,
                approved=False,
                db=mock_db,
            )

        assert result.reply == "Okay, I won't create that file."

    async def test_resume_non_delegated_unchanged(self, mock_db, tmp_path):
        """Non-delegated resume works as before (backward compat)."""
        provider = AsyncMock()
        provider.model_name = "ollama/test-model"
        provider.chat = AsyncMock(
            return_value=_text_response("File written."),
        )

        (tmp_path / "proj").mkdir()

        pending = PendingConfirmation(
            id="conf-1",
            session_id="test-session",
            tool_name="write_file",
            tool_args={"path": "test.py", "content": "hello"},
            tool_call_id="call-1",
            preview="Write test.py",
            system="system prompt",
            messages=[{"role": "user", "content": "write test.py"}],
            session_state=SessionState(active_project="proj"),
            # No coordinator state → backward compat path
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

        assert result.reply == "File written."
        assert (tmp_path / "proj" / "test.py").read_text() == "hello"


class TestCoordinatorFormatsAfterSpecialist:
    async def test_coordinator_processes_output(self, mock_db):
        """After specialist completes, coordinator gets the result and formats it."""
        provider = AsyncMock()
        provider.model_name = "ollama/test-model"
        call_count = 0

        async def mock_chat(messages, system, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                # Coordinator delegates
                return _coordinator_delegate_response("explore", "find README")
            elif call_count == 2:
                # Specialist returns result
                return _text_response("README.md contents:\n# My Project\nA cool project.")
            elif call_count == 3:
                # Coordinator formats specialist output
                return _text_response("Here's the README:\n\n# My Project\nA cool project.")
            return _text_response("unexpected")

        provider.chat = AsyncMock(side_effect=mock_chat)

        with _patch_repo():
            result = await run_agent(
                provider=provider,
                messages=[{"role": "user", "content": "show me the readme"}],
                system="coordinator prompt",
                session_id="test-session",
                session_state=SessionState(),
                db=mock_db,
                tools=COORDINATOR_TOOLS,
            )

        assert "README" in result.reply
        assert call_count == 3  # coordinator + specialist + coordinator format


class TestInvalidToolArguments:
    async def test_json_decode_error_handled(self, mock_db):
        """Malformed JSON in tool arguments returns error to LLM instead of crashing."""
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
                            "id": "call-bad",
                            "function": {
                                "name": "list_files",
                                "arguments": "{invalid json",
                            },
                        }
                    ],
                ),
                _text_response("I see the error, let me try again."),
            ]
        )

        with _patch_repo():
            result = await run_agent(
                provider=provider,
                messages=[{"role": "user", "content": "list files"}],
                system="system",
                session_id="test-session",
                session_state=SessionState(active_project="proj"),
                db=mock_db,
            )

        assert result.reply == "I see the error, let me try again."
        assert result.pending is None


class TestDelegateAuditLogging:
    async def test_delegate_call_is_audit_logged(self, mock_db):
        """Successful delegate calls are logged to the tool_audit table."""
        mock_repo = AsyncMock()
        mock_repo.log_tool_call = AsyncMock()

        provider = AsyncMock()
        provider.model_name = "ollama/test-model"
        provider.chat = AsyncMock(
            side_effect=[
                _coordinator_delegate_response("explore", "find files"),
                _text_response("Found some files."),
                _text_response("Here are your files."),
            ]
        )

        with patch("llm.agent.repo", mock_repo):
            await run_agent(
                provider=provider,
                messages=[{"role": "user", "content": "find files"}],
                system="coordinator prompt",
                session_id="test-session",
                session_state=SessionState(),
                db=mock_db,
                tools=COORDINATOR_TOOLS,
            )

        # Verify log_tool_call was called with tool_name="delegate"
        delegate_logs = [
            call
            for call in mock_repo.log_tool_call.call_args_list
            if call.kwargs.get("tool_name") == "delegate"
        ]
        assert len(delegate_logs) == 1
        assert delegate_logs[0].kwargs["external_id"] == "test-session"


class TestResumeExecuteToolError:
    async def test_resume_approved_tool_failure_continues(self, mock_db):
        """When an approved tool raises an exception, the error is fed to the LLM."""
        provider = AsyncMock()
        provider.model_name = "ollama/test-model"
        provider.chat = AsyncMock(
            return_value=_text_response("The command failed, but I can try something else."),
        )

        pending = PendingConfirmation(
            id="conf-1",
            session_id="test-session",
            tool_name="run_command",
            tool_args={"command": "make build"},
            tool_call_id="call-1",
            preview="Run: make build",
            system="system prompt",
            messages=[{"role": "user", "content": "run make build"}],
            session_state=SessionState(active_project="proj"),
        )

        with (
            _patch_repo(),
            patch(
                "llm.agent.execute_tool",
                new_callable=AsyncMock,
                side_effect=RuntimeError("Command timed out"),
            ),
        ):
            result = await resume_agent(
                provider=provider,
                pending=pending,
                approved=True,
                db=mock_db,
            )

        assert result.pending is None
        # The LLM received the error and produced a response
        assert "failed" in result.reply.lower() or "try" in result.reply.lower()


class TestTestWriterDelegation:
    async def test_test_writer_gets_read_write_tools(self, mock_db):
        """Delegating to test-writer provides READ_WRITE_TOOLS (write but no run_command)."""
        provider = AsyncMock()
        provider.model_name = "ollama/test-model"

        specialist_tools = None
        responses = [
            _coordinator_delegate_response("test-writer", "write unit tests"),
            _text_response("Tests written: test_foo.py"),
            _text_response("I wrote the tests for you."),
        ]
        call_idx = 0

        async def tracking_chat(messages, system, tools=None, **kwargs):
            nonlocal call_idx, specialist_tools
            result = responses[call_idx]
            call_idx += 1
            if call_idx == 2:  # specialist call
                specialist_tools = tools
            return result

        provider.chat = AsyncMock(side_effect=tracking_chat)

        with _patch_repo():
            await run_agent(
                provider=provider,
                messages=[{"role": "user", "content": "write tests"}],
                system="coordinator prompt",
                session_id="test-session",
                session_state=SessionState(active_project="myproj"),
                db=mock_db,
                tools=COORDINATOR_TOOLS,
            )

        assert specialist_tools is READ_WRITE_TOOLS


class TestDelegateModelValidation:
    def test_delegate_empty_skill_rejected(self):
        """Delegate model rejects empty skill field."""
        from pydantic import ValidationError

        from tools.models import Delegate

        with pytest.raises(ValidationError):
            Delegate(skill="", task="do something")

    def test_delegate_empty_task_rejected(self):
        """Delegate model rejects empty task field."""
        from pydantic import ValidationError

        from tools.models import Delegate

        with pytest.raises(ValidationError):
            Delegate(skill="code", task="")

    def test_delegate_valid_passes(self):
        """Delegate model accepts valid inputs."""
        from tools.models import Delegate

        d = Delegate(skill="code", task="write a file")
        assert d.skill == "code"
        assert d.specialist == "code"  # backward-compat property
        assert d.task == "write a file"
        assert d.context == ""


class TestDelegateInExecutor:
    async def test_delegate_rejected_by_executor(self):
        """Delegate tool is handled by agent loop, executor returns informational message."""
        from tools.executor import execute_tool

        result = await execute_tool("delegate", {"skill": "code", "task": "test"}, SessionState())
        assert "agent loop" in result.lower()


class TestMultiProviderDelegation:
    async def test_specialist_provider_used_for_delegate(self, mock_db, tmp_path):
        """When specialist_provider is set, delegate uses it instead of coordinator provider."""
        coordinator = AsyncMock()
        coordinator.model_name = "anthropic/claude-sonnet-4-6"

        specialist = AsyncMock()
        specialist.model_name = "ollama/test-model"

        # Coordinator delegates, specialist runs, coordinator formats
        coordinator.chat = AsyncMock(
            side_effect=[
                _coordinator_delegate_response("explore", "list files"),
                _text_response("Here are your files."),
            ]
        )
        specialist.chat = AsyncMock(
            return_value=_text_response("Found: main.py, utils.py"),
        )

        with _patch_repo():
            result = await run_agent(
                provider=coordinator,
                messages=[{"role": "user", "content": "list files"}],
                system="coordinator prompt",
                session_id="test-session",
                session_state=SessionState(),
                db=mock_db,
                tools=COORDINATOR_TOOLS,
                specialist_provider=specialist,
            )

        assert result.reply == "Here are your files."
        # Specialist provider should have been called (for the explore agent)
        assert specialist.chat.call_count == 1
        # Coordinator should have been called twice (delegate + format)
        assert coordinator.chat.call_count == 2

    async def test_resume_with_coordinator_provider(self, mock_db, tmp_path):
        """Resume passes coordinator_provider to _resume_coordinator."""
        specialist = AsyncMock()
        specialist.model_name = "ollama/test-model"
        specialist.chat = AsyncMock(
            return_value=_text_response("File written: hello.py"),
        )

        coordinator = AsyncMock()
        coordinator.model_name = "anthropic/claude-sonnet-4-6"
        coordinator.chat = AsyncMock(
            return_value=_text_response("Done — I wrote hello.py for you."),
        )

        (tmp_path / "proj").mkdir()

        pending = PendingConfirmation(
            id="conf-1",
            session_id="test-session",
            tool_name="write_file",
            tool_args={"path": "hello.py", "content": "print('hello')"},
            tool_call_id="call-w",
            preview="Write hello.py",
            system="specialist prompt",
            messages=[{"role": "user", "content": "Task: write hello.py"}],
            session_state=SessionState(active_project="proj"),
            coordinator_messages=[
                {"role": "user", "content": "create hello.py"},
                {"role": "assistant", "content": "", "tool_calls": [{"id": "call-d"}]},
            ],
            coordinator_system="coordinator prompt",
            delegate_tool_call_id="call-d",
        )

        with (
            _patch_repo(),
            patch("tools.executor.REPOS_ROOT", tmp_path),
            patch("tools.safety.REPOS_ROOT", tmp_path),
        ):
            result = await resume_agent(
                provider=specialist,
                pending=pending,
                approved=True,
                db=mock_db,
                coordinator_provider=coordinator,
            )

        assert result.reply == "Done — I wrote hello.py for you."
        # Coordinator should have been used for the final formatting
        assert coordinator.chat.call_count == 1
