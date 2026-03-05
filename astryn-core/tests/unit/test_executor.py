"""Tests for tools/executor.py — tool dispatch, confirmation, and preview."""

from contextlib import contextmanager
from unittest.mock import patch

from store.domain import SessionState
from tools.executor import (
    build_preview,
    execute_tool,
    requires_confirmation,
)


def _git_env(tmp_path):
    """Minimal env for git commits in test repos."""
    return {
        "GIT_AUTHOR_NAME": "test",
        "GIT_AUTHOR_EMAIL": "t@t",
        "GIT_COMMITTER_NAME": "test",
        "GIT_COMMITTER_EMAIL": "t@t",
        "HOME": str(tmp_path),
        "PATH": "/usr/bin:/bin:/usr/sbin:/sbin:/usr/local/bin",
    }


@contextmanager
def _patch_repos_root(tmp_path):
    """Patch REPOS_ROOT in both executor and safety modules."""
    with (
        patch("tools.executor.REPOS_ROOT", tmp_path),
        patch("tools.safety.REPOS_ROOT", tmp_path),
    ):
        yield


class TestRequiresConfirmation:
    def test_write_file_new_file_no_confirm(self, tmp_path):
        """Writing a new file (doesn't exist yet) should not require confirmation."""
        proj = tmp_path / "proj"
        proj.mkdir()
        state = SessionState(active_project="proj")
        with _patch_repos_root(tmp_path):
            assert (
                requires_confirmation("write_file", {"path": "new.py", "content": "y"}, state)
                is False
            )

    def test_write_file_existing_file_confirms(self, tmp_path):
        """Overwriting an existing file should require confirmation."""
        proj = tmp_path / "proj"
        proj.mkdir()
        (proj / "existing.py").write_text("old content")
        state = SessionState(active_project="proj")
        with _patch_repos_root(tmp_path):
            assert (
                requires_confirmation("write_file", {"path": "existing.py", "content": "y"}, state)
                is True
            )

    def test_write_file_no_session_state_confirms(self):
        """No session state → always confirm (safe fallback)."""
        assert requires_confirmation("write_file", {"path": "x", "content": "y"}) is True

    def test_write_file_no_active_project_confirms(self):
        """No active project → always confirm (safe fallback)."""
        state = SessionState()
        assert requires_confirmation("write_file", {"path": "x", "content": "y"}, state) is True

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

    def test_grep_files_no_confirm(self):
        assert requires_confirmation("grep_files", {"pattern": "def main"}) is False

    def test_run_command_immediate(self):
        assert requires_confirmation("run_command", {"command": "git status"}) is False

    def test_run_command_confirmation(self):
        assert requires_confirmation("run_command", {"command": "git checkout main"}) is True

    def test_unknown_tool_confirms(self):
        assert requires_confirmation("unknown_tool", {}) is True

    def test_create_branch_no_confirm(self):
        assert requires_confirmation("create_branch", {"name": "feat/test"}) is False

    def test_commit_changes_always_confirms(self):
        assert requires_confirmation("commit_changes", {"message": "fix", "files": []}) is True


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
        preview = build_preview("run_command", {"command": "git checkout main"})
        assert "git checkout" in preview

    def test_commit_changes_preview(self):
        preview = build_preview(
            "commit_changes", {"message": "fix: typo", "files": ["main.py", "utils.py"]}
        )
        assert "fix: typo" in preview
        assert "main.py" in preview
        assert "utils.py" in preview

    def test_commit_changes_preview_all_files(self):
        preview = build_preview("commit_changes", {"message": "fix: typo", "files": []})
        assert "fix: typo" in preview
        assert "(all changes)" in preview

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


class TestCreateProject:
    async def test_creates_directory(self, tmp_path):
        state = SessionState()
        with _patch_repos_root(tmp_path):
            result = await execute_tool("create_project", {"name": "my-project"}, state)
        assert (tmp_path / "my-project").is_dir()
        assert state.active_project == "my-project"
        assert "Created" in result

    async def test_initializes_git(self, tmp_path):
        state = SessionState()
        with _patch_repos_root(tmp_path):
            await execute_tool("create_project", {"name": "git-proj"}, state)
        assert (tmp_path / "git-proj" / ".git").is_dir()

    async def test_existing_project_rejected(self, tmp_path):
        (tmp_path / "existing").mkdir()
        state = SessionState()
        with _patch_repos_root(tmp_path):
            result = await execute_tool("create_project", {"name": "existing"}, state)
        assert "already exists" in result
        assert state.active_project is None

    async def test_invalid_name_rejected(self, tmp_path):
        state = SessionState()
        with _patch_repos_root(tmp_path):
            result = await execute_tool("create_project", {"name": "../escape"}, state)
        assert "Invalid" in result
        assert state.active_project is None

    async def test_slash_in_name_rejected(self, tmp_path):
        state = SessionState()
        with _patch_repos_root(tmp_path):
            result = await execute_tool("create_project", {"name": "foo/bar"}, state)
        assert "Invalid" in result

    async def test_dot_start_rejected(self, tmp_path):
        state = SessionState()
        with _patch_repos_root(tmp_path):
            result = await execute_tool("create_project", {"name": ".hidden"}, state)
        assert "Invalid" in result

    async def test_no_confirmation_required(self):
        assert requires_confirmation("create_project", {"name": "test"}) is False


class TestCreateBranch:
    async def test_creates_branch(self, tmp_path):
        import subprocess

        proj = tmp_path / "proj"
        proj.mkdir()
        subprocess.run(["git", "init"], cwd=str(proj), capture_output=True)
        subprocess.run(
            ["git", "commit", "--allow-empty", "-m", "init"],
            cwd=str(proj),
            capture_output=True,
            env=_git_env(tmp_path),
        )

        with _patch_repos_root(tmp_path):
            result = await execute_tool(
                "create_branch", {"name": "feat/new"}, SessionState(active_project="proj")
            )

        assert "Created" in result
        assert "feat/new" in result

    async def test_no_project_error(self):
        result = await execute_tool("create_branch", {"name": "test"}, SessionState())
        assert "No project is active" in result

    async def test_invalid_name_dotdot(self, tmp_path):
        proj = tmp_path / "proj"
        proj.mkdir()
        with _patch_repos_root(tmp_path):
            result = await execute_tool(
                "create_branch", {"name": "a/../b"}, SessionState(active_project="proj")
            )
        assert "Invalid" in result

    async def test_invalid_name_special_chars(self, tmp_path):
        proj = tmp_path / "proj"
        proj.mkdir()
        with _patch_repos_root(tmp_path):
            result = await execute_tool(
                "create_branch", {"name": "bad;name"}, SessionState(active_project="proj")
            )
        assert "Invalid" in result

    def test_no_confirmation_required(self):
        assert requires_confirmation("create_branch", {"name": "feat/test"}) is False


class TestCommitChanges:
    async def test_commits_all_changes(self, tmp_path):
        import subprocess

        proj = tmp_path / "proj"
        proj.mkdir()
        subprocess.run(["git", "init"], cwd=str(proj), capture_output=True)
        subprocess.run(
            ["git", "commit", "--allow-empty", "-m", "init"],
            cwd=str(proj),
            capture_output=True,
            env=_git_env(tmp_path),
        )
        (proj / "hello.py").write_text("print('hi')")

        with _patch_repos_root(tmp_path):
            result = await execute_tool(
                "commit_changes",
                {"message": "add hello", "files": []},
                SessionState(active_project="proj"),
            )

        assert "Committed" in result

    async def test_commits_specific_files(self, tmp_path):
        import subprocess

        proj = tmp_path / "proj"
        proj.mkdir()
        subprocess.run(["git", "init"], cwd=str(proj), capture_output=True)
        subprocess.run(
            ["git", "commit", "--allow-empty", "-m", "init"],
            cwd=str(proj),
            capture_output=True,
            env=_git_env(tmp_path),
        )
        (proj / "a.py").write_text("a")
        (proj / "b.py").write_text("b")

        with _patch_repos_root(tmp_path):
            result = await execute_tool(
                "commit_changes",
                {"message": "add a", "files": ["a.py"]},
                SessionState(active_project="proj"),
            )

        assert "Committed" in result

    async def test_no_project_error(self):
        result = await execute_tool(
            "commit_changes",
            {"message": "test", "files": []},
            SessionState(),
        )
        assert "No project is active" in result

    async def test_always_requires_confirmation(self):
        assert requires_confirmation("commit_changes", {"message": "x", "files": []}) is True

    async def test_path_traversal_blocked(self, tmp_path):
        import subprocess

        proj = tmp_path / "proj"
        proj.mkdir()
        subprocess.run(["git", "init"], cwd=str(proj), capture_output=True)

        with _patch_repos_root(tmp_path):
            result = await execute_tool(
                "commit_changes",
                {"message": "bad", "files": ["../../etc/passwd"]},
                SessionState(active_project="proj"),
            )

        assert "Security error" in result


class TestGrepFiles:
    async def test_finds_matches(self, tmp_path):
        proj = tmp_path / "proj"
        proj.mkdir()
        (proj / "main.py").write_text("def hello():\n    pass\ndef world():\n    pass\n")

        with _patch_repos_root(tmp_path):
            result = await execute_tool(
                "grep_files",
                {"pattern": "def \\w+"},
                SessionState(active_project="proj"),
            )

        assert "main.py" in result
        assert "def hello" in result
        assert "def world" in result

    async def test_no_matches(self, tmp_path):
        proj = tmp_path / "proj"
        proj.mkdir()
        (proj / "main.py").write_text("print('hi')\n")

        with _patch_repos_root(tmp_path):
            result = await execute_tool(
                "grep_files",
                {"pattern": "def \\w+"},
                SessionState(active_project="proj"),
            )

        assert "No matches" in result

    async def test_include_filter(self, tmp_path):
        proj = tmp_path / "proj"
        proj.mkdir()
        (proj / "main.py").write_text("hello world\n")
        (proj / "readme.md").write_text("hello docs\n")

        with _patch_repos_root(tmp_path):
            result = await execute_tool(
                "grep_files",
                {"pattern": "hello", "include": "*.py"},
                SessionState(active_project="proj"),
            )

        assert "main.py" in result
        assert "readme.md" not in result

    async def test_invalid_regex(self, tmp_path):
        proj = tmp_path / "proj"
        proj.mkdir()
        (proj / "f.py").write_text("x\n")

        with _patch_repos_root(tmp_path):
            result = await execute_tool(
                "grep_files",
                {"pattern": "[invalid"},
                SessionState(active_project="proj"),
            )

        assert "Invalid" in result or "invalid" in result

    async def test_no_project(self):
        result = await execute_tool(
            "grep_files",
            {"pattern": "test"},
            SessionState(),
        )
        assert "No project is active" in result

    async def test_skips_noise_dirs(self, tmp_path):
        proj = tmp_path / "proj"
        proj.mkdir()
        venv = proj / ".venv" / "lib"
        venv.mkdir(parents=True)
        (venv / "cached.py").write_text("def cached(): pass\n")
        (proj / "main.py").write_text("def main(): pass\n")

        with _patch_repos_root(tmp_path):
            result = await execute_tool(
                "grep_files",
                {"pattern": "def \\w+"},
                SessionState(active_project="proj"),
            )

        assert "main.py" in result
        assert "cached.py" not in result

    async def test_max_results(self, tmp_path):
        """Results should be capped at 100 with a truncation note."""
        proj = tmp_path / "proj"
        proj.mkdir()
        # Create a file with >100 matching lines
        lines = [f"match_{i}" for i in range(150)]
        (proj / "big.py").write_text("\n".join(lines))

        with _patch_repos_root(tmp_path):
            result = await execute_tool(
                "grep_files",
                {"pattern": "match_\\d+"},
                SessionState(active_project="proj"),
            )

        assert "truncated" in result.lower() or "more results" in result.lower()
