import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

import services.session as session_service
from api.deps import verify_api_key
from api.schemas import ChatRequest, ChatResponse, ConfirmationAction
from db.engine import get_db
from llm.agent import run_agent
from llm.router import get_provider
from store.domain import pending_confirmations
from tools.registry import TOOLS

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/chat", response_model=ChatResponse, dependencies=[Depends(verify_api_key)])
async def chat(req: ChatRequest, db: AsyncSession = Depends(get_db)):
    try:
        state = await session_service.ensure_session(db, req.session_id)
    except SQLAlchemyError as exc:
        logger.exception("Database error while loading session %s", req.session_id)
        raise HTTPException(
            status_code=503,
            detail="Database is unavailable. Please try again shortly.",
        ) from exc

    provider = get_provider()
    if not await provider.is_available():
        raise HTTPException(status_code=503, detail="Ollama is not available. Is it running?")

    logger.info("Chat request: session=%s model=%s", req.session_id, provider.model_name)

    try:
        await session_service.add_user_message(db, req.session_id, req.message)

        history = await session_service.get_history_for_llm(db, req.session_id)
        old_count = len(history)

        result = await run_agent(
            provider=provider,
            messages=list(history),
            system=session_service.build_system_prompt(state),
            session_id=req.session_id,
            session_state=state,
            tools=TOOLS if state.active_project else [],
            db=db,
        )

        await session_service.persist_agent_messages(db, req.session_id, old_count, result.messages)
        await session_service.update_state(db, req.session_id, state)
    except SQLAlchemyError as exc:
        logger.exception("Database error during chat processing for session %s", req.session_id)
        raise HTTPException(
            status_code=503,
            detail="Database is unavailable. Please try again shortly.",
        ) from exc

    if result.pending:
        pending_confirmations[result.pending.id] = result.pending
        logger.info(
            "Agent paused for confirmation: id=%s tool=%s",
            result.pending.id,
            result.pending.tool_name,
        )
        return ChatResponse(
            reply=result.reply,
            model=result.model,
            action=ConfirmationAction(id=result.pending.id, preview=result.pending.preview),
        )

    return ChatResponse(reply=result.reply, model=result.model)


@router.delete("/chat/{session_id}", dependencies=[Depends(verify_api_key)])
async def clear_session(session_id: str, db: AsyncSession = Depends(get_db)):
    await session_service.clear(db, session_id)
    return {"cleared": session_id}
