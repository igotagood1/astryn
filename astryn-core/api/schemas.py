from pydantic import BaseModel


class ChatRequest(BaseModel):
    """Incoming chat message from a client."""

    message: str
    session_id: str = "default"


class ConfirmationInfo(BaseModel):
    """Details of a pending tool confirmation returned to the client.

    Sent when the agent pauses and needs the user to approve or reject
    a write or exec tool call before it can continue.
    """

    id: str
    preview: str


class ChatResponse(BaseModel):
    """Response from the /chat or /confirm endpoints.

    If `confirmation` is present, the agent is paused and the client
    should present the user with an approve/reject prompt.
    If `confirmation` is None, `reply` contains the agent's final answer.
    """

    reply: str
    model: str
    confirmation: ConfirmationInfo | None = None


class ConfirmRequest(BaseModel):
    """Client approval or rejection of a pending tool call."""

    action: str  # "approve" or "reject"


class SetModelRequest(BaseModel):
    """Request to switch the active LLM model."""

    model: str
