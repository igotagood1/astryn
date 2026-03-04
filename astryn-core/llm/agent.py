import json
import logging
import uuid
from dataclasses import dataclass, field

from store.memory import SessionState
from llm.base import LLMProvider
from tools.executor import build_preview, execute_tool, requires_confirmation
from tools.registry import TOOLS

logger = logging.getLogger(__name__)

MAX_ITERATIONS = 10

MODEL_TOOL_UNSUPPORTED_REPLY = (
    "This model doesn't support tool use — it described the action instead of executing it.\n\n"
    "Use `/model` to switch to one that does. `llama3.1:8b` is a reliable choice."
)


def _looks_like_failed_tool_call(content: str) -> bool:
    """Detect when a model outputs a tool call as plain text instead of using the tool API.

    Some models that don't properly support tool use will respond with a JSON
    string describing the call rather than a structured tool_calls list. This
    heuristic catches that case so we can surface a helpful error message.
    """
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
    """Snapshot of a paused agent loop waiting for user approval.

    When the agent encounters a tool that requires confirmation, it stops,
    stores everything needed to resume, and returns this to the API layer.
    The API layer persists it in pending_confirmations until the user responds.
    """

    id: str
    session_id: str
    tool_name: str
    tool_args: dict
    tool_call_id: str
    preview: str
    system: str
    messages: list[dict]
    remaining_tool_calls: list[dict] = field(default_factory=list)
    session_state: SessionState = field(default_factory=SessionState)


@dataclass
class AgentResult:
    """Outcome of a completed or paused agent loop iteration.

    If `pending` is set, the loop is paused and the caller should present
    the confirmation to the user before calling resume_agent().
    If `pending` is None, `reply` contains the agent's final answer.
    If `projects` is set, list_projects was called and the client should
    render them as selectable buttons rather than plain text.
    """

    reply: str
    model: str
    messages: list[dict]
    pending: PendingConfirmation | None = None
    projects: list[str] | None = None


def _extract_projects(messages: list[dict]) -> list[str] | None:
    """Return project names if list_projects was called in this loop.

    Scans the message history for list_projects tool calls, finds the
    corresponding tool result, and parses the project names out of it.
    Returns None if list_projects was not called.
    """
    # Collect tool_call_ids for any list_projects calls
    list_projects_ids: set[str] = set()
    for msg in messages:
        if msg.get("role") == "assistant":
            for tc in msg.get("tool_calls") or []:
                if tc.get("function", {}).get("name") == "list_projects":
                    list_projects_ids.add(tc.get("id", ""))

    if not list_projects_ids:
        return None

    # Find the matching tool result and parse project names from it
    for msg in messages:
        if msg.get("role") == "tool" and msg.get("tool_call_id") in list_projects_ids:
            lines = msg.get("content", "").splitlines()
            projects = [line[2:].strip() for line in lines if line.startswith("- ")]
            if projects:
                return projects

    return None


async def run_agent(
    provider: LLMProvider,
    messages: list[dict],
    system: str,
    session_id: str,
    session_state: SessionState,
) -> AgentResult:
    """Run the agentic tool loop.

    Calls the LLM repeatedly, executing safe tool calls immediately and
    pausing on any tool that requires user confirmation. Returns either a
    final reply or a paused AgentResult with a PendingConfirmation.
    """
    for iteration in range(MAX_ITERATIONS):
        logger.debug("Agent iteration %d: session=%s", iteration + 1, session_id)
        response = await provider.chat(messages, system, tools=TOOLS)
        messages = [*messages, response.to_message()]

        if not response.tool_calls:
            if _looks_like_failed_tool_call(response.content):
                logger.warning("Model output a tool call as plain text: session=%s", session_id)
                return AgentResult(
                    reply=MODEL_TOOL_UNSUPPORTED_REPLY,
                    model=response.model,
                    messages=messages,
                )
            return AgentResult(
                reply=response.content,
                model=response.model,
                messages=messages,
                projects=_extract_projects(messages),
            )

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

    logger.warning("Agent hit max iterations without a final reply: session=%s", session_id)
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
    """Resume the agent after the user approves or rejects a pending tool call.

    Executes or skips the tool, then continues the loop with any remaining
    tool calls from the same LLM response before asking the LLM again.
    """
    if approved:
        logger.info("Executing approved tool: %s", pending.tool_name)
        tool_result = await execute_tool(pending.tool_name, pending.tool_args, pending.session_state)
    else:
        logger.info("Tool rejected by user: %s", pending.tool_name)
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
    session_state: SessionState,
    provider: LLMProvider,
) -> "list[dict] | AgentResult":
    """Process a batch of tool calls sequentially.

    Runs safe tools immediately. Pauses and returns an AgentResult with a
    PendingConfirmation when a tool that requires user approval is encountered.
    Remaining unprocessed calls are stored on the PendingConfirmation so they
    can be picked up after the user responds.
    """
    for i, tool_call in enumerate(tool_calls):
        fn = tool_call.get("function", {})
        tool_name = fn.get("name", "")
        raw_args = fn.get("arguments", {})
        tool_args = raw_args if isinstance(raw_args, dict) else json.loads(raw_args)
        tool_call_id = tool_call.get("id") or str(uuid.uuid4())

        if requires_confirmation(tool_name, tool_args):
            logger.info("Tool requires confirmation: %s session=%s", tool_name, session_id)
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

        logger.info("Executing tool immediately: %s session=%s", tool_name, session_id)
        result = await execute_tool(tool_name, tool_args, session_state)
        messages = [*messages, {"role": "tool", "tool_call_id": tool_call_id, "content": result}]

    return messages
