import os
import subprocess
from pathlib import Path
from tools.safety import validate_path, validate_command, REPOS_ROOT, SecurityError

NOISE_DIRS = {".venv", "venv", "node_modules", "__pycache__", ".git", "dist", "build", ".eggs"}


async def list_projects() -> str:
    projects = [
        d.name for d in REPOS_ROOT.iterdir()
        if d.is_dir() and not d.name.startswith(".")
    ]
    if not projects:
        return "No projects found in ~/repos."
    return "Projects in ~/repos:\n" + "\n".join(f"• {p}" for p in sorted(projects))


async def set_project(name: str, session_state: dict) -> str:
    path = validate_path(name)
    if not path.is_dir():
        return f"'{name}' is not a directory in ~/repos."
    session_state["active_project"] = name
    return f"Active project set to '{name}'. Ready to work."


async def list_files(path: str = ".", active_project: str | None = None) -> str:
    resolved = validate_path(path, active_project)
    if not resolved.exists():
        return f"Path '{path}' does not exist."

    entries = []
    for item in sorted(resolved.iterdir()):
        if item.name in NOISE_DIRS or item.name.startswith("."):
            continue
        prefix = "📁" if item.is_dir() else "📄"
        entries.append(f"{prefix} {item.name}")

    return "\n".join(entries) if entries else "(empty directory)"


async def read_file(path: str, active_project: str | None = None) -> str:
    resolved = validate_path(path, active_project)
    if not resolved.exists():
        return f"File '{path}' does not exist."
    if not resolved.is_file():
        return f"'{path}' is a directory, not a file."

    MAX_CHARS = 20_000
    content = resolved.read_text(encoding="utf-8", errors="replace")
    if len(content) > MAX_CHARS:
        lines = content.splitlines()
        content = content[:MAX_CHARS]
        content += f"\n\n[truncated — {len(lines)} lines total, showing first ~{MAX_CHARS} chars]"
    return content


async def apply_diff(
    path: str,
    old_str: str,
    new_str: str,
    active_project: str | None = None,
) -> str:
    """
    Apply a targeted search-and-replace to a file.
    Fails cleanly if old_str is not found or is ambiguous (appears more than once).
    """
    resolved = validate_path(path, active_project)
    if not resolved.exists():
        return f"File '{path}' does not exist. Use write_file to create it."

    content = resolved.read_text(encoding="utf-8", errors="replace")
    count = content.count(old_str)

    if count == 0:
        return (
            f"Could not apply diff — the target string was not found in '{path}'. "
            f"The file may have changed. Try read_file first, then use write_file with the full updated content."
        )
    if count > 1:
        return (
            f"Could not apply diff — the target string appears {count} times in '{path}'. "
            f"Expand old_str to include more surrounding context to make it unique."
        )

    new_content = content.replace(old_str, new_str, 1)
    resolved.write_text(new_content, encoding="utf-8")
    return f"✅ Applied diff to {path}"


async def write_file(path: str, content: str, active_project: str | None = None) -> str:
    resolved = validate_path(path, active_project)
    resolved.parent.mkdir(parents=True, exist_ok=True)
    resolved.write_text(content, encoding="utf-8")
    return f"✅ Written: {path}"


async def run_command(command: str, active_project: str | None = None) -> str:
    validate_command(command)  # raises SecurityError if blocked

    cwd = str(validate_path(".", active_project)) if active_project else str(REPOS_ROOT)

    try:
        result = subprocess.run(
            command,
            shell=True,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=60,
        )
        output = result.stdout + result.stderr
        return output.strip() or "(no output)"
    except subprocess.TimeoutExpired:
        return "Command timed out after 60 seconds."
    except Exception as e:
        return f"Error running command: {e}"


async def execute_tool(
    tool_name: str,
    tool_args: dict,
    session_state: dict,
) -> str:
    """Dispatch a tool call. Returns string result."""
    active_project = session_state.get("active_project")

    match tool_name:
        case "list_projects":
            return await list_projects()
        case "set_project":
            return await set_project(tool_args["name"], session_state)
        case "list_files":
            return await list_files(tool_args.get("path", "."), active_project)
        case "read_file":
            return await read_file(tool_args["path"], active_project)
        case "apply_diff":
            return await apply_diff(
                tool_args["path"],
                tool_args["old_str"],
                tool_args["new_str"],
                active_project,
            )
        case "write_file":
            return await write_file(tool_args["path"], tool_args["content"], active_project)
        case "run_command":
            return await run_command(tool_args["command"], active_project)
        case _:
            return f"Unknown tool: {tool_name}"


def requires_confirmation(tool_name: str, tool_args: dict) -> bool:
    """Returns True if this tool call needs user confirmation before executing."""
    if tool_name in ("write_file", "apply_diff"):
        return True
    if tool_name == "run_command":
        try:
            needs_confirm, _ = validate_command(tool_args.get("command", ""))
            return needs_confirm
        except Exception:
            return True  # if in doubt, confirm
    return False


def build_preview(tool_name: str, tool_args: dict) -> str:
    """Human-readable description of what this tool will do."""
    match tool_name:
        case "apply_diff":
            path = tool_args.get("path", "?")
            old = tool_args.get("old_str", "")
            new = tool_args.get("new_str", "")
            return (
                f"Apply diff to `{path}`:\n\n"
                f"```diff\n- {old}\n+ {new}\n```"
            )
        case "write_file":
            path = tool_args.get("path", "?")
            content = tool_args.get("content", "")
            preview_content = content[:1500] + ("\n...[truncated]" if len(content) > 1500 else "")
            return f"Write to `{path}`:\n\n```\n{preview_content}\n```"
        case "run_command":
            return f"Run: `{tool_args.get('command', '?')}`"
        case _:
            return f"Execute `{tool_name}` with args: {tool_args}"
            