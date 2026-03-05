"""Domain types for sessions and in-memory transient state.

SessionState is the core domain object used throughout the codebase.
The DB layer (db/repository.py) maps between it and SQLAlchemy ORM models.

pending_confirmations remains in-memory — confirmations are transient and
don't survive restarts by design.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from llm.agent import PendingConfirmation


VERBOSITY_OPTIONS = ("concise", "balanced", "detailed")
TONE_OPTIONS = ("casual", "professional")
CODE_EXPLANATION_OPTIONS = ("minimal", "explain", "teach")


@dataclass
class CommunicationPreferences:
    """User-configurable communication style preferences.

    Persisted to the communication_preferences table via db/repository.py.
    Injected into the coordinator system prompt as a formatted block.
    """

    verbosity: str = "balanced"
    tone: str = "casual"
    code_explanation: str = "explain"
    proactive_suggestions: bool = True


@dataclass
class SessionState:
    """Mutable per-session state passed through the agent loop.

    Persisted to the session_state table via db/repository.py.
    Passed by reference into run_agent so tool calls (e.g., set_project)
    can update it in place without return value plumbing.
    """

    active_project: str | None = None
    last_activity_at: datetime | None = field(default=None, repr=False)


@dataclass
class ApiUsageRecord:
    """A single Anthropic API usage record."""

    model: str
    input_tokens: int
    output_tokens: int
    estimated_cost_usd: Decimal
    session_id: str | None = None


# ── In-memory transient state ────────────────────────────────────────────────

# Keyed by confirmation ID (UUID). Entries are added when the agent pauses on a
# write/exec tool and removed when the user approves or rejects via POST /confirm.
# Intentionally not persisted — confirmations expire on restart.
pending_confirmations: dict[str, PendingConfirmation] = {}

_CONFIRMATION_TTL = 600  # 10 minutes


def cleanup_expired_confirmations() -> list[str]:
    """Remove confirmations older than TTL. Returns list of expired IDs."""
    import time

    now = time.monotonic()
    expired = [
        cid
        for cid, pc in pending_confirmations.items()
        if (now - pc.created_at) > _CONFIRMATION_TTL
    ]
    for cid in expired:
        del pending_confirmations[cid]
    return expired
