import logging

from fastapi import APIRouter, Depends, HTTPException

from api.deps import verify_api_key
from api.schemas import ChatResponse, ConfirmationInfo, ConfirmRequest
from store.memory import pending_confirmations, sessions
from llm.agent import resume_agent
from llm.router import get_provider

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post(
    "/confirm/{confirmation_id}",
    response_model=ChatResponse,
    dependencies=[Depends(verify_api_key)],
)
async def confirm_tool(confirmation_id: str, req: ConfirmRequest):
    if req.action not in ("approve", "reject"):
        raise HTTPException(status_code=400, detail="action must be 'approve' or 'reject'")

    pending = pending_confirmations.pop(confirmation_id, None)
    if not pending:
        raise HTTPException(status_code=404, detail="Confirmation not found or already resolved")

    approved = req.action == "approve"
    logger.info(
        "Confirmation %s: tool=%s action=%s", confirmation_id, pending.tool_name, req.action
    )

    provider = get_provider()
    result = await resume_agent(provider=provider, pending=pending, approved=approved)

    session = sessions.get(pending.session_id)
    if session is not None:
        session.history = result.messages

    if result.pending:
        pending_confirmations[result.pending.id] = result.pending
        logger.info(
            "Agent paused for next confirmation: id=%s tool=%s",
            result.pending.id,
            result.pending.tool_name,
        )
        return ChatResponse(
            reply=result.reply,
            model=result.model,
            confirmation=ConfirmationInfo(id=result.pending.id, preview=result.pending.preview),
        )

    return ChatResponse(reply=result.reply, model=result.model)
