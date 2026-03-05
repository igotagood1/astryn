from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from pydantic import BaseModel

from tools.models import (
    ApplyDiff,
    CommitChanges,
    CreateBranch,
    CreateProject,
    Delegate,
    GrepFiles,
    ListFiles,
    ListProjects,
    ReadFile,
    RunCommand,
    SearchFiles,
    SetProject,
    WriteFile,
)

if TYPE_CHECKING:
    from store.domain import SessionState


@dataclass
class ToolDef:
    """Metadata for a single tool available to the agent.

    Keeps everything about a tool co-located so that adding a new tool
    means editing exactly one place (the REGISTRY dict below) rather
    than four separate locations.

    Attributes:
        schema: JSON schema in OpenAI tool format, passed directly to the LLM
            on every request so the model knows what tools it can call.
        requires_confirmation: Whether the user must approve this tool before it
            runs. Use True for tools that always need approval (write_file,
            apply_diff). Pass a callable (tool_args: dict) -> bool for tools
            whose confirmation requirement depends on the specific call
            (e.g., run_command checks the command against the whitelist).
        build_preview: Optional callable that produces a human-readable summary
            of what the tool will do. Shown to the user in the Telegram
            confirmation prompt. If None, a generic fallback is used.
    """

    schema: dict
    requires_confirmation: bool | Callable[[dict, SessionState | None], bool] = False
    build_preview: Callable[[dict], str] | None = None


def _schema_from_model(name: str, model: type[BaseModel]) -> dict:
    """Build an OpenAI-compatible tool schema from a Pydantic model class.

    The model's docstring becomes the tool description.
    Field names, types, and descriptions come from model_json_schema().
    """
    json_schema = model.model_json_schema()
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": (model.__doc__ or "").strip(),
            "parameters": {
                "type": "object",
                "properties": json_schema.get("properties", {}),
                "required": json_schema.get("required", []),
            },
        },
    }


def _run_command_needs_confirmation(
    tool_args: dict, session_state: SessionState | None = None
) -> bool:
    """Check the command whitelist to decide if confirmation is required.

    Defers to validate_command so the same whitelist rules apply
    whether the decision is being made for confirmation or for execution.
    """
    from tools.safety import SecurityError, validate_command

    try:
        needs_confirm, _ = validate_command(tool_args.get("command", ""))
        return needs_confirm
    except SecurityError:
        return True  # blocked commands always confirm (executor will reject them)
    except Exception:
        return True  # unknown parse errors: confirm rather than silently run


def _write_file_needs_confirmation(
    tool_args: dict, session_state: SessionState | None = None
) -> bool:
    """Check if the target file already exists — only overwrites need confirmation.

    New files are safe to create without asking. Existing files require
    confirmation to protect against accidental data loss.

    Falls back to confirming when the path can't be resolved (no active
    project, security error) — safer to ask than to silently allow.
    """
    from tools.safety import SecurityError, validate_path

    if session_state is None or session_state.active_project is None:
        return True  # no project context → always confirm

    try:
        resolved = validate_path(tool_args.get("path", ""), session_state.active_project)
        return resolved.exists()
    except (SecurityError, Exception):
        return True  # can't resolve → always confirm


REGISTRY: dict[str, ToolDef] = {
    "list_projects": ToolDef(
        schema=_schema_from_model("list_projects", ListProjects),
    ),
    "create_project": ToolDef(
        schema=_schema_from_model("create_project", CreateProject),
    ),
    "set_project": ToolDef(
        schema=_schema_from_model("set_project", SetProject),
    ),
    "list_files": ToolDef(
        schema=_schema_from_model("list_files", ListFiles),
    ),
    "read_file": ToolDef(
        schema=_schema_from_model("read_file", ReadFile),
    ),
    "apply_diff": ToolDef(
        schema=_schema_from_model("apply_diff", ApplyDiff),
        requires_confirmation=True,
        build_preview=lambda args: (
            f"**apply_diff** → `{args.get('path', '?')}`\n\n"
            f"```diff\n- {args.get('old_str', '')}\n+ {args.get('new_str', '')}\n```"
        ),
    ),
    "write_file": ToolDef(
        schema=_schema_from_model("write_file", WriteFile),
        requires_confirmation=_write_file_needs_confirmation,
        build_preview=lambda args: "**write_file** → `{}`\n\n```\n{}\n```".format(
            args.get("path", "?"),
            args.get("content", "")[:1500]
            + ("\n...[truncated]" if len(args.get("content", "")) > 1500 else ""),
        ),
    ),
    "run_command": ToolDef(
        schema=_schema_from_model("run_command", RunCommand),
        requires_confirmation=_run_command_needs_confirmation,
        build_preview=lambda args: f"**run_command**\n\n`{args.get('command', '?')}`",
    ),
    "search_files": ToolDef(
        schema=_schema_from_model("search_files", SearchFiles),
    ),
    "grep_files": ToolDef(
        schema=_schema_from_model("grep_files", GrepFiles),
    ),
    "create_branch": ToolDef(
        schema=_schema_from_model("create_branch", CreateBranch),
    ),
    "commit_changes": ToolDef(
        schema=_schema_from_model("commit_changes", CommitChanges),
        requires_confirmation=True,
        build_preview=lambda args: "**commit_changes**\n\n{}\nFiles: {}".format(
            args.get("message", "?"),
            ", ".join(args.get("files", [])) or "(all changes)",
        ),
    ),
    "delegate": ToolDef(
        schema=_schema_from_model("delegate", Delegate),
    ),
}

# Minimal tool set for sessions with no active project.
# The user can still list and select projects; file/code tools
# become available once a project is set.
_NO_PROJECT_TOOL_NAMES = {"list_projects", "create_project", "set_project"}
NO_PROJECT_TOOLS: list[dict] = [
    t.schema for name, t in REGISTRY.items() if name in _NO_PROJECT_TOOL_NAMES
]

# Coordinator only sees the delegate tool — it cannot call file/code tools directly.
COORDINATOR_TOOLS: list[dict] = [REGISTRY["delegate"].schema]

# Read-only tools — fallback for user-defined skills.
_READ_ONLY_TOOL_NAMES = {
    "list_projects",
    "set_project",
    "list_files",
    "read_file",
    "search_files",
    "grep_files",
}
READ_ONLY_TOOLS: list[dict] = [
    t.schema for name, t in REGISTRY.items() if name in _READ_ONLY_TOOL_NAMES
]

# Writer tools: full read/write/run access, create branches. Cannot commit.
_WRITER_TOOL_NAMES = {
    "list_projects",
    "create_project",
    "set_project",
    "list_files",
    "read_file",
    "search_files",
    "grep_files",
    "write_file",
    "apply_diff",
    "run_command",
    "create_branch",
}
WRITER_TOOLS: list[dict] = [t.schema for name, t in REGISTRY.items() if name in _WRITER_TOOL_NAMES]

# Reviewer tools: read + run tests + commit. Cannot write files.
_REVIEWER_TOOL_NAMES = {
    "list_projects",
    "set_project",
    "list_files",
    "read_file",
    "search_files",
    "grep_files",
    "run_command",
    "commit_changes",
}
REVIEWER_TOOLS: list[dict] = [
    t.schema for name, t in REGISTRY.items() if name in _REVIEWER_TOOL_NAMES
]
