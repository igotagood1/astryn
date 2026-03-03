from telegram import Update
from telegram.ext import ContextTypes
from core_client import health_check, clear_session


async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        '🌟 *Astryn Commands*\n\n'
        'Just type anything — no /ask needed\n'
        '/clear — Reset conversation history\n'
        '/status — Check if Ollama is running\n'
        '/model — Show current model',
        parse_mode='Markdown',
    )


async def cmd_clear(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    session_id = str(update.effective_user.id)
    await clear_session(session_id)
    await update.message.reply_text('🗑️ Conversation cleared.')


async def cmd_status(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try:
        h = await health_check()
        emoji = '✅' if h['ollama'] == 'up' else '⚠️'
        await update.message.reply_text(
            f"{emoji} Status: {h['status']}\n"
            f"Ollama: {h['ollama']}\n"
            f"Model: {h['model']}"
        )
    except Exception as e:
        await update.message.reply_text(f'❌ Core unreachable: {e}')


async def cmd_model(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try:
        h = await health_check()
        await update.message.reply_text(f"🤖 Model: {h['model']}")
    except Exception:
        await update.message.reply_text('❌ Could not reach core')