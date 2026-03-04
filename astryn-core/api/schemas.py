from typing import Annotated, Literal

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    """Incoming chat message from a client."""

    message: str
    session_id: str = "default"


# ── Action payloads ───────────────────────────────────────────────────────────
# Each action type the agent can return is its own class with a `type` literal.
# Adding a new interactive response means adding a new class here — ChatResponse
# never needs to change.


class ConfirmationAction(BaseModel):
    """Agent is paused, waiting for the user to approve or reject a tool call."""

    type: Literal["confirmation"]
    id: str
    preview: str


class ProjectSelectAction(BaseModel):
    """Agent called list_projects — client should render these as selectable buttons."""

    type: Literal["project_select"]
    projects: list[str]


Action = Annotated[
    ConfirmationAction | ProjectSelectAction,
    Field(discriminator="type"),
]


class ChatResponse(BaseModel):
    """Response from the /chat or /confirm endpoints.

    `action` carries any structured UI payload the client needs to render.
    If None, `reply` is a plain text final answer with nothing else to do.
    """

    reply: str
    model: str
    action: Action | None = None


class ConfirmRequest(BaseModel):
    """Client approval or rejection of a pending tool call."""

    action: str  # "approve" or "reject"


class SetModelRequest(BaseModel):
    """Request to switch the active LLM model."""

    model: str
