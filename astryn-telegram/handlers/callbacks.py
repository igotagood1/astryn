import os

from telegram import Update
from telegram.ext import ContextTypes

from core_client import confirm_tool
from handlers.message import _send_result

ALLOWED_USER_ID = int(os.getenv("ALLOWED_USER_ID", "0"))


async def handle_confirmation(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if update.effective_user.id != ALLOWED_USER_ID:
        return

    # callback_data format: "confirm:<id>:<action>"
    parts = query.data.split(":")
    if len(parts) != 3:
        return

    _, confirmation_id, action = parts
    approved = action == "approve"

    # Remove the keyboard so the buttons can't be clicked again
    await query.edit_message_reply_markup(reply_markup=None)

    status = "✅ Approved" if approved else "❌ Rejected"
    await query.message.reply_text(f"{status} — working...")

    try:
        result = await confirm_tool(confirmation_id, approved)
        await _send_result(query.message, result)
    except Exception as e:
        await query.message.reply_text(f"❌ Error: {e}")
