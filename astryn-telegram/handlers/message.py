import asyncio
import contextlib
import logging
import re
import time
from difflib import get_close_matches
from typing import TypedDict  # used for _ChatResult

import httpx
import telegram.error
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Message, Update
from telegram.ext import ContextTypes

import config
from core_client import CoreError, stream_message
from formatting import markdown_to_telegram_html, strip_markdown
from handlers.commands import (
    cmd_clear,
    cmd_help,
    cmd_model,
    cmd_preferences,
    cmd_projects,
    cmd_status,
)

logger = logging.getLogger(__name__)

# Map of recognised command names to their handlers.
# Fuzzy matching checks plain-text messages against these keys.
_COMMAND_MAP = {
    "help": cmd_help,
    "clear": cmd_clear,
    "status": cmd_status,
    "model": cmd_model,
    "models": cmd_model,
    "projects": cmd_projects,
    "project": cmd_projects,
    "preferences": cmd_preferences,
    "prefs": cmd_preferences,
}


def _fuzzy_command(text: str):
    """Return a command handler if the message looks like a command name, else None.

    Only matches single-word messages so natural sentences never get intercepted.
    Uses difflib with a similarity cutoff so minor typos (modls -> model) still match.
    """
    word = text.strip().lower().lstrip("/")
    if not word or " " in word:
        return None
    if word in _COMMAND_MAP:
        return _COMMAND_MAP[word]
    matches = get_close_matches(word, _COMMAND_MAP.keys(), n=1, cutoff=0.75)
    return _COMMAND_MAP[matches[0]] if matches else None


class _ChatResult(TypedDict, total=False):
    """Shape of the JSON response from POST /chat and POST /confirm/{id}."""

    reply: str
    model: str
    action: dict | None
    fallback_from: str | None


# Per-user busy flags for concurrent message protection
_user_busy: dict[int, bool] = {}
_user_queue: dict[int, list[Update]] = {}

# Stale session threshold (2 hours in seconds)
_STALE_THRESHOLD = 7200

# Edit-in-place streaming config
_EDIT_THROTTLE_MS = 500  # minimum ms between edits
_MIN_CHARS_PER_EDIT = 100  # don't edit for tiny deltas
_TELEGRAM_MAX_LEN = 4000  # leave room under 4096 limit


async def handle_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != config.ALLOWED_USER_ID:
        await update.message.reply_text("Not authorised.")
        return

    # Intercept single-word messages that look like command names
    command_handler = _fuzzy_command(update.message.text)
    if command_handler:
        await command_handler(update, ctx)
        return

    user_id = update.effective_user.id

    # Per-user concurrency: if already processing, queue the message
    if _user_busy.get(user_id):
        _user_queue.setdefault(user_id, []).append(update)
        await update.message.reply_text("Got it — I'll handle this after the current request.")
        return

    _user_busy[user_id] = True
    try:
        await _process_message(update, ctx)

        # Process any queued messages
        while _user_queue.get(user_id):
            queued = _user_queue[user_id].pop(0)
            await _process_message(queued, ctx)
    finally:
        _user_busy[user_id] = False


async def _process_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Process a single message with streaming."""
    session_id = str(update.effective_user.id)

    try:
        await _handle_streaming(update.message, session_id)
    except CoreError as e:
        await update.message.reply_text(f"❌ {e}")
    except httpx.TimeoutException:
        await update.message.reply_text(
            "⏱️ Response timed out. The model may be overloaded — try again in a moment."
        )
    except httpx.ConnectError:
        await update.message.reply_text("🔌 Can't reach the backend. Is astryn-core running?")
    except Exception as e:
        logger.error("Error handling message for session %s: %s", session_id, e)
        await update.message.reply_text("❌ Something went wrong. Please try again.")


async def _handle_streaming(message: Message, session_id: str):
    """Send the message via SSE streaming and edit-in-place."""
    typing_task = asyncio.create_task(_keep_typing(message.chat))

    try:
        accumulated_text = ""
        sent_message: Message | None = None
        last_edit_time = 0.0
        last_edit_len = 0
        status_lines: list[str] = []
        done_data: dict | None = None

        async for event in stream_message(message.text, session_id):
            event_type = event.get("event")

            if event_type == "text_delta":
                accumulated_text += event.get("text", "")

                # Edit the message if enough text has accumulated
                now = time.monotonic()
                chars_since_edit = len(accumulated_text) - last_edit_len
                ms_since_edit = (now - last_edit_time) * 1000

                if chars_since_edit >= _MIN_CHARS_PER_EDIT and ms_since_edit >= _EDIT_THROTTLE_MS:
                    display = _build_display(accumulated_text, status_lines)
                    sent_message = await _edit_or_send(message, sent_message, display)
                    last_edit_time = now
                    last_edit_len = len(accumulated_text)

            elif event_type == "tool_start":
                tool = event.get("tool", "?")
                args = event.get("args", {})
                status = _format_tool_status(tool, args)
                status_lines.append(status)

                display = _build_display(accumulated_text, status_lines)
                sent_message = await _edit_or_send(message, sent_message, display)
                last_edit_time = time.monotonic()

            elif event_type == "tool_result":
                # Remove the tool_start status and add a completion note
                tool = event.get("tool", "?")
                status_lines = [s for s in status_lines if tool not in s]

            elif event_type == "status":
                status_msg = event.get("message", "")
                if status_msg:
                    status_lines.append(f"💬 {status_msg}")
                    display = _build_display(accumulated_text, status_lines)
                    sent_message = await _edit_or_send(message, sent_message, display)
                    last_edit_time = time.monotonic()

            elif event_type == "done":
                done_data = event
                break

            elif event_type == "error":
                typing_task.cancel()
                error_msg = event.get("error", "Unknown error")
                await message.reply_text(f"❌ {error_msg}")
                return

        typing_task.cancel()

        if done_data is None:
            await message.reply_text("❌ Stream ended unexpectedly.")
            return

        # Build final result for _send_result
        result: _ChatResult = {
            "reply": done_data.get("reply", ""),
            "model": done_data.get("model", ""),
            "action": done_data.get("action"),
            "fallback_from": done_data.get("fallback_from"),
        }

        # If we have a pending action (confirmation), send it via the normal handler
        if result.get("action"):
            # If we had a streaming message, do a final edit to show the reply
            if sent_message and result["reply"]:
                await _safe_edit(sent_message, result["reply"])
            await _send_result(message, result)
            return

        # Final edit with the complete response
        final_text = result.get("reply", "") or "(no reply)"

        # Add fallback notice if applicable
        fallback = result.get("fallback_from")
        if fallback:
            final_text += f"\n\n<i>Responded via local model (fallback from {fallback})</i>"

        if sent_message:
            await _safe_edit(sent_message, final_text)
        else:
            await _send_chunked(message, final_text)

    except Exception:
        typing_task.cancel()
        raise


def _format_tool_status(tool_name: str, args: dict) -> str:
    """Format a tool execution status line."""
    match tool_name:
        case "read_file":
            return f"📖 Reading `{args.get('path', '?')}`..."
        case "write_file":
            return f"✏️ Writing `{args.get('path', '?')}`..."
        case "apply_diff":
            return f"✏️ Editing `{args.get('path', '?')}`..."
        case "run_command":
            cmd = args.get("command", "?")
            if len(cmd) > 60:
                cmd = cmd[:57] + "..."
            return f"⚙️ Running `{cmd}`..."
        case "list_files":
            return f"📁 Listing `{args.get('path', '.')}`..."
        case "search_files" | "grep_files":
            return "🔍 Searching..."
        case "delegate":
            skill = args.get("skill", args.get("specialist", "?"))
            return f"🤖 Delegating to {skill}..."
        case _:
            return f"🔧 {tool_name}..."


def _build_display(text: str, status_lines: list[str]) -> str:
    """Build the display text with accumulated content and status lines."""
    parts = []
    if text:
        parts.append(text)
    if status_lines:
        parts.append("\n".join(status_lines))
    return "\n\n".join(parts) if parts else "..."


async def _edit_or_send(
    original: Message,
    sent: Message | None,
    text: str,
) -> Message:
    """Edit the sent message if it exists, otherwise send a new one."""
    if len(text) > _TELEGRAM_MAX_LEN:
        # Text exceeds limit — finalize current message and start new one
        if sent:
            # Finalize with what we have so far
            await _safe_edit(sent, text[:_TELEGRAM_MAX_LEN])
        # Start a new message with the overflow
        return await _safe_send(original, text[_TELEGRAM_MAX_LEN:])

    if sent is None:
        return await _safe_send(original, text)

    await _safe_edit(sent, text)
    return sent


async def _safe_send(message: Message, text: str) -> Message:
    """Send a message with HTML formatting, falling back to plain text."""
    html_text = markdown_to_telegram_html(text)
    try:
        return await message.reply_text(html_text, parse_mode="HTML")
    except telegram.error.BadRequest:
        plain = strip_markdown(text)
        return await message.reply_text(plain)


async def _safe_edit(sent: Message, text: str) -> None:
    """Edit a message with HTML formatting, suppressing errors."""
    html_text = markdown_to_telegram_html(text)
    try:
        await sent.edit_text(html_text, parse_mode="HTML")
    except telegram.error.BadRequest as e:
        # "Message is not modified" is expected when text hasn't changed
        if "not modified" not in str(e).lower():
            try:
                plain = strip_markdown(text)
                await sent.edit_text(plain)
            except telegram.error.BadRequest:
                pass  # give up on this edit


async def _keep_typing(chat, interval: float = 4.0):
    """Resend the typing indicator every `interval` seconds until cancelled."""
    try:
        while True:
            with contextlib.suppress(Exception):
                await chat.send_action("typing")
            await asyncio.sleep(interval)
    except asyncio.CancelledError:
        pass


async def _send_result(message: Message, result: _ChatResult):
    """Send a chat or confirmation result back to the user.

    Dispatches on action["type"] to render the appropriate UI.
    """
    reply = result.get("reply", "")
    action = result.get("action")
    action_type = action.get("type") if action else None

    match action_type:
        case "confirmation":
            preview = action["preview"]
            text = f"{reply}\n\n{preview}".strip() if reply else preview
            keyboard = InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            "✅ Approve",
                            callback_data=f"confirm:{action['id']}:approve",
                        ),
                        InlineKeyboardButton(
                            "❌ Reject",
                            callback_data=f"confirm:{action['id']}:reject",
                        ),
                    ],
                    [
                        InlineKeyboardButton(
                            "✏️ Request changes",
                            callback_data=f"confirm:{action['id']}:context",
                        ),
                    ],
                ]
            )
            await _send_chunked(message, text, reply_markup=keyboard)

        case "project_select":
            rows = [
                [InlineKeyboardButton(p, callback_data=f"project:{p}")] for p in action["projects"]
            ]
            keyboard = InlineKeyboardMarkup(rows)
            await _send_chunked(message, reply or "Choose a project:", reply_markup=keyboard)

        case _:
            text = reply or "(no reply)"
            fallback = result.get("fallback_from")
            if fallback:
                text += f"\n\n<i>Responded via local model (fallback from {fallback})</i>"
            await _send_chunked(message, text)


def _split_message(text: str, max_len: int = 4096) -> list[str]:
    """Split text into chunks respecting newlines and code block boundaries."""
    if len(text) <= max_len:
        return [text]

    chunks: list[str] = []
    remaining = text
    in_code_block = False
    code_open_tag = ""

    while remaining:
        if len(remaining) <= max_len:
            chunks.append(remaining)
            break

        # Find the best split point: last newline within max_len
        split_at = remaining.rfind("\n", 0, max_len)
        if split_at <= 0:
            chunk = remaining[:max_len]
            remaining = remaining[max_len:]
        else:
            chunk = remaining[:split_at]
            remaining = remaining[split_at + 1 :]

        # Track code block state within this chunk
        for line in chunk.split("\n"):
            stripped = line.strip()
            if not in_code_block and ("<pre>" in stripped or "<pre><code" in stripped):
                in_code_block = True
                pre_match = re.search(r"(<pre>(?:<code[^>]*>)?)", stripped)
                code_open_tag = pre_match.group(1) if pre_match else "<pre>"
            if "</pre>" in stripped or "</code></pre>" in stripped:
                in_code_block = False
                code_open_tag = ""
            if stripped.startswith("```"):
                if not in_code_block:
                    in_code_block = True
                    lang = stripped[3:].strip()
                    code_open_tag = f"```{lang}" if lang else "```"
                else:
                    in_code_block = False
                    code_open_tag = ""

        if in_code_block:
            if code_open_tag.startswith("<pre>"):
                close = "</code></pre>" if "<code" in code_open_tag else "</pre>"
                chunk += f"\n{close}"
                remaining = f"{code_open_tag}\n{remaining}"
            else:
                chunk += "\n```"
                remaining = f"{code_open_tag}\n{remaining}"

        chunks.append(chunk)

    return chunks


async def _send_chunked(message: Message, text: str, reply_markup=None):
    """Split long text into Telegram's 4096-char limit and send each chunk."""
    html_text = markdown_to_telegram_html(text)
    chunks = _split_message(html_text)
    for i, chunk in enumerate(chunks):
        markup = reply_markup if i == len(chunks) - 1 else None
        try:
            await message.reply_text(chunk, parse_mode="HTML", reply_markup=markup)
        except telegram.error.BadRequest:
            logger.debug("HTML parse failed for chunk, falling back to plain text")
            plain = strip_markdown(text) if i == 0 else strip_markdown(chunk)
            plain_chunks = _split_message(plain)
            for j, pc in enumerate(plain_chunks):
                m = markup if j == len(plain_chunks) - 1 else None
                await message.reply_text(pc, reply_markup=m)
            break
