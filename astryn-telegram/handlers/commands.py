import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from core_client import (
    CoreError,
    clear_session,
    get_preferences,
    get_projects,
    health_check,
    list_models,
)

logger = logging.getLogger(__name__)


async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "*Astryn Commands*\n\n"
        "Just type anything — no /ask needed\n"
        "/projects — Pick a project to work on\n"
        "/clear — Reset conversation history\n"
        "/status — Check if Ollama is running\n"
        "/model — Show and switch models\n"
        "/preferences — Communication style settings",
        parse_mode="Markdown",
    )


async def cmd_projects(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try:
        projects = await get_projects()
    except CoreError as e:
        await update.message.reply_text(f"❌ {e}")
        return
    except Exception as e:
        logger.error("Error fetching projects: %s", e)
        await update.message.reply_text("❌ Something went wrong. Please try again.")
        return

    if not projects:
        await update.message.reply_text("No projects found in ~/repos.")
        return

    rows = [[InlineKeyboardButton(p, callback_data=f"project:{p}")] for p in projects]
    await update.message.reply_text(
        "Choose a project:",
        reply_markup=InlineKeyboardMarkup(rows),
    )


async def cmd_clear(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    session_id = str(update.effective_user.id)
    try:
        await clear_session(session_id)
    except CoreError as e:
        await update.message.reply_text(f"❌ {e}")
        return
    except Exception as e:
        logger.error("Error clearing session %s: %s", session_id, e)
        await update.message.reply_text("❌ Something went wrong. Please try again.")
        return
    await update.message.reply_text("🗑️ Conversation cleared.")


async def cmd_status(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try:
        h = await health_check()
        emoji = "✅" if h["ollama"] == "up" else "⚠️"
        await update.message.reply_text(
            f"{emoji} Status: {h['status']}\nOllama: {h['ollama']}\nModel: {h['model']}"
        )
    except CoreError as e:
        await update.message.reply_text(f"❌ {e}")
    except Exception as e:
        logger.error("Error checking status: %s", e)
        await update.message.reply_text("❌ Core unreachable. Please try again.")


async def cmd_model(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try:
        data = await list_models()
    except CoreError as e:
        await update.message.reply_text(f"❌ {e}")
        return
    except Exception as e:
        logger.error("Error fetching models: %s", e)
        await update.message.reply_text("❌ Something went wrong. Please try again.")
        return

    active = data["active"]
    models = data["models"]

    buttons = [
        [InlineKeyboardButton(f"✅ {m}" if m == active else m, callback_data=f"model_select:{m}")]
        for m in models
    ]

    await update.message.reply_text(
        f"Active: `{active}`\n\nTap to switch:",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(buttons),
    )


_PREF_LABELS = {
    "verbosity": "Verbosity",
    "tone": "Tone",
    "code_explanation": "Code explanations",
    "proactive_suggestions": "Proactive suggestions",
}

_PREF_OPTIONS = {
    "verbosity": ["concise", "balanced", "detailed"],
    "tone": ["casual", "professional"],
    "code_explanation": ["minimal", "explain", "teach"],
    "proactive_suggestions": ["true", "false"],
}


async def cmd_preferences(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    session_id = str(update.effective_user.id)
    try:
        prefs = await get_preferences(session_id)
    except CoreError as e:
        await update.message.reply_text(f"❌ {e}")
        return
    except Exception as e:
        logger.error("Error fetching preferences: %s", e)
        await update.message.reply_text("❌ Something went wrong. Please try again.")
        return

    buttons = []
    for field, label in _PREF_LABELS.items():
        current = str(prefs[field]).lower()
        buttons.append(
            [InlineKeyboardButton(f"{label}: {current}", callback_data=f"pref_menu:{field}")]
        )

    await update.message.reply_text(
        "*Communication Preferences*\n\nTap a setting to change it:",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(buttons),
    )
