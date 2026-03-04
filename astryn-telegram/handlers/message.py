import logging
from difflib import get_close_matches
from typing import TypedDict  # used for _ChatResult

import telegram.error
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Message, Update
from telegram.ext import ContextTypes

import config
from core_client import CoreError, send_message
from handlers.commands import cmd_clear, cmd_help, cmd_model, cmd_projects, cmd_status

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
    await update.message.chat.send_action("typing")

    try:
        result: _ChatResult = await send_message(update.message.text, session_id)
        await _send_result(update.message, result)
    except CoreError as e:
        await update.message.reply_text(f"❌ {e}")
    except Exception as e:
        logger.error("Error handling message for session %s: %s", session_id, e)
        await update.message.reply_text("❌ Something went wrong. Please try again.")


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
                            "💬 More context",
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


async def _send_chunked(message: Message, text: str, reply_markup=None):
    """Split long text into Telegram's 4096-char limit and send each chunk.

    Attaches reply_markup to the last chunk only. Falls back to plain text
    if Markdown parsing fails for a chunk (e.g. unbalanced backticks).
    """
    chunks = [text[i : i + 4096] for i in range(0, len(text), 4096)]
    for i, chunk in enumerate(chunks):
        markup = reply_markup if i == len(chunks) - 1 else None
        try:
            await message.reply_text(chunk, parse_mode="Markdown", reply_markup=markup)
        except telegram.error.BadRequest:
            logger.debug("Markdown parse failed for chunk, falling back to plain text")
            await message.reply_text(chunk, reply_markup=markup)
