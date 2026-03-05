"""Shared test fixtures for astryn-core.

Patches settings at import time so no real DB/Ollama is needed for unit + API tests.
Integration tests override these with real Postgres via testcontainers.
"""

import os

# Patch env BEFORE any astryn imports to prevent settings validation failures
os.environ.setdefault("ASTRYN_API_KEY", "test-key")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://fake:fake@localhost/fake")
os.environ.setdefault("OLLAMA_BASE_URL", "http://localhost:11434")
os.environ.setdefault("ASTRYN_DEFAULT_MODEL", "test-model")
os.environ.setdefault("ASTRYN_COORDINATOR_PROVIDER", "ollama")
os.environ.setdefault("ASTRYN_SPECIALIST_MODEL", "test-model")

from unittest.mock import AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient

from llm.base import LLMResponse
from store.domain import pending_confirmations


@pytest.fixture(autouse=True)
def _clear_global_state():
    """Reset in-memory global state between tests."""
    pending_confirmations.clear()
    # Reset active model to default
    from llm import router

    router._active_model = "test-model"
    yield
    pending_confirmations.clear()


@pytest.fixture
def api_key():
    return "test-key"


@pytest.fixture
def auth_headers(api_key):
    return {"X-Api-Key": api_key}


@pytest.fixture
def mock_db():
    """AsyncSession mock for unit tests that don't need real DB."""
    db = AsyncMock()
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    db.flush = AsyncMock()
    db.execute = AsyncMock()
    return db


@pytest.fixture
def mock_provider():
    """LLMProvider mock that returns a simple text reply."""
    provider = AsyncMock()
    provider.model_name = "ollama/test-model"
    provider.is_available = AsyncMock(return_value=True)
    provider.chat = AsyncMock(
        return_value=LLMResponse(
            content="Hello from the LLM",
            model="ollama/test-model",
            provider="ollama",
            tool_calls=[],
        )
    )
    provider.list_models = AsyncMock(return_value=["test-model", "other-model"])
    return provider


@pytest.fixture
def client(mock_provider, mock_db):
    """Async test client with DB mocked. ASGITransport skips lifespan (no migrations)."""
    from api.main import app
    from db.engine import get_db

    async def override_get_db():
        yield mock_db

    app.dependency_overrides[get_db] = override_get_db

    transport = ASGITransport(app=app)
    client = AsyncClient(transport=transport, base_url="http://test")

    yield client

    app.dependency_overrides.clear()
