"""Session service — business logic for managing conversation sessions.

All methods are async and accept a db: AsyncSession. The database is the
source of truth; in-memory pending_confirmations remain transient.
"""

import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

import db.repository as repo
from llm.config import settings
from llm.skills import format_available_skills_block, load_skill_metadata
from prompts.coordinator import COORDINATOR_PROMPT_TEMPLATE
from prompts.system import SYSTEM_PROMPT
from services.preferences import format_preferences_block
from store.domain import (
    CommunicationPreferences,
    SessionState,
    cancel_events,
    pending_confirmations,
)

logger = logging.getLogger(__name__)


async def ensure_session(db: AsyncSession, session_id: str) -> SessionState:
    """Ensure session + state rows exist. Returns the current SessionState."""
    await repo.ensure_session(db, session_id)
    return await repo.get_state(db, session_id)


async def add_user_message(db: AsyncSession, session_id: str, message: str) -> None:
    """Append the user's message to the DB."""
    await repo.add_message(db, session_id, {"role": "user", "content": message})


async def get_history_for_llm(db: AsyncSession, session_id: str) -> list[dict]:
    """Fetch the last N messages for the LLM context window."""
    max_messages = settings.max_history_turns * 2
    return await repo.get_messages(db, session_id, limit=max_messages)


async def persist_agent_messages(
    db: AsyncSession, session_id: str, old_count: int, messages: list[dict]
) -> None:
    """Persist only the new messages produced by the agent loop.

    old_count is the number of messages that were already in the DB before
    run_agent was called. Everything after that index is new.
    """
    new_messages = messages[old_count:]
    if new_messages:
        await repo.add_messages(db, session_id, new_messages)


async def get_state(db: AsyncSession, session_id: str) -> SessionState:
    """Load session state from the DB."""
    return await repo.get_state(db, session_id)


async def update_state(db: AsyncSession, session_id: str, state: SessionState) -> None:
    """Persist session state changes to the DB."""
    await repo.update_state(db, session_id, state)


async def clear(db: AsyncSession, session_id: str) -> None:
    """Delete messages, reset state, cancel in-flight requests, and clean up."""
    # Signal cancellation to any in-flight agent loop
    if session_id in cancel_events:
        cancel_events[session_id].set()
        del cancel_events[session_id]

    await repo.clear_session(db, session_id)

    stale_ids = [k for k, v in pending_confirmations.items() if v.session_id == session_id]
    for k in stale_ids:
        del pending_confirmations[k]

    logger.info(
        "Cleared session: %s (%d stale confirmations removed)",
        session_id,
        len(stale_ids),
    )


_STALE_SESSION_THRESHOLD = timedelta(hours=2)


def _is_stale(state: SessionState) -> bool:
    """Return True if the session hasn't been touched recently."""
    if state.last_activity_at is None:
        return False
    now = datetime.now(UTC)
    last = state.last_activity_at
    if last.tzinfo is None:
        last = last.replace(tzinfo=UTC)
    return (now - last) > _STALE_SESSION_THRESHOLD


def build_coordinator_prompt(
    state: SessionState,
    prefs: CommunicationPreferences | None = None,
) -> str:
    """Assemble the coordinator system prompt with preferences, skills, and session state."""
    if prefs is None:
        prefs = CommunicationPreferences()

    preferences_block = format_preferences_block(prefs)
    session_state_block = _build_session_state_block(state)
    skills_metadata = load_skill_metadata()
    available_skills_block = format_available_skills_block(skills_metadata)

    return COORDINATOR_PROMPT_TEMPLATE.format(
        preferences_block=preferences_block,
        session_state_block=session_state_block,
        available_skills_block=available_skills_block,
    )


def _build_session_state_block(state: SessionState) -> str:
    """Build the session state section for prompt injection."""
    if state.active_project:
        stale_note = ""
        if _is_stale(state):
            stale_note = (
                " (set from a previous conversation — if the user seems to be "
                "asking about something unrelated, ask if they want to switch)"
            )
        return (
            f"## Current Session State\n\n"
            f"Active project: {state.active_project}{stale_note}\n"
            f"The specialist agents have full access to this project's files."
        )
    return (
        "## Current Session State\n\n"
        "No project is selected yet. When delegating, the specialist can use "
        "list_projects and set_project to find and select a project.\n"
        "If the user mentions a project by name, include it in the delegation context."
    )


def build_system_prompt(state: SessionState) -> str:
    """Assemble the full system prompt by injecting current session state.

    Sync — no DB needed. The base prompt lives in prompts/system.md.
    """
    if state.active_project:
        stale_note = ""
        if _is_stale(state):
            stale_note = (
                " (set from a previous conversation — if the user seems to be "
                "asking about something unrelated, ask if they want to switch)"
            )
        return (
            SYSTEM_PROMPT + f"\n\n## Current Session State\n\n"
            f"Active project: {state.active_project}{stale_note}\n"
            f"You have full access to this project's files. "
            f"Don't call list_projects or set_project again "
            f"unless the user asks to switch projects.\n"
            f"If a file path fails, try to resolve it "
            f"(check the path, list files) rather than asking the user."
        )
    return (
        SYSTEM_PROMPT + "\n\n## Current Session State\n\n"
        "No project is selected yet. You can use list_projects and set_project.\n"
        "If the user wants to explore or work on code, show them what projects "
        "are available and let them choose. If they mention a project by name, "
        "go ahead and set it — then continue with what they asked for.\n"
        "For general questions or conversation, just respond naturally — "
        "not everything requires a project."
    )
