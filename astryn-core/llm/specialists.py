"""Specialist agent definitions — registry of available specialists and their config."""

from dataclasses import dataclass

from prompts.specialists.loader import CODE_PROMPT, EXPLORE_PROMPT, PLAN_PROMPT
from tools.registry import READ_ONLY_TOOLS, TOOLS


@dataclass(frozen=True)
class SpecialistDef:
    """Definition of a specialist agent type.

    Attributes:
        name: Unique identifier (matches the delegate tool's specialist field).
        system_prompt: Base system prompt for this specialist.
        tools: Tool schemas available to this specialist.
    """

    name: str
    system_prompt: str
    tools: list[dict]


SPECIALISTS: dict[str, SpecialistDef] = {
    "code": SpecialistDef(
        name="code",
        system_prompt=CODE_PROMPT,
        tools=TOOLS,
    ),
    "explore": SpecialistDef(
        name="explore",
        system_prompt=EXPLORE_PROMPT,
        tools=READ_ONLY_TOOLS,
    ),
    "plan": SpecialistDef(
        name="plan",
        system_prompt=PLAN_PROMPT,
        tools=READ_ONLY_TOOLS,
    ),
}
