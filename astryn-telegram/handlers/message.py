import os

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Message, Update
from telegram.ext import ContextTypes

from core_client import send_message

ALLOWED_USER_ID = int(os.getenv("ALLOWED_USER_ID", "0"))


async def handle_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ALLOWED_USER_ID:
        await update.message.reply_text("Not authorised.")
        return

    session_id = str(update.effective_user.id)
    await update.message.chat.send_action("typing")

    try:
        result = await send_message(update.message.text, session_id)
        await _send_result(update.message, result)
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")


async def _send_result(message: Message, result: dict):
    """Send a chat/confirm result back to a Telegram message."""
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
                ]
            ]
        )
        await _send_chunked(message, text, reply_markup=keyboard)
    else:
        await _send_chunked(message, reply or "(no reply)")


async def _send_chunked(message: Message, text: str, reply_markup=None):
    """Split long text into ≤4096-char chunks. Attach reply_markup to the last chunk."""
    chunks = [text[i : i + 4096] for i in range(0, len(text), 4096)]
    for i, chunk in enumerate(chunks):
        markup = reply_markup if i == len(chunks) - 1 else None
        try:
            await message.reply_text(chunk, parse_mode="Markdown", reply_markup=markup)
        except Exception:
            # Fall back to plain text if Markdown parsing fails
            await message.reply_text(chunk, reply_markup=markup)
