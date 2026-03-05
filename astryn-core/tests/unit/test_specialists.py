"""Tests for specialist definitions, tool sets, and prompt loading."""

from llm.specialists import SPECIALISTS, SpecialistDef
from prompts.specialists.loader import CODE_REVIEWER_PROMPT, CODE_WRITER_PROMPT
from tools.registry import (
    COORDINATOR_TOOLS,
    NO_PROJECT_TOOLS,
    READ_ONLY_TOOLS,
    REVIEWER_TOOLS,
    WRITER_TOOLS,
)


class TestSpecialistDefinitions:
    def test_all_specialists_defined(self):
        expected = {"code-writer", "code-reviewer"}
        assert set(SPECIALISTS.keys()) == expected

    def test_all_are_specialist_def(self):
        for spec in SPECIALISTS.values():
            assert isinstance(spec, SpecialistDef)

    def test_writer_has_writer_tools(self):
        assert SPECIALISTS["code-writer"].tools is WRITER_TOOLS

    def test_reviewer_has_reviewer_tools(self):
        assert SPECIALISTS["code-reviewer"].tools is REVIEWER_TOOLS

    def test_writer_prompt_loaded(self):
        assert SPECIALISTS["code-writer"].system_prompt == CODE_WRITER_PROMPT
        assert "code-writer" in CODE_WRITER_PROMPT.lower()

    def test_reviewer_prompt_loaded(self):
        assert SPECIALISTS["code-reviewer"].system_prompt == CODE_REVIEWER_PROMPT
        assert "code-reviewer" in CODE_REVIEWER_PROMPT.lower()


class TestToolSets:
    def test_coordinator_tools_include_delegate_and_project_tools(self):
        names = {t["function"]["name"] for t in COORDINATOR_TOOLS}
        assert "delegate" in names
        assert "list_projects" in names
        assert "set_project" in names
        assert "read_file" in names
        # Coordinator should NOT have write/exec tools
        assert "write_file" not in names
        assert "run_command" not in names
        assert "apply_diff" not in names

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

    def test_writer_tools_includes_write_ops(self):
        names = {t["function"]["name"] for t in WRITER_TOOLS}
        assert "apply_diff" in names
        assert "write_file" in names
        assert "run_command" in names
        assert "create_branch" in names

    def test_writer_tools_excludes_commit(self):
        names = {t["function"]["name"] for t in WRITER_TOOLS}
        assert "commit_changes" not in names
        assert "delegate" not in names

    def test_reviewer_tools_includes_commit(self):
        names = {t["function"]["name"] for t in REVIEWER_TOOLS}
        assert "commit_changes" in names
        assert "run_command" in names

    def test_reviewer_tools_excludes_write(self):
        names = {t["function"]["name"] for t in REVIEWER_TOOLS}
        assert "write_file" not in names
        assert "apply_diff" not in names
        assert "create_branch" not in names
        assert "create_project" not in names

    def test_no_project_tools_has_create_project(self):
        names = {t["function"]["name"] for t in NO_PROJECT_TOOLS}
        assert "create_project" in names
        assert "list_projects" in names
        assert "set_project" in names

    def test_writer_tools_has_create_project(self):
        names = {t["function"]["name"] for t in WRITER_TOOLS}
        assert "create_project" in names

    def test_read_only_excludes_create_project(self):
        names = {t["function"]["name"] for t in READ_ONLY_TOOLS}
        assert "create_project" not in names


class TestPromptFiles:
    def test_writer_prompt_mentions_apply_diff(self):
        assert "apply_diff" in CODE_WRITER_PROMPT

    def test_writer_prompt_cannot_commit(self):
        assert "cannot commit" in CODE_WRITER_PROMPT.lower()

    def test_reviewer_prompt_cannot_write(self):
        assert "cannot write" in CODE_REVIEWER_PROMPT.lower()

    def test_prompts_are_nonempty(self):
        assert len(CODE_WRITER_PROMPT) > 100
        assert len(CODE_REVIEWER_PROMPT) > 100
