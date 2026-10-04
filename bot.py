import logging
import os
from datetime import datetime, timezone, timedelta

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

from ai import AIService
from config import load_settings
from db import Database

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger(__name__)

settings = load_settings()
db = Database(settings.database_path)
db.reset_processing()
ai = AIService()

JOB_NAME = "hourly_topic_publisher"


def ok(uid):
    return not settings.admin_user_ids or uid in settings.admin_user_ids


def safe_error_text(exc):
    msg = str(exc)
    for secret in (settings.openai_api_key, settings.telegram_bot_token):
        if secret:
            msg = msg.replace(secret, "[SECRET_HIDDEN]")
    if len(msg) > 1800:
        msg = msg[:1800] + "\n…"
    return msg


async def start(u: Update, c: ContextTypes.DEFAULT_TYPE):
    if u.effective_user and ok(u.effective_user.id):
        await u.message.reply_text(
            "سلام! 🤖\n\n"
            "سیستم انتشار زنجیره‌ای آماده است.\n\n"
            "/starttopic موضوع اصلی ← شروع زنجیره\n"
            "/autostatus ← وضعیت انتشار خودکار\n"
            "/stopauto ← توقف انتشار خودکار\n"
            "/status ← وضعیت تنظیمات\n\n"
            "بعد از شروع، پست اول ساخته و منتشر می‌شود و سپس هر ساعت "
            "یک موضوع فرعی از زنجیره انتخاب و منتشر می‌شود."
        )


async def help_command(u: Update, c: ContextTypes.DEFAULT_TYPE):
    if u.effective_user and ok(u.effective_user.id):
        await u.message.reply_text(
            "/starttopic موضوع اصلی - شروع یک زنجیره جدید\n"
            "/autostatus - وضعیت سیستم خودکار\n"
            "/stopauto - توقف انتشار خودکار\n"
            "/status - بررسی تنظیمات\n"
            "/newpost موضوع - ساخت یک پست دستی"
        )


async def status_command(u: Update, c: ContextTypes.DEFAULT_TYPE):
    if not u.effective_user or not ok(u.effective_user.id):
        return
    webhook = bool(os.getenv("RENDER_EXTERNAL_URL"))
    lines = [
        "🔎 وضعیت ربات",
        "",
        f"TELEGRAM_BOT_TOKEN: {'تنظیم شده' if settings.telegram_bot_token else '❌ خالی'}",
        f"TELEGRAM_CHANNEL_ID: {settings.telegram_channel_id}",
        f"OPENAI_API_KEY: {'تنظیم شده' if settings.openai_api_key else '❌ خالی'}",
        f"📝 مدل متن: {settings.openai_text_model}",
        "🚫 تولید تصویر: خاموش",
        f"🌐 RENDER_EXTERNAL_URL: {'تنظیم شده' if webhook else '❌ پیدا نشد'}",
    ]
    await u.message.reply_text("\n".join(lines))


async def publish_text(bot, text):
    await bot.send_message(chat_id=settings.telegram_channel_id, text=text)


async def create_and_publish(topic, previous_text=None, parent_node_id=None, depth=0, notify_chat=None, context=None):
    # 1) متن
    try:
        text = ai.generate_text(topic, previous_text=previous_text)
    except Exception as exc:
        log.exception("TEXT_GENERATION_FAILED topic=%s", topic)
        if notify_chat and context:
            await context.bot.send_message(
                chat_id=notify_chat,
                text=f"❌ خطا در مرحله ۱: ساخت متن\n\nموضوع: {topic}\n🔴 {safe_error_text(exc)}"
            )
        raise

    # 2) استخراج شاخه‌های بعدی
    try:
        children = ai.extract_topics(topic, text)
    except Exception as exc:
        log.exception("TOPIC_EXTRACTION_FAILED topic=%s", topic)
        if notify_chat and context:
            await context.bot.send_message(
                chat_id=notify_chat,
                text=f"❌ خطا در مرحله ۲: استخراج موضوعات بعدی\n\nموضوع: {topic}\n🔴 {safe_error_text(exc)}"
            )
        raise

    # 3) ذخیره
    try:
        post_id = db.create_post(topic, text, None)
        node_id = parent_node_id
        db.add_topics(children, parent_id=node_id, depth=depth + 1, source_post_id=post_id)
    except Exception as exc:
        log.exception("DATABASE_FAILED topic=%s", topic)
        if notify_chat and context:
            await context.bot.send_message(
                chat_id=notify_chat,
                text=f"❌ خطا در مرحله ۳: ذخیره زنجیره\n\nموضوع: {topic}\n🔴 {safe_error_text(exc)}"
            )
        raise

    # 4) انتشار
    try:
        await publish_text(context.bot, text)
        db.update_post(post_id, "published")
        db.set_last_post(post_id)
        if parent_node_id:
            db.mark_topic_used(parent_node_id)
    except Exception as exc:
        log.exception("PUBLISH_FAILED topic=%s", topic)
        if notify_chat and context:
            await context.bot.send_message(
                chat_id=notify_chat,
                text=f"❌ خطا در مرحله ۴: انتشار در کانال\n\nموضوع: {topic}\n🔴 {safe_error_text(exc)}"
            )
        raise

    return post_id, children


async def start_topic(u: Update, c: ContextTypes.DEFAULT_TYPE):
    if not u.effective_user or not ok(u.effective_user.id):
        return
    topic = " ".join(c.args).strip()
    if not topic:
        await u.message.reply_text("مثال:\n/starttopic گوشی سامسونگ Galaxy S24")
        return

    # New chain: clear pending old branches so the new root takes over.
    try:
        db.stop_automation()
        db.reset_processing()
        now = datetime.now(timezone.utc)
        post_id, children = await create_and_publish(
            topic=topic,
            previous_text=None,
            parent_node_id=None,
            depth=0,
            notify_chat=u.effective_chat.id,
            context=c,
        )
        next_run = now + timedelta(hours=1)
        db.start_automation(topic, next_run.isoformat())
        schedule_hourly(c.application)
        await u.message.reply_text(
            f"✅ زنجیره شروع شد.\n\n"
            f"موضوع اصلی: {topic}\n"
            f"پست اول: #{post_id} منتشر شد.\n"
            f"موضوعات بعدی آماده: {len(children)}\n"
            f"⏰ پست بعدی حدود یک ساعت دیگر منتشر می‌شود.\n\n"
            f"از اینجا به بعد دخالت تو لازم نیست."
        )
    except Exception:
        # Detailed stage error already sent.
        return


async def new_post(u: Update, c: ContextTypes.DEFAULT_TYPE):
    if not u.effective_user or not ok(u.effective_user.id):
        return
    topic = " ".join(c.args).strip()
    if not topic:
        await u.message.reply_text("مثال: /newpost درباره هوش مصنوعی")
        return
    try:
        post_id, children = await create_and_publish(
            topic=topic,
            previous_text=db.get_last_post_text(),
            notify_chat=u.effective_chat.id,
            context=c,
        )
        await u.message.reply_text(
            f"✅ پست #{post_id} منتشر شد.\n"
            f"🌱 {len(children)} موضوع فرعی جدید به زنجیره اضافه شد."
        )
    except Exception:
        return


async def hourly_job(context: ContextTypes.DEFAULT_TYPE):
    state = db.get_automation()
    if not state or not state[0]:
        return

    claimed = db.claim_next_topic()
    if not claimed:
        await context.bot.send_message(
            chat_id=settings.telegram_channel_id,
            text="ℹ️ زنجیره موضوعات فعلاً تمام شده است. برای شروع موضوع جدید از /starttopic استفاده کنید."
        )
        db.stop_automation()
        return

    node_id, topic, parent_id, depth = claimed
    previous_text = db.get_last_post_text()

    try:
        post_id, children = await create_and_publish(
            topic=topic,
            previous_text=previous_text,
            parent_node_id=node_id,
            depth=depth,
            notify_chat=None,
            context=context,
        )
        next_run = datetime.now(timezone.utc) + timedelta(hours=1)
        db.set_next_run(next_run.isoformat())
        log.info(
            "AUTO_POST_PUBLISHED post=%s topic=%s children=%s next=%s",
            post_id, topic, len(children), next_run.isoformat()
        )
    except Exception as exc:
        log.exception("HOURLY_JOB_FAILED topic=%s", topic)
        # Make the topic available again instead of losing it.
        try:
            db.reset_processing()
            await context.bot.send_message(
                chat_id=settings.telegram_channel_id,
                text=(
                    "⚠️ انتشار خودکار این ساعت ناموفق بود.\n"
                    f"موضوع: {topic}\n"
                    f"خطا: {safe_error_text(exc)}\n\n"
                    "این موضوع حذف نشده و در اجرای بعدی دوباره تلاش می‌شود."
                ),
            )
        except Exception:
            log.exception("AUTO_ERROR_NOTIFICATION_FAILED")


def schedule_hourly(application):
    jobs = application.job_queue.get_jobs_by_name(JOB_NAME)
    for job in jobs:
        job.schedule_removal()
    application.job_queue.run_repeating(
        hourly_job,
        interval=3600,
        first=3600,
        name=JOB_NAME,
    )


async def autostatus(u: Update, c: ContextTypes.DEFAULT_TYPE):
    if not u.effective_user or not ok(u.effective_user.id):
        return
    state = db.get_automation()
    posts, pending, used = db.stats()
    active = bool(state and state[0])
    next_run = state[3] if state else None
    await u.message.reply_text(
        "🤖 وضعیت انتشار خودکار\n\n"
        f"فعال: {'✅ بله' if active else '❌ خیر'}\n"
        f"پست‌های منتشرشده: {posts}\n"
        f"موضوعات منتظر: {pending}\n"
        f"موضوعات مصرف‌شده: {used}\n"
        f"پست بعدی: {next_run or '---'}\n\n"
        "فاصله انتشار: هر ۱ ساعت"
    )


async def stop_auto(u: Update, c: ContextTypes.DEFAULT_TYPE):
    if not u.effective_user or not ok(u.effective_user.id):
        return
    db.stop_automation()
    for job in c.application.job_queue.get_jobs_by_name(JOB_NAME):
        job.schedule_removal()
    await u.message.reply_text("🛑 انتشار خودکار متوقف شد. زنجیره در دیتابیس باقی می‌ماند.")


async def post_init(application):
    state = db.get_automation()
    if state and state[0]:
        schedule_hourly(application)
        log.info("HOURLY_AUTOMATION_RESTORED next_run_at=%s", state[3])


def main():
    url = os.getenv("RENDER_EXTERNAL_URL", "").rstrip("/")
    if not url:
        raise RuntimeError(
            "RENDER_EXTERNAL_URL تنظیم نشده است؛ این متغیر برای Webhook لازم است."
        )

    app = (
        Application.builder()
        .token(settings.telegram_bot_token)
        .post_init(post_init)
        .build()
    )
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("status", status_command))
    app.add_handler(CommandHandler("starttopic", start_topic))
    app.add_handler(CommandHandler("autostatus", autostatus))
    app.add_handler(CommandHandler("stopauto", stop_auto))
    app.add_handler(CommandHandler("newpost", new_post))

    app.run_webhook(
        listen="0.0.0.0",
        port=int(os.getenv("PORT", "10000")),
        url_path="telegram",
        webhook_url=f"{url}/telegram",
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=False,
    )


if __name__ == "__main__":
    main()
