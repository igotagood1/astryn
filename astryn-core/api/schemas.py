from typing import Literal

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    """Incoming chat message from a client."""

    message: str = Field(..., min_length=1, max_length=32_000)
    session_id: str = "default"


class ConfirmationAction(BaseModel):
    """Agent is paused, waiting for the user to approve or reject a tool call."""

    type: Literal["confirmation"] = "confirmation"
    id: str
    preview: str


class ChatResponse(BaseModel):
    """Response from the /chat or /confirm endpoints.

    `action` carries any structured UI payload the client needs to render.
    If None, `reply` is a plain text final answer with nothing else to do.
    New interactive response types add a new Action subclass and a new case
    in the Telegram _send_result dispatcher — ChatResponse itself never changes.
    """

    reply: str
    model: str
    action: ConfirmationAction | None = None
    fallback_from: str | None = None


class ConfirmRequest(BaseModel):
    """Client approval or rejection of a pending tool call."""

    action: Literal["approve", "reject"]


class SetModelRequest(BaseModel):
    """Request to switch the active LLM model."""

    model: str


class SetProjectRequest(BaseModel):
    """Request to set the active project for a session directly (bypasses LLM)."""

    name: str
    session_id: str = "default"


class PreferencesResponse(BaseModel):
    """Current communication preferences for a session."""

    verbosity: str
    tone: str
    code_explanation: str
    proactive_suggestions: bool


class UpdatePreferenceRequest(BaseModel):
    """Request to update a single communication preference."""

    field: str
    value: str | bool


class PullModelRequest(BaseModel):
    """Request to pull a model from the Ollama registry."""

    model: str
