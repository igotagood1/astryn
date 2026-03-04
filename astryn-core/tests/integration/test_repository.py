"""Integration tests for db/repository.py — CRUD against real Postgres."""

import pytest

import db.repository as repo
from store.domain import SessionState

pytestmark = pytest.mark.integration


class TestSessionOps:
    async def test_ensure_session_creates_session(self, integration_db):
        await repo.ensure_session(integration_db, "user-1")
        # Should not raise on second call
        await repo.ensure_session(integration_db, "user-1")

    async def test_get_state_default(self, integration_db):
        await repo.ensure_session(integration_db, "user-1")
        state = await repo.get_state(integration_db, "user-1")
        assert isinstance(state, SessionState)
        assert state.active_project is None

    async def test_update_state(self, integration_db):
        await repo.ensure_session(integration_db, "user-1")
        state = SessionState(active_project="myproject")
        await repo.update_state(integration_db, "user-1", state)

        loaded = await repo.get_state(integration_db, "user-1")
        assert loaded.active_project == "myproject"


class TestMessageOps:
    async def test_add_and_get_messages(self, integration_db):
        await repo.ensure_session(integration_db, "user-1")
        await repo.add_message(integration_db, "user-1", {"role": "user", "content": "hello"})
        await repo.add_message(integration_db, "user-1", {"role": "assistant", "content": "hi"})

        msgs = await repo.get_messages(integration_db, "user-1")
        assert len(msgs) == 2
        assert msgs[0]["role"] == "user"
        assert msgs[0]["content"] == "hello"
        assert msgs[1]["role"] == "assistant"

    async def test_add_messages_bulk(self, integration_db):
        await repo.ensure_session(integration_db, "user-1")
        await repo.add_messages(
            integration_db,
            "user-1",
            [
                {"role": "user", "content": "msg1"},
                {"role": "assistant", "content": "msg2"},
                {"role": "user", "content": "msg3"},
            ],
        )

        msgs = await repo.get_messages(integration_db, "user-1")
        assert len(msgs) == 3

    async def test_get_messages_with_limit(self, integration_db):
        await repo.ensure_session(integration_db, "user-1")
        for i in range(10):
            await repo.add_message(
                integration_db, "user-1", {"role": "user", "content": f"msg-{i}"}
            )

        msgs = await repo.get_messages(integration_db, "user-1", limit=3)
        assert len(msgs) == 3
        # Should be the last 3 messages
        assert msgs[0]["content"] == "msg-7"
        assert msgs[2]["content"] == "msg-9"

    async def test_delete_messages(self, integration_db):
        await repo.ensure_session(integration_db, "user-1")
        await repo.add_message(integration_db, "user-1", {"role": "user", "content": "hello"})
        count = await repo.delete_messages(integration_db, "user-1")
        assert count == 1

        msgs = await repo.get_messages(integration_db, "user-1")
        assert len(msgs) == 0

    async def test_messages_preserve_tool_calls(self, integration_db):
        await repo.ensure_session(integration_db, "user-1")
        msg = {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {"id": "call-1", "function": {"name": "read_file", "arguments": {"path": "x"}}}
            ],
        }
        await repo.add_message(integration_db, "user-1", msg)

        msgs = await repo.get_messages(integration_db, "user-1")
        assert msgs[0]["tool_calls"] is not None
        assert msgs[0]["tool_calls"][0]["id"] == "call-1"

    async def test_tool_message_preserved(self, integration_db):
        await repo.ensure_session(integration_db, "user-1")
        msg = {"role": "tool", "tool_call_id": "call-1", "content": "file content here"}
        await repo.add_message(integration_db, "user-1", msg)

        msgs = await repo.get_messages(integration_db, "user-1")
        assert msgs[0]["role"] == "tool"
        assert msgs[0]["tool_call_id"] == "call-1"


class TestToolAudit:
    async def test_log_tool_call(self, integration_db):
        await repo.ensure_session(integration_db, "user-1")
        await repo.log_tool_call(
            db=integration_db,
            external_id="user-1",
            tool_name="read_file",
            tool_args={"path": "test.py"},
            required_confirmation=False,
            approved=None,
            result="file content",
        )
        # Should not raise — just verifying it doesn't crash


class TestClearSession:
    async def test_clear_deletes_messages_and_resets_state(self, integration_db):
        await repo.ensure_session(integration_db, "user-1")
        await repo.add_message(integration_db, "user-1", {"role": "user", "content": "hello"})
        await repo.update_state(integration_db, "user-1", SessionState(active_project="proj"))

        await repo.clear_session(integration_db, "user-1")

        msgs = await repo.get_messages(integration_db, "user-1")
        assert len(msgs) == 0

        state = await repo.get_state(integration_db, "user-1")
        assert state.active_project is None
