import logging
import shlex
import subprocess

from store.memory import SessionState
from tools.registry import REGISTRY
from tools.safety import REPOS_ROOT, SecurityError, validate_command, validate_path

logger = logging.getLogger(__name__)

NOISE_DIRS = {".venv", "venv", "node_modules", "__pycache__", ".git", "dist", "build", ".eggs"}


async def list_projects() -> str:
    projects = [
        d.name for d in REPOS_ROOT.iterdir() if d.is_dir() and not d.name.startswith(".")
    ]
    if not projects:
        return "No projects found in ~/repos."
    return "Projects in ~/repos:\n" + "\n".join(f"- {p}" for p in sorted(projects))


async def set_project(name: str, session_state: SessionState) -> str:
    path = validate_path(name)
    if not path.is_dir():
        return f"'{name}' is not a directory in ~/repos."
    session_state.active_project = name
    return f"Active project set to '{name}'. Ready to work."


async def list_files(path: str = ".", active_project: str | None = None) -> str:
    resolved = validate_path(path, active_project)
    if not resolved.exists():
        return f"Path '{path}' does not exist."

    entries = []
    for item in sorted(resolved.iterdir()):
        if item.name in NOISE_DIRS or item.name.startswith("."):
            continue
        kind = "[dir]" if item.is_dir() else "[file]"
        entries.append(f"{kind} {item.name}")

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
    """Apply a targeted search-and-replace to a file.

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
    logger.info("Applied diff to: %s", path)
    return f"Applied diff to {path}"


async def write_file(path: str, content: str, active_project: str | None = None) -> str:
    resolved = validate_path(path, active_project)
    resolved.parent.mkdir(parents=True, exist_ok=True)
    resolved.write_text(content, encoding="utf-8")
    logger.info("Wrote file: %s", path)
    return f"Written: {path}"


async def run_command(command: str, active_project: str | None = None) -> str:
    validate_command(command)  # raises SecurityError if blocked

    cwd = str(validate_path(".", active_project)) if active_project else str(REPOS_ROOT)
    logger.info("Running command: %r cwd=%s", command, cwd)

    try:
        result = subprocess.run(
            shlex.split(command),
            shell=False,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=60,
        )
        output = result.stdout + result.stderr
        return output.strip() or "(no output)"
    except subprocess.TimeoutExpired:
        return "Command timed out after 60 seconds."
    except OSError as e:
        logger.error("Command failed with OSError: %s", e)
        return f"Error running command: {e}"


async def execute_tool(
    tool_name: str,
    tool_args: dict,
    session_state: SessionState,
) -> str:
    """Dispatch a tool call by name. Returns a plain-text result for the LLM."""
    active_project = session_state.active_project

    try:
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
                logger.warning("Unknown tool called: %s", tool_name)
                return f"Unknown tool: {tool_name}"
    except SecurityError as e:
        logger.warning("Security error for tool %s: %s", tool_name, e)
        return f"Security error: {e} Use a relative path within the active project."


def requires_confirmation(tool_name: str, tool_args: dict) -> bool:
    """Return True if this tool call needs user confirmation before executing.

    Delegates to the tool's registry entry so the logic is co-located with
    the tool definition rather than scattered across separate functions.
    """
    tool = REGISTRY.get(tool_name)
    if not tool:
        return True  # unknown tools always require confirmation
    if callable(tool.requires_confirmation):
        return tool.requires_confirmation(tool_args)
    return bool(tool.requires_confirmation)


def build_preview(tool_name: str, tool_args: dict) -> str:
    """Return a human-readable description of what this tool call will do.

    Used in the Telegram confirmation prompt. Delegates to the tool's
    registry entry so preview logic stays co-located with the tool definition.
    """
    tool = REGISTRY.get(tool_name)
    if tool and tool.build_preview:
        return tool.build_preview(tool_args)
    return f"Execute `{tool_name}` with args: {tool_args}"
