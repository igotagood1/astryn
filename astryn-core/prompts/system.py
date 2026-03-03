from pathlib import Path

SYSTEM_PROMPT = (Path(__file__).parent / "system.md").read_text()
