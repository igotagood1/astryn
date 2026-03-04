import logging

from fastapi import APIRouter, Depends, HTTPException

import services.session as session_service
from api.deps import verify_api_key
from api.schemas import ChatRequest, ChatResponse, ConfirmationAction
from llm.agent import run_agent
from llm.router import get_provider
from tools.registry import TOOLS
from store.memory import pending_confirmations

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/chat", response_model=ChatResponse, dependencies=[Depends(verify_api_key)])
async def chat(req: ChatRequest):
    session = session_service.get_or_create(req.session_id)
    session_service.add_user_message(session, req.message)

    provider = get_provider()
    if not await provider.is_available():
        raise HTTPException(status_code=503, detail="Ollama is not available. Is it running?")

    logger.info("Chat request: session=%s model=%s", req.session_id, provider.model_name)

    result = await run_agent(
        provider=provider,
        messages=list(session.history),
        system=session_service.build_system_prompt(session.state),
        session_id=req.session_id,
        session_state=session.state,
        tools=TOOLS if session.state.active_project else [],
    )

    session.history = result.messages

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
async def clear_session(session_id: str):
    session_service.clear(session_id)
    return {"cleared": session_id}
