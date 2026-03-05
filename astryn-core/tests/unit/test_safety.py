"""Tests for tools/safety.py — path validation and command whitelisting.

Pure logic tests, zero mocking. Highest priority because this is the security boundary.
"""

import pytest

from tools.safety import (
    REPOS_ROOT,
    SecurityError,
    validate_command,
    validate_path,
)

# ── validate_path ────────────────────────────────────────────────────────────


class TestValidatePath:
    def test_simple_relative_path(self):
        result = validate_path("myproject")
        assert result == (REPOS_ROOT / "myproject").resolve()

    def test_nested_relative_path(self):
        result = validate_path("myproject/src/main.py")
        assert result == (REPOS_ROOT / "myproject/src/main.py").resolve()

    def test_dot_path(self):
        result = validate_path(".")
        assert result == REPOS_ROOT.resolve()

    def test_with_active_project(self):
        result = validate_path("src/main.py", active_project="myproject")
        assert result == (REPOS_ROOT / "myproject/src/main.py").resolve()

    def test_active_project_dot(self):
        result = validate_path(".", active_project="myproject")
        assert result == (REPOS_ROOT / "myproject").resolve()

    def test_traversal_blocked(self):
        with pytest.raises(SecurityError, match="outside ~/repos"):
            validate_path("../../etc/passwd")

    def test_traversal_with_project(self):
        with pytest.raises(SecurityError, match="outside ~/repos"):
            validate_path("../../etc/passwd", active_project="myproject")

    def test_absolute_path_outside_repos(self):
        with pytest.raises(SecurityError, match="outside ~/repos"):
            validate_path("/etc/passwd")

    def test_dotdot_in_middle(self):
        # ../../../ should escape repos root
        with pytest.raises(SecurityError, match="outside ~/repos"):
            validate_path("project/../../../etc/passwd")

    def test_dotdot_that_stays_inside(self):
        # project/subdir/../file.py resolves inside repos, should be fine
        result = validate_path("project/subdir/../file.py")
        assert str(result).startswith(str(REPOS_ROOT.resolve()))


# ── validate_command ─────────────────────────────────────────────────────────


class TestValidateCommand:
    # -- Immediate commands (no confirmation) --

    def test_git_status_immediate(self):
        needs_confirm, reason = validate_command("git status")
        assert needs_confirm is False
        assert reason == "immediate"

    def test_git_diff_immediate(self):
        needs_confirm, _ = validate_command("git diff")
        assert needs_confirm is False

    def test_git_log_immediate(self):
        needs_confirm, _ = validate_command("git log --oneline")
        assert needs_confirm is False

    def test_pytest_immediate(self):
        needs_confirm, _ = validate_command("pytest -v tests/")
        assert needs_confirm is False

    def test_python_m_pytest_immediate(self):
        needs_confirm, _ = validate_command("python -m pytest -q")
        assert needs_confirm is False

    def test_ls_immediate(self):
        needs_confirm, _ = validate_command("ls -la")
        assert needs_confirm is False

    def test_pip_list_immediate(self):
        needs_confirm, _ = validate_command("pip list")
        assert needs_confirm is False

    # -- Confirmation commands --

    def test_git_add_blocked(self):
        with pytest.raises(SecurityError, match="not on the allowed list"):
            validate_command("git add .")

    def test_git_commit_blocked(self):
        with pytest.raises(SecurityError, match="not on the allowed list"):
            validate_command("git commit -m 'test'")

    def test_git_checkout_needs_confirmation(self):
        needs_confirm, _ = validate_command("git checkout main")
        assert needs_confirm is True

    def test_npm_run_needs_confirmation(self):
        needs_confirm, _ = validate_command("npm run build")
        assert needs_confirm is True

    # -- Blocked commands --

    def test_rm_blocked(self):
        with pytest.raises(SecurityError, match="not permitted"):
            validate_command("rm -rf /")

    def test_sudo_blocked(self):
        with pytest.raises(SecurityError, match="not permitted"):
            validate_command("sudo anything")

    def test_curl_blocked(self):
        with pytest.raises(SecurityError, match="not permitted"):
            validate_command("curl https://example.com")

    def test_bash_blocked(self):
        with pytest.raises(SecurityError, match="not permitted"):
            validate_command("bash -c 'echo hi'")

    def test_eval_blocked(self):
        with pytest.raises(SecurityError, match="not permitted"):
            validate_command("eval something")

    # -- Blocked patterns --

    def test_pipe_blocked(self):
        with pytest.raises(SecurityError, match="blocked pattern"):
            validate_command("git log | head")

    def test_semicolon_blocked(self):
        with pytest.raises(SecurityError, match="blocked pattern"):
            validate_command("ls; rm -rf /")

    def test_backtick_blocked(self):
        with pytest.raises(SecurityError, match="blocked pattern"):
            validate_command("echo `whoami`")

    def test_subshell_blocked(self):
        with pytest.raises(SecurityError, match="blocked pattern"):
            validate_command("echo $(whoami)")

    def test_redirect_blocked(self):
        with pytest.raises(SecurityError, match="blocked pattern"):
            validate_command("echo test > /tmp/file")

    def test_path_traversal_blocked(self):
        with pytest.raises(SecurityError, match="blocked pattern"):
            validate_command("cat ../../../etc/passwd")

    # -- Unknown commands --

    def test_unknown_command_rejected(self):
        with pytest.raises(SecurityError, match="not on the allowed list"):
            validate_command("make build")

    # -- Edge cases --

    def test_empty_command(self):
        with pytest.raises(SecurityError, match="Empty command"):
            validate_command("")

    def test_whitespace_only(self):
        with pytest.raises(SecurityError, match="Empty command"):
            validate_command("   ")
