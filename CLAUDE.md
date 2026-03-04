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

**After adding a new package**, update the requirements file from within the service directory:
```bash
uv pip install <package>
uv pip freeze > requirements.txt
```
Always do this before committing — if a package is imported but missing from `requirements.txt`, the service will fail to start in a clean environment.

## Phase Status

| Phase | Focus | Status |
|-------|-------|--------|
| 1 | Chat via Telegram + Ollama | ✅ Complete |
| 2 | Tool use — file r/w, shell, project scoping, model switching | 🔲 Next |
| 3 | SQLite persistence, launchd services, Anthropic fallback | 🔲 Planned |
| 4 | Cloudflare Tunnel, webhooks, GitHub integration, Draft & Compose | 🔲 Planned |
| 5+ | MCP servers, persistent memory, Android app | 🔲 Future |

## Architecture

### astryn-core
- `api/main.py` — FastAPI app, mounts routers
- `api/routes/chat.py` — `POST /chat`, `DELETE /chat/{session_id}`; runs agentic loop (Phase 2+), in-memory sessions (Phase 1)
- `api/routes/health.py` — `GET /health`, pings Ollama
- `api/routes/models.py` — `GET /models`, `POST /models/active` (Phase 2+)
- `llm/base.py` — `LLMProvider` ABC and `LLMResponse` dataclass
- `llm/providers/ollama.py` — `OllamaProvider`, calls Ollama's `/api/chat`; supports tool_calls (Phase 2+)
- `llm/router.py` — provider factory, active model state, fallback chain (Phase 3+)
- `llm/agent.py` — agentic loop: executes tool calls, handles confirmation pause/resume (Phase 2+)
- `llm/config.py` — `AstrynSettings` via pydantic-settings
- `tools/safety.py` — path validation (scoped to `~/repos`), shell command whitelist (Phase 2+)
- `tools/definitions.py` — tool JSON schemas passed to LLM (Phase 2+)
- `tools/executor.py` — tool execution functions (Phase 2+)
- `db/` — SQLite via aiosqlite: sessions, session state, pending confirmations (Phase 3+)

### astryn-telegram
- `bot.py` — entry point; registers handlers including `CallbackQueryHandler` (Phase 2+)
- `core_client.py` — async HTTP client for astryn-core
- `handlers/message.py` — handles text messages; renders confirmation inline keyboards (Phase 2+)
- `handlers/commands.py` — `/help`, `/clear`, `/status`, `/model`
- `handlers/callbacks.py` — inline keyboard button handler for tool confirmations (Phase 2+)

### Key Design Decisions
- All file/shell operations are scoped to `~/repos` — enforced in `tools/safety.py`
- Write/exec tool calls require Telegram inline keyboard confirmation before executing
- Active model is global state in `llm/router.py`; switched via `/model use <name>`
- Adding a new LLM provider: implement `LLMProvider` in `llm/providers/`, add a `case` to `router.py`
- The coworker system prompt (challenge, alternatives, confirm before acting) lives in `api/routes/chat.py`

## Branching Rules

- Before starting any work, check the current branch with `git branch --show-current`.
- If the work is unrelated to the current branch's scope (different feature, fix, or phase), stop and propose a new branch name before touching any files.
- Never commit work for two different concerns on the same branch — keep branches focused.
- Branch naming convention: `feat/<name>`, `fix/<name>`, `refactor/<name>`, `docs/<name>`.

**Creating a new branch — always follow these steps in order:**
1. `git fetch origin` — update remote refs
2. `git pull origin main` — bring main up to date
3. `git checkout -b <branch-name> origin/main` — branch from origin/main, not from wherever HEAD is

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
