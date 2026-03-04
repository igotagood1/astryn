"""Integration test fixtures — real Postgres via testcontainers."""

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from testcontainers.postgres import PostgresContainer

from db.models import Base


@pytest.fixture(scope="session")
def postgres_url():
    """Spin up a Postgres container for the test session."""
    with PostgresContainer("postgres:16-alpine") as pg:
        # testcontainers returns psycopg2 URL; convert to asyncpg
        url = pg.get_connection_url()
        async_url = url.replace("psycopg2", "asyncpg")
        yield async_url


@pytest.fixture
async def integration_engine(postgres_url):
    """Create tables from ORM models (no Alembic) for fast test setup."""
    engine = create_async_engine(postgres_url, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest.fixture
async def integration_db(integration_engine):
    """Async session against the real Postgres container."""
    factory = async_sessionmaker(integration_engine, expire_on_commit=False)
    async with factory() as session:
        yield session
        await session.rollback()
