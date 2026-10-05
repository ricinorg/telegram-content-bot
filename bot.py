import logging
import os
from datetime import datetime, timedelta, timezone

from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Update,
)
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from ai import AIService, AIServiceError
from config import load_settings
from db import Database


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)

logger = logging.getLogger("telegram-content-bot")

settings = load_settings()

db = Database(settings.database_path)

ai = AIService(
    key=settings.gemini_api_key,
    text_model=settings.gemini_model,
)


def is_admin(user_id):
    if not settings.admin_user_ids:
        return False

    return user_id in settings.admin_user_ids


async def deny(update: Update):
    if update.effective_message:
        await update.effective_message.reply_text(
            "⛔ شما دسترسی ادمین ندارید."
        )


async def publish_post(
    context: ContextTypes.DEFAULT_TYPE,
    post_id: int,
):
    post = db.get_post(post_id)

    if not post:
        raise RuntimeError(
            f"Post {post_id} پیدا نشد."
        )

    text = post[2]

    await context.bot.send_message(
        chat_id=settings.telegram_channel_id,
        text=text,
    )

    db.update_post(
        post_id,
        "published",
    )

    db.set_last_post(post_id)

    try:
        topics = ai.extract_topics(
            post[1],
            text,
            count=6,
        )

        db.add_topics(
            topics,
            source_post_id=post_id,
        )

        logger.info(
            "Extracted %s child topics from post %s",
            len(topics),
            post_id,
        )

    except Exception as exc:
        logger.exception(
            "Topic extraction failed: %s",
            exc,
        )


def approval_keyboard(post_id: int):
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "✅ انتشار",
                    callback_data=f"approve:{post_id}",
                ),
                InlineKeyboardButton(
                    "❌ رد",
                    callback_data=f"reject:{post_id}",
                ),
            ],
            [
                InlineKeyboardButton(
                    "🔄 بازتولید",
                    callback_data=f"regenerate:{post_id}",
                ),
                InlineKeyboardButton(
                    "✏️ ویرایش",
                    callback_data=f"edit:{post_id}",
                ),
            ],
        ]
    )


async def send_post_preview(
    context: ContextTypes.DEFAULT_TYPE,
    post_id: int,
):
    post = db.get_post(post_id)

    if not post:
        return

    preview = (
        "📝 پیش‌نویس جدید\n\n"
        f"موضوع:\n{post[1]}\n\n"
        "━━━━━━━━━━━━━━\n\n"
        f"{post[2]}"
    )

    for admin_id in settings.admin_user_ids:
        await context.bot.send_message(
            chat_id=admin_id,
            text=preview,
            reply_markup=approval_keyboard(post_id),
        )


async def generate_post(
    topic: str,
    context: ContextTypes.DEFAULT_TYPE,
    publish_direct: bool = False,
):
    previous_text = db.get_last_post_text()

    text = ai.generate_text(
        topic=topic,
        previous_text=previous_text,
    )

    post_id = db.create_post(
        prompt=topic,
        text=text,
    )

    if settings.approval_required and not publish_direct:
        for admin_id in settings.admin_user_ids:
            await context.bot.send_message(
                chat_id=admin_id,
                text=(
                    "📝 پیش‌نویس جدید\n\n"
                    f"موضوع:\n{topic}\n\n"
                    "━━━━━━━━━━━━━━\n\n"
                    f"{text}"
                ),
                reply_markup=approval_keyboard(post_id),
            )

        return post_id, "pending"

    await publish_post(
        context,
        post_id,
    )

    return post_id, "published"


async def start_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    if not is_admin(update.effective_user.id):
        await deny(update)
        return

    await update.message.reply_text(
        "🤖 ربات تولید محتوای فارسی آماده است.\n\n"
        "دستورات اصلی:\n"
        "/help - راهنما\n"
        "/status - وضعیت سیستم\n"
        "/newpost موضوع - تولید پست\n"
        "/starttopic موضوع - شروع درخت موضوعی\n"
        "/autostatus - وضعیت اتوماسیون\n"
        "/stopauto - توقف اتوماسیون\n"
        "/cancel - لغو عملیات فعلی"
    )


async def help_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    if not is_admin(update.effective_user.id):
        await deny(update)
        return

    await update.message.reply_text(
        "📚 راهنمای ربات\n\n"
        "/newpost موضوع\n"
        "تولید یک پست جدید.\n\n"
        "/starttopic موضوع\n"
        "شروع تولید خودکار از یک موضوع اصلی.\n\n"
        "/status\n"
        "نمایش وضعیت دیتابیس و Gemini.\n\n"
        "/autostatus\n"
        "نمایش وضعیت اتوماسیون.\n\n"
        "/stopauto\n"
        "توقف اتوماسیون.\n\n"
        "/cancel\n"
        "لغو عملیات فعلی."
    )


async def status_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    if not is_admin(update.effective_user.id):
        await deny(update)
        return

    try:
        connection = ai.test_connection()

        posts, pending, used, processing, drafts = db.stats()

        await update.message.reply_text(
            "📊 وضعیت سیستم\n\n"
            f"🤖 Gemini: {connection}\n"
            f"🧠 مدل: {settings.gemini_model}\n\n"
            f"📢 پست‌های منتشرشده: {posts}\n"
            f"📝 پیش‌نویس‌ها: {drafts}\n"
            f"⏳ موضوعات در صف: {pending}\n"
            f"⚙️ موضوعات در حال پردازش: {processing}\n"
            f"✅ موضوعات مصرف‌شده: {used}"
        )

    except Exception as exc:
        logger.exception(
            "Status error: %s",
            exc,
        )

        await update.message.reply_text(
            "❌ تست سیستم ناموفق بود.\n\n"
            f"{exc}"
        )


async def newpost_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    if not is_admin(update.effective_user.id):
        await deny(update)
        return

    if not context.args:
        await update.message.reply_text(
            "مثال:\n"
            "/newpost هوش مصنوعی در آینده تولید محتوا"
        )
        return

    topic = " ".join(context.args).strip()

    await update.message.reply_text(
        "⏳ در حال تولید پست..."
    )

    try:
        post_id, status = await generate_post(
            topic,
            context,
        )

        if status == "pending":
            await update.message.reply_text(
                f"📝 پیش‌نویس #{post_id} آماده شد.\n"
                "از دکمه‌های زیر پیام پیش‌نویس استفاده کن."
            )
        else:
            await update.message.reply_text(
                f"✅ پست #{post_id} منتشر شد."
            )

    except AIServiceError as exc:
        logger.exception(
            "AI generation failed: %s",
            exc,
        )

        await update.message.reply_text(
            "❌ خطا در تولید محتوا:\n"
            f"{exc}"
        )

    except Exception as exc:
        logger.exception(
            "New post failed: %s",
            exc,
        )

        await update.message.reply_text(
            "❌ خطا در تولید یا انتشار پست:\n"
            f"{exc}"
        )


async def starttopic_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    if not is_admin(update.effective_user.id):
        await deny(update)
        return

    if not context.args:
        await update.message.reply_text(
            "مثال:\n"
            "/starttopic هوش مصنوعی"
        )
        return

    root_topic = " ".join(context.args).strip()

    try:
        topic_id = db.add_topic(
            root_topic,
            parent_id=None,
            depth=0,
        )

        if not topic_id:
            await update.message.reply_text(
                "❌ موضوع معتبر نیست."
            )
            return

        await update.message.reply_text(
            "🌳 درخت موضوعی ایجاد شد.\n\n"
            f"موضوع اصلی:\n{root_topic}\n\n"
            "⏳ اولین پست در حال تولید است..."
        )

        await generate_topic_job(
            context,
            force_topic_id=topic_id,
        )

    except Exception as exc:
        logger.exception(
            "Start topic failed: %s",
            exc,
        )

        await update.message.reply_text(
            "❌ خطا در شروع درخت موضوعی:\n"
            f"{exc}"
        )


async def generate_topic_job(
    context: ContextTypes.DEFAULT_TYPE,
    force_topic_id=None,
):
    topic_row = None

    if force_topic_id:
        topic_row = db.get_topic(
            force_topic_id
        )
    else:
        topic_row = db.claim_next_topic()

    if not topic_row:
        logger.info(
            "No pending topics."
        )
        return

    topic_id = topic_row[0]
    topic = topic_row[1]

    try:
        logger.info(
            "Generating topic: %s",
            topic,
        )

        previous_text = db.get_last_post_text()

        text = ai.generate_text(
            topic=topic,
            previous_text=previous_text,
        )

        post_id = db.create_post(
            prompt=topic,
            text=text,
        )

        if settings.approval_required:
            for admin_id in settings.admin_user_ids:
                await context.bot.send_message(
                    chat_id=admin_id,
                    text=(
                        "🌳 پست جدید از درخت موضوعی\n\n"
                        f"موضوع:\n{topic}\n\n"
                        "━━━━━━━━━━━━━━\n\n"
                        f"{text}"
                    ),
                    reply_markup=approval_keyboard(
                        post_id
                    ),
                )

            logger.info(
                "Topic %s generated as draft %s",
                topic_id,
                post_id,
            )

        else:
            await publish_post(
                context,
                post_id,
            )

            db.mark_topic_used(
                topic_id
            )

            logger.info(
                "Topic %s published as post %s",
                topic_id,
                post_id,
            )

    except Exception as exc:
        logger.exception(
            "Topic generation failed: %s",
            exc,
        )

        db.reset_processing()


async def automation_job(
    context: ContextTypes.DEFAULT_TYPE,
):
    try:
        automation = db.get_automation()

        if not automation:
            return

        active = automation[0]

        if not active:
            return

        await generate_topic_job(
            context
        )

        interval_hours = automation[5] or 4

        next_run = (
            datetime.now(timezone.utc)
            + timedelta(hours=interval_hours)
        )

        db.set_next_run(
            next_run.isoformat()
        )

        logger.info(
            "Next automation run: %s",
            next_run.isoformat(),
        )

    except Exception as exc:
        logger.exception(
            "Automation job failed: %s",
            exc,
        )


async def autostatus_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    if not is_admin(update.effective_user.id):
        await deny(update)
        return

    automation = db.get_automation()

    if not automation:
        await update.message.reply_text(
            "❌ اطلاعات اتوماسیون پیدا نشد."
        )
        return

    active = bool(automation[0])
    root_topic = automation[1]
    next_run = automation[3]
    start_time = automation[4]
    interval_hours = automation[5]

    await update.message.reply_text(
        "⏰ وضعیت اتوماسیون\n\n"
        f"وضعیت: {'🟢 فعال' if active else '🔴 متوقف'}\n"
        f"موضوع اصلی: {root_topic or '---'}\n"
        f"ساعت شروع: {start_time or '---'}\n"
        f"فاصله انتشار: {interval_hours or 4} ساعت\n"
        f"اجرای بعدی: {next_run or '---'}"
    )


async def stopauto_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    if not is_admin(update.effective_user.id):
        await deny(update)
        return

    db.stop_automation()

    await update.message.reply_text(
        "🔴 اتوماسیون متوقف شد."
    )


async def cancel_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    if not is_admin(update.effective_user.id):
        await deny(update)
        return

    context.user_data.pop(
        "editing_post_id",
        None,
    )

    await update.message.reply_text(
        "✅ عملیات فعلی لغو شد."
    )


async def callback_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    query = update.callback_query

    if not is_admin(query.from_user.id):
        await query.answer(
            "دسترسی ندارید.",
            show_alert=True,
        )
        return

    await query.answer()

    data = query.data or ""

    try:
        action, post_id_text = data.split(
            ":",
            1,
        )

        post_id = int(
            post_id_text
        )

    except (ValueError, TypeError):
        await query.message.reply_text(
            "❌ درخواست نامعتبر است."
        )
        return

    post = db.get_post(post_id)

    if not post:
        await query.message.reply_text(
            "❌ پست پیدا نشد."
        )
        return

    if action == "approve":
        try:
            await publish_post(
                context,
                post_id,
            )

            await query.message.reply_text(
                f"✅ پست #{post_id} منتشر شد."
            )

        except Exception as exc:
            logger.exception(
                "Approve failed: %s",
                exc,
            )

            await query.message.reply_text(
                "❌ انتشار ناموفق بود:\n"
                f"{exc}"
            )

        return

    if action == "reject":
        db.update_post(
            post_id,
            "rejected",
        )

        db.add_feedback(
            post_id,
            "reject",
        )

        await query.message.reply_text(
            f"❌ پست #{post_id} رد شد."
        )

        return

    if action == "regenerate":
        await query.message.reply_text(
            "🔄 در حال بازتولید..."
        )

        try:
            new_text = ai.regenerate(
                topic=post[1],
                old_text=post[2],
            )

            db.update_post_text(
                post_id,
                new_text,
            )

            db.add_feedback(
                post_id,
                "regenerate",
            )

            await query.message.reply_text(
                "🔄 نسخه جدید:\n\n"
                f"{new_text}",
                reply_markup=approval_keyboard(
                    post_id
                ),
            )

        except Exception as exc:
            logger.exception(
                "Regenerate failed: %s",
                exc,
            )

            await query.message.reply_text(
                "❌ بازتولید ناموفق بود:\n"
                f"{exc}"
            )

        return

    if action == "edit":
        context.user_data[
            "editing_post_id"
        ] = post_id

        await query.message.reply_text(
            "✏️ دستور ویرایش را در پیام بعدی بنویس.\n\n"
            "مثال:\n"
            "لحن را صمیمی‌تر کن و متن را کوتاه‌تر کن.\n\n"
            "برای لغو: /cancel"
        )

        return

    await query.message.reply_text(
        "❌ عملیات ناشناخته است."
    )


async def text_message_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    if not is_admin(update.effective_user.id):
        await deny(update)
        return

    post_id = context.user_data.get(
        "editing_post_id"
    )

    if not post_id:
        return

    instruction = (
        update.message.text or ""
    ).strip()

    if not instruction:
        return

    post = db.get_post(post_id)

    if not post:
        context.user_data.pop(
            "editing_post_id",
            None,
        )

        await update.message.reply_text(
            "❌ پست پیدا نشد."
        )
        return

    await update.message.reply_text(
        "✏️ در حال ویرایش..."
    )

    try:
        new_text = ai.edit_text(
            topic=post[1],
            old_text=post[2],
            instruction=instruction,
        )

        db.update_post_text(
            post_id,
            new_text,
        )

        db.add_feedback(
            post_id,
            "edit",
            instruction,
        )

        context.user_data.pop(
            "editing_post_id",
            None,
        )

        await update.message.reply_text(
            "✏️ نسخه ویرایش‌شده:\n\n"
            f"{new_text}",
            reply_markup=approval_keyboard(
                post_id
            ),
        )

    except Exception as exc:
        logger.exception(
            "Edit failed: %s",
            exc,
        )

        await update.message.reply_text(
            "❌ ویرایش ناموفق بود:\n"
            f"{exc}"
        )


async def error_handler(
    update: object,
    context: ContextTypes.DEFAULT_TYPE,
):
    logger.exception(
        "Unhandled Telegram error: %s",
        context.error,
    )


def build_application():
    application = (
        Application.builder()
        .token(
            settings.telegram_bot_token
        )
        .build()
    )

    application.add_handler(
        CommandHandler(
            "start",
            start_command,
        )
    )

    application.add_handler(
        CommandHandler(
            "help",
            help_command,
        )
    )

    application.add_handler(
        CommandHandler(
            "status",
            status_command,
        )
    )

    application.add_handler(
        CommandHandler(
            "newpost",
            newpost_command,
        )
    )

    application.add_handler(
        CommandHandler(
            "starttopic",
            starttopic_command,
        )
    )

    application.add_handler(
        CommandHandler(
            "autostatus",
            autostatus_command,
        )
    )

    application.add_handler(
        CommandHandler(
            "stopauto",
            stopauto_command,
        )
    )

    application.add_handler(
        CommandHandler(
            "cancel",
            cancel_command,
        )
    )

    application.add_handler(
        CallbackQueryHandler(
            callback_handler
        )
    )

    application.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            text_message_handler,
        )
    )

    application.add_error_handler(
        error_handler
    )

    if application.job_queue:
        application.job_queue.run_repeating(
            automation_job,
            interval=60,
            first=30,
            name="automation-check",
        )
    else:
        logger.warning(
            "JobQueue is not available. "
            "Install python-telegram-bot[job-queue] "
            "if automation is required."
        )

    return application


def main():
    logger.info(
        "Starting Telegram Content Bot..."
    )

    logger.info(
        "Gemini model: %s",
        settings.gemini_model,
    )

    logger.info(
        "Approval required: %s",
        settings.approval_required,
    )

    logger.info(
        "Research enabled: %s",
        settings.research_enabled,
    )

    logger.info(
        "Database: %s",
        settings.database_path,
    )

    if not settings.admin_user_ids:
        logger.warning(
    "ADMIN_USER_IDS is empty. "
    "No Telegram user will have admin access."
        )
