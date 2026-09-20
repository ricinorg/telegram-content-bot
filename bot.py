import logging
from pathlib import Path

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
)

from .ai import AIService
from .config import load_settings
from .db import Database


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

settings = load_settings()
db = Database(settings.database_path)
ai = AIService(
    settings.openai_api_key,
    settings.openai_text_model,
    settings.openai_image_model,
)


def authorized(user_id: int | None) -> bool:
    # If ADMIN_USER_IDS is empty, allow the bot owner during initial setup.
    # Set ADMIN_USER_IDS in production for strict access control.
    return not settings.admin_user_ids or (user_id in settings.admin_user_ids)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_user or not authorized(update.effective_user.id):
        return
    await update.message.reply_text(
        "سلام! 🤖\n\n"
        "ربات مدیریت محتوای شما آماده است.\n\n"
        "/newpost متن درخواست\n"
        "/help راهنما"
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_user or not authorized(update.effective_user.id):
        return
    await update.message.reply_text(
        "دستورها:\n"
        "/start شروع\n"
        "/newpost درخواست تولید پست\n"
        "/help راهنما\n\n"
        "مثال:\n"
        "/newpost یک پست کوتاه درباره هوش مصنوعی بنویس"
    )


async def new_post(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_user or not authorized(update.effective_user.id):
        return

    prompt = " ".join(context.args).strip()
    if not prompt:
        await update.message.reply_text(
            "بعد از /newpost موضوع را بنویس.\n"
            "مثال: /newpost درباره تکنولوژی یک پست جذاب بنویس"
        )
        return

    status = await update.message.reply_text("⏳ در حال تولید متن...")
    try:
        text = ai.generate_text(prompt)
        post_id = db.create_post(prompt, text)
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("✅ انتشار", callback_data=f"publish:{post_id}"),
                InlineKeyboardButton("🗑 رد", callback_data=f"reject:{post_id}"),
            ]
        ])
        await status.edit_text(
            f"📝 پیش‌نمایش پست #{post_id}\n\n{text}",
            reply_markup=keyboard,
        )
    except Exception:
        logger.exception("Text generation failed")
        await status.edit_text("❌ تولید محتوا ناموفق بود. لاگ را بررسی کنید.")


async def callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    if not query.from_user or not authorized(query.from_user.id):
        return

    action, raw_id = query.data.split(":", 1)
    post_id = int(raw_id)
    post = db.get_post(post_id)
    if not post:
        await query.edit_message_text("پست پیدا نشد.")
        return

    if action == "reject":
        db.update_post(post_id, status="rejected")
        await query.edit_message_text(f"🗑 پست #{post_id} رد شد.")
        return

    if action == "publish":
        text = post[2]
        try:
            await context.bot.send_message(
                chat_id=settings.telegram_channel_id,
                text=text,
            )
            db.update_post(post_id, status="published")
            await query.edit_message_text(f"✅ پست #{post_id} منتشر شد.")
        except Exception:
            logger.exception("Publishing failed")
            await query.edit_message_text(
                "❌ انتشار ناموفق بود. مطمئن شوید ربات در کانال ادمین است."
            )


def main() -> None:
    application = (
        Application.builder()
        .token(settings.telegram_bot_token)
        .build()
    )

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("newpost", new_post))
    application.add_handler(CallbackQueryHandler(callback))

    logger.info("Bot is running")
    application.run_polling()


if __name__ == "__main__":
    main()
