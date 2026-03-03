import re
import shlex
from pathlib import Path

REPOS_ROOT = Path.home() / "repos"

# Commands that execute immediately (no confirmation needed)
IMMEDIATE_COMMANDS: dict[str, list[str] | None] = {
    "git":    ["status", "diff", "log", "branch", "show", "stash list"],
    "pytest": None,   # any pytest args are fine
    "python": ["-m pytest"],
    "uv":     ["run pytest", "pip list"],
    "pip":    ["list"],
    "npm":    ["test", "list"],
    "cargo":  ["test"],
    "go":     ["test"],
    "ls":     None,
}

# Commands that require confirmation before running
CONFIRMATION_COMMANDS: dict[str, list[str] | None] = {
    "git": ["add", "commit", "checkout", "stash pop", "stash drop", "stash"],
    "npm": ["run"],
}

# Patterns that are always blocked regardless of command
BLOCKED_PATTERNS = [
    r"[|;&`]",          # pipes, semicolons, command chaining, backticks
    r"\$\(",            # subshell
    r"\.\.(?:/|$)",     # path traversal
    r">\s*\S",          # output redirect
    r"<\s*\S",          # input redirect
]

BLOCKED_COMMANDS = {
    "rm", "rmdir", "mv", "cp", "chmod", "chown",
    "curl", "wget", "ssh", "scp", "sftp",
    "sudo", "su", "bash", "sh", "zsh", "fish",
    "env", "printenv", "export", "source",
    "eval", "exec", "kill", "pkill",
}


class SecurityError(Exception):
    pass


def validate_path(path: str, active_project: str | None = None) -> Path:
    """Resolve and validate that path is within ~/repos."""
    base = REPOS_ROOT / active_project if active_project else REPOS_ROOT
    resolved = (base / path).resolve()
    if not str(resolved).startswith(str(REPOS_ROOT.resolve())):
        raise SecurityError(f"Path '{path}' is outside ~/repos — access denied.")
    return resolved


def validate_command(command: str) -> tuple[bool, str]:
    """
    Validate a shell command against the whitelist.
    Returns (requires_confirmation, reason).
    Raises SecurityError if blocked.
    """
    command = command.strip()

    # Check for blocked patterns first
    for pattern in BLOCKED_PATTERNS:
        if re.search(pattern, command):
            raise SecurityError(f"Command contains blocked pattern: '{pattern}'")

    try:
        parts = shlex.split(command)
    except ValueError as e:
        raise SecurityError(f"Could not parse command: {e}")

    if not parts:
        raise SecurityError("Empty command.")

    base_cmd = parts[0].lower()
    args_str = " ".join(parts[1:]).lower()

    if base_cmd in BLOCKED_COMMANDS:
        raise SecurityError(f"Command '{base_cmd}' is not permitted.")

    # Check immediate whitelist
    if base_cmd in IMMEDIATE_COMMANDS:
        allowed_args = IMMEDIATE_COMMANDS[base_cmd]
        if allowed_args is None:
            return False, "immediate"  # all args allowed
        if any(args_str.startswith(a) for a in allowed_args):
            return False, "immediate"

    # Check confirmation whitelist
    if base_cmd in CONFIRMATION_COMMANDS:
        allowed_args = CONFIRMATION_COMMANDS[base_cmd]
        if allowed_args is None:
            return True, "confirmation"
        if any(args_str.startswith(a) for a in allowed_args):
            return True, "confirmation"

    raise SecurityError(
        f"Command '{command}' is not on the allowed list. "
        f"Permitted commands: git, pytest, npm test/run, cargo test, go test, pip list, uv."
    )