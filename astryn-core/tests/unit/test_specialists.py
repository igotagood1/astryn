"""Tests for specialist definitions, tool sets, and prompt loading."""

from llm.specialists import SPECIALISTS, SpecialistDef
from prompts.specialists.loader import CODE_PROMPT, EXPLORE_PROMPT, PLAN_PROMPT
from tools.registry import COORDINATOR_TOOLS, READ_ONLY_TOOLS, READ_WRITE_TOOLS, TOOLS


class TestSpecialistDefinitions:
    def test_all_specialists_defined(self):
        expected = {
            "code",
            "explore",
            "plan",
            "code-review",
            "design-review",
            "security-review",
            "test-writer",
        }
        assert set(SPECIALISTS.keys()) == expected

    def test_all_are_specialist_def(self):
        for spec in SPECIALISTS.values():
            assert isinstance(spec, SpecialistDef)

    def test_code_has_full_tools(self):
        code = SPECIALISTS["code"]
        assert code.tools is TOOLS

    def test_explore_has_read_only_tools(self):
        explore = SPECIALISTS["explore"]
        assert explore.tools is READ_ONLY_TOOLS

    def test_plan_has_read_only_tools(self):
        plan = SPECIALISTS["plan"]
        assert plan.tools is READ_ONLY_TOOLS

    def test_code_prompt_loaded(self):
        assert SPECIALISTS["code"].system_prompt == CODE_PROMPT
        assert "code specialist" in CODE_PROMPT.lower()

    def test_explore_prompt_loaded(self):
        assert SPECIALISTS["explore"].system_prompt == EXPLORE_PROMPT
        assert "explore specialist" in EXPLORE_PROMPT.lower()

    def test_plan_prompt_loaded(self):
        assert SPECIALISTS["plan"].system_prompt == PLAN_PROMPT
        assert "plan specialist" in PLAN_PROMPT.lower()


class TestToolSets:
    def test_coordinator_tools_only_delegate(self):
        assert len(COORDINATOR_TOOLS) == 1
        assert COORDINATOR_TOOLS[0]["function"]["name"] == "delegate"

    def test_read_only_tools_no_write_ops(self):
        names = {t["function"]["name"] for t in READ_ONLY_TOOLS}
        assert "apply_diff" not in names
        assert "write_file" not in names
        assert "run_command" not in names

    def test_read_only_tools_has_expected(self):
        names = {t["function"]["name"] for t in READ_ONLY_TOOLS}
        assert "list_files" in names
        assert "read_file" in names
        assert "search_files" in names
        assert "grep_files" in names
        assert "list_projects" in names
        assert "set_project" in names

    def test_full_tools_includes_write_ops(self):
        names = {t["function"]["name"] for t in TOOLS}
        assert "apply_diff" in names
        assert "write_file" in names
        assert "run_command" in names

    def test_read_write_includes_read_only(self):
        ro_names = {t["function"]["name"] for t in READ_ONLY_TOOLS}
        rw_names = {t["function"]["name"] for t in READ_WRITE_TOOLS}
        assert ro_names.issubset(rw_names)

    def test_read_write_includes_write_tools(self):
        names = {t["function"]["name"] for t in READ_WRITE_TOOLS}
        assert "write_file" in names
        assert "apply_diff" in names

    def test_read_write_excludes_run_command(self):
        names = {t["function"]["name"] for t in READ_WRITE_TOOLS}
        assert "run_command" not in names

    def test_read_write_excludes_delegate(self):
        names = {t["function"]["name"] for t in READ_WRITE_TOOLS}
        assert "delegate" not in names


class TestPromptFiles:
    def test_code_prompt_mentions_apply_diff(self):
        assert "apply_diff" in CODE_PROMPT

    def test_explore_prompt_cannot_modify(self):
        assert "CANNOT modify" in EXPLORE_PROMPT

    def test_plan_prompt_devils_advocate(self):
        assert "devil" in PLAN_PROMPT.lower()

    def test_prompts_are_nonempty(self):
        assert len(CODE_PROMPT) > 100
        assert len(EXPLORE_PROMPT) > 100
        assert len(PLAN_PROMPT) > 100
