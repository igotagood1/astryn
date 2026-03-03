# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Astryn is a personal AI assistant with two services:

- **astryn-core** — FastAPI backend that manages LLM interactions and conversation sessions
- **astryn-telegram** — Telegram bot frontend that proxies messages to astryn-core

## Running the Services

**Prerequisites:** Ollama must be running (`ollama serve`) before starting astryn-core.

```bash
# astryn-core (from astryn-core/)
uvicorn api.main:app --reload

# astryn-telegram (from astryn-telegram/)
python bot.py
```

**Install dependencies** (from within each service directory):
```bash
uv pip install -r requirements.txt
```

## Architecture

### astryn-core
- `api/main.py` — FastAPI app, mounts routers
- `api/routes/chat.py` — `POST /chat`, `DELETE /chat/{session_id}`; in-memory sessions keyed by session_id (Phase 1 — SQLite planned for Phase 2)
- `api/routes/health.py` — `GET /health`, pings Ollama and returns model info
- `llm/base.py` — `LLMProvider` ABC and `LLMResponse` dataclass; all providers must implement `chat()`, `is_available()`, and `model_name`
- `llm/providers/ollama.py` — Concrete `OllamaProvider`, calls Ollama's `/api/chat`
- `llm/router.py` — `chat_with_fallback()`: currently no fallback (Phase 1 raises if Ollama is down); designed for future provider fallback chain
- `llm/config.py` — `AstrynSettings` via pydantic-settings; reads from `.env`

### astryn-telegram
- `bot.py` — Entry point; registers command and message handlers
- `core_client.py` — Async HTTP client for astryn-core; uses `X-Api-Key` header and `ASTRYN_CORE_URL`
- `handlers/message.py` — Restricts to `ALLOWED_USER_ID`; uses Telegram `user_id` as session_id
- `handlers/commands.py` — `/help`, `/clear`, `/status`, `/model`

### Key Design Decisions
- Authentication between telegram bot and core is via `X-Api-Key` header
- Adding a new LLM provider means implementing `LLMProvider` in `llm/providers/` and wiring it into `llm/router.py`
- The system prompt defining Astryn's persona lives in `api/routes/chat.py`

## Project Context

Check `tmp/docs/` for project definition, vision, and planning documents (gitignored, not committed).

## Environment Variables

**astryn-core** (`.env`):
```
OLLAMA_BASE_URL=http://localhost:11434
ASTRYN_DEFAULT_MODEL=qwen2.5-coder:7b
ASTRYN_API_KEY=<key>
MAX_HISTORY_TURNS=20
```

**astryn-telegram** (`.env`):
```
TELEGRAM_BOT_TOKEN=<token>
ASTRYN_CORE_URL=http://localhost:8000
ASTRYN_CORE_API_KEY=<key>
ALLOWED_USER_ID=<telegram_user_id>
```
