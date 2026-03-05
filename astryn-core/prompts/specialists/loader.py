"""Load specialist prompts from SKILL.md files.

Provides backward-compatible exports (CODE_PROMPT, EXPLORE_PROMPT, PLAN_PROMPT)
by reading the body from the SKILL.md files in each skill subdirectory.
"""

from llm.skills import discover_skills

_skills = discover_skills()

CODE_PROMPT = _skills["code"].system_prompt if "code" in _skills else ""
EXPLORE_PROMPT = _skills["explore"].system_prompt if "explore" in _skills else ""
PLAN_PROMPT = _skills["plan"].system_prompt if "plan" in _skills else ""
