import os
from telegram import Update
from telegram.ext import ContextTypes
from core_client import send_message

ALLOWED_USER_ID = int(os.getenv('ALLOWED_USER_ID', '0'))


async def handle_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    if user_id != ALLOWED_USER_ID:
        await update.message.reply_text('Not authorised.')
        return

    user_text = update.message.text
    session_id = str(user_id)

    await update.message.chat.send_action('typing')

    try:
        result = await send_message(user_text, session_id)
        reply = result['reply']

        if len(reply) > 4096:
            for i in range(0, len(reply), 4096):
                await update.message.reply_text(reply[i:i+4096], parse_mode='Markdown')
        else:
            await update.message.reply_text(reply, parse_mode='Markdown')

    except Exception as e:
        await update.message.reply_text(f'❌ Error: {e}')