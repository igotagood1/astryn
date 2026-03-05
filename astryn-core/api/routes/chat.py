import asyncio
import logging
import time

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
from store.domain import cancel_events, cleanup_expired_confirmations, pending_confirmations
from tools.registry import COORDINATOR_TOOLS

logger = logging.getLogger(__name__)

router = APIRouter()

# Cache provider availability to avoid per-request API calls (~200-500ms each)
_availability_cache: dict[str, tuple[bool, float]] = {}
_AVAILABILITY_TTL = 60  # seconds

# Per-session locks to prevent concurrent processing of the same session
_session_locks: dict[str, asyncio.Lock] = {}


async def _is_available_cached(provider) -> bool:
    """Check provider availability with a 60-second cache."""
    key = provider.model_name
    now = time.monotonic()
    cached = _availability_cache.get(key)
    if cached and (now - cached[1]) < _AVAILABILITY_TTL:
        return cached[0]
    result = await provider.is_available()
    _availability_cache[key] = (result, now)
    return result


def _get_session_lock(session_id: str) -> asyncio.Lock:
    """Get or create a lock for the given session."""
    if session_id not in _session_locks:
        _session_locks[session_id] = asyncio.Lock()
    return _session_locks[session_id]


@router.post("/chat", response_model=ChatResponse, dependencies=[Depends(verify_api_key)])
async def chat(req: ChatRequest, db: AsyncSession = Depends(get_db)):
    logger.info("POST /chat received: session=%s", req.session_id)
    cleanup_expired_confirmations()

    lock = _get_session_lock(req.session_id)
    if lock.locked():
        raise HTTPException(
            status_code=409,
            detail="This session is already processing a request. Please wait.",
        )

    async with lock:
        return await _process_chat(req, db)


async def _process_chat(req: ChatRequest, db: AsyncSession) -> ChatResponse:
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
    fallback_from = None

    # Budget check: if Anthropic budget is exhausted, fall back to Ollama
    if coordinator.model_name.startswith(
        "anthropic/"
    ) and not await budget_service.can_use_anthropic(db):
        logger.info("Anthropic budget exhausted, falling back to Ollama")
        fallback_from = coordinator.model_name
        coordinator = get_fallback_provider()

    available = await _is_available_cached(coordinator)

    if not available:
        fallback = get_fallback_provider()
        if fallback.model_name != coordinator.model_name and await _is_available_cached(fallback):
            logger.warning("Coordinator unavailable, falling back to %s", fallback.model_name)
            fallback_from = coordinator.model_name
            coordinator = fallback
        else:
            raise HTTPException(
                status_code=503, detail="LLM provider is not available. Is Ollama running?"
            )

    logger.info("Chat request: session=%s model=%s", req.session_id, coordinator.model_name)

    # Auto-reject orphaned confirmations for this session
    orphaned = [cid for cid, pc in pending_confirmations.items() if pc.session_id == req.session_id]
    for cid in orphaned:
        del pending_confirmations[cid]
    if orphaned:
        logger.info(
            "Auto-rejected %d orphaned confirmation(s) for session %s",
            len(orphaned),
            req.session_id,
        )

    try:
        await session_service.add_user_message(db, req.session_id, req.message)

        history = await session_service.get_history_for_llm(db, req.session_id)
        old_count = len(history)

        prefs = await preferences_service.get_preferences(db, req.session_id)
        system = session_service.build_coordinator_prompt(state, prefs)

        # Create a cancellation event for this session
        cancel = asyncio.Event()
        cancel_events[req.session_id] = cancel

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
                cancel_event=cancel,
            )
        except ProviderUnavailable:
            logger.warning("Provider failed mid-request, retrying with fallback")
            fallback = get_fallback_provider()
            fallback_from = fallback_from or coordinator.model_name
            result = await run_agent(
                provider=fallback,
                messages=list(history),
                system=system,
                session_id=req.session_id,
                session_state=state,
                db=db,
                tools=COORDINATOR_TOOLS,
                specialist_provider=specialist,
                cancel_event=cancel,
            )
        finally:
            cancel_events.pop(req.session_id, None)

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
            fallback_from=fallback_from,
        )

    return ChatResponse(reply=result.reply, model=result.model, fallback_from=fallback_from)


@router.delete("/chat/{session_id}", dependencies=[Depends(verify_api_key)])
async def clear_session(session_id: str, db: AsyncSession = Depends(get_db)):
    await session_service.clear(db, session_id)
    return {"cleared": session_id}
