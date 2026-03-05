"""Skill loader — discover and parse SKILL.md files for specialist definitions.

Skills follow the AgentSkills format (https://agentskills.io) with Astryn
extensions in the ``metadata`` block:

    ---
    name: code
    description: >
      Read, write, and modify files...
    metadata:
      tools: full          # "full" | "read-write" | "read-only"
      model: ""            # optional preferred Ollama model
    ---

    You are a code specialist agent...

Built-in skills ship in ``prompts/specialists/*/SKILL.md``.
User skills live in ``~/.astryn/skills/*/SKILL.md`` and override built-ins.
"""

import logging
import re
from dataclasses import dataclass
from pathlib import Path

from tools.registry import READ_ONLY_TOOLS, READ_WRITE_TOOLS, TOOLS

logger = logging.getLogger(__name__)

_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)

# Built-in skill directory (shipped with code)
_BUILTIN_SKILLS_DIR = Path(__file__).parent.parent / "prompts" / "specialists"


@dataclass(frozen=True)
class SkillDef:
    """A specialist skill loaded from a SKILL.md file."""

    name: str
    description: str
    system_prompt: str
    tools: list[dict]
    preferred_model: str | None = None


def discover_skills(skill_dirs: list[Path] | None = None) -> dict[str, SkillDef]:
    """Scan directories for SKILL.md files, parse metadata.

    Directories are processed in order — later entries override earlier ones
    (user skills override built-in skills with the same name).

    Args:
        skill_dirs: Additional directories to scan after the built-in directory.
    """
    dirs = [_BUILTIN_SKILLS_DIR]
    if skill_dirs:
        dirs.extend(skill_dirs)

    skills: dict[str, SkillDef] = {}
    for directory in dirs:
        directory = Path(directory).expanduser()
        if not directory.is_dir():
            continue
        for skill_file in sorted(directory.glob("*/SKILL.md")):
            skill = _parse_skill_file(skill_file)
            if skill is not None:
                skills[skill.name] = skill
    return skills


def load_skill_metadata(skill_dirs: list[Path] | None = None) -> list[dict]:
    """Load only name + description for prompt injection (progressive disclosure).

    Returns a list of dicts with ``name`` and ``description`` keys.
    """
    skills = discover_skills(skill_dirs)
    return [{"name": skill.name, "description": skill.description} for skill in skills.values()]


def format_available_skills_block(skills_metadata: list[dict]) -> str:
    """Format <available_skills> XML for the coordinator prompt."""
    if not skills_metadata:
        return "<available_skills>\nNo skills available.\n</available_skills>"

    lines = ["<available_skills>"]
    for skill in skills_metadata:
        lines.append(f"- **{skill['name']}** — {skill['description'].strip()}")
    lines.append("</available_skills>")
    return "\n".join(lines)


def _parse_skill_file(path: Path) -> SkillDef | None:
    """Parse a single SKILL.md file into a SkillDef."""
    try:
        content = path.read_text()
    except OSError:
        logger.warning("Could not read skill file: %s", path)
        return None

    match = _FRONTMATTER_RE.match(content)
    if not match:
        logger.warning("No YAML frontmatter found in %s", path)
        return None

    frontmatter_text = match.group(1)
    body = content[match.end() :].strip()

    meta = _parse_simple_yaml(frontmatter_text)
    name = meta.get("name")
    description = meta.get("description", "")

    if not name:
        logger.warning("Skill file missing 'name' in frontmatter: %s", path)
        return None

    # Parse metadata block
    metadata = meta.get("metadata", {})
    tools_key = metadata.get("tools", "read-only") if isinstance(metadata, dict) else "read-only"
    preferred_model = metadata.get("model", "") if isinstance(metadata, dict) else ""

    tools = _resolve_tools(tools_key)

    return SkillDef(
        name=name,
        description=description,
        system_prompt=body,
        tools=tools,
        preferred_model=preferred_model or None,
    )


def _resolve_tools(tools_key: str) -> list[dict]:
    """Map a tools key to a predefined tool set."""
    match tools_key:
        case "full":
            return TOOLS
        case "read-write":
            return READ_WRITE_TOOLS
        case "read-only" | _:
            return READ_ONLY_TOOLS


def _parse_simple_yaml(text: str) -> dict:
    """Minimal YAML parser for SKILL.md frontmatter.

    Handles the subset of YAML used in skill files: top-level keys with
    string values, multi-line strings (``>``), and a single level of nested
    keys (``metadata:`` block).

    Not a full YAML parser — intentionally avoids a PyYAML dependency.
    """
    result: dict = {}
    current_key = None
    current_value_lines: list[str] = []
    in_block_scalar = False
    in_nested = False
    nested_key = ""
    nested_dict: dict = {}

    def _flush():
        nonlocal current_key, current_value_lines, in_block_scalar
        nonlocal in_nested, nested_key, nested_dict
        if in_nested and nested_key:
            result[nested_key] = nested_dict
            nested_key = ""
            nested_dict = {}
            in_nested = False
        if current_key:
            val = " ".join(line.strip() for line in current_value_lines if line.strip())
            result[current_key] = val
            current_key = None
            current_value_lines = []
            in_block_scalar = False

    for line in text.split("\n"):
        stripped = line.strip()

        # Continuation of block scalar or multiline value
        if in_block_scalar and (line.startswith("  ") or not stripped):
            current_value_lines.append(stripped)
            continue

        # Nested key (indented under a top-level key like metadata:)
        if in_nested and line.startswith("  ") and ":" in stripped:
            k, _, v = stripped.partition(":")
            nested_dict[k.strip()] = v.strip()
            continue

        # If we were collecting something, flush it
        if in_nested and not line.startswith("  "):
            result[nested_key] = nested_dict
            nested_key = ""
            nested_dict = {}
            in_nested = False
        if in_block_scalar and not line.startswith("  "):
            _flush()

        # Top-level key
        if ":" in stripped and not stripped.startswith("-"):
            _flush()
            key, _, value = stripped.partition(":")
            key = key.strip()
            value = value.strip()

            if value == ">" or value == "|":
                current_key = key
                current_value_lines = []
                in_block_scalar = True
            elif value == "":
                # Nested block (like metadata:)
                nested_key = key
                nested_dict = {}
                in_nested = True
            else:
                result[key] = value

    _flush()
    return result
