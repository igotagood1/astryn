"""Tests for coordinator prompt building with preferences and session state."""

from datetime import UTC, datetime, timedelta

from services.session import build_coordinator_prompt
from store.domain import CommunicationPreferences, SessionState


class TestBuildCoordinatorPrompt:
    def test_includes_preferences_block(self):
        prefs = CommunicationPreferences(verbosity="concise", tone="professional")
        prompt = build_coordinator_prompt(SessionState(), prefs)
        assert "Be concise" in prompt
        assert "Professional tone" in prompt

    def test_default_preferences(self):
        prompt = build_coordinator_prompt(SessionState())
        assert "Balanced responses" in prompt
        assert "Casual tone" in prompt

    def test_includes_session_state_with_project(self):
        state = SessionState(active_project="my-app")
        prompt = build_coordinator_prompt(state)
        assert "my-app" in prompt

    def test_includes_session_state_no_project(self):
        prompt = build_coordinator_prompt(SessionState())
        assert "No project is selected" in prompt

    def test_stale_session_note(self):
        stale_time = datetime.now(UTC) - timedelta(hours=3)
        state = SessionState(active_project="old-project", last_activity_at=stale_time)
        prompt = build_coordinator_prompt(state)
        assert "previous conversation" in prompt

    def test_fresh_session_no_stale_note(self):
        fresh_time = datetime.now(UTC) - timedelta(minutes=5)
        state = SessionState(active_project="fresh-project", last_activity_at=fresh_time)
        prompt = build_coordinator_prompt(state)
        assert "previous conversation" not in prompt

    def test_contains_delegation_instructions(self):
        prompt = build_coordinator_prompt(SessionState())
        assert "delegate" in prompt.lower()
        assert "code" in prompt
        assert "explore" in prompt
        assert "plan" in prompt

    def test_contains_critical_output_rule(self):
        prompt = build_coordinator_prompt(SessionState())
        assert "CRITICAL" in prompt

    def test_all_preference_combinations(self):
        prefs = CommunicationPreferences(
            verbosity="detailed",
            tone="casual",
            code_explanation="teach",
            proactive_suggestions=False,
        )
        prompt = build_coordinator_prompt(SessionState(), prefs)
        assert "Be thorough" in prompt
        assert "Teach mode" in prompt
        assert "Only act on what is explicitly asked" in prompt
