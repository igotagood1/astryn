from telegram import Update
from telegram.ext import ContextTypes

from core_client import clear_session, health_check, list_models, set_model


async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "*Astryn Commands*\n\n"
        "Just type anything — no /ask needed\n"
        "/clear — Reset conversation history\n"
        "/status — Check if Ollama is running\n"
        "/model — Show current model\n"
        "/model list — List available models\n"
        "/model use <name> — Switch active model",
        parse_mode="Markdown",
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
    args = ctx.args or []

    if not args:
        try:
            h = await health_check()
            await update.message.reply_text(f"🤖 Model: {h['model']}")
        except Exception:
            await update.message.reply_text("❌ Could not reach core")
        return

    subcmd = args[0].lower()

    if subcmd == "list":
        try:
            data = await list_models()
            active = data["active"]
            lines = [
                f"→ `{m}`" if m == active else f"  `{m}`"
                for m in data["models"]
            ]
            await update.message.reply_text(
                "Available models:\n" + "\n".join(lines),
                parse_mode="Markdown",
            )
        except Exception as e:
            await update.message.reply_text(f"❌ Error: {e}")

    elif subcmd == "use" and len(args) > 1:
        model_name = args[1]
        try:
            data = await set_model(model_name)
            await update.message.reply_text(f"✅ Switched to `{data['active']}`", parse_mode="Markdown")
        except Exception as e:
            await update.message.reply_text(f"❌ {e}")

    else:
        await update.message.reply_text(
            "/model — show current\n"
            "/model list — list available\n"
            "/model use <name> — switch model"
        )
