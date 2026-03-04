import json
import logging
import uuid
from dataclasses import dataclass, field

from sqlalchemy.ext.asyncio import AsyncSession

import db.repository as repo
from llm.base import LLMProvider
from store.domain import SessionState
from tools.executor import build_preview, execute_tool, requires_confirmation
from tools.registry import TOOLS

logger = logging.getLogger(__name__)

MAX_ITERATIONS = 10

MODEL_TOOL_UNSUPPORTED_REPLY = (
    "This model doesn't support tool use — it described the action instead of executing it.\n\n"
    "Use `/model` to switch to one that does. `llama3.1:8b` is a reliable choice."
)


def _looks_like_failed_tool_call(content: str) -> bool:
    """Detect when a model outputs a tool call as plain text instead of using the tool API."""
    content = content.strip()
    if not content.startswith("{"):
        return False
    try:
        data = json.loads(content)
        return (
            isinstance(data, dict)
            and "name" in data
            and ("arguments" in data or "parameters" in data)
        )
    except json.JSONDecodeError:
        return False


@dataclass
class PendingConfirmation:
    """Snapshot of a paused agent loop waiting for user approval."""

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
    """Outcome of a completed or paused agent loop iteration."""

    reply: str
    model: str
    messages: list[dict]
    pending: PendingConfirmation | None = None


async def run_agent(
    provider: LLMProvider,
    messages: list[dict],
    system: str,
    session_id: str,
    session_state: SessionState,
    db: AsyncSession,
    tools: list[dict] | None = None,
) -> AgentResult:
    """Run the agentic tool loop.

    Calls the LLM repeatedly, executing safe tool calls immediately and
    pausing on any tool that requires user confirmation.
    """
    effective_tools = tools if tools is not None else TOOLS

    for iteration in range(MAX_ITERATIONS):
        logger.debug("Agent iteration %d: session=%s", iteration + 1, session_id)
        response = await provider.chat(messages, system, tools=effective_tools)
        messages = [*messages, response.to_message()]

        if not response.tool_calls:
            if _looks_like_failed_tool_call(response.content):
                logger.warning("Model output a tool call as plain text: session=%s", session_id)
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
            db=db,
        )

        if isinstance(outcome, AgentResult):
            return outcome

        messages = outcome

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
    db: AsyncSession,
) -> AgentResult:
    """Resume the agent after the user approves or rejects a pending tool call."""
    if approved:
        logger.info("Executing approved tool: %s", pending.tool_name)
        tool_result = await execute_tool(
            pending.tool_name, pending.tool_args, pending.session_state
        )
    else:
        logger.info("Tool rejected by user: %s", pending.tool_name)
        tool_result = "User rejected this action. Do not retry it."

    await repo.log_tool_call(
        db=db,
        external_id=pending.session_id,
        tool_name=pending.tool_name,
        tool_args=pending.tool_args,
        required_confirmation=True,
        approved=approved,
        result=tool_result if approved else None,
    )

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
            db=db,
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
        db=db,
    )


async def _process_tool_calls(
    tool_calls: list[dict],
    messages: list[dict],
    system: str,
    session_id: str,
    session_state: SessionState,
    provider: LLMProvider,
    db: AsyncSession,
) -> "list[dict] | AgentResult":
    """Process a batch of tool calls sequentially.

    Runs safe tools immediately. Pauses on tools that require confirmation.
    Logs each execution to the tool_audit table.
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
        tool_error = None
        try:
            result = await execute_tool(tool_name, tool_args, session_state)
        except Exception as e:
            logger.error("Tool execution failed: %s error=%s", tool_name, e)
            result = f"Tool execution failed: {e}"
            tool_error = str(e)

        await repo.log_tool_call(
            db=db,
            external_id=session_id,
            tool_name=tool_name,
            tool_args=tool_args,
            required_confirmation=False,
            approved=None,
            result=result if tool_error is None else None,
            error=tool_error,
        )

        messages = [*messages, {"role": "tool", "tool_call_id": tool_call_id, "content": result}]

    return messages
