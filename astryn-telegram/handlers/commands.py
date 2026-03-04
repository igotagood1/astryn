from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
import logging

logger = logging.getLogger(__name__)
from telegram.ext import ContextTypes

from core_client import clear_session, get_projects, health_check, list_models, set_model


async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "*Astryn Commands*\n\n"
        "Just type anything — no /ask needed\n"
        "/projects — Pick a project to work on\n"
        "/clear — Reset conversation history\n"
        "/status — Check if Ollama is running\n"
        "/model — Show and switch models",
        parse_mode="Markdown",
    )


async def cmd_projects(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try:
        projects = await get_projects()
    except Exception as e:
        await update.message.reply_text(f"❌ Could not fetch projects: {e}")
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
    await clear_session(session_id)
    await update.message.reply_text("🗑️ Conversation cleared.")


async def cmd_status(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try:
        h = await health_check()
        emoji = "✅" if h["ollama"] == "up" else "⚠️"
        await update.message.reply_text(
            f"{emoji} Status: {h['status']}\n"
            f"Ollama: {h['ollama']}\n"
            f"Model: {h['model']}"
        )
    except Exception as e:
        await update.message.reply_text(f"❌ Core unreachable: {e}")


async def cmd_model(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try:
        data = await list_models()
    except Exception as e:
        await update.message.reply_text(f"❌ Could not reach core: {e}")
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
