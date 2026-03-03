import os
import logging

from dotenv import load_dotenv
from telegram.ext import (
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    MessageHandler,
    filters,
)

from handlers.callbacks import handle_confirmation
from handlers.commands import cmd_clear, cmd_help, cmd_model, cmd_status
from handlers.message import handle_message

load_dotenv()
logging.basicConfig(level=logging.INFO)

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")


def main():
    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("clear", cmd_clear))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("model", cmd_model))
    app.add_handler(CallbackQueryHandler(handle_confirmation, pattern=r"^confirm:"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("Starting Astryn Telegram bot (polling mode)...")
    app.run_polling()


if __name__ == "__main__":
    main()
