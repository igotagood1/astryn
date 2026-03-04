from collections.abc import Callable
from dataclasses import dataclass

from pydantic import BaseModel

from tools.models import (
    ApplyDiff,
    GrepFiles,
    ListFiles,
    ListProjects,
    ReadFile,
    RunCommand,
    SearchFiles,
    SetProject,
    WriteFile,
)


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
    requires_confirmation: bool | Callable[[dict], bool] = False
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


def _run_command_needs_confirmation(tool_args: dict) -> bool:
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


REGISTRY: dict[str, ToolDef] = {
    "list_projects": ToolDef(
        schema=_schema_from_model("list_projects", ListProjects),
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
            f"Apply diff to `{args.get('path', '?')}`:\n\n"
            f"```diff\n- {args.get('old_str', '')}\n+ {args.get('new_str', '')}\n```"
        ),
    ),
    "write_file": ToolDef(
        schema=_schema_from_model("write_file", WriteFile),
        requires_confirmation=True,
        build_preview=lambda args: "Write to `{}`:\n\n```\n{}\n```".format(
            args.get("path", "?"),
            args.get("content", "")[:1500]
            + ("\n...[truncated]" if len(args.get("content", "")) > 1500 else ""),
        ),
    ),
    "run_command": ToolDef(
        schema=_schema_from_model("run_command", RunCommand),
        requires_confirmation=_run_command_needs_confirmation,
        build_preview=lambda args: f"Run: `{args.get('command', '?')}`",
    ),
    "search_files": ToolDef(
        schema=_schema_from_model("search_files", SearchFiles),
    ),
    "grep_files": ToolDef(
        schema=_schema_from_model("grep_files", GrepFiles),
    ),
}

# The list of tool schemas passed to the LLM on every request.
# Derived directly from REGISTRY so it never drifts out of sync.
TOOLS: list[dict] = [t.schema for t in REGISTRY.values()]

# Minimal tool set for sessions with no active project.
# The user can still list and select projects; file/code tools
# become available once a project is set.
_NO_PROJECT_TOOL_NAMES = {"list_projects", "set_project"}
NO_PROJECT_TOOLS: list[dict] = [
    t.schema for name, t in REGISTRY.items() if name in _NO_PROJECT_TOOL_NAMES
]
