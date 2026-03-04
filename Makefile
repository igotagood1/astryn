# Default model to pull if not already downloaded
MODEL ?= qwen2.5-coder:7b

.PHONY: start start-detached dev stop logs build restart-telegram lint format check test test-all test-integration _ensure-ollama _ensure-model

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

## lint: Run ruff linter on both services
lint:
	cd astryn-core && .venv/bin/ruff check ../astryn-core/ ../astryn-telegram/

## format: Auto-format both services with ruff
format:
	cd astryn-core && .venv/bin/ruff format ../astryn-core/ ../astryn-telegram/

## check: Lint + format check + tests (what the pre-commit hook runs)
check: lint
	cd astryn-core && .venv/bin/ruff format --check ../astryn-core/ ../astryn-telegram/
	cd astryn-core && .venv/bin/python -m pytest -m "not integration" -q -W error

## test: Run unit + API tests (no Docker/infra required)
test:
	cd astryn-core && .venv/bin/python -m pytest -m "not integration" -q

## test-all: Run all tests including integration (Docker must be running)
test-all:
	cd astryn-core && .venv/bin/python -m pytest -q

## test-integration: Run only integration tests (Docker must be running)
test-integration:
	cd astryn-core && .venv/bin/python -m pytest -m integration -q

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
