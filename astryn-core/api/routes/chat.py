from fastapi import APIRouter, HTTPException, Header
from pydantic import BaseModel

from api.state import Session, pending_confirmations, sessions
from llm.agent import run_agent
from llm.config import settings
from llm.router import get_provider
from prompts.system import SYSTEM_PROMPT

router = APIRouter()


class ChatRequest(BaseModel):
    message: str
    session_id: str = "default"


class ConfirmationInfo(BaseModel):
    id: str
    preview: str


class ChatResponse(BaseModel):
    reply: str
    model: str
    used_fallback: bool = False
    confirmation: ConfirmationInfo | None = None


def _get_or_create(session_id: str) -> Session:
    if session_id not in sessions:
        sessions[session_id] = Session()
    return sessions[session_id]


def _trim(history: list[dict]) -> list[dict]:
    max_messages = settings.max_history_turns * 2
    return history[-max_messages:] if len(history) > max_messages else history


@router.post("/chat", response_model=ChatResponse)
async def chat(
    req: ChatRequest,
    x_api_key: str = Header(...),
):
    if x_api_key != settings.astryn_api_key:
        raise HTTPException(status_code=401, detail="Invalid API key")

    session = _get_or_create(req.session_id)
    session.history = _trim(session.history)
    session.history.append({"role": "user", "content": req.message})

    provider = get_provider()
    if not await provider.is_available():
        raise HTTPException(status_code=503, detail="Ollama is not available. Is it running?")

    result = await run_agent(
        provider=provider,
        messages=list(session.history),
        system=SYSTEM_PROMPT,
        session_id=req.session_id,
        session_state=session.state,
    )

    session.history = result.messages

    if result.pending:
        pending_confirmations[result.pending.id] = result.pending
        return ChatResponse(
            reply=result.reply,
            model=result.model,
            confirmation=ConfirmationInfo(id=result.pending.id, preview=result.pending.preview),
        )

    return ChatResponse(reply=result.reply, model=result.model)


@router.delete("/chat/{session_id}")
async def clear_session(
    session_id: str,
    x_api_key: str = Header(...),
):
    if x_api_key != settings.astryn_api_key:
        raise HTTPException(status_code=401, detail="Invalid API key")

    sessions.pop(session_id, None)

    # Clean up any pending confirmations that belong to this session
    stale = [k for k, v in pending_confirmations.items() if v.session_id == session_id]
    for k in stale:
        del pending_confirmations[k]

    return {"cleared": session_id}
