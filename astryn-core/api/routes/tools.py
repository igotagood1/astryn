import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

import services.session as session_service
from api.deps import verify_api_key
from api.schemas import ChatResponse, ConfirmationAction, ConfirmRequest
from db.engine import get_db
from store.domain import pending_confirmations
from llm.agent import resume_agent
from llm.router import get_provider

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post(
    "/confirm/{confirmation_id}",
    response_model=ChatResponse,
    dependencies=[Depends(verify_api_key)],
)
async def confirm_tool(
    confirmation_id: str,
    req: ConfirmRequest,
    db: AsyncSession = Depends(get_db),
):
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
    old_count = len(pending.messages)

    result = await resume_agent(provider=provider, pending=pending, approved=approved, db=db)

    await session_service.persist_agent_messages(db, pending.session_id, old_count, result.messages)
    await session_service.update_state(db, pending.session_id, pending.session_state)

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
            action=ConfirmationAction(id=result.pending.id, preview=result.pending.preview),
        )

    return ChatResponse(reply=result.reply, model=result.model)
