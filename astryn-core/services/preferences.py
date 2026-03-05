"""Preferences service — validation and formatting for communication preferences."""

from sqlalchemy.ext.asyncio import AsyncSession

import db.repository as repo
from store.domain import (
    CODE_EXPLANATION_OPTIONS,
    TONE_OPTIONS,
    VERBOSITY_OPTIONS,
    CommunicationPreferences,
)

VALID_FIELDS: dict[str, tuple[str, ...] | type] = {
    "verbosity": VERBOSITY_OPTIONS,
    "tone": TONE_OPTIONS,
    "code_explanation": CODE_EXPLANATION_OPTIONS,
    "proactive_suggestions": bool,
}


def validate_preference(field: str, value: str | bool) -> str | bool:
    """Validate a single preference field+value. Returns the validated value.

    Raises ValueError if the field or value is invalid.
    """
    if field not in VALID_FIELDS:
        raise ValueError(
            f"Unknown preference field: {field!r}. Valid fields: {', '.join(VALID_FIELDS)}"
        )

    allowed = VALID_FIELDS[field]

    if allowed is bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            lower = value.lower()
            if lower in ("true", "yes", "on", "1"):
                return True
            if lower in ("false", "no", "off", "0"):
                return False
        raise ValueError(f"Invalid value for {field}: {value!r}. Expected true/false.")

    if value not in allowed:
        raise ValueError(f"Invalid value for {field}: {value!r}. Options: {', '.join(allowed)}")
    return value


def format_preferences_block(prefs: CommunicationPreferences) -> str:
    """Format preferences as a directive block for injection into system prompts."""
    lines = []

    match prefs.verbosity:
        case "concise":
            lines.append("- Be concise. Short, direct responses.")
        case "balanced":
            lines.append("- Balanced responses. Include enough detail to be helpful.")
        case "detailed":
            lines.append("- Be thorough. Include full explanations and context.")

    match prefs.tone:
        case "casual":
            lines.append("- Casual tone. Conversational, direct.")
        case "professional":
            lines.append("- Professional tone. Clear and polished.")

    match prefs.code_explanation:
        case "minimal":
            lines.append("- Minimal code explanations. Just show the changes.")
        case "explain":
            lines.append("- Explain code changes. Say what changed and why.")
        case "teach":
            lines.append(
                "- Teach mode. Explain code changes in depth, "
                "cover underlying concepts and patterns."
            )

    if prefs.proactive_suggestions:
        lines.append("- Proactively suggest next steps.")
    else:
        lines.append("- Only act on what is explicitly asked. No unsolicited suggestions.")

    return "\n".join(lines)


async def get_preferences(db: AsyncSession, session_id: str) -> CommunicationPreferences:
    """Load preferences for a session, returning defaults if none are saved."""
    return await repo.get_preferences(db, session_id)


async def update_preference(
    db: AsyncSession, session_id: str, field: str, value: str | bool
) -> CommunicationPreferences:
    """Validate and update a single preference field. Returns updated preferences."""
    validated = validate_preference(field, value)
    prefs = await repo.get_preferences(db, session_id)
    setattr(prefs, field, validated)
    await repo.update_preferences(db, session_id, prefs)
    return prefs
