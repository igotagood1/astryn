"""Tests for COORDINATOR_TOOLS composition in tools/registry.py.

Locks in:
- Coordinator has exactly the tools it needs: delegate, list_projects, set_project, read_file
- Coordinator does NOT have dangerous tools: write_file, run_command, apply_diff, commit_changes
- Tool count is stable (prevents accidental additions)
"""

from tools.registry import _COORDINATOR_TOOL_NAMES, COORDINATOR_TOOLS


def _tool_names(tool_list: list[dict]) -> set[str]:
    """Extract function names from a list of OpenAI-format tool schemas."""
    return {t["function"]["name"] for t in tool_list}


class TestCoordinatorTools:
    def test_coordinator_has_delegate(self):
        """Coordinator must have the delegate tool to dispatch work to specialists."""
        assert "delegate" in _tool_names(COORDINATOR_TOOLS)

    def test_coordinator_has_list_projects(self):
        """Coordinator can list available projects without delegating."""
        assert "list_projects" in _tool_names(COORDINATOR_TOOLS)

    def test_coordinator_has_set_project(self):
        """Coordinator can set the active project without delegating."""
        assert "set_project" in _tool_names(COORDINATOR_TOOLS)

    def test_coordinator_has_read_file(self):
        """Coordinator can read files directly for quick lookups."""
        assert "read_file" in _tool_names(COORDINATOR_TOOLS)

    def test_coordinator_does_not_have_write_file(self):
        """Coordinator must NOT write files -- that is specialist work."""
        assert "write_file" not in _tool_names(COORDINATOR_TOOLS)

    def test_coordinator_does_not_have_run_command(self):
        """Coordinator must NOT run commands -- that is specialist work."""
        assert "run_command" not in _tool_names(COORDINATOR_TOOLS)

    def test_coordinator_does_not_have_apply_diff(self):
        """Coordinator must NOT apply diffs -- that is specialist work."""
        assert "apply_diff" not in _tool_names(COORDINATOR_TOOLS)

    def test_coordinator_does_not_have_commit_changes(self):
        """Coordinator must NOT commit -- that is reviewer specialist work."""
        assert "commit_changes" not in _tool_names(COORDINATOR_TOOLS)

    def test_coordinator_tool_count(self):
        """Coordinator has exactly 4 tools. Update this if the set intentionally changes."""
        assert len(COORDINATOR_TOOLS) == 4

    def test_coordinator_tool_names_match_schemas(self):
        """The _COORDINATOR_TOOL_NAMES set and the actual COORDINATOR_TOOLS list agree."""
        assert _tool_names(COORDINATOR_TOOLS) == _COORDINATOR_TOOL_NAMES

    def test_all_schemas_have_function_key(self):
        """Every tool schema follows OpenAI format with a 'function' key."""
        for tool in COORDINATOR_TOOLS:
            assert "function" in tool
            assert "name" in tool["function"]
            assert "description" in tool["function"]
            assert "parameters" in tool["function"]
