from pydantic import BaseModel, Field


class ListProjects(BaseModel):
    """List all available projects in ~/repos."""


class CreateProject(BaseModel):
    """Create a new project directory in ~/repos and set it as active.

    Creates the folder, initializes a git repository, and switches to it.
    Requires confirmation.
    """

    name: str = Field(
        min_length=1,
        description=(
            "Name for the new project (e.g., 'my-new-app'). Letters, numbers, hyphens, underscores."
        ),
    )


class SetProject(BaseModel):
    """Set the active project for this session.

    All subsequent file operations are scoped to this project.
    """

    name: str = Field(description="Project folder name within ~/repos")


class ListFiles(BaseModel):
    """List files and directories at a path within the active project."""

    path: str = Field(
        default=".",
        description="Relative path from project root. Defaults to '.' (project root).",
    )


class ReadFile(BaseModel):
    """Read the full contents of a file in the active project."""

    path: str = Field(description="Relative path from project root")


class ApplyDiff(BaseModel):
    """Apply a targeted change to a file using search-and-replace.

    PREFER this over write_file for changes to existing files — it is surgical
    and easier to review. Show the user what you're changing before calling this.
    Requires confirmation.
    """

    path: str = Field(description="Relative path from project root")
    old_str: str = Field(
        description="The exact string to find and replace. Must be unique in the file."
    )
    new_str: str = Field(description="The replacement string. Empty string to delete.")


class WriteFile(BaseModel):
    """Write full content to a file (creates or overwrites).

    Use for new files or when apply_diff would cover the entire file.
    ALWAYS explain what you're writing and why before calling this.
    Requires confirmation.
    """

    path: str = Field(description="Relative path from project root")
    content: str = Field(description="Full file content to write")


class RunCommand(BaseModel):
    """Run a whitelisted shell command in the active project directory.

    Read-only commands (git status, pytest, etc.) run immediately.
    Write commands (git commit, git add, npm run) require confirmation.
    """

    command: str = Field(description="The command to run")


class SearchFiles(BaseModel):
    """Search for files matching a glob pattern within the active project."""

    pattern: str = Field(description="Glob pattern to match, e.g. '*.py' or 'src/**/*.ts'")
    path: str = Field(
        default=".",
        description=(
            "Subdirectory to search within, relative to project root. "
            "Defaults to '.' (entire project)."
        ),
    )


class GrepFiles(BaseModel):
    """Search file contents for lines matching a regex pattern.

    Returns matching lines with file paths and line numbers.
    Useful for finding function definitions, usages, TODOs, etc.
    """

    pattern: str = Field(description="Regex pattern to search for, e.g. 'def main' or 'TODO'")
    include: str = Field(
        default="",
        description=(
            "Glob filter for filenames, e.g. '*.py' or '*.ts'. "
            "Empty string means search all text files."
        ),
    )


class Delegate(BaseModel):
    """Delegate a task to a specialist skill.

    Use this when the user's request requires file access, code changes,
    or deep exploration. The skill runs with its own tools and context,
    then returns its result to you for formatting.
    """

    skill: str = Field(
        min_length=1,
        description="Which skill to use (e.g., 'code', 'explore', 'plan')",
    )
    task: str = Field(min_length=1, description="Clear task description for the specialist")
    context: str = Field(
        default="",
        description="Relevant file paths, error messages, or constraints from the conversation",
    )

    @property
    def specialist(self) -> str:
        """Backward-compat alias for skill."""
        return self.skill


type AnyTool = (
    ListProjects
    | CreateProject
    | SetProject
    | ListFiles
    | ReadFile
    | ApplyDiff
    | WriteFile
    | RunCommand
    | SearchFiles
    | GrepFiles
    | Delegate
)


def parse_tool(name: str, args: dict) -> AnyTool:
    """Parse a tool name and args dict from the LLM into a typed model instance.

    Raises ValueError for unknown tool names.
    Raises pydantic.ValidationError if args don't match the model's schema.
    """
    match name:
        case "list_projects":
            return ListProjects.model_validate(args)
        case "create_project":
            return CreateProject.model_validate(args)
        case "set_project":
            return SetProject.model_validate(args)
        case "list_files":
            return ListFiles.model_validate(args)
        case "read_file":
            return ReadFile.model_validate(args)
        case "apply_diff":
            return ApplyDiff.model_validate(args)
        case "write_file":
            return WriteFile.model_validate(args)
        case "run_command":
            return RunCommand.model_validate(args)
        case "search_files":
            return SearchFiles.model_validate(args)
        case "grep_files":
            return GrepFiles.model_validate(args)
        case "delegate":
            # Accept both "skill" (new) and "specialist" (legacy) field names
            if "specialist" in args and "skill" not in args:
                args = {**args, "skill": args.pop("specialist")}
            return Delegate.model_validate(args)
        case _:
            raise ValueError(f"Unknown tool: {name!r}")
