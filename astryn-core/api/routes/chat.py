from fastapi import APIRouter, HTTPException, Header
from pydantic import BaseModel
from llm.router import chat_with_fallback
from llm.config import settings

router = APIRouter()

SYSTEM_PROMPT = """You are Astryn, a personal AI assistant for a senior software engineer.
You are direct, technical, and precise. You challenge assumptions and ask clarifying
questions rather than making guesses. You prefer code examples over prose.
You never pad responses with unnecessary caveats."""

# In-memory sessions. Resets on restart. Replaced with SQLite in Phase 2.
sessions: dict[str, list[dict]] = {}


class ChatRequest(BaseModel):
    message: str
    session_id: str = 'default'


class ChatResponse(BaseModel):
    reply: str
    model: str
    used_fallback: bool


@router.post('/chat', response_model=ChatResponse)
async def chat(
    req: ChatRequest,
    x_api_key: str = Header(...),
):
    if x_api_key != settings.astryn_api_key:
        raise HTTPException(status_code=401, detail='Invalid API key')

    history = sessions.get(req.session_id, [])
    history.append({'role': 'user', 'content': req.message})

    max_messages = settings.max_history_turns * 2
    if len(history) > max_messages:
        history = history[-max_messages:]

    response, used_fallback = await chat_with_fallback(
        messages=history,
        system=SYSTEM_PROMPT,
    )

    history.append({'role': 'assistant', 'content': response.content})
    sessions[req.session_id] = history

    return ChatResponse(
        reply=response.content,
        model=response.model,
        used_fallback=used_fallback,
    )


@router.delete('/chat/{session_id}')
async def clear_session(
    session_id: str,
    x_api_key: str = Header(...),
):
    if x_api_key != settings.astryn_api_key:
        raise HTTPException(status_code=401, detail='Invalid API key')
    sessions.pop(session_id, None)
    return {'cleared': session_id}