"""Integration tests for preferences repository operations — real Postgres."""

import pytest

import db.repository as repo
from store.domain import CommunicationPreferences


@pytest.mark.integration
class TestPreferencesRepository:
    async def test_get_defaults_when_none_saved(self, integration_db):
        """get_preferences returns defaults for a session with no saved prefs."""
        prefs = await repo.get_preferences(integration_db, "prefs-test-1")
        assert prefs.verbosity == "balanced"
        assert prefs.tone == "casual"
        assert prefs.code_explanation == "explain"
        assert prefs.proactive_suggestions is True

    async def test_save_and_load(self, integration_db):
        """update_preferences saves, get_preferences loads them back."""
        prefs = CommunicationPreferences(
            verbosity="concise",
            tone="professional",
            code_explanation="teach",
            proactive_suggestions=False,
        )
        await repo.update_preferences(integration_db, "prefs-test-2", prefs)

        loaded = await repo.get_preferences(integration_db, "prefs-test-2")
        assert loaded.verbosity == "concise"
        assert loaded.tone == "professional"
        assert loaded.code_explanation == "teach"
        assert loaded.proactive_suggestions is False

    async def test_update_existing(self, integration_db):
        """Updating an existing preferences row works (upsert behavior)."""
        prefs = CommunicationPreferences(verbosity="concise")
        await repo.update_preferences(integration_db, "prefs-test-3", prefs)

        prefs.verbosity = "detailed"
        await repo.update_preferences(integration_db, "prefs-test-3", prefs)

        loaded = await repo.get_preferences(integration_db, "prefs-test-3")
        assert loaded.verbosity == "detailed"

    async def test_preferences_scoped_to_session(self, integration_db):
        """Different sessions have independent preferences."""
        prefs_a = CommunicationPreferences(verbosity="concise")
        prefs_b = CommunicationPreferences(verbosity="detailed")

        await repo.update_preferences(integration_db, "prefs-scope-a", prefs_a)
        await repo.update_preferences(integration_db, "prefs-scope-b", prefs_b)

        loaded_a = await repo.get_preferences(integration_db, "prefs-scope-a")
        loaded_b = await repo.get_preferences(integration_db, "prefs-scope-b")

        assert loaded_a.verbosity == "concise"
        assert loaded_b.verbosity == "detailed"
