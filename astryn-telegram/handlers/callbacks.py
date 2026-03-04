import contextlib
import logging

import httpx
from telegram import Update
from telegram.ext import ContextTypes

import config
from core_client import CoreError, confirm_tool, set_model, set_project_direct, update_preference
from handlers.commands import _PREF_LABELS, _PREF_OPTIONS
from handlers.message import _send_result  # used by handle_confirmation

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
        with contextlib.suppress(CoreError, httpx.HTTPStatusError):
            await confirm_tool(confirmation_id, approved=False)
        await query.message.reply_text("Go ahead — what would you like to add or change?")
        return

    approved = action == "approve"
    status = "✅ Approved" if approved else "❌ Rejected"
    await query.message.reply_text(f"{status} — working...")

    try:
        result = await confirm_tool(confirmation_id, approved)
        await _send_result(query.message, result)
    except CoreError as e:
        await query.message.reply_text(f"❌ {e}")
    except Exception as e:
        logger.error("Error processing confirmation %s: %s", confirmation_id, e)
        await query.message.reply_text("❌ Something went wrong. Please try again.")


async def handle_project_select(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if update.effective_user.id != config.ALLOWED_USER_ID:
        return

    # callback_data format: "project:<name>"
    project_name = query.data[len("project:") :]
    session_id = str(update.effective_user.id)

    await query.edit_message_reply_markup(reply_markup=None)

    try:
        await set_project_direct(project_name, session_id)
        await query.message.reply_text(
            f"Active project: *{project_name}*\n\nWhat would you like to do?",
            parse_mode="Markdown",
        )
    except CoreError as e:
        await query.message.reply_text(f"❌ {e}")
    except Exception as e:
        logger.error("Error selecting project %s: %s", project_name, e)
        await query.message.reply_text("❌ Something went wrong. Please try again.")


async def handle_model_select(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if update.effective_user.id != config.ALLOWED_USER_ID:
        return

    # callback_data format: "model_select:<model_name>"
    model_name = query.data[len("model_select:") :]

    try:
        data = await set_model(model_name)
        await query.edit_message_text(f"✅ Switched to `{data['active']}`", parse_mode="Markdown")
    except CoreError as e:
        await query.edit_message_text(f"❌ {e}")
    except Exception as e:
        logger.error("Error switching model to %s: %s", model_name, e)
        await query.edit_message_text("❌ Something went wrong. Please try again.")


async def handle_pref_menu(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Show options for a specific preference field."""
    query = update.callback_query
    await query.answer()

    if update.effective_user.id != config.ALLOWED_USER_ID:
        return

    # callback_data format: "pref_menu:<field>"
    field = query.data[len("pref_menu:") :]
    label = _PREF_LABELS.get(field, field)
    options = _PREF_OPTIONS.get(field, [])

    from telegram import InlineKeyboardButton, InlineKeyboardMarkup

    buttons = [
        [InlineKeyboardButton(opt, callback_data=f"pref_set:{field}:{opt}")] for opt in options
    ]

    await query.edit_message_text(
        f"*{label}*\n\nChoose a value:",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(buttons),
    )


async def handle_pref_set(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Apply a preference value and confirm."""
    query = update.callback_query
    await query.answer()

    if update.effective_user.id != config.ALLOWED_USER_ID:
        return

    # callback_data format: "pref_set:<field>:<value>"
    parts = query.data.split(":", 2)
    if len(parts) != 3:
        return
    _, field, value = parts
    session_id = str(update.effective_user.id)

    # Convert "true"/"false" strings for boolean field
    actual_value: str | bool = value
    if field == "proactive_suggestions":
        actual_value = value == "true"

    try:
        await update_preference(session_id, field, actual_value)
        label = _PREF_LABELS.get(field, field)
        await query.edit_message_text(f"✅ {label} set to *{value}*", parse_mode="Markdown")
    except CoreError as e:
        await query.edit_message_text(f"❌ {e}")
    except Exception as e:
        logger.error("Error updating preference %s=%s: %s", field, value, e)
        await query.edit_message_text("❌ Something went wrong. Please try again.")
