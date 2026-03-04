"""Load specialist prompts at import time."""

from pathlib import Path

_DIR = Path(__file__).parent

CODE_PROMPT = (_DIR / "code.md").read_text()
EXPLORE_PROMPT = (_DIR / "explore.md").read_text()
PLAN_PROMPT = (_DIR / "plan.md").read_text()
