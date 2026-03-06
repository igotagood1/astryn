# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Astryn is a personal AI assistant with two services:

- **astryn-core** — FastAPI backend that manages LLM interactions and conversation sessions
- **astryn-telegram** — Telegram bot frontend that proxies messages to astryn-core

## Running the Services

**Prerequisites:** Ollama must be running (`ollama serve`) and Postgres must be available before starting astryn-core.

```bash
# astryn-core (from astryn-core/)
uvicorn api.main:app --reload

# astryn-telegram (from astryn-telegram/)
python bot.py
```

**Install dependencies** (from within each service directory):
```bash
uv sync              # production deps only
uv sync --extra dev  # dev + test (includes prod)
```

**After adding a new package**, update `pyproject.toml` and regenerate the lockfile:
```bash
uv add <package>              # runtime dependency → [project.dependencies]
uv add --dev <package>        # dev/test dependency → [project.optional-dependencies.dev]
```
This updates `pyproject.toml` and `uv.lock` automatically. Always commit both files. The Dockerfile installs from the lockfile (`uv sync --frozen --no-dev`).

## Phase Status

| Phase | Focus | Status |
|-------|-------|--------|
| 1 | Chat via Telegram + Ollama | ✅ Complete |
| 2 | Tool use, coordinator/specialist architecture, communication preferences | ✅ Complete |
| 3a | Postgres persistence, multi-provider routing (Anthropic + Ollama), skills system, budget tracking | ✅ Complete |
| 3b | Plugin architecture, Draft & Compose, web research, notes integration | 🔲 Planned |
| 4 | Background services, home automation, web SPA, GitHub integration | 🔲 Planned |
| 5+ | Mobile app, Alexa, semantic memory, proactive intelligence | 🔲 Future |

## Architecture

### astryn-core
- `api/main.py` — FastAPI app, mounts routers
- `api/routes/chat.py` — `POST /chat` (coordinator mode), `DELETE /chat/{session_id}`. Per-session locking (409 on concurrent access), orphaned confirmation cleanup, cancellation events, budget check + Anthropic fallback logic.
- `api/routes/stream.py` — `POST /chat/stream` SSE endpoint. Streams `text_delta`, `tool_start`, `tool_result`, `status`, `done`, `error` events via `asyncio.Queue`.
- `api/routes/preferences.py` — `GET/POST /preferences/{session_id}` for communication style
- `api/routes/health.py` — `GET /health`, pings Ollama
- `api/routes/models.py` — `GET /models`, `POST /models/active`
- `api/routes/projects.py` — `GET /projects`, `POST /projects/active`, `DELETE /projects/active`
- `api/routes/tools.py` — `POST /confirm/{id}` for tool confirmation
- `llm/base.py` — `LLMProvider` ABC (with `chat_stream()` async generator), `LLMResponse` dataclass, `ProviderUnavailable`
- `llm/events.py` — Streaming event types: `TextDelta`, `ToolStart`, `ToolResult`, `StatusUpdate`, `AgentDone`, `AgentError`
- `llm/providers/ollama.py` — `OllamaProvider`, non-streaming `chat()` + true token-by-token `chat_stream()` via Ollama streaming API
- `llm/providers/anthropic.py` — `AnthropicProvider`, non-streaming `chat()` + `chat_stream()` via `client.messages.stream()`
- `llm/router.py` — `get_coordinator_provider()` (Anthropic or Ollama), `get_specialist_provider()` (always Ollama), `get_fallback_provider()`, active model state
- `llm/agent.py` — coordinator/specialist agent loop: `run_agent()`, `resume_agent()`, `_run_specialist()`, `_resume_coordinator()`. Supports `event_queue` for streaming and `cancel_event` for per-session cancellation.
- `llm/skills.py` — skill discovery from SKILL.md files: `discover_skills()`, `load_skill_metadata()`, `SkillDef` dataclass. Cached after first call (`invalidate_skill_cache()` to re-read). Load-time gating via `requires_bins`/`requires_env` in SKILL.md metadata.
- `llm/specialists.py` — backward-compat shim wrapping skills as `SpecialistDef`/`SPECIALISTS`
- `llm/config.py` — `AstrynSettings` via pydantic-settings (Ollama, Anthropic, budget, skills dir)
- `tools/registry.py` — `REGISTRY`, `WRITER_TOOLS`, `REVIEWER_TOOLS`, `NO_PROJECT_TOOLS`, `COORDINATOR_TOOLS`, `READ_ONLY_TOOLS`
- `tools/models.py` — Pydantic models for all tools including `Delegate`, `CreateBranch`, `CommitChanges`
- `tools/executor.py` — tool execution functions
- `tools/safety.py` — path validation (scoped to `~/repos`), shell command whitelist
- `prompts/coordinator.md` — coordinator system prompt template with `{preferences_block}`, `{available_skills_block}`, and `{session_state_block}`
- `prompts/specialists/*/SKILL.md` — skill definitions (2 built-in: code-writer, code-reviewer)
- `services/session.py` — `build_coordinator_prompt()`, session management
- `services/preferences.py` — `validate_preference()`, `format_preferences_block()`
- `services/budget.py` — `estimate_cost()`, `can_use_anthropic()`, `record_usage()` for Anthropic API budget tracking
- `store/domain.py` — `SessionState`, `CommunicationPreferences`, `pending_confirmations`, `cancel_events`, `cleanup_expired_confirmations()` (10-min TTL)
- `db/` — Postgres via asyncpg: sessions, session state, communication preferences, tool audit, API usage

### astryn-telegram
- `bot.py` — entry point; registers handlers including confirmation, model, project, and preferences callbacks
- `core_client.py` — async HTTP client for astryn-core (persistent connection pool). `stream_message()` SSE consumer.
- `formatting.py` — Markdown-to-Telegram-HTML converter
- `handlers/message.py` — handles text messages; edit-in-place streaming (500ms throttle, 4000-char overflow handling); per-user busy flag + message queue; renders confirmation inline keyboards with `parse_mode="HTML"`
- `handlers/commands.py` — `/help`, `/clear`, `/status`, `/model`, `/projects`, `/preferences`
- `handlers/callbacks.py` — inline keyboard handlers for confirmations, model select, project select, preferences

### Key Design Decisions
- **Coordinator/Specialist architecture**: coordinator agent handles conversation (1 LLM call for simple chat), delegates technical work to specialist skills via `delegate` tool
- **Multi-provider routing**: coordinator can use Anthropic (cloud) or Ollama (local), configured via `ASTRYN_COORDINATOR_PROVIDER`. Specialists always use Ollama. Automatic fallback to Ollama if Anthropic is unavailable or budget exhausted.
- **Skills system**: skills defined in `prompts/specialists/*/SKILL.md` using AgentSkills format. User skills in `~/.astryn/skills/` override built-ins. 2 built-in skills:
  - `code-writer` (writer tools: read/write/run/create-branch — cannot commit)
  - `code-reviewer` (reviewer tools: read/run/commit — cannot write files)
- **Writer/Reviewer gate**: code-writer creates and tests code, code-reviewer reviews and commits. Enforces a review step before commits.
- **Purpose-built git tools**: `create_branch` (writer) and `commit_changes` (reviewer) replace git commands in `run_command`. `git add`/`git commit` via `run_command` are blocked.
- **Tool sets**: `WRITER_TOOLS` (read + write + run + create_branch), `REVIEWER_TOOLS` (read + run + commit_changes), `READ_ONLY_TOOLS` (browse only, fallback for user skills), `COORDINATOR_TOOLS` (delegate + list_projects + set_project + read_file), `NO_PROJECT_TOOLS` (list/set project)
- **Budget tracking**: daily and monthly USD limits for Anthropic API usage, tracked in `api_usage` table
- Specialist messages are ephemeral — not persisted to DB. Coordinator history captures the full flow.
- Confirmation nesting: specialist pauses → coordinator state saved on `PendingConfirmation` → resume resumes specialist then coordinator
- Communication preferences: user-configurable (verbosity, tone, code_explanation, proactive_suggestions) persisted in DB, injected into coordinator prompt
- All file/shell operations are scoped to `~/repos` — enforced in `tools/safety.py`
- Write/exec tool calls require Telegram inline keyboard confirmation before executing
- Adding a new skill: create `prompts/specialists/<name>/SKILL.md` with YAML frontmatter (name, description, metadata.tools). Discovered automatically.
- Adding a new LLM provider: implement `LLMProvider` in `llm/providers/`, add routing logic in `router.py`

### Auth Patterns (MUST follow for new code)

#### astryn-core
- ALL new routes MUST include `dependencies=[Depends(verify_api_key)]` — the only exception is `GET /health`
- `verify_api_key` uses `hmac.compare_digest()` for constant-time comparison — NEVER use `==`/`!=` for secret comparison
- Validate input lengths on all string fields in request schemas using `Field(max_length=...)`
- NEVER expose raw exception messages in HTTP responses — log internally, return generic messages to clients

#### astryn-telegram
- ALL new command handlers MUST be registered with `filters=auth_filter` in `bot.py` (framework-level `filters.User` gating)
- ALL new callback handlers MUST check `update.effective_user.id != config.ALLOWED_USER_ID` at the top (CallbackQueryHandler does not support filters)
- NEVER add a handler without auth — the bot is single-user and must reject all other users

## Branching Rules

- Before starting any work, check the current branch with `git branch --show-current`.
- If the work is unrelated to the current branch's scope (different feature, fix, or phase), stop and propose a new branch name before touching any files.
- Never commit work for two different concerns on the same branch — keep branches focused.
- Branch naming convention: `feat/<name>`, `fix/<name>`, `refactor/<name>`, `docs/<name>`.

**Creating a new branch — always follow these steps in order:**
1. `git fetch origin` — update remote refs
2. `git pull origin main` — bring main up to date
3. `git checkout -b <branch-name> --no-track origin/main` — branch from origin/main without tracking it (avoids pushing to main by accident)

## Development Workflow (TDD with Agents)

The project follows a test-driven workflow. These roles exist as both Claude Code agents (`.claude/agents/`) for development and as astryn-core skills (`prompts/specialists/*/SKILL.md`) so astryn itself can perform them:

1. **code-writer** — Writes tests first (TDD), then implements the code to make them pass. Handles exploration, planning, and all file changes.
2. **code-reviewer** — Runs AFTER implementation. Reviews for correctness, design, and security. Runs tests and commits approved changes.

## Linting & Formatting

Uses **ruff** for both linting and formatting. Config is in `pyproject.toml`. Zero warnings/errors policy — no suppressing warnings without fixing the root cause.

```bash
make lint               # run ruff linter
make format             # auto-format with ruff
make check              # lint + format check + tests (what pre-commit runs)
```

## Testing

**Always run tests before committing.** A Claude Code pre-commit hook runs lint, format check, and tests automatically.

```bash
# From repo root (via Makefile):
make test               # unit + API tests (fast, no Docker needed)
make test-all           # all tests including integration
make test-integration   # integration tests only (Docker must be running)

# From astryn-core/ directly:
pytest                        # all tests
pytest tests/api/             # API tests only
pytest tests/unit/            # unit tests only
pytest -m "not integration"   # skip tests needing real infra
pytest -m integration         # only integration tests
```

**Test categories:**
- `tests/unit/` — pure logic tests (safety, schemas, executor, agent, router). No DB/HTTP needed.
- `tests/api/` — FastAPI endpoint contracts via `httpx.AsyncClient`. DB and LLM are mocked.
- `tests/integration/` — real Postgres via testcontainers. Docker must be running.

## Project Context

Check `tmp/docs/` for project definition, vision, and planning documents (gitignored, not committed).

## Environment Variables

**astryn-core** (`.env`):
```
OLLAMA_BASE_URL=http://localhost:11434
ASTRYN_DEFAULT_MODEL=qwen3:30b-a3b
ASTRYN_API_KEY=<key>
MAX_HISTORY_TURNS=20
DATABASE_URL=postgresql+asyncpg://user:pass@localhost:5432/astryn

# Multi-provider (optional — omit for Ollama-only mode)
ANTHROPIC_API_KEY=<key>
ASTRYN_COORDINATOR_PROVIDER=ollama       # "anthropic" or "ollama"
ASTRYN_COORDINATOR_MODEL=claude-sonnet-4-6
ASTRYN_SPECIALIST_MODEL=qwen3:30b-a3b

# Budget (Anthropic only)
ASTRYN_ANTHROPIC_DAILY_BUDGET_USD=5.00
ASTRYN_ANTHROPIC_MONTHLY_BUDGET_USD=50.00

# User skills directory (optional)
ASTRYN_SKILLS_DIR=~/.astryn/skills
```

**astryn-telegram** (`.env`):
```
TELEGRAM_BOT_TOKEN=<token>
ASTRYN_CORE_URL=http://localhost:8000
ASTRYN_CORE_API_KEY=<key>
ALLOWED_USER_ID=<telegram_user_id>
```
