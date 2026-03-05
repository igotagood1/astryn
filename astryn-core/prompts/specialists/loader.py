"""Load specialist prompts from SKILL.md files.

Provides backward-compatible exports by reading the body from the SKILL.md
files in each skill subdirectory.
"""

from llm.skills import discover_skills

_skills = discover_skills()

CODE_WRITER_PROMPT = _skills["code-writer"].system_prompt if "code-writer" in _skills else ""
CODE_REVIEWER_PROMPT = _skills["code-reviewer"].system_prompt if "code-reviewer" in _skills else ""
