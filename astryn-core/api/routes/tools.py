import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

import services.session as session_service
from api.deps import verify_api_key
from api.schemas import ChatResponse, ConfirmationAction, ConfirmRequest
from db.engine import get_db
from llm.agent import resume_agent
from llm.router import get_provider
from store.domain import pending_confirmations

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
    pending = pending_confirmations.pop(confirmation_id, None)
    if not pending:
        raise HTTPException(status_code=404, detail="Confirmation not found or already resolved")

    approved = req.action == "approve"
    logger.info(
        "Confirmation %s: tool=%s action=%s", confirmation_id, pending.tool_name, req.action
    )

    provider = get_provider()
    # When resuming a delegated confirmation, result.messages will be coordinator
    # messages (after _resume_coordinator), not specialist messages. Use the
    # coordinator message count so persist_agent_messages diffs correctly.
    if pending.coordinator_messages is not None:
        old_count = len(pending.coordinator_messages)
    else:
        old_count = len(pending.messages)

    try:
        result = await resume_agent(provider=provider, pending=pending, approved=approved, db=db)

        await session_service.persist_agent_messages(
            db, pending.session_id, old_count, result.messages
        )
        await session_service.update_state(db, pending.session_id, pending.session_state)
    except SQLAlchemyError as exc:
        logger.exception(
            "Database error during confirmation %s for session %s",
            confirmation_id,
            pending.session_id,
        )
        raise HTTPException(
            status_code=503,
            detail="Database is unavailable. Please try again shortly.",
        ) from exc

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
