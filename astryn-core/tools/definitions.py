TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "list_projects",
            "description": "List all projects in ~/repos. Call this at the start of a session to let the user choose a project.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "set_project",
            "description": "Set the active project for this session. All subsequent file operations are scoped to this project.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Project folder name within ~/repos"}
                },
                "required": ["name"],
            },
        },
    },
    {
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
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read the full contents of a file in the active project.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Relative path from project root"}
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "apply_diff",
            "description": (
                "Apply a targeted change to a file using search-and-replace. "
                "PREFER this over write_file for changes to existing files — it is surgical and easier to review. "
                "Show the user what you're changing before calling this. Requires confirmation."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Relative path from project root"},
                    "old_str": {
                        "type": "string",
                        "description": "The exact string to find and replace. Must be unique in the file.",
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
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": (
                "Write full content to a file (creates or overwrites). "
                "Use for new files or when apply_diff would cover the entire file. "
                "ALWAYS explain what you're writing and why before calling this. Requires confirmation."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Relative path from project root"},
                    "content": {"type": "string", "description": "Full file content to write"},
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_command",
            "description": "Run a whitelisted shell command in the active project directory. Read-only commands run immediately. Write commands (git commit, git add, npm run) require confirmation.",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "The command to run"}
                },
                "required": ["command"],
            },
        },
    },
]