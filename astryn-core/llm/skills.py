"""Skill loader — discover and parse SKILL.md files for specialist definitions.

Skills follow the AgentSkills format (https://agentskills.io) with Astryn
extensions in the ``metadata`` block:

    ---
    name: code
    description: >
      Read, write, and modify files...
    metadata:
      tools: writer        # "writer" | "reviewer" | "read-only"
      model: ""            # optional preferred Ollama model
      requires_bins: git   # optional space-separated binary requirements
      requires_env: TOKEN  # optional space-separated env var requirements
    ---

    You are a code specialist agent...

Built-in skills ship in ``prompts/specialists/*/SKILL.md``.
User skills live in ``~/.astryn/skills/*/SKILL.md`` and override built-ins.
"""

import logging
import os
import re
import shutil
from dataclasses import dataclass
from pathlib import Path

from tools.registry import READ_ONLY_TOOLS, REVIEWER_TOOLS, WRITER_TOOLS

logger = logging.getLogger(__name__)

_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)

# Built-in skill directory (shipped with code)
_BUILTIN_SKILLS_DIR = Path(__file__).parent.parent / "prompts" / "specialists"

# Cached skills — populated on first access, cleared on invalidation
_skill_cache: dict[str, "SkillDef"] | None = None


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

    Results are cached after the first call. Use ``invalidate_skill_cache()``
    to force a re-read (e.g. on SIGHUP or skill file change).

    Directories are processed in order — later entries override earlier ones
    (user skills override built-in skills with the same name).

    Args:
        skill_dirs: Additional directories to scan after the built-in directory.
    """
    global _skill_cache
    if _skill_cache is not None:
        return _skill_cache

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

    _skill_cache = skills
    return skills


def invalidate_skill_cache() -> None:
    """Clear the cached skills so the next discover_skills() re-reads from disk."""
    global _skill_cache
    _skill_cache = None


def load_skill_metadata(skill_dirs: list[Path] | None = None) -> list[dict]:
    """Load only name + description for prompt injection (progressive disclosure).

    Returns a slim list — only name and one-line description per skill.
    Full SKILL.md body is loaded on delegation, not in the coordinator prompt.
    """
    skills = discover_skills(skill_dirs)
    return [{"name": skill.name, "description": skill.description} for skill in skills.values()]


def format_available_skills_block(skills_metadata: list[dict]) -> str:
    """Format <available_skills> XML for the coordinator prompt.

    Only includes name + description (progressive disclosure tier 1).
    """
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

    # Load-time gating: check requirements
    if isinstance(metadata, dict) and not _check_requirements(metadata, path):
        return None

    tools = _resolve_tools(tools_key)

    return SkillDef(
        name=name,
        description=description,
        system_prompt=body,
        tools=tools,
        preferred_model=preferred_model or None,
    )


def _check_requirements(metadata: dict, path: Path) -> bool:
    """Check if a skill's requirements are met. Returns False to skip the skill."""
    # Check required binaries
    requires_bins = metadata.get("requires_bins", "")
    if requires_bins:
        for binary in requires_bins.split():
            if not shutil.which(binary):
                logger.info("Skill %s skipped: missing binary '%s'", path.parent.name, binary)
                return False

    # Check required environment variables
    requires_env = metadata.get("requires_env", "")
    if requires_env:
        for var in requires_env.split():
            if not os.environ.get(var):
                logger.info("Skill %s skipped: missing env var '%s'", path.parent.name, var)
                return False

    return True


def _resolve_tools(tools_key: str) -> list[dict]:
    """Map a tools key to a predefined tool set."""
    match tools_key:
        case "writer":
            return WRITER_TOOLS
        case "reviewer":
            return REVIEWER_TOOLS
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
