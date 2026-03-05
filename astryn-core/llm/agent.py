import asyncio
import json
import logging
import time
import uuid
from dataclasses import dataclass, field

from sqlalchemy.ext.asyncio import AsyncSession

import db.repository as repo
from llm.base import LLMProvider, LLMResponse
from llm.events import StatusUpdate, TextDelta, ToolResult, ToolStart
from store.domain import SessionState
from tools.executor import build_preview, execute_tool, requires_confirmation
from tools.registry import COORDINATOR_TOOLS, NO_PROJECT_TOOLS, WRITER_TOOLS

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
    created_at: float = field(default_factory=time.monotonic)
    # Coordinator state for nested confirmation resume (delegation)
    coordinator_messages: list[dict] | None = None
    coordinator_system: str | None = None
    delegate_tool_call_id: str | None = None


@dataclass
class AgentResult:
    """Outcome of a completed or paused agent loop iteration."""

    reply: str
    model: str
    messages: list[dict]
    pending: PendingConfirmation | None = None
    usage: dict | None = None  # cumulative token usage {"input_tokens": N, "output_tokens": N}


async def _emit(event_queue: asyncio.Queue | None, event) -> None:
    """Push an event to the queue if streaming is enabled."""
    if event_queue is not None:
        await event_queue.put(event)


async def _chat_with_streaming(
    provider: LLMProvider,
    messages: list[dict],
    system: str,
    tools: list[dict] | None,
    event_queue: asyncio.Queue | None,
) -> LLMResponse:
    """Call the provider, streaming text deltas if event_queue is set."""
    if event_queue is None:
        return await provider.chat(messages, system, tools=tools)

    response: LLMResponse | None = None
    async for chunk in provider.chat_stream(messages, system, tools=tools):
        if isinstance(chunk, str):
            await event_queue.put(TextDelta(text=chunk))
        elif isinstance(chunk, LLMResponse):
            response = chunk

    if response is None:
        raise RuntimeError("Provider stream ended without yielding an LLMResponse")
    return response


async def run_agent(
    provider: LLMProvider,
    messages: list[dict],
    system: str,
    session_id: str,
    session_state: SessionState,
    db: AsyncSession,
    tools: list[dict] | None = None,
    specialist_provider: LLMProvider | None = None,
    event_queue: asyncio.Queue | None = None,
    cancel_event: asyncio.Event | None = None,
) -> AgentResult:
    """Run the agentic tool loop.

    Calls the LLM repeatedly, executing safe tool calls immediately and
    pausing on any tool that requires user confirmation.

    Args:
        specialist_provider: Provider used for specialist sub-agents when
            handling delegate tool calls. Falls back to ``provider`` if None.
        event_queue: Optional queue for streaming events. When set, text
            deltas and tool status updates are pushed as they happen.
        cancel_event: Optional event that signals cancellation. Checked
            at each iteration boundary.
    """
    cumulative_usage = {"input_tokens": 0, "output_tokens": 0}

    for iteration in range(MAX_ITERATIONS):
        # Check for cancellation
        if cancel_event and cancel_event.is_set():
            return AgentResult(
                reply="Request cancelled.",
                model=provider.model_name,
                messages=messages,
            )

        # Re-derive available tools each iteration so that set_project
        # mid-turn unlocks file/code tools without needing a second request.
        if tools is not None:
            effective_tools = tools
        elif session_state.active_project:
            effective_tools = WRITER_TOOLS
        else:
            effective_tools = NO_PROJECT_TOOLS

        logger.info("Agent iteration %d/%d: session=%s", iteration + 1, MAX_ITERATIONS, session_id)
        response = await _chat_with_streaming(
            provider, messages, system, effective_tools, event_queue
        )
        messages = [*messages, response.to_message()]

        # Accumulate token usage
        if response.usage:
            cumulative_usage["input_tokens"] += response.usage.get("input_tokens", 0)
            cumulative_usage["output_tokens"] += response.usage.get("output_tokens", 0)

        if not response.tool_calls:
            usage = cumulative_usage if any(cumulative_usage.values()) else None
            if _looks_like_failed_tool_call(response.content):
                logger.warning("Model output a tool call as plain text: session=%s", session_id)
                return AgentResult(
                    reply=MODEL_TOOL_UNSUPPORTED_REPLY,
                    model=response.model,
                    messages=messages,
                    usage=usage,
                )
            reply = (response.content or "").strip()
            if not reply:
                logger.warning(
                    "LLM returned empty content: session=%s model=%s",
                    session_id,
                    response.model,
                )
                reply = "I wasn't able to generate a response. Could you try rephrasing?"
            return AgentResult(reply=reply, model=response.model, messages=messages, usage=usage)

        outcome = await _process_tool_calls(
            tool_calls=response.tool_calls,
            messages=messages,
            system=system,
            session_id=session_id,
            session_state=session_state,
            provider=provider,
            db=db,
            specialist_provider=specialist_provider,
            event_queue=event_queue,
            cancel_event=cancel_event,
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
    coordinator_provider: LLMProvider | None = None,
    event_queue: asyncio.Queue | None = None,
) -> AgentResult:
    """Resume the agent after the user approves or rejects a pending tool call.

    Args:
        provider: Provider for the specialist (or single-agent) continuation.
        coordinator_provider: Provider for resuming the coordinator after a
            delegated specialist completes. Falls back to ``provider`` if None.
        event_queue: Optional queue for streaming events.
    """
    if approved:
        logger.info("Executing approved tool: %s", pending.tool_name)
        await _emit(
            event_queue,
            ToolStart(tool_name=pending.tool_name, tool_args=pending.tool_args),
        )
        try:
            tool_result = await execute_tool(
                pending.tool_name, pending.tool_args, pending.session_state
            )
        except Exception as e:
            logger.error("Approved tool execution failed: %s error=%s", pending.tool_name, e)
            tool_result = f"Tool execution failed: {e}"
        await _emit(
            event_queue,
            ToolResult(
                tool_name=pending.tool_name,
                summary=tool_result[:200] if len(tool_result) > 200 else tool_result,
            ),
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
            event_queue=event_queue,
        )
        if isinstance(outcome, AgentResult):
            # If another confirmation needed, preserve coordinator state
            if outcome.pending and pending.coordinator_messages is not None:
                outcome.pending.coordinator_messages = pending.coordinator_messages
                outcome.pending.coordinator_system = pending.coordinator_system
                outcome.pending.delegate_tool_call_id = pending.delegate_tool_call_id
            return outcome
        messages = outcome

    # Continue the specialist loop to completion
    specialist_result = await run_agent(
        provider=provider,
        messages=messages,
        system=pending.system,
        session_id=pending.session_id,
        session_state=pending.session_state,
        db=db,
        event_queue=event_queue,
    )

    # If specialist needs another confirmation, preserve coordinator state
    if specialist_result.pending and pending.coordinator_messages is not None:
        specialist_result.pending.coordinator_messages = pending.coordinator_messages
        specialist_result.pending.coordinator_system = pending.coordinator_system
        specialist_result.pending.delegate_tool_call_id = pending.delegate_tool_call_id
        return specialist_result

    # If this was a delegated confirmation, feed result back to coordinator
    if pending.coordinator_messages is not None:
        assert pending.coordinator_system is not None, (
            "coordinator_system must be set for delegation"
        )
        assert pending.delegate_tool_call_id is not None, (
            "delegate_tool_call_id must be set for delegation"
        )
        coord_provider = coordinator_provider or provider
        return await _resume_coordinator(
            provider=coord_provider,
            specialist_reply=specialist_result.reply,
            coordinator_messages=pending.coordinator_messages,
            coordinator_system=pending.coordinator_system,
            delegate_tool_call_id=pending.delegate_tool_call_id,
            session_id=pending.session_id,
            session_state=pending.session_state,
            db=db,
            specialist_provider=provider,
            event_queue=event_queue,
        )

    return specialist_result


async def _run_specialist(
    skill_name: str,
    task: str,
    context: str,
    coordinator_messages: list[dict],
    coordinator_system: str,
    delegate_tool_call_id: str,
    session_id: str,
    session_state: SessionState,
    provider: LLMProvider,
    db: AsyncSession,
    event_queue: asyncio.Queue | None = None,
    cancel_event: asyncio.Event | None = None,
) -> "AgentResult | str":
    """Run a specialist sub-agent. Returns AgentResult if confirmation needed, else reply string."""
    from llm.skills import discover_skills

    skills = discover_skills(_get_user_skill_dirs())
    skill = skills.get(skill_name)
    if skill is None:
        available = ", ".join(skills.keys())
        return f"Unknown skill: {skill_name!r}. Available: {available}"

    await _emit(event_queue, StatusUpdate(message=f"Delegating to {skill_name}..."))

    # Build fresh messages for specialist
    user_content = f"Task: {task}"
    if context:
        user_content += f"\n\nContext: {context}"
    specialist_messages = [{"role": "user", "content": user_content}]

    # Build specialist system prompt with session state
    specialist_system = skill.system_prompt
    if session_state.active_project:
        specialist_system += f"\n\nActive project: {session_state.active_project}"

    specialist_tools = skill.tools if session_state.active_project else NO_PROJECT_TOOLS

    # Use skill's preferred model if set
    effective_provider = provider
    if skill.preferred_model:
        from llm.router import get_specialist_provider

        effective_provider = get_specialist_provider(model=skill.preferred_model)

    logger.info(
        "Running skill: %s session=%s task=%s",
        skill_name,
        session_id,
        task[:100],
    )

    result = await run_agent(
        provider=effective_provider,
        messages=specialist_messages,
        system=specialist_system,
        session_id=session_id,
        session_state=session_state,
        db=db,
        tools=specialist_tools,
        event_queue=event_queue,
        cancel_event=cancel_event,
    )

    # If specialist needs confirmation, attach coordinator state
    if result.pending:
        result.pending.coordinator_messages = coordinator_messages
        result.pending.coordinator_system = coordinator_system
        result.pending.delegate_tool_call_id = delegate_tool_call_id
        return result

    return result.reply


def _get_user_skill_dirs() -> list:
    """Return user skill directories from config (if any)."""
    from pathlib import Path

    from llm.config import settings

    user_dir = Path(settings.astryn_skills_dir).expanduser()
    return [user_dir] if user_dir.is_dir() else []


async def _resume_coordinator(
    provider: LLMProvider,
    specialist_reply: str,
    coordinator_messages: list[dict],
    coordinator_system: str,
    delegate_tool_call_id: str,
    session_id: str,
    session_state: SessionState,
    db: AsyncSession,
    specialist_provider: LLMProvider | None = None,
    event_queue: asyncio.Queue | None = None,
) -> AgentResult:
    """Resume the coordinator after a specialist completes."""
    await _emit(event_queue, StatusUpdate(message="Specialist complete, resuming..."))

    messages = [
        *coordinator_messages,
        {
            "role": "tool",
            "tool_call_id": delegate_tool_call_id,
            "content": specialist_reply,
        },
    ]

    return await run_agent(
        provider=provider,
        messages=messages,
        system=coordinator_system,
        session_id=session_id,
        session_state=session_state,
        db=db,
        tools=COORDINATOR_TOOLS,
        specialist_provider=specialist_provider,
        event_queue=event_queue,
    )


async def _process_tool_calls(
    tool_calls: list[dict],
    messages: list[dict],
    system: str,
    session_id: str,
    session_state: SessionState,
    provider: LLMProvider,
    db: AsyncSession,
    specialist_provider: LLMProvider | None = None,
    event_queue: asyncio.Queue | None = None,
    cancel_event: asyncio.Event | None = None,
) -> "list[dict] | AgentResult":
    """Process a batch of tool calls sequentially.

    Runs safe tools immediately. Pauses on tools that require confirmation.
    Handles delegate tool by spinning up specialist sub-agents.
    Logs each execution to the tool_audit table.
    """
    for i, tool_call in enumerate(tool_calls):
        fn = tool_call.get("function", {})
        tool_name = fn.get("name", "")
        raw_args = fn.get("arguments", {})
        try:
            tool_args = raw_args if isinstance(raw_args, dict) else json.loads(raw_args)
        except (json.JSONDecodeError, TypeError) as e:
            logger.warning("Invalid tool arguments for %s: %s", tool_name, e)
            tool_call_id = tool_call.get("id") or str(uuid.uuid4())
            messages = [
                *messages,
                {
                    "role": "tool",
                    "tool_call_id": tool_call_id,
                    "content": f"Invalid arguments: {e}",
                },
            ]
            continue
        tool_call_id = tool_call.get("id") or str(uuid.uuid4())

        # Handle delegate tool specially
        if tool_name == "delegate":
            # Accept both "skill" (new) and "specialist" (legacy) field names
            skill_name = tool_args.get("skill") or tool_args.get("specialist", "")
            logger.info(
                "Coordinator delegating to skill: %s session=%s",
                skill_name,
                session_id,
            )
            # Use specialist_provider for the delegate sub-agent
            delegate_provider = specialist_provider or provider
            outcome = await _run_specialist(
                skill_name=skill_name,
                task=tool_args.get("task", ""),
                context=tool_args.get("context", ""),
                coordinator_messages=messages,
                coordinator_system=system,
                delegate_tool_call_id=tool_call_id,
                session_id=session_id,
                session_state=session_state,
                provider=delegate_provider,
                db=db,
                event_queue=event_queue,
                cancel_event=cancel_event,
            )

            if isinstance(outcome, AgentResult):
                # Specialist needs confirmation — bubble up
                return outcome

            # Specialist completed — log and feed reply as tool result
            await repo.log_tool_call(
                db=db,
                external_id=session_id,
                tool_name="delegate",
                tool_args=tool_args,
                result=outcome[:2000] if len(outcome) > 2000 else outcome,
            )
            messages = [
                *messages,
                {"role": "tool", "tool_call_id": tool_call_id, "content": outcome},
            ]
            continue

        if requires_confirmation(tool_name, tool_args, session_state):
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
        await _emit(event_queue, ToolStart(tool_name=tool_name, tool_args=tool_args))

        tool_error = None
        try:
            result = await execute_tool(tool_name, tool_args, session_state)
        except Exception as e:
            logger.error("Tool execution failed: %s error=%s", tool_name, e)
            result = f"Tool execution failed: {e}"
            tool_error = str(e)

        summary = result[:200] if len(result) > 200 else result
        await _emit(event_queue, ToolResult(tool_name=tool_name, summary=summary))

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
