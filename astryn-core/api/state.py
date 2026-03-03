from dataclasses import dataclass, field


@dataclass
class Session:
    history: list[dict] = field(default_factory=list)
    state: dict = field(default_factory=dict)  # {active_project: str | None}


# In-memory session storage. Replaced with SQLite in Phase 3.
sessions: dict[str, Session] = {}

# Paused agent states waiting for user confirmation. Keyed by confirmation ID.
pending_confirmations: dict = {}
