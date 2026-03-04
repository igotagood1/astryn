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

from handlers.callbacks import handle_confirmation, handle_model_select
from handlers.commands import cmd_clear, cmd_help, cmd_model, cmd_status
from handlers.message import handle_message

load_dotenv()

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
if not TOKEN:
    raise RuntimeError("TELEGRAM_BOT_TOKEN environment variable is not set")


class _RedactSecretsFilter(logging.Filter):
    """
    Scrubs secrets from every log record on every logger.
    Applied to the root logger so nothing slips through regardless of
    which logger emits the message or what level it runs at.
    """

    def __init__(self, secrets: list[str]):
        super().__init__()
        self._secrets = [s for s in secrets if s]

    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        for secret in self._secrets:
            msg = msg.replace(secret, "<REDACTED>")
        record.msg = msg
        record.args = ()
        return True


logging.basicConfig(level=logging.INFO)
_secrets_filter = _RedactSecretsFilter([TOKEN, os.getenv("ASTRYN_CORE_API_KEY")])
for handler in logging.root.handlers:
    handler.addFilter(_secrets_filter)


def main():
    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("clear", cmd_clear))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("model", cmd_model))
    app.add_handler(CallbackQueryHandler(handle_confirmation, pattern=r"^confirm:"))
    app.add_handler(CallbackQueryHandler(handle_model_select, pattern=r"^model_select:"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("Starting Astryn Telegram bot (polling mode)...")
    app.run_polling()


if __name__ == "__main__":
    main()
