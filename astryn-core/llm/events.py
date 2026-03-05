"""Event types emitted during streaming agent execution.

Used by the SSE endpoint to send real-time updates to clients.
The agent loop pushes these to an asyncio.Queue when streaming is enabled.
"""

from dataclasses import dataclass, field


@dataclass
class AgentEvent:
    """Base class for all streaming events."""


@dataclass
class TextDelta(AgentEvent):
    """Partial text from an LLM response."""

    text: str


@dataclass
class ToolStart(AgentEvent):
    """A tool is about to execute."""

    tool_name: str
    tool_args: dict = field(default_factory=dict)


@dataclass
class ToolResult(AgentEvent):
    """A tool has finished executing."""

    tool_name: str
    summary: str


@dataclass
class StatusUpdate(AgentEvent):
    """Status message (e.g. "Delegating to code-writer...")."""

    message: str


@dataclass
class AgentDone(AgentEvent):
    """Agent loop completed."""

    reply: str
    model: str
    action: dict | None = None
    usage: dict | None = None


@dataclass
class AgentError(AgentEvent):
    """Agent loop encountered an error."""

    error: str
