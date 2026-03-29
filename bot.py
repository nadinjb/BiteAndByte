"""BiteAndByte — The Ultimate Bio-Hacking & Health Telegram Bot.

Powered by Gemini 1.5 Flash/Pro + Google Sheets.
"""

import logging

from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ConversationHandler,
    MessageHandler,
    filters,
)

import config
import handlers

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


def main() -> None:
    if not config.TELEGRAM_BOT_TOKEN:
        raise SystemExit("TELEGRAM_BOT_TOKEN is not set. Check your .env file.")
    if not config.GOOGLE_SHEET_ID:
        raise SystemExit("GOOGLE_SHEET_ID is not set. Check your .env file.")
    if not config.GEMINI_API_KEY:
        raise SystemExit("GEMINI_API_KEY is not set. Check your .env file.")

    app = ApplicationBuilder().token(config.TELEGRAM_BOT_TOKEN).build()

    # --- Conversation handlers ---

    profile_conv = ConversationHandler(
        entry_points=[CommandHandler("start", handlers.start_command)],
        states={
            handlers.NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, handlers.get_name)],
            handlers.AGE: [MessageHandler(filters.TEXT & ~filters.COMMAND, handlers.get_age)],
            handlers.GENDER: [MessageHandler(filters.TEXT & ~filters.COMMAND, handlers.get_gender)],
            handlers.HEIGHT: [MessageHandler(filters.TEXT & ~filters.COMMAND, handlers.get_height)],
            handlers.WEIGHT: [MessageHandler(filters.TEXT & ~filters.COMMAND, handlers.get_weight)],
        },
        fallbacks=[CommandHandler("cancel", handlers.cancel)],
    )

    blood_conv = ConversationHandler(
        entry_points=[CommandHandler("upload_blood", handlers.upload_blood_command)],
        states={
            handlers.BLOOD_INPUT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handlers.blood_input_handler),
            ],
        },
        fallbacks=[CommandHandler("cancel", handlers.cancel)],
    )

    app.add_handler(profile_conv)
    app.add_handler(blood_conv)

    # --- Simple command handlers ---

    app.add_handler(CommandHandler("log_food", handlers.log_food_command))
    app.add_handler(CommandHandler("log_water", handlers.log_water_command))
    app.add_handler(CommandHandler("log_workout", handlers.log_workout_command))
    app.add_handler(CommandHandler("log_scale", handlers.log_scale_command))
    app.add_handler(CommandHandler("log_cycle", handlers.log_cycle_command))
    app.add_handler(CommandHandler("log_wearable", handlers.log_wearable_command))
    app.add_handler(CommandHandler("status", handlers.status_command))
    app.add_handler(CommandHandler("review", handlers.review_command))

    # --- Photo handler (food / blood / scale detection) ---

    app.add_handler(MessageHandler(filters.PHOTO, handlers.photo_handler))

    logger.info("BiteAndByte bot starting...")
    app.run_polling()


if __name__ == "__main__":
    main()
