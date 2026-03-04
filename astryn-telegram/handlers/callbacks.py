import logging

from telegram import Update
from telegram.ext import ContextTypes

import config
from core_client import confirm_tool, set_model
from handlers.message import _send_result

logger = logging.getLogger(__name__)


async def handle_confirmation(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if update.effective_user.id != config.ALLOWED_USER_ID:
        return

    # callback_data format: "confirm:<id>:<action>"
    parts = query.data.split(":")
    if len(parts) != 3:
        return

    _, confirmation_id, action = parts

    # Remove the keyboard so the buttons can't be clicked again
    await query.edit_message_reply_markup(reply_markup=None)

    if action == "context":
        # Cancel the pending tool call and invite the user to add more detail.
        # The agent will see it was rejected and wait for the next message.
        try:
            await confirm_tool(confirmation_id, approved=False)
        except Exception:
            pass  # already expired or cleared — that's fine
        await query.message.reply_text("Go ahead — what would you like to add or change?")
        return

    approved = action == "approve"
    status = "✅ Approved" if approved else "❌ Rejected"
    await query.message.reply_text(f"{status} — working...")

    try:
        result = await confirm_tool(confirmation_id, approved)
        await _send_result(query.message, result)
    except Exception as e:
        logger.error("Error processing confirmation %s: %s", confirmation_id, e)
        await query.message.reply_text(f"❌ Error: {e}")


async def handle_model_select(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if update.effective_user.id != config.ALLOWED_USER_ID:
        return

    # callback_data format: "model_select:<model_name>"
    model_name = query.data[len("model_select:"):]

    try:
        data = await set_model(model_name)
        await query.edit_message_text(f"✅ Switched to `{data['active']}`", parse_mode="Markdown")
    except Exception as e:
        logger.error("Error switching model to %s: %s", model_name, e)
        await query.edit_message_text(f"❌ {e}")
