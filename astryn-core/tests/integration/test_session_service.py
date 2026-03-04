"""Integration tests for services/session.py — service layer against real DB."""

import pytest

import services.session as session_service
from store.domain import SessionState

pytestmark = pytest.mark.integration


class TestSessionService:
    async def test_ensure_session_returns_state(self, integration_db):
        state = await session_service.ensure_session(integration_db, "user-1")
        assert isinstance(state, SessionState)
        assert state.active_project is None

    async def test_add_user_message(self, integration_db):
        await session_service.ensure_session(integration_db, "user-1")
        await session_service.add_user_message(integration_db, "user-1", "hello")

        history = await session_service.get_history_for_llm(integration_db, "user-1")
        assert len(history) == 1
        assert history[0]["role"] == "user"
        assert history[0]["content"] == "hello"

    async def test_persist_agent_messages(self, integration_db):
        await session_service.ensure_session(integration_db, "user-1")
        await session_service.add_user_message(integration_db, "user-1", "hello")

        # Simulate agent loop producing new messages
        messages = [
            {"role": "user", "content": "hello"},  # old (already in DB)
            {"role": "assistant", "content": "Hi there!"},  # new
        ]
        await session_service.persist_agent_messages(
            integration_db, "user-1", old_count=1, messages=messages
        )

        history = await session_service.get_history_for_llm(integration_db, "user-1")
        assert len(history) == 2
        assert history[1]["content"] == "Hi there!"

    async def test_update_and_get_state(self, integration_db):
        await session_service.ensure_session(integration_db, "user-1")
        new_state = SessionState(active_project="myproject")
        await session_service.update_state(integration_db, "user-1", new_state)

        state = await session_service.get_state(integration_db, "user-1")
        assert state.active_project == "myproject"

    async def test_clear_removes_messages_and_resets_state(self, integration_db):
        await session_service.ensure_session(integration_db, "user-1")
        await session_service.add_user_message(integration_db, "user-1", "hello")
        await session_service.update_state(
            integration_db, "user-1", SessionState(active_project="proj")
        )

        await session_service.clear(integration_db, "user-1")

        history = await session_service.get_history_for_llm(integration_db, "user-1")
        assert len(history) == 0

        state = await session_service.get_state(integration_db, "user-1")
        assert state.active_project is None

    async def test_build_system_prompt_no_project(self):
        prompt = session_service.build_system_prompt(SessionState())
        assert "No active project" in prompt

    async def test_build_system_prompt_with_project(self):
        prompt = session_service.build_system_prompt(SessionState(active_project="astryn"))
        assert "astryn" in prompt
