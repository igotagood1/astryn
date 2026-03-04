"""Guard tests for critical system prompt phrases.

These tests ensure the system prompt contains the rules that fix the
'invisible tool results' bug — without these phrases, the LLM will
call read_file and say "here it is" without showing the content.
"""

from prompts.system import SYSTEM_PROMPT


class TestToolOutputVisibility:
    def test_section_exists_and_marked_critical(self):
        """The visibility section must exist and be clearly marked."""
        assert "Tool Output Visibility" in SYSTEM_PROMPT
        assert "CRITICAL" in SYSTEM_PROMPT

    def test_user_cannot_see_tool_results(self):
        assert "user cannot see tool results" in SYSTEM_PROMPT.lower()

    def test_read_file_instruction(self):
        """After read_file, the LLM must paste file content into its reply."""
        assert "after read_file" in SYSTEM_PROMPT.lower()

    def test_include_file_content_in_code_block(self):
        assert "code block" in SYSTEM_PROMPT.lower()

    def test_include_command_output(self):
        assert "after run_command" in SYSTEM_PROMPT.lower()

    def test_include_results_instruction(self):
        """The prompt must tell the LLM to include results for list/search tools."""
        assert "include the results" in SYSTEM_PROMPT.lower()

    def test_large_output_guidance(self):
        assert "relevant portion" in SYSTEM_PROMPT.lower()


class TestConversationStyle:
    def test_conversational(self):
        assert "conversational" in SYSTEM_PROMPT.lower()

    def test_do_not_assume(self):
        lower = SYSTEM_PROMPT.lower()
        assert "don't assume" in lower or "do not assume" in lower

    def test_one_step_at_a_time(self):
        lower = SYSTEM_PROMPT.lower()
        assert "one step at a time" in lower or "do not jump ahead" in lower

    def test_no_filler(self):
        """The 'short responses' rule should discourage filler."""
        lower = SYSTEM_PROMPT.lower()
        assert "filler" in lower or "no filler" in lower

    def test_relay_tool_output(self):
        """The prompt must instruct relaying tool output to the user."""
        lower = SYSTEM_PROMPT.lower()
        assert "relay" in lower or "include" in lower


class TestCapabilities:
    def test_describes_capabilities(self):
        """The prompt should describe what the assistant can do."""
        lower = SYSTEM_PROMPT.lower()
        assert "what you can do" in lower

    def test_mentions_code_changes(self):
        lower = SYSTEM_PROMPT.lower()
        assert "change" in lower or "edit" in lower

    def test_mentions_commands(self):
        lower = SYSTEM_PROMPT.lower()
        assert "command" in lower or "run" in lower
