"""Session service — business logic for managing conversation sessions.

This is the service layer. Routes call these functions instead of touching
the store or building prompts themselves. No FastAPI or HTTP types appear here.

Analogy to C#: this is the service class that a controller would inject and call.
The route (controller) handles HTTP; this module handles the what and how.
"""

import logging

from llm.config import settings
from prompts.system import SYSTEM_PROMPT
from store.memory import Session, SessionState, pending_confirmations, sessions

logger = logging.getLogger(__name__)


def get_or_create(session_id: str) -> Session:
    """Return the existing session for this ID, or create a fresh one."""
    if session_id not in sessions:
        logger.debug("Creating new session: %s", session_id)
        sessions[session_id] = Session()
    return sessions[session_id]


def add_user_message(session: Session, message: str) -> None:
    """Append the user's message and trim history to the configured window.

    Trimming is done here so the route doesn't need to know about history limits.
    The window is max_history_turns * 2 because each turn is a user + assistant pair.
    """
    max_messages = settings.max_history_turns * 2
    if len(session.history) > max_messages:
        session.history = session.history[-max_messages:]
    session.history.append({"role": "user", "content": message})


def build_system_prompt(state: SessionState) -> str:
    """Assemble the full system prompt by injecting current session state.

    The base prompt lives in prompts/system.md. Session state (active project)
    is appended so the model always knows the working context.
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


def clear(session_id: str) -> None:
    """Remove a session and all of its pending confirmations from the store.

    Cleaning up confirmations prevents orphaned entries in the pending dict
    when a user clears mid-conversation while a tool is awaiting approval.
    """
    sessions.pop(session_id, None)
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
