"""Database operations — the only place SQLAlchemy is imported outside db/.

Maps between SQLAlchemy ORM models and the domain types in store/domain.py.

All public functions accept `external_id` (the Telegram user ID string).
`_resolve_session` handles the external_id → internal UUID lookup once per
request via SQLAlchemy's identity map cache.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import (
    CommunicationPreferencesModel,
    MessageModel,
    SessionModel,
    SessionStateModel,
    ToolAuditModel,
)
from store.domain import CommunicationPreferences, SessionState

logger = logging.getLogger(__name__)


# ── Internal helpers ─────────────────────────────────────────────────────────


async def _resolve_session(db: AsyncSession, external_id: str) -> SessionModel:
    """Get or create a session row by external ID.

    Within a single AsyncSession, SQLAlchemy's identity map caches the result,
    so multiple calls with the same external_id hit the DB only once.
    """
    result = await db.execute(select(SessionModel).where(SessionModel.external_id == external_id))
    session = result.scalar_one_or_none()

    if session is None:
        session = SessionModel(external_id=external_id)
        db.add(session)
        await db.flush()

        state = SessionStateModel(session_id=session.id)
        db.add(state)
        await db.flush()

        logger.debug("Created new session: external_id=%s", external_id)

    return session


# ── Session operations ───────────────────────────────────────────────────────


async def ensure_session(db: AsyncSession, external_id: str) -> None:
    """Ensure session + state rows exist. No return value — use get_state to read."""
    await _resolve_session(db, external_id)


async def get_state(db: AsyncSession, external_id: str) -> SessionState:
    """Load session state as a domain object."""
    session = await _resolve_session(db, external_id)
    result = await db.execute(
        select(SessionStateModel).where(SessionStateModel.session_id == session.id)
    )
    state_row = result.scalar_one_or_none()

    if state_row is None:
        return SessionState(last_activity_at=session.updated_at)

    return SessionState(
        active_project=state_row.active_project,
        last_activity_at=session.updated_at,
    )


async def update_state(db: AsyncSession, external_id: str, state: SessionState) -> None:
    """Persist session state changes."""
    session = await _resolve_session(db, external_id)
    result = await db.execute(
        select(SessionStateModel).where(SessionStateModel.session_id == session.id)
    )
    state_row = result.scalar_one_or_none()

    if state_row is None:
        state_row = SessionStateModel(session_id=session.id)
        db.add(state_row)

    state_row.active_project = state.active_project
    await db.flush()


# ── Preferences operations ───────────────────────────────────────────────────


async def get_preferences(db: AsyncSession, external_id: str) -> CommunicationPreferences:
    """Load communication preferences for a session, returning defaults if none exist."""
    session = await _resolve_session(db, external_id)
    result = await db.execute(
        select(CommunicationPreferencesModel).where(
            CommunicationPreferencesModel.session_id == session.id
        )
    )
    row = result.scalar_one_or_none()

    if row is None:
        return CommunicationPreferences()

    return CommunicationPreferences(
        verbosity=row.verbosity,
        tone=row.tone,
        code_explanation=row.code_explanation,
        proactive_suggestions=row.proactive_suggestions,
    )


async def update_preferences(
    db: AsyncSession, external_id: str, prefs: CommunicationPreferences
) -> None:
    """Persist communication preferences for a session."""
    session = await _resolve_session(db, external_id)
    result = await db.execute(
        select(CommunicationPreferencesModel).where(
            CommunicationPreferencesModel.session_id == session.id
        )
    )
    row = result.scalar_one_or_none()

    if row is None:
        row = CommunicationPreferencesModel(session_id=session.id)
        db.add(row)

    row.verbosity = prefs.verbosity
    row.tone = prefs.tone
    row.code_explanation = prefs.code_explanation
    row.proactive_suggestions = prefs.proactive_suggestions
    await db.flush()


# ── Message operations ───────────────────────────────────────────────────────


def _msg_to_row(session_id: uuid.UUID, msg: dict) -> MessageModel:
    """Convert a message dict (as used by the LLM) to a DB row."""
    return MessageModel(
        session_id=session_id,
        role=msg["role"],
        content=msg.get("content"),
        tool_calls=msg.get("tool_calls"),
        tool_call_id=msg.get("tool_call_id"),
    )


def _row_to_msg(row: MessageModel) -> dict:
    """Convert a DB row back to a message dict for the LLM.

    Only includes keys that are present — does not coerce None to empty string.
    This preserves the exact shape the LLM provider expects.
    """
    msg: dict = {"role": row.role}
    if row.content is not None:
        msg["content"] = row.content
    if row.tool_calls is not None:
        msg["tool_calls"] = row.tool_calls
    if row.tool_call_id is not None:
        msg["tool_call_id"] = row.tool_call_id
    return msg


async def _touch_session(session: SessionModel) -> None:
    """Update the session's updated_at timestamp.

    SQLAlchemy's onupdate only fires on explicit UPDATEs to the row itself,
    not when child rows (messages) are added. We touch it manually so that
    staleness detection sees the real last-activity time.
    """
    session.updated_at = datetime.now(UTC)


async def add_message(db: AsyncSession, external_id: str, msg: dict) -> None:
    """Append a single message to a session's history."""
    session = await _resolve_session(db, external_id)
    row = _msg_to_row(session.id, msg)
    db.add(row)
    await _touch_session(session)
    await db.flush()


async def add_messages(db: AsyncSession, external_id: str, msgs: list[dict]) -> None:
    """Append multiple messages to a session's history."""
    if not msgs:
        return
    session = await _resolve_session(db, external_id)
    for msg in msgs:
        db.add(_msg_to_row(session.id, msg))
    await _touch_session(session)
    await db.flush()


async def get_messages(db: AsyncSession, external_id: str, limit: int | None = None) -> list[dict]:
    """Fetch message history for a session, ordered by creation time.

    When limit is set, returns the most recent N messages using a single
    efficient query (ORDER BY DESC LIMIT N, then reverse in Python).
    """
    session = await _resolve_session(db, external_id)

    if limit is not None:
        # Fetch last N rows ordered newest-first, then reverse for chronological order
        stmt = (
            select(MessageModel)
            .where(MessageModel.session_id == session.id)
            .order_by(MessageModel.created_at.desc())
            .limit(limit)
        )
        result = await db.execute(stmt)
        rows = list(reversed(result.scalars().all()))
    else:
        stmt = (
            select(MessageModel)
            .where(MessageModel.session_id == session.id)
            .order_by(MessageModel.created_at)
        )
        result = await db.execute(stmt)
        rows = result.scalars().all()

    return [_row_to_msg(row) for row in rows]


async def delete_messages(db: AsyncSession, external_id: str) -> int:
    """Delete all messages for a session. Returns count deleted."""
    session = await _resolve_session(db, external_id)
    result = await db.execute(delete(MessageModel).where(MessageModel.session_id == session.id))
    await db.flush()
    return result.rowcount


# ── Tool audit ───────────────────────────────────────────────────────────────


async def log_tool_call(
    db: AsyncSession,
    external_id: str,
    tool_name: str,
    tool_args: dict,
    required_confirmation: bool = False,
    approved: bool | None = None,
    result: str | None = None,
    error: str | None = None,
) -> None:
    """Log a tool call to the audit table."""
    session = await _resolve_session(db, external_id)
    row = ToolAuditModel(
        session_id=session.id,
        tool_name=tool_name,
        tool_args=tool_args,
        required_confirmation=required_confirmation,
        approved=approved,
        result=result[:2000] if result and len(result) > 2000 else result,
        error=error,
    )
    db.add(row)
    await db.flush()


# ── Clear ────────────────────────────────────────────────────────────────────


async def clear_session(db: AsyncSession, external_id: str) -> None:
    """Delete messages and reset state for a session. Keeps the session row."""
    session = await _resolve_session(db, external_id)
    await db.execute(delete(MessageModel).where(MessageModel.session_id == session.id))

    result = await db.execute(
        select(SessionStateModel).where(SessionStateModel.session_id == session.id)
    )
    state_row = result.scalar_one_or_none()
    if state_row:
        state_row.active_project = None

    await db.flush()
    logger.info("Cleared session: external_id=%s", external_id)
