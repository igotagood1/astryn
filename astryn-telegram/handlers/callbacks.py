import asyncio
import contextlib
import logging

import httpx
from telegram import Update
from telegram.ext import ContextTypes

import config
from core_client import (
    CoreError,
    confirm_tool,
    pull_model,
    set_model,
    set_project_direct,
    update_preference,
)
from handlers.commands import _PREF_LABELS, _PREF_OPTIONS
from handlers.message import _keep_typing, _send_result

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
        # Cancel the pending tool call and invite the user to refine.
        with contextlib.suppress(CoreError, httpx.HTTPStatusError):
            await confirm_tool(confirmation_id, approved=False)
        await query.message.reply_text(
            "Action cancelled. Tell me what you'd like to change and I'll try again."
        )
        return

    approved = action == "approve"
    status = "✅ Approved" if approved else "❌ Rejected"
    await query.message.reply_text(f"{status} — working...")

    typing_task = asyncio.create_task(_keep_typing(query.message.chat))
    try:
        result = await confirm_tool(confirmation_id, approved)
        typing_task.cancel()
        await _send_result(query.message, result)
    except CoreError as e:
        typing_task.cancel()
        await query.message.reply_text(f"❌ {e}")
    except httpx.TimeoutException:
        typing_task.cancel()
        await query.message.reply_text(
            "⏱️ Response timed out. The model may be overloaded — try again in a moment."
        )
    except httpx.ConnectError:
        typing_task.cancel()
        await query.message.reply_text("🔌 Can't reach the backend. Is astryn-core running?")
    except Exception as e:
        typing_task.cancel()
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
            f"Active project: <b>{project_name}</b>\n\nWhat would you like to do?",
            parse_mode="HTML",
        )
    except CoreError as e:
        await query.message.reply_text(f"❌ {e}")
    except httpx.TimeoutException:
        await query.message.reply_text("⏱️ Request timed out. Please try again.")
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
        await query.edit_message_text(
            f"✅ Switched to <code>{data['active']}</code>", parse_mode="HTML"
        )
    except CoreError as e:
        await query.edit_message_text(f"❌ {e}")
    except httpx.TimeoutException:
        await query.edit_message_text("⏱️ Request timed out. Please try again.")
    except Exception as e:
        logger.error("Error switching model to %s: %s", model_name, e)
        await query.edit_message_text("❌ Something went wrong. Please try again.")


async def handle_model_pull_prompt(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Prompt the user to type a model name to pull."""
    query = update.callback_query
    await query.answer()

    if update.effective_user.id != config.ALLOWED_USER_ID:
        return

    await query.edit_message_text(
        "Type the model name to pull (e.g. <code>deepseek-r1:7b</code>).\n\n"
        "Send it as: <code>/pull deepseek-r1:7b</code>",
        parse_mode="HTML",
    )


async def handle_pull_command(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Handle /pull <model> command to pull a model from Ollama registry."""
    if update.effective_user.id != config.ALLOWED_USER_ID:
        return

    args = update.message.text.split(maxsplit=1)
    if len(args) < 2:
        await update.message.reply_text("Usage: /pull <model-name>")
        return

    model_name = args[1].strip()
    await update.message.reply_text(
        f"⬇️ Pulling <code>{model_name}</code>... this may take a while.",
        parse_mode="HTML",
    )

    try:
        result = await pull_model(model_name)
        await update.message.reply_text(
            f"✅ Pulled <code>{model_name}</code> — {result.get('status', 'done')}",
            parse_mode="HTML",
        )
    except CoreError as e:
        await update.message.reply_text(f"❌ {e}")
    except httpx.TimeoutException:
        await update.message.reply_text("⏱️ Pull timed out. The model may be very large.")
    except Exception as e:
        logger.error("Error pulling model %s: %s", model_name, e)
        await update.message.reply_text("❌ Pull failed. Please try again.")


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
        f"<b>{label}</b>\n\nChoose a value:",
        parse_mode="HTML",
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
        await query.edit_message_text(f"✅ {label} set to <b>{value}</b>", parse_mode="HTML")
    except CoreError as e:
        await query.edit_message_text(f"❌ {e}")
    except Exception as e:
        logger.error("Error updating preference %s=%s: %s", field, value, e)
        await query.edit_message_text("❌ Something went wrong. Please try again.")
