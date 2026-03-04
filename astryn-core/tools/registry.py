from dataclasses import dataclass
from typing import Callable


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
    "set_project": ToolDef(
        schema={
            "type": "function",
            "function": {
                "name": "set_project",
                "description": (
                    "Set the active project for this session. "
                    "All subsequent file operations are scoped to this project."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "name": {
                            "type": "string",
                            "description": "Project folder name within ~/repos",
                        }
                    },
                    "required": ["name"],
                },
            },
        },
    ),
    "list_files": ToolDef(
        schema={
            "type": "function",
            "function": {
                "name": "list_files",
                "description": "List files and directories at a path within the active project.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": "Relative path from project root. Defaults to '.' (project root).",
                            "default": ".",
                        }
                    },
                    "required": [],
                },
            },
        },
    ),
    "read_file": ToolDef(
        schema={
            "type": "function",
            "function": {
                "name": "read_file",
                "description": "Read the full contents of a file in the active project.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": "Relative path from project root",
                        }
                    },
                    "required": ["path"],
                },
            },
        },
    ),
    "apply_diff": ToolDef(
        schema={
            "type": "function",
            "function": {
                "name": "apply_diff",
                "description": (
                    "Apply a targeted change to a file using search-and-replace. "
                    "PREFER this over write_file for changes to existing files — "
                    "it is surgical and easier to review. "
                    "Show the user what you're changing before calling this. "
                    "Requires confirmation."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": "Relative path from project root",
                        },
                        "old_str": {
                            "type": "string",
                            "description": (
                                "The exact string to find and replace. "
                                "Must be unique in the file."
                            ),
                        },
                        "new_str": {
                            "type": "string",
                            "description": "The replacement string. Empty string to delete.",
                        },
                    },
                    "required": ["path", "old_str", "new_str"],
                },
            },
        },
        requires_confirmation=True,
        build_preview=lambda args: (
            f"Apply diff to `{args.get('path', '?')}`:\n\n"
            f"```diff\n- {args.get('old_str', '')}\n+ {args.get('new_str', '')}\n```"
        ),
    ),
    "write_file": ToolDef(
        schema={
            "type": "function",
            "function": {
                "name": "write_file",
                "description": (
                    "Write full content to a file (creates or overwrites). "
                    "Use for new files or when apply_diff would cover the entire file. "
                    "ALWAYS explain what you're writing and why before calling this. "
                    "Requires confirmation."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": "Relative path from project root",
                        },
                        "content": {
                            "type": "string",
                            "description": "Full file content to write",
                        },
                    },
                    "required": ["path", "content"],
                },
            },
        },
        requires_confirmation=True,
        build_preview=lambda args: (
            "Write to `{}`:\n\n```\n{}\n```".format(
                args.get("path", "?"),
                args.get("content", "")[:1500]
                + ("\n...[truncated]" if len(args.get("content", "")) > 1500 else ""),
            )
        ),
    ),
    "run_command": ToolDef(
        schema={
            "type": "function",
            "function": {
                "name": "run_command",
                "description": (
                    "Run a whitelisted shell command in the active project directory. "
                    "Read-only commands (git status, pytest, etc.) run immediately. "
                    "Write commands (git commit, git add, npm run) require confirmation."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "command": {
                            "type": "string",
                            "description": "The command to run",
                        }
                    },
                    "required": ["command"],
                },
            },
        },
        requires_confirmation=_run_command_needs_confirmation,
        build_preview=lambda args: f"Run: `{args.get('command', '?')}`",
    ),
}

# The list of tool schemas passed to the LLM on every request.
# Derived directly from REGISTRY so it never drifts out of sync.
TOOLS: list[dict] = [t.schema for t in REGISTRY.values()]
