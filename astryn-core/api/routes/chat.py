import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

import services.budget as budget_service
import services.preferences as preferences_service
import services.session as session_service
from api.deps import verify_api_key
from api.schemas import ChatRequest, ChatResponse, ConfirmationAction
from db.engine import get_db
from llm.agent import run_agent
from llm.base import ProviderUnavailable
from llm.router import get_coordinator_provider, get_fallback_provider, get_specialist_provider
from store.domain import pending_confirmations
from tools.registry import COORDINATOR_TOOLS

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

    coordinator = get_coordinator_provider()
    specialist = get_specialist_provider()

    # Budget check: if Anthropic budget is exhausted, fall back to Ollama
    if coordinator.model_name.startswith(
        "anthropic/"
    ) and not await budget_service.can_use_anthropic(db):
        logger.info("Anthropic budget exhausted, falling back to Ollama")
        coordinator = get_fallback_provider()

    if not await coordinator.is_available():
        # If coordinator is Anthropic and unavailable, try Ollama fallback
        fallback = get_fallback_provider()
        if fallback.model_name != coordinator.model_name and await fallback.is_available():
            logger.warning("Coordinator unavailable, falling back to %s", fallback.model_name)
            coordinator = fallback
        else:
            raise HTTPException(
                status_code=503, detail="LLM provider is not available. Is Ollama running?"
            )

    logger.info("Chat request: session=%s model=%s", req.session_id, coordinator.model_name)

    try:
        await session_service.add_user_message(db, req.session_id, req.message)

        history = await session_service.get_history_for_llm(db, req.session_id)
        old_count = len(history)

        prefs = await preferences_service.get_preferences(db, req.session_id)
        system = session_service.build_coordinator_prompt(state, prefs)

        try:
            result = await run_agent(
                provider=coordinator,
                messages=list(history),
                system=system,
                session_id=req.session_id,
                session_state=state,
                db=db,
                tools=COORDINATOR_TOOLS,
                specialist_provider=specialist,
            )
        except ProviderUnavailable:
            logger.warning("Provider failed mid-request, retrying with fallback")
            fallback = get_fallback_provider()
            result = await run_agent(
                provider=fallback,
                messages=list(history),
                system=system,
                session_id=req.session_id,
                session_state=state,
                db=db,
                tools=COORDINATOR_TOOLS,
                specialist_provider=specialist,
            )

        await session_service.persist_agent_messages(db, req.session_id, old_count, result.messages)
        await session_service.update_state(db, req.session_id, state)

        # Record Anthropic usage if applicable (fire-and-forget)
        if result.usage and coordinator.model_name.startswith("anthropic/"):
            await budget_service.record_usage(
                db=db,
                model=result.model,
                input_tokens=result.usage.get("input_tokens", 0),
                output_tokens=result.usage.get("output_tokens", 0),
                session_id=req.session_id,
            )
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
