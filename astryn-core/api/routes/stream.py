"""SSE streaming endpoint for real-time chat responses.

POST /chat/stream yields server-sent events as the agent processes a request:
  - text_delta: partial text from the LLM
  - tool_start: a tool is about to execute
  - tool_result: a tool has finished
  - status: status message (e.g. "Delegating to code-writer...")
  - done: final response with metadata
  - error: something went wrong
"""

import asyncio
import json
import logging

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

import services.budget as budget_service
import services.preferences as preferences_service
import services.session as session_service
from api.deps import verify_api_key
from api.routes.chat import _is_available_cached
from api.schemas import ChatRequest, ConfirmationAction
from db.engine import get_db
from llm.agent import run_agent
from llm.base import ProviderUnavailable
from llm.events import (
    AgentDone,
    AgentError,
    StatusUpdate,
    TextDelta,
    ToolResult,
    ToolStart,
)
from llm.router import get_coordinator_provider, get_fallback_provider, get_specialist_provider
from store.domain import cleanup_expired_confirmations, pending_confirmations
from tools.registry import COORDINATOR_TOOLS

logger = logging.getLogger(__name__)

router = APIRouter()


def _sse_event(event_type: str, data: dict) -> str:
    """Format a server-sent event."""
    return f"event: {event_type}\ndata: {json.dumps(data)}\n\n"


@router.post("/chat/stream", dependencies=[Depends(verify_api_key)])
async def chat_stream(req: ChatRequest, db: AsyncSession = Depends(get_db)):
    """Stream chat response as server-sent events."""
    logger.info("POST /chat/stream received: session=%s", req.session_id)
    cleanup_expired_confirmations()

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

    # Budget check
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

    # Prepare messages and prompt
    try:
        await session_service.add_user_message(db, req.session_id, req.message)
        history = await session_service.get_history_for_llm(db, req.session_id)
        old_count = len(history)
        prefs = await preferences_service.get_preferences(db, req.session_id)
        system = session_service.build_coordinator_prompt(state, prefs)
    except SQLAlchemyError as exc:
        logger.exception("Database error preparing chat for session %s", req.session_id)
        raise HTTPException(
            status_code=503,
            detail="Database is unavailable. Please try again shortly.",
        ) from exc

    event_queue: asyncio.Queue = asyncio.Queue()

    async def _run_agent_task():
        """Run the agent loop and push AgentDone/AgentError when complete."""
        try:
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
                    event_queue=event_queue,
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
                    event_queue=event_queue,
                )

            # Persist results
            await session_service.persist_agent_messages(
                db, req.session_id, old_count, result.messages
            )
            await session_service.update_state(db, req.session_id, state)

            # Record Anthropic usage
            if result.usage and coordinator.model_name.startswith("anthropic/"):
                await budget_service.record_usage(
                    db=db,
                    model=result.model,
                    input_tokens=result.usage.get("input_tokens", 0),
                    output_tokens=result.usage.get("output_tokens", 0),
                    session_id=req.session_id,
                )

            # Build done event
            action = None
            if result.pending:
                pending_confirmations[result.pending.id] = result.pending
                action = ConfirmationAction(
                    id=result.pending.id, preview=result.pending.preview
                ).model_dump()

            await event_queue.put(
                AgentDone(
                    reply=result.reply,
                    model=result.model,
                    action=action,
                    usage=result.usage,
                )
            )
        except Exception:
            logger.exception("Agent task failed for session %s", req.session_id)
            await event_queue.put(AgentError(error="An internal error occurred. Please try again."))

    async def _event_generator():
        """Read from event_queue and yield SSE events."""
        task = asyncio.create_task(_run_agent_task())

        try:
            while True:
                try:
                    event = await asyncio.wait_for(event_queue.get(), timeout=120)
                except TimeoutError:
                    yield _sse_event("error", {"error": "Response timed out"})
                    break

                if isinstance(event, TextDelta):
                    yield _sse_event("text_delta", {"text": event.text})
                elif isinstance(event, ToolStart):
                    yield _sse_event(
                        "tool_start",
                        {"tool": event.tool_name, "args": event.tool_args},
                    )
                elif isinstance(event, ToolResult):
                    yield _sse_event(
                        "tool_result",
                        {"tool": event.tool_name, "summary": event.summary},
                    )
                elif isinstance(event, StatusUpdate):
                    yield _sse_event("status", {"message": event.message})
                elif isinstance(event, AgentDone):
                    data = {
                        "reply": event.reply,
                        "model": event.model,
                        "action": event.action,
                    }
                    if fallback_from:
                        data["fallback_from"] = fallback_from
                    yield _sse_event("done", data)
                    break
                elif isinstance(event, AgentError):
                    yield _sse_event("error", {"error": event.error})
                    break
        finally:
            if not task.done():
                task.cancel()

    return StreamingResponse(
        _event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
