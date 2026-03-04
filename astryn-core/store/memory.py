"""In-memory data store for sessions and pending confirmations.

This is the data layer. In Phase 3 it will be replaced by SQLite via aiosqlite,
at which point this file is swapped out for db/ implementations without touching
the service or API layers above it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    # Only imported for type-checker annotations — not at runtime.
    # Avoids a circular import since llm/agent.py imports SessionState from here.
    from llm.agent import PendingConfirmation


@dataclass
class SessionState:
    """Mutable per-session state passed through the agent loop.

    Stored on Session and passed by reference into run_agent, so tool calls
    (e.g., set_project) can update it in place without any return value plumbing.
    Phase 3 will persist this alongside session history in SQLite.
    """

    active_project: str | None = None


@dataclass
class Session:
    """A single user session: its conversation history and mutable state."""

    history: list[dict] = field(default_factory=list)
    state: SessionState = field(default_factory=SessionState)


# ── In-memory storage ─────────────────────────────────────────────────────────
# Both dicts are module-level singletons for now.
# The service layer (services/session.py) is the only code that should
# read or write these directly. Routes and lower layers go through the service.

# Keyed by session_id (Telegram user ID as a string).
sessions: dict[str, Session] = {}

# Keyed by confirmation ID (UUID). Entries are added when the agent pauses on a
# write/exec tool and removed when the user approves or rejects via POST /confirm.
pending_confirmations: dict[str, PendingConfirmation] = {}
