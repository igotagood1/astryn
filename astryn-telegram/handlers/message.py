import logging
from typing import TypedDict

import telegram.error
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Message, Update
from telegram.ext import ContextTypes

import config
from core_client import send_message

logger = logging.getLogger(__name__)


class _ConfirmationData(TypedDict):
    """Shape of the confirmation object inside a ChatResult."""

    id: str
    preview: str


class _ChatResult(TypedDict, total=False):
    """Shape of the JSON response from POST /chat and POST /confirm/{id}.

    `total=False` means the type checker treats all fields as optional.
    In practice, reply and model are always present. confirmation is only
    included when the agent is paused waiting for user approval.
    """

    reply: str
    model: str
    confirmation: _ConfirmationData | None


async def handle_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != config.ALLOWED_USER_ID:
        await update.message.reply_text("Not authorised.")
        return

    session_id = str(update.effective_user.id)
    await update.message.chat.send_action("typing")

    try:
        result: _ChatResult = await send_message(update.message.text, session_id)
        await _send_result(update.message, result)
    except Exception as e:
        logger.error("Error handling message for session %s: %s", session_id, e)
        await update.message.reply_text(f"❌ Error: {e}")


async def _send_result(message: Message, result: _ChatResult):
    """Send a chat or confirmation result back to the user."""
    reply = result.get("reply", "")
    confirmation = result.get("confirmation")

    if confirmation:
        preview = confirmation["preview"]
        text = f"{reply}\n\n{preview}".strip() if reply else preview
        keyboard = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "✅ Approve",
                        callback_data=f"confirm:{confirmation['id']}:approve",
                    ),
                    InlineKeyboardButton(
                        "❌ Reject",
                        callback_data=f"confirm:{confirmation['id']}:reject",
                    ),
                ],
                [
                    InlineKeyboardButton(
                        "💬 More context",
                        callback_data=f"confirm:{confirmation['id']}:context",
                    ),
                ],
            ]
        )
        await _send_chunked(message, text, reply_markup=keyboard)
    else:
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
