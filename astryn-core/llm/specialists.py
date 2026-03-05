"""Backward-compatibility shim — wraps skill-based definitions as SpecialistDef.

Prefer using ``llm.skills.discover_skills()`` directly for new code.
This module exists so that existing tests and any code referencing SPECIALISTS
continues to work during the transition.
"""

from dataclasses import dataclass

from llm.skills import discover_skills


@dataclass(frozen=True)
class SpecialistDef:
    """Definition of a specialist agent type."""

    name: str
    system_prompt: str
    tools: list[dict]


def _build_specialists() -> dict[str, SpecialistDef]:
    skills = discover_skills()
    return {
        name: SpecialistDef(
            name=skill.name,
            system_prompt=skill.system_prompt,
            tools=skill.tools,
        )
        for name, skill in skills.items()
    }


SPECIALISTS = _build_specialists()
