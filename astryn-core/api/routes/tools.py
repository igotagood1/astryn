from fastapi import APIRouter, HTTPException, Header
from pydantic import BaseModel

from api.routes.chat import ChatResponse, ConfirmationInfo
from api.state import pending_confirmations, sessions
from llm.agent import resume_agent
from llm.config import settings
from llm.router import get_provider

router = APIRouter()


class ConfirmRequest(BaseModel):
    action: str  # "approve" or "reject"


@router.post("/confirm/{confirmation_id}", response_model=ChatResponse)
async def confirm_tool(
    confirmation_id: str,
    req: ConfirmRequest,
    x_api_key: str = Header(...),
):
    if x_api_key != settings.astryn_api_key:
        raise HTTPException(status_code=401, detail="Invalid API key")

    if req.action not in ("approve", "reject"):
        raise HTTPException(status_code=400, detail="action must be 'approve' or 'reject'")

    pending = pending_confirmations.pop(confirmation_id, None)
    if not pending:
        raise HTTPException(status_code=404, detail="Confirmation not found or already resolved")

    provider = get_provider()
    result = await resume_agent(
        provider=provider,
        pending=pending,
        approved=(req.action == "approve"),
    )

    session = sessions.get(pending.session_id)
    if session is not None:
        session.history = result.messages

    if result.pending:
        pending_confirmations[result.pending.id] = result.pending
        return ChatResponse(
            reply=result.reply,
            model=result.model,
            confirmation=ConfirmationInfo(id=result.pending.id, preview=result.pending.preview),
        )

    return ChatResponse(reply=result.reply, model=result.model)
