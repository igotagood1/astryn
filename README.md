# Astryn

> A local-first personal AI assistant. Send a message from Telegram, get a reply from a local LLM running on your Mac.

**Current state: Phase 1** — Telegram bot backed by Ollama running locally. No cloud, no tunnel, no external dependencies beyond Telegram's servers.

---

## What It Does

- Send a message from Telegram on your phone
- Bot polls Telegram for new messages every second
- Forwards your message to a local FastAPI server
- FastAPI calls Ollama running on your Mac
- Response comes back to your phone in seconds
- Multi-turn conversation — it remembers context within a session
- `/clear` resets the conversation

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
        │  POST /chat
        ▼
astryn-core  (port 8000, FastAPI)
        │  HTTP
        ▼
Ollama  (port 11434, runs locally)
        │
        ▼
qwen2.5-coder:7b  (4.5GB, runs on-device)
```

---

## Repo Structure

```
astryn/
├── astryn-core/                 # FastAPI backend
│   ├── api/
│   │   ├── main.py              # App entry point
│   │   └── routes/
│   │       ├── chat.py          # POST /chat, DELETE /chat/{id}
│   │       └── health.py        # GET /health
│   ├── llm/
│   │   ├── base.py              # Abstract LLMProvider
│   │   ├── config.py            # Settings from .env
│   │   ├── router.py            # Provider selection + fallback
│   │   └── providers/
│   │       └── ollama.py        # Ollama implementation
│   ├── .env.example
│   └── requirements.txt
│
├── astryn-telegram/             # Telegram bot
│   ├── bot.py                   # Entry point, polling loop
│   ├── core_client.py           # HTTP client for astryn-core
│   ├── handlers/
│   │   ├── message.py           # Handles text messages
│   │   └── commands.py          # /help /clear /status /model
│   ├── .env.example
│   └── requirements.txt
│
├── .vscode/
│   └── extensions.json          # Recommended VS Code extensions
├── .gitignore
└── README.md
```

---

## Prerequisites

- macOS (M-series Mac recommended)
- [Homebrew](https://brew.sh)
- Python 3.12+
- [uv](https://docs.astral.sh/uv/) (Python package manager)
- [Ollama](https://ollama.com) with `qwen2.5-coder:7b` pulled
- A Telegram account and bot token from [@BotFather](https://t.me/botfather)

---

## Setup

### 1. Install dependencies

```bash
# Install Homebrew (if not already installed)
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

# Install Python and uv
brew install python
curl -LsSf https://astral.sh/uv/install.sh | sh
source ~/.zshrc

# Install and start Ollama
brew install ollama
ollama serve  # or open the Ollama app
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
# Edit .env — set ASTRYN_API_KEY to a random string
deactivate
cd ..
```

### 4. Set up astryn-telegram

```bash
cd astryn-telegram
uv venv && source .venv/bin/activate
uv pip install -r requirements.txt
cp .env.example .env
# Edit .env — add TELEGRAM_BOT_TOKEN, ALLOWED_USER_ID, and ASTRYN_CORE_API_KEY
deactivate
cd ..
```

### 5. Get your Telegram credentials

- **Bot token**: Message [@BotFather](https://t.me/botfather) → `/newbot` → copy the token
- **Your user ID**: Message [@userinfobot](https://t.me/userinfobot) → it replies with your ID

---

## Running

Three terminals, all from the `astryn/` root:

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
# Health check
curl http://localhost:8000/health
# Expected: {"status":"ok","ollama":"up","model":"qwen2.5-coder:7b"}
```

Then open Telegram, find your bot, and send `/status`.

---

## Telegram Commands

| Command | What it does |
|---------|-------------|
| `/help` | Show available commands |
| `/status` | Check if Ollama is running |
| `/model` | Show the current model |
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

> **Note:** `ASTRYN_API_KEY` in astryn-core and `ASTRYN_CORE_API_KEY` in astryn-telegram must match.

---

## Phase Roadmap

| Phase | Status | Description |
|-------|--------|-------------|
| **1** | ✅ Current | Telegram bot + local Ollama, polling mode |
| **2** | Planned | SQLite persistence, Cloudflare Tunnel, webhooks, Anthropic fallback |
| **3** | Planned | MCP servers — memory, Obsidian, calendar, GitHub |
| **4** | Planned | Native Android app |

---

## Troubleshooting

**Bot doesn't respond**
- Check Terminal 3 (astryn-telegram) for errors
- Verify `ALLOWED_USER_ID` matches your actual Telegram ID
- Confirm `ASTRYN_CORE_API_KEY` matches in both `.env` files

**`{"detail":"Ollama is not available"}`**
- Run `ollama serve` or check the Ollama menu bar icon
- Verify with `curl http://localhost:11434/api/tags`

**`ModuleNotFoundError`**
- You forgot to activate the venv: `source .venv/bin/activate`

**Port 8000 already in use**
- `lsof -i :8000` to find the process, then `kill -9 <PID>`
