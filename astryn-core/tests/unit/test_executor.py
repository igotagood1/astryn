"""Tests for tools/executor.py — tool dispatch, confirmation, and preview."""

from contextlib import contextmanager
from unittest.mock import patch

from store.domain import SessionState
from tools.executor import (
    build_preview,
    execute_tool,
    requires_confirmation,
)


@contextmanager
def _patch_repos_root(tmp_path):
    """Patch REPOS_ROOT in both executor and safety modules."""
    with (
        patch("tools.executor.REPOS_ROOT", tmp_path),
        patch("tools.safety.REPOS_ROOT", tmp_path),
    ):
        yield


class TestRequiresConfirmation:
    def test_write_file_always_confirms(self):
        assert requires_confirmation("write_file", {"path": "x", "content": "y"}) is True

    def test_apply_diff_always_confirms(self):
        args = {"path": "x", "old_str": "a", "new_str": "b"}
        assert requires_confirmation("apply_diff", args) is True

    def test_list_projects_no_confirm(self):
        assert requires_confirmation("list_projects", {}) is False

    def test_read_file_no_confirm(self):
        assert requires_confirmation("read_file", {"path": "x"}) is False

    def test_list_files_no_confirm(self):
        assert requires_confirmation("list_files", {"path": "."}) is False

    def test_search_files_no_confirm(self):
        assert requires_confirmation("search_files", {"pattern": "*.py"}) is False

    def test_run_command_immediate(self):
        assert requires_confirmation("run_command", {"command": "git status"}) is False

    def test_run_command_confirmation(self):
        assert requires_confirmation("run_command", {"command": "git add ."}) is True

    def test_unknown_tool_confirms(self):
        assert requires_confirmation("unknown_tool", {}) is True


class TestBuildPreview:
    def test_write_file_preview(self):
        preview = build_preview("write_file", {"path": "test.py", "content": "print('hi')"})
        assert "test.py" in preview
        assert "print('hi')" in preview

    def test_apply_diff_preview(self):
        preview = build_preview("apply_diff", {"path": "f.py", "old_str": "old", "new_str": "new"})
        assert "f.py" in preview
        assert "old" in preview
        assert "new" in preview

    def test_run_command_preview(self):
        preview = build_preview("run_command", {"command": "git commit -m 'fix'"})
        assert "git commit" in preview

    def test_unknown_tool_fallback(self):
        preview = build_preview("unknown", {"foo": "bar"})
        assert "unknown" in preview


class TestExecuteTool:
    async def test_unknown_tool(self):
        result = await execute_tool("nonexistent", {}, SessionState())
        assert "Unknown tool" in result

    async def test_invalid_args_caught(self):
        """Missing required 'path' — caught as ValueError (Pydantic v2 inherits from it)."""
        result = await execute_tool("read_file", {}, SessionState())
        assert "Unknown tool" in result or "Invalid arguments" in result

    async def test_list_projects(self, tmp_path):
        (tmp_path / "proj1").mkdir()
        (tmp_path / "proj2").mkdir()

        with _patch_repos_root(tmp_path):
            result = await execute_tool("list_projects", {}, SessionState())

        assert "proj1" in result
        assert "proj2" in result

    async def test_list_files_no_project(self):
        result = await execute_tool("list_files", {"path": "."}, SessionState())
        assert "No project is active" in result

    async def test_read_file(self, tmp_path):
        (tmp_path / "proj" / "hello.txt").parent.mkdir(parents=True)
        (tmp_path / "proj" / "hello.txt").write_text("file content")

        with _patch_repos_root(tmp_path):
            result = await execute_tool(
                "read_file",
                {"path": "hello.txt"},
                SessionState(active_project="proj"),
            )

        assert "file content" in result

    async def test_set_project(self, tmp_path):
        (tmp_path / "myproj").mkdir()

        state = SessionState()
        with _patch_repos_root(tmp_path):
            result = await execute_tool("set_project", {"name": "myproj"}, state)

        assert "myproj" in result
        assert state.active_project == "myproj"

    async def test_security_error_returns_message(self, tmp_path):
        with _patch_repos_root(tmp_path):
            result = await execute_tool(
                "read_file",
                {"path": "/etc/passwd"},
                SessionState(active_project="proj"),
            )
        assert "Security error" in result
