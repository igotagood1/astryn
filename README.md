# Astryn

A personal AI assistant you control from Telegram, running entirely on your own machine. Send a message from your phone, get a response from a local LLM — with the ability to read files, make edits, and run shell commands in your repos.

Built as a hands-on way to explore Python and the AI/LLM ecosystem — FastAPI, async patterns, tool use, provider abstractions, and how agentic loops actually work.

---

## How it works

- **astryn-core** — FastAPI backend that manages conversation sessions and runs the LLM
- **astryn-telegram** — Telegram bot that forwards your messages to core and sends back replies

Write operations (file edits, git commits) pause and ask for your approval via an inline Telegram keyboard. Read-only operations (file reads, git status, tests) execute immediately.

The two app services run in Docker. [Ollama](https://ollama.com) runs natively on your machine so it has full access to your GPU.

---

## Prerequisites

- [Docker](https://docs.docker.com/get-docker/) with Compose
- [Ollama](https://ollama.com) installed and running (`ollama serve`)
- `make` (pre-installed on macOS and Linux; Windows users see note below)
- A Telegram account

---

## Setup

### 1. Create a Telegram bot

1. Message [@BotFather](https://t.me/botfather) on Telegram
2. Send `/newbot` and follow the prompts — copy the **bot token** it gives you

Find your **Telegram user ID**:

1. Message [@userinfobot](https://t.me/userinfobot)
2. It replies with your numeric ID

### 2. Clone the repo

```bash
git clone git@github.com:yourusername/astryn.git
cd astryn
```

### 3. Configure astryn-core

```bash
cp astryn-core/.env.example astryn-core/.env
```

Edit `astryn-core/.env` — set `ASTRYN_API_KEY` to any secret string:

```env
ASTRYN_API_KEY=pick-any-secret-string
```

### 4. Configure astryn-telegram

```bash
cp astryn-telegram/.env.example astryn-telegram/.env
```

Edit `astryn-telegram/.env`:

```env
TELEGRAM_BOT_TOKEN=your-bot-token-from-botfather
ALLOWED_USER_ID=your-numeric-telegram-user-id
ASTRYN_CORE_API_KEY=same-secret-string-as-above
```

---

## Starting the app

Make sure Ollama is running first, then:

```bash
make start
```

This will:
1. Check that Ollama is reachable
2. Pull the default model (`qwen2.5-coder:7b`) if it isn't already downloaded
3. Start both services via Docker Compose

To run in the background instead:

```bash
make start-detached
```

Other useful commands:

```bash
make stop     # stop all services
make logs     # follow logs from all services
make build    # rebuild images after dependency changes
```

**Windows users:** `make` isn't available by default. Either use [WSL](https://learn.microsoft.com/en-us/windows/wsl/) or run the steps manually:

```bash
ollama pull qwen2.5-coder:7b
docker compose up
```

---

## Notes

**Your repos:** Astryn can read and edit files under `~/repos` on your machine. That directory is mounted into the container automatically. If your projects live somewhere else, update the volume in `docker-compose.yml`:

```yaml
volumes:
  - /your/path/to/projects:/root/repos
```

**Switching models:** Any Ollama model that supports tool use works. Pull one with `ollama pull <model>` and switch via `/model` in Telegram. `llama3.1:8b` is a solid general-purpose option.

---

## Commands

| Command | What it does |
|---------|-------------|
| `/help` | Show available commands |
| `/status` | Check Ollama status and active model |
| `/model` | Show current model and switch to another |
| `/clear` | Reset conversation history |

---

## Troubleshooting

**Bot doesn't respond**
- Make sure `ALLOWED_USER_ID` is your numeric ID, not a username
- Confirm `ASTRYN_CORE_API_KEY` matches `ASTRYN_API_KEY`

**`503 Ollama is not available`**
- Ollama must be running on the host before starting the containers
- Check it's up: `curl http://localhost:11434/api/tags`
- If not running: `ollama serve`

**`ModuleNotFoundError`**
- Rebuild the images: `make build`

---

## License

MIT — see [LICENSE](./LICENSE)
