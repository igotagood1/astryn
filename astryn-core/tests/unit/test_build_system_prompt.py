"""Tests for services/session.py — build_system_prompt()."""

from datetime import UTC, datetime, timedelta

from services.session import build_system_prompt
from store.domain import SessionState


class TestBuildSystemPromptActiveProject:
    def test_includes_project_name(self):
        state = SessionState(active_project="my-app")
        prompt = build_system_prompt(state)
        assert "my-app" in prompt

    def test_discourages_re_selecting_project(self):
        state = SessionState(active_project="my-app")
        prompt = build_system_prompt(state)
        lower = prompt.lower()
        assert "don't call list_projects" in lower or "don't call set_project" in lower

    def test_encourages_error_resolution(self):
        """When a project is active, the LLM should try to resolve errors
        rather than asking the user to re-select the project."""
        state = SessionState(active_project="my-app")
        prompt = build_system_prompt(state)
        lower = prompt.lower()
        assert "resolve" in lower or "check the path" in lower


class TestBuildSystemPromptNoProject:
    def test_no_telegram_reference(self):
        """The no-project message should be frontend-agnostic."""
        state = SessionState()
        prompt = build_system_prompt(state)
        assert "Telegram" not in prompt

    def test_mentions_list_projects(self):
        """No-project case should reference list_projects for showing options."""
        state = SessionState()
        prompt = build_system_prompt(state)
        assert "list_projects" in prompt

    def test_let_user_pick(self):
        """Should let the user pick, not pick for them."""
        state = SessionState()
        prompt = build_system_prompt(state)
        assert "pick" in prompt.lower() or "select" in prompt.lower()


class TestBuildSystemPromptStaleness:
    def test_fresh_session_no_stale_note(self):
        """A recently active session should NOT mention previous conversation."""
        state = SessionState(
            active_project="my-app",
            last_activity_at=datetime.now(UTC) - timedelta(minutes=30),
        )
        prompt = build_system_prompt(state)
        assert "previous conversation" not in prompt

    def test_stale_session_includes_note(self):
        """A session idle for >2 hours should warn the model."""
        state = SessionState(
            active_project="my-app",
            last_activity_at=datetime.now(UTC) - timedelta(hours=3),
        )
        prompt = build_system_prompt(state)
        assert "previous conversation" in prompt

    def test_no_timestamp_no_stale_note(self):
        """Without a timestamp, default to not stale."""
        state = SessionState(active_project="my-app")
        prompt = build_system_prompt(state)
        assert "previous conversation" not in prompt

    def test_no_project_ignores_staleness(self):
        """Staleness only matters when a project is set."""
        state = SessionState(
            last_activity_at=datetime.now(UTC) - timedelta(hours=5),
        )
        prompt = build_system_prompt(state)
        assert "previous conversation" not in prompt

    def test_just_under_threshold_not_stale(self):
        """Just under 2 hours should NOT be stale."""
        state = SessionState(
            active_project="my-app",
            last_activity_at=datetime.now(UTC) - timedelta(hours=1, minutes=59),
        )
        prompt = build_system_prompt(state)
        assert "previous conversation" not in prompt

    def test_just_past_threshold_is_stale(self):
        """Just over 2 hours should trigger staleness."""
        state = SessionState(
            active_project="my-app",
            last_activity_at=datetime.now(UTC) - timedelta(hours=2, seconds=1),
        )
        prompt = build_system_prompt(state)
        assert "previous conversation" in prompt


class TestBuildSystemPromptBase:
    def test_includes_base_prompt(self):
        """Both branches should include the base system prompt."""
        from prompts.system import SYSTEM_PROMPT

        for state in [SessionState(), SessionState(active_project="x")]:
            prompt = build_system_prompt(state)
            assert SYSTEM_PROMPT in prompt
