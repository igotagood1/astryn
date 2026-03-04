"""Load coordinator prompt template at import time."""

from pathlib import Path

COORDINATOR_PROMPT_TEMPLATE = (Path(__file__).parent / "coordinator.md").read_text()
