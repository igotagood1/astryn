# Default model to pull if not already downloaded
MODEL ?= qwen2.5-coder:7b

.PHONY: start start-detached dev stop logs build restart-telegram _ensure-ollama _ensure-model

## start: Ensure Ollama is running, pull model if needed, start services (foreground)
start: _ensure-model
	docker compose up

## start-detached: Same as start but runs services in the background
start-detached: _ensure-model
	docker compose up -d

## dev: Start with hot reload — core restarts on file changes, edit telegram then `make restart-telegram`
dev: _ensure-model
	docker compose -f docker-compose.yml -f docker-compose.dev.yml up

## restart-telegram: Restart the telegram bot container to pick up code changes (dev only)
restart-telegram:
	docker compose restart astryn-telegram

## stop: Stop all running services
stop:
	docker compose down

## logs: Follow logs from all services
logs:
	docker compose logs -f

## build: Rebuild service images from scratch (use after dependency changes)
build:
	docker compose build --no-cache

# ── Internal targets ──────────────────────────────────────────────────────────

_ensure-ollama:
	@if ! curl -sf http://localhost:11434/api/tags > /dev/null; then \
		echo ""; \
		echo "  Ollama is not running."; \
		echo "  Start it with: ollama serve"; \
		echo "  Or download it at: https://ollama.com"; \
		echo ""; \
		exit 1; \
	fi

_ensure-model: _ensure-ollama
	@if ollama list | grep -q "$(MODEL)"; then \
		echo "Model '$(MODEL)' is ready."; \
	else \
		echo "Pulling '$(MODEL)'..."; \
		ollama pull "$(MODEL)"; \
	fi
