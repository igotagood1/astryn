# Astryn

> A local-first personal AI assistant. Send a message from Telegram, get a reply from a local LLM running on your Mac — with tool use, file editing, and shell access.

**Current state: Phase 2** — Agentic tool use. Astryn can read and write files, run whitelisted shell commands, and switch between locally installed Ollama models. Write operations pause and ask for your approval via Telegram inline buttons before executing.

---

## What It Does

- Send a message from Telegram on your phone
- Bot polls Telegram for new messages every second
- Forwards your message to a local FastAPI server
- FastAPI runs an agentic loop — the LLM can call tools, read files, run commands
- Write/exec operations (file writes, `git commit`, etc.) pause and send you an **Approve / Reject** inline keyboard
- Read-only operations (file reads, `git status`, `pytest`) run immediately without asking
- Response comes back to your phone
- Multi-turn conversation — session history is kept in memory until you `/clear`

---

## Architecture

```
Your Phone (Telegram)
        │
        ▼
Telegram Servers  (free, Telegram's infrastructure)
        │  long-polling
        ▼
astryn-telegram  (port: none, polls outbound)
        │  POST /chat  /  POST /confirm/{id}
        ▼
astryn-core  (port 8000, FastAPI)
        │  HTTP
        ▼
Ollama  (port 11434, runs locally)
        │
        ▼
qwen2.5-coder:7b  (or whichever model is active)
```

---

## Repo Structure

```
astryn/
├── astryn-core/                 # FastAPI backend
│   ├── api/
│   │   ├── main.py              # App entry point
│   │   ├── state.py             # In-memory sessions + pending confirmations
│   │   └── routes/
│   │       ├── chat.py          # POST /chat, DELETE /chat/{id}
│   │       ├── tools.py         # POST /confirm/{id}
│   │       ├── models.py        # GET /models, POST /models/active
│   │       └── health.py        # GET /health
│   ├── llm/
│   │   ├── agent.py             # Agentic loop, pause/resume on confirmation
│   │   ├── base.py              # Abstract LLMProvider + LLMResponse
│   │   ├── config.py            # Settings from .env
│   │   ├── router.py            # Provider selection + active model state
│   │   └── providers/
│   │       └── ollama.py        # Ollama implementation (with tool call support)
│   ├── tools/
│   │   ├── definitions.py       # Tool JSON schemas passed to the LLM
│   │   ├── executor.py          # Tool dispatch, confirmation check, preview text
│   │   └── safety.py            # Path validation (~/repos only), command whitelist
│   ├── prompts/
│   │   └── system.md            # System prompt
│   ├── .env.example
│   └── requirements.txt
│
├── astryn-telegram/             # Telegram bot
│   ├── bot.py                   # Entry point, polling loop
│   ├── core_client.py           # HTTP client for astryn-core
│   ├── handlers/
│   │   ├── message.py           # Handles text messages + renders confirmation keyboard
│   │   ├── callbacks.py         # Handles Approve/Reject button taps
│   │   └── commands.py          # /help /clear /status /model
│   ├── .env.example
│   └── requirements.txt
│
├── tmp/docs/                    # Planning docs (gitignored)
├── .gitignore
└── README.md
```

---

## Prerequisites

- macOS (M-series Mac recommended)
- [Homebrew](https://brew.sh)
- Python 3.12+
- [uv](https://docs.astral.sh/uv/) (Python package manager)
- [Ollama](https://ollama.com) with at least one model pulled
- A Telegram account and bot token from [@BotFather](https://t.me/botfather)

---

## Setup

### 1. Install dependencies

```bash
# Homebrew
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

# Python + uv
brew install python
curl -LsSf https://astral.sh/uv/install.sh | sh
source ~/.zshrc

# Ollama
brew install ollama
ollama serve
ollama pull qwen2.5-coder:7b
```

### 2. Clone the repo

```bash
git clone git@github.com:yourusername/astryn.git
cd astryn
```

### 3. Set up astryn-core

```bash
cd astryn-core
uv venv && source .venv/bin/activate
uv pip install -r requirements.txt
cp .env.example .env
# Edit .env — set ASTRYN_API_KEY to any secret string
deactivate && cd ..
```

### 4. Set up astryn-telegram

```bash
cd astryn-telegram
uv venv && source .venv/bin/activate
uv pip install -r requirements.txt
cp .env.example .env
# Edit .env — add your bot token, user ID, and the same API key
deactivate && cd ..
```

### 5. Get your Telegram credentials

- **Bot token**: Message [@BotFather](https://t.me/botfather) → `/newbot` → copy the token
- **Your user ID**: Message [@userinfobot](https://t.me/userinfobot) → it replies with your numeric ID

---

## Running

Three terminals, all from `astryn/`:

```bash
# Terminal 1 — Ollama (skip if already running in menu bar)
ollama serve

# Terminal 2 — astryn-core
cd astryn-core && source .venv/bin/activate
uvicorn api.main:app --reload --port 8000

# Terminal 3 — astryn-telegram
cd astryn-telegram && source .venv/bin/activate
python bot.py
```

### Verify it's working

```bash
curl http://localhost:8000/health
# {"status":"ok","ollama":"up","model":"ollama/qwen2.5-coder:7b"}
```

Then open Telegram, find your bot, and send `/status`.

---

## Telegram Commands

| Command | What it does |
|---------|-------------|
| `/help` | Show available commands |
| `/status` | Check Ollama status + active model |
| `/model` | Show the current model |
| `/model list` | List all locally installed models |
| `/model use <name>` | Switch to a different model |
| `/clear` | Reset conversation history |

---

## Environment Variables

### astryn-core/.env

```env
OLLAMA_BASE_URL=http://localhost:11434
ASTRYN_DEFAULT_MODEL=qwen2.5-coder:7b
ASTRYN_API_KEY=your-secret-key-here
MAX_HISTORY_TURNS=20
```

### astryn-telegram/.env

```env
TELEGRAM_BOT_TOKEN=your-bot-token-here
ALLOWED_USER_ID=your-telegram-user-id
ASTRYN_CORE_URL=http://localhost:8000
ASTRYN_CORE_API_KEY=your-secret-key-here
```

> `ASTRYN_API_KEY` in astryn-core and `ASTRYN_CORE_API_KEY` in astryn-telegram must match.

---

## Phase Roadmap

| Phase | Status | Description |
|-------|--------|-------------|
| **1** | ✅ Done | Telegram bot + local Ollama, polling mode, multi-turn conversation |
| **2** | ✅ Done | Agentic tool use — file r/w, shell commands, project scoping, model switching, inline confirmation |
| **3** | Planned | SQLite persistence, launchd services, Anthropic fallback |
| **4** | Planned | Cloudflare Tunnel, webhooks, GitHub integration |
| **5+** | Future | MCP servers, persistent memory, Android app |

---

## Troubleshooting

**Bot doesn't respond**
- Check Terminal 3 for errors
- Verify `ALLOWED_USER_ID` is your numeric Telegram ID (not a username)
- Confirm `ASTRYN_CORE_API_KEY` matches `ASTRYN_API_KEY`

**`503 Ollama is not available`**
- Run `ollama serve` or check the Ollama menu bar icon
- Test: `curl http://localhost:11434/api/tags`

**`404 Confirmation not found or already resolved`**
- The confirmation expired (session was cleared) or the button was clicked twice

**`ModuleNotFoundError`**
- Activate the venv first: `source .venv/bin/activate`
- Make sure you're in the right directory

**Port 8000 already in use**
- `lsof -i :8000` to find the PID, then `kill <PID>`
