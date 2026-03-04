"""Domain types for sessions and in-memory transient state.

SessionState is the core domain object used throughout the codebase.
The DB layer (db/repository.py) maps between it and SQLAlchemy ORM models.

pending_confirmations remains in-memory — confirmations are transient and
don't survive restarts by design.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from llm.agent import PendingConfirmation


@dataclass
class SessionState:
    """Mutable per-session state passed through the agent loop.

    Persisted to the session_state table via db/repository.py.
    Passed by reference into run_agent so tool calls (e.g., set_project)
    can update it in place without return value plumbing.
    """

    active_project: str | None = None
    last_activity_at: datetime | None = field(default=None, repr=False)


# ── In-memory transient state ────────────────────────────────────────────────

# Keyed by confirmation ID (UUID). Entries are added when the agent pauses on a
# write/exec tool and removed when the user approves or rejects via POST /confirm.
# Intentionally not persisted — confirmations expire on restart.
pending_confirmations: dict[str, PendingConfirmation] = {}
