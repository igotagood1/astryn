"""Integration tests for Alembic migrations — upgrade/downgrade against real Postgres."""

import pytest
from sqlalchemy import inspect

pytestmark = pytest.mark.integration


EXPECTED_TABLES = {"sessions", "messages", "session_state", "tool_audit"}


class TestMigrations:
    async def test_orm_creates_all_tables(self, integration_engine):
        """Verify ORM metadata.create_all produces the expected tables."""
        async with integration_engine.connect() as conn:
            table_names = await conn.run_sync(
                lambda sync_conn: set(inspect(sync_conn).get_table_names())
            )

        assert EXPECTED_TABLES.issubset(table_names), (
            f"Missing tables: {EXPECTED_TABLES - table_names}"
        )

    async def test_sessions_table_has_external_id_index(self, integration_engine):
        """Verify the external_id column has an index."""
        async with integration_engine.connect() as conn:
            indexes = await conn.run_sync(
                lambda sync_conn: inspect(sync_conn).get_indexes("sessions")
            )

        index_columns = {col for idx in indexes for col in idx.get("column_names", [])}
        assert "external_id" in index_columns

    async def test_messages_table_has_composite_index(self, integration_engine):
        """Verify the (session_id, created_at) composite index exists."""
        async with integration_engine.connect() as conn:
            indexes = await conn.run_sync(
                lambda sync_conn: inspect(sync_conn).get_indexes("messages")
            )

        composite_found = any(
            set(idx.get("column_names", [])) == {"session_id", "created_at"} for idx in indexes
        )
        assert composite_found, (
            f"Expected composite index on (session_id, created_at), found: {indexes}"
        )

    async def test_tables_support_basic_operations(self, integration_db):
        """Smoke test: insert and read via ORM repository."""
        import db.repository as repo

        await repo.ensure_session(integration_db, "smoke-test")
        await repo.add_message(integration_db, "smoke-test", {"role": "user", "content": "hello"})

        msgs = await repo.get_messages(integration_db, "smoke-test")
        assert len(msgs) == 1
        assert msgs[0]["content"] == "hello"
