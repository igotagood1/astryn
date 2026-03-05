import asyncio
import contextlib
import logging
import re
from difflib import get_close_matches
from typing import TypedDict  # used for _ChatResult

import httpx
import telegram.error
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Message, Update
from telegram.ext import ContextTypes

import config
from core_client import CoreError, send_message
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
    Uses difflib with a similarity cutoff so minor typos (modls → model) still match.
    """
    word = text.strip().lower().lstrip("/")
    if not word or " " in word:
        return None
    if word in _COMMAND_MAP:
        return _COMMAND_MAP[word]
    matches = get_close_matches(word, _COMMAND_MAP.keys(), n=1, cutoff=0.75)
    return _COMMAND_MAP[matches[0]] if matches else None


class _ChatResult(TypedDict, total=False):
    """Shape of the JSON response from POST /chat and POST /confirm/{id}.

    `total=False` means all fields are optional to the type checker.
    In practice, reply and model are always present.
    action is present when the agent needs the client to render something
    (a confirmation prompt, a project picker, etc.). Its `type` field
    determines which keys to expect alongside it.
    """

    reply: str
    model: str
    action: dict | None  # typed as dict; dispatch via action["type"]


async def handle_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != config.ALLOWED_USER_ID:
        await update.message.reply_text("Not authorised.")
        return

    # Intercept single-word messages that look like command names so the user
    # doesn't have to type a slash or spell things perfectly.
    command_handler = _fuzzy_command(update.message.text)
    if command_handler:
        await command_handler(update, ctx)
        return

    session_id = str(update.effective_user.id)
    typing_task = asyncio.create_task(_keep_typing(update.message.chat))

    try:
        result: _ChatResult = await send_message(update.message.text, session_id)
        typing_task.cancel()
        await _send_result(update.message, result)
    except CoreError as e:
        typing_task.cancel()
        await update.message.reply_text(f"❌ {e}")
    except httpx.TimeoutException:
        typing_task.cancel()
        await update.message.reply_text(
            "⏱️ Response timed out. The model may be overloaded — try again in a moment."
        )
    except httpx.ConnectError:
        typing_task.cancel()
        await update.message.reply_text(
            "🔌 Can't reach the backend. Is astryn-core running?"
        )
    except Exception as e:
        typing_task.cancel()
        logger.error("Error handling message for session %s: %s", session_id, e)
        await update.message.reply_text("❌ Something went wrong. Please try again.")


async def _keep_typing(chat, interval: float = 4.0):
    """Resend the typing indicator every `interval` seconds until cancelled.

    Telegram's typing indicator expires after ~5 seconds. This keeps it
    visible for the entire duration of a long-running core request.
    """
    try:
        while True:
            with contextlib.suppress(Exception):
                await chat.send_action("typing")
            await asyncio.sleep(interval)
    except asyncio.CancelledError:
        pass


async def _send_result(message: Message, result: _ChatResult):
    """Send a chat or confirmation result back to the user.

    Dispatches on action["type"] to render the appropriate UI. Adding a new
    interactive response type means adding a new case here and a new Action
    subclass in astryn-core's schemas — nothing else needs to change.
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
            await _send_chunked(message, reply or "(no reply)")


def _split_message(text: str, max_len: int = 4096) -> list[str]:
    """Split text into chunks respecting newlines and code block boundaries.

    Handles both HTML <pre> tags and markdown ``` fences. When a split
    occurs inside a code block, the current chunk gets a closing tag and
    the next chunk reopens it.
    """
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
            # No newline found — hard split at max_len (no char to skip)
            chunk = remaining[:max_len]
            remaining = remaining[max_len:]
        else:
            chunk = remaining[:split_at]
            remaining = remaining[split_at + 1 :]  # skip the newline

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
    """Split long text into Telegram's 4096-char limit and send each chunk.

    Converts markdown to Telegram HTML. Falls back to stripped plain text
    if HTML parsing fails.
    """
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
