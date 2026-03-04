"""Session service — business logic for managing conversation sessions.

All methods are async and accept a db: AsyncSession. The database is the
source of truth; in-memory pending_confirmations remain transient.
"""

import logging

from sqlalchemy.ext.asyncio import AsyncSession

import db.repository as repo
from llm.config import settings
from prompts.system import SYSTEM_PROMPT
from store.domain import SessionState, pending_confirmations

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
    """Delete messages, reset state, and clean up pending confirmations."""
    await repo.clear_session(db, session_id)

    stale_ids = [
        k for k, v in pending_confirmations.items() if v.session_id == session_id
    ]
    for k in stale_ids:
        del pending_confirmations[k]

    logger.info(
        "Cleared session: %s (%d stale confirmations removed)",
        session_id,
        len(stale_ids),
    )


def build_system_prompt(state: SessionState) -> str:
    """Assemble the full system prompt by injecting current session state.

    Sync — no DB needed. The base prompt lives in prompts/system.md.
    """
    if state.active_project:
        return (
            SYSTEM_PROMPT + f"\n\n## Current Session State\n\n"
            f"Active project: {state.active_project}\n"
            f"Do NOT call list_projects or set_project again unless the user explicitly asks to change projects."
        )
    return (
        SYSTEM_PROMPT + "\n\n## Current Session State\n\n"
        "No active project is set. Respond conversationally.\n"
        "The user can pick a project with the /projects command in Telegram."
    )
