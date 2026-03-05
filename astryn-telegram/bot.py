import logging

from telegram.ext import (
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    MessageHandler,
    filters,
)

# config must be imported before handlers so env vars are loaded and validated
# before any other module tries to read them.
import config
from core_client import close_client
from handlers.callbacks import (
    handle_confirmation,
    handle_model_pull_prompt,
    handle_model_select,
    handle_pref_menu,
    handle_pref_set,
    handle_project_select,
    handle_pull_command,
)
from handlers.commands import (
    cmd_clear,
    cmd_help,
    cmd_model,
    cmd_preferences,
    cmd_projects,
    cmd_status,
)
from handlers.message import handle_message


async def _on_shutdown(_app):
    """Clean up the persistent HTTP client."""
    await close_client()


class _RedactSecretsFilter(logging.Filter):
    """Scrubs secrets from every log record before it is emitted.

    Applied to the root logger so nothing leaks regardless of which logger
    emits the message or what level it runs at.
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
_secrets_filter = _RedactSecretsFilter([config.TELEGRAM_BOT_TOKEN, config.ASTRYN_CORE_API_KEY])
for handler in logging.root.handlers:
    handler.addFilter(_secrets_filter)

logger = logging.getLogger(__name__)


def main():
    app = ApplicationBuilder().token(config.TELEGRAM_BOT_TOKEN).build()

    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("clear", cmd_clear))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("model", cmd_model))
    app.add_handler(CommandHandler("projects", cmd_projects))
    app.add_handler(CommandHandler("preferences", cmd_preferences))
    app.add_handler(CommandHandler("pull", handle_pull_command))
    app.add_handler(CallbackQueryHandler(handle_confirmation, pattern=r"^confirm:"))
    app.add_handler(CallbackQueryHandler(handle_model_select, pattern=r"^model_select:"))
    app.add_handler(CallbackQueryHandler(handle_model_pull_prompt, pattern=r"^model_pull_prompt$"))
    app.add_handler(CallbackQueryHandler(handle_project_select, pattern=r"^project:"))
    app.add_handler(CallbackQueryHandler(handle_pref_menu, pattern=r"^pref_menu:"))
    app.add_handler(CallbackQueryHandler(handle_pref_set, pattern=r"^pref_set:"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    app.post_shutdown = _on_shutdown

    logger.info("Starting Astryn Telegram bot (polling mode)...")
    app.run_polling()


if __name__ == "__main__":
    main()
