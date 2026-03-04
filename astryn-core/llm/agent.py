import json
import uuid
from dataclasses import dataclass, field

from llm.base import LLMProvider
from tools.definitions import TOOLS
from tools.executor import build_preview, execute_tool, requires_confirmation

MAX_ITERATIONS = 10

MODEL_TOOL_UNSUPPORTED_REPLY = (
    "⚠️ This model doesn't support tool use — it described the action instead of executing it.\n\n"
    "Use `/model` to switch to one that does. `llama3.1:8b` is a reliable choice."
)


def _looks_like_failed_tool_call(content: str) -> bool:
    """Detect when a model outputs a tool call as plain text instead of using the tool API."""
    content = content.strip()
    if not content.startswith("{"):
        return False
    try:
        data = json.loads(content)
        return isinstance(data, dict) and "name" in data and "arguments" in data
    except json.JSONDecodeError:
        return False


@dataclass
class PendingConfirmation:
    id: str
    session_id: str
    tool_name: str
    tool_args: dict
    tool_call_id: str
    preview: str
    system: str
    messages: list[dict]
    remaining_tool_calls: list[dict] = field(default_factory=list)
    session_state: dict = field(default_factory=dict)


@dataclass
class AgentResult:
    reply: str
    model: str
    messages: list[dict]
    pending: PendingConfirmation | None = None


async def run_agent(
    provider: LLMProvider,
    messages: list[dict],
    system: str,
    session_id: str,
    session_state: dict,
) -> AgentResult:
    """
    Run the agentic tool loop.

    Calls the LLM, executes any safe tool calls immediately, and returns
    either a final reply or a paused state when a tool needs user confirmation.
    """
    for _ in range(MAX_ITERATIONS):
        response = await provider.chat(messages, system, tools=TOOLS)
        messages = [*messages, response.to_message()]

        if not response.tool_calls:
            if _looks_like_failed_tool_call(response.content):
                return AgentResult(
                    reply=MODEL_TOOL_UNSUPPORTED_REPLY,
                    model=response.model,
                    messages=messages,
                )
            return AgentResult(reply=response.content, model=response.model, messages=messages)

        outcome = await _process_tool_calls(
            tool_calls=response.tool_calls,
            messages=messages,
            system=system,
            session_id=session_id,
            session_state=session_state,
            provider=provider,
        )

        if isinstance(outcome, AgentResult):
            return outcome

        messages = outcome  # updated messages after all safe tool calls ran

    return AgentResult(
        reply="[Agent reached max iterations without a final response. Try rephrasing.]",
        model=provider.model_name,
        messages=messages,
    )


async def resume_agent(
    provider: LLMProvider,
    pending: PendingConfirmation,
    approved: bool,
) -> AgentResult:
    """
    Resume the agent after the user approves or rejects a pending tool call.

    Executes or skips the tool, then continues the loop with any remaining
    tool calls from the same LLM response before asking the LLM again.
    """
    if approved:
        tool_result = await execute_tool(pending.tool_name, pending.tool_args, pending.session_state)
    else:
        tool_result = "User rejected this action. Do not retry it."

    messages = [
        *pending.messages,
        {"role": "tool", "tool_call_id": pending.tool_call_id, "content": tool_result},
    ]

    if pending.remaining_tool_calls:
        outcome = await _process_tool_calls(
            tool_calls=pending.remaining_tool_calls,
            messages=messages,
            system=pending.system,
            session_id=pending.session_id,
            session_state=pending.session_state,
            provider=provider,
        )
        if isinstance(outcome, AgentResult):
            return outcome
        messages = outcome

    return await run_agent(
        provider=provider,
        messages=messages,
        system=pending.system,
        session_id=pending.session_id,
        session_state=pending.session_state,
    )


async def _process_tool_calls(
    tool_calls: list[dict],
    messages: list[dict],
    system: str,
    session_id: str,
    session_state: dict,
    provider: LLMProvider,
) -> "list[dict] | AgentResult":
    """
    Process a batch of tool calls sequentially.

    Runs safe tools immediately. Pauses and returns an AgentResult with a
    PendingConfirmation when a tool that requires user approval is encountered.
    The remaining unprocessed calls are stored so they can be resumed later.
    """
    for i, tool_call in enumerate(tool_calls):
        fn = tool_call.get("function", {})
        tool_name = fn.get("name", "")
        raw_args = fn.get("arguments", {})
        tool_args = raw_args if isinstance(raw_args, dict) else json.loads(raw_args)
        tool_call_id = tool_call.get("id") or str(uuid.uuid4())

        if requires_confirmation(tool_name, tool_args):
            return AgentResult(
                reply="",
                model=provider.model_name,
                messages=messages,
                pending=PendingConfirmation(
                    id=str(uuid.uuid4()),
                    session_id=session_id,
                    tool_name=tool_name,
                    tool_args=tool_args,
                    tool_call_id=tool_call_id,
                    preview=build_preview(tool_name, tool_args),
                    system=system,
                    messages=messages,
                    remaining_tool_calls=tool_calls[i + 1 :],
                    session_state=session_state,
                ),
            )

        result = await execute_tool(tool_name, tool_args, session_state)
        messages = [*messages, {"role": "tool", "tool_call_id": tool_call_id, "content": result}]

    return messages
