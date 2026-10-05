# ============================================================
# bot.py
# فایل اصلی اجرای ربات تلگرام
#
# وظایف:
# 1. اجرای ربات Telegram
# 2. اتصال Gemini
# 3. تولید و انتشار پست
# 4. ساخت زنجیره موضوعات فرعی
# 5. مدیریت اتوماسیون انتشار
# 6. مدیریت Scheduler
# 7. اتصال پنل مدیریت
# ============================================================


# ============================================================
# بخش 1 — کتابخانه‌ها
# ============================================================

import logging
import os
from datetime import datetime, timezone, timedelta

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
)

from ai import AIService
from config import load_settings
from db import Database
from admin_panel import register_admin_handlers


# ============================================================
# بخش 2 — تنظیمات Logging
# ============================================================

logging.basicConfig(
    level=os.getenv(
        "LOG_LEVEL",
        "INFO",
    ),
    format=(
        "%(asctime)s "
        "%(levelname)s "
        "%(name)s: "
        "%(message)s"
    ),
)

log = logging.getLogger(__name__)


# ============================================================
# بخش 3 — بارگذاری تنظیمات
# ============================================================

settings = load_settings()

db = Database(
    settings.database_path
)

# اگر ربات قبلاً در وسط پردازش Restart شده باشد،
# موضوعات processing دوباره pending می‌شوند.
db.reset_processing()

# اتصال به Gemini
ai = AIService()


# ============================================================
# بخش 4 — نام Job اتوماسیون
# ============================================================

JOB_NAME = "topic_publisher"


# ============================================================
# بخش 5 — بررسی دسترسی ادمین
# ============================================================

def ok(uid):
    """
    اگر ADMIN_USER_IDS خالی باشد،
    دسترسی برای همه مجاز است.

    در حالت عادی بهتر است ADMIN_USER_IDS
    در Render تنظیم شده باشد.
    """

    return (
        not settings.admin_user_ids
        or uid in settings.admin_user_ids
    )


# ============================================================
# بخش 6 — مخفی کردن Secretها از خطاها
# ============================================================

def safe_error_text(exc):
    """
    جلوگیری از نمایش API Key یا Bot Token
    داخل پیام‌های خطا.
    """

    msg = str(exc)

    secrets = (
        settings.gemini_api_key,
        settings.telegram_bot_token,
    )

    for secret in secrets:

        if secret:
            msg = msg.replace(
                secret,
                "[SECRET_HIDDEN]",
            )

    if len(msg) > 1800:
        msg = msg[:1800] + "\n…"

    return msg


# ============================================================
# بخش 7 — محاسبه زمان اجرای بعدی
# ============================================================

def calculate_next_run(
    start_time,
    interval_hours,
):
    """
    زمان اجرای بعدی را بر اساس:

    start_time:
        مثلاً 09:00

    interval_hours:
        مثلاً 4

    محاسبه می‌کند.

    مثال:

    09:00
    13:00
    17:00
    21:00
    01:00
    ...
    """

    try:
        hour, minute = map(
            int,
            start_time.split(":"),
        )

        if not (
            0 <= hour <= 23
            and 0 <= minute <= 59
        ):
            raise ValueError

    except Exception:
        # اگر ساعت خراب بود،
        # یک ساعت بعد را انتخاب می‌کنیم.
        return (
            datetime.now(timezone.utc)
            + timedelta(hours=1)
        )

    interval_hours = int(interval_hours)

    if interval_hours < 1:
        interval_hours = 4

    if interval_hours > 24:
        interval_hours = 24

    now = datetime.now(timezone.utc)

    # زمان شروع امروز
    candidate = now.replace(
        hour=hour,
        minute=minute,
        second=0,
        microsecond=0,
    )

    # اگر ساعت شروع گذشته باشد،
    # از همان ساعت شروع حرکت کرده و
    # با فاصله مشخص جلو می‌رویم.
    while candidate <= now:
        candidate += timedelta(
            hours=interval_hours
        )

    return candidate


# ============================================================
# بخش 8 — انتشار مستقیم متن در کانال
# ============================================================

async def publish_text(
    bot,
    text,
):
    """
    انتشار متن در کانال تلگرام.
    """

    await bot.send_message(
        chat_id=settings.telegram_channel_id,
        text=text,
    )


# ============================================================
# بخش 9 — تولید + استخراج موضوع + ذخیره + انتشار
# ============================================================

async def create_and_publish(
    topic,
    previous_text=None,
    parent_node_id=None,
    depth=0,
    notify_chat=None,
    context=None,
):
    """
    چرخه کامل تولید یک پست:

    1. Gemini متن را تولید می‌کند.
    2. Gemini موضوعات فرعی را استخراج می‌کند.
    3. پست در دیتابیس ذخیره می‌شود.
    4. موضوعات فرعی در دیتابیس ذخیره می‌شوند.
    5. پست در Telegram منتشر می‌شود.
    6. وضعیت پست published می‌شود.
    7. موضوع فعلی used می‌شود.
    """

    # ========================================================
    # مرحله 1 — تولید متن
    # ========================================================

    try:

        text = ai.generate_text(
            topic,
            previous_text=previous_text,
        )

    except Exception as exc:

        log.exception(
            "TEXT_GENERATION_FAILED topic=%s",
            topic,
        )

        if notify_chat and context:

            await context.bot.send_message(
                chat_id=notify_chat,
                text=(
                    "❌ خطا در مرحله ۱: ساخت متن\n\n"
                    f"موضوع: {topic}\n"
                    f"🔴 {safe_error_text(exc)}"
                ),
            )

        raise

    # ========================================================
    # مرحله 2 — استخراج موضوعات فرعی
    # ========================================================

    try:

        children = ai.extract_topics(
            topic,
            text,
        )

    except Exception as exc:

        log.exception(
            "TOPIC_EXTRACTION_FAILED topic=%s",
            topic,
        )

        if notify_chat and context:

            await context.bot.send_message(
                chat_id=notify_chat,
                text=(
                    "❌ خطا در مرحله ۲: "
                    "استخراج موضوعات بعدی\n\n"
                    f"موضوع: {topic}\n"
                    f"🔴 {safe_error_text(exc)}"
                ),
            )

        raise

    # ========================================================
    # مرحله 3 — ذخیره در دیتابیس
    # ========================================================

    try:

        post_id = db.create_post(
            prompt=topic,
            text=text,
            image_path=None,
        )

        # اگر این پست از یک موضوع فرعی ساخته شده،
        # همان node والد آن است.
        node_id = parent_node_id

        db.add_topics(
            children,
            parent_id=node_id,
            depth=depth + 1,
            source_post_id=post_id,
        )

    except Exception as exc:

        log.exception(
            "DATABASE_FAILED topic=%s",
            topic,
        )

        if notify_chat and context:

            await context.bot.send_message(
                chat_id=notify_chat,
                text=(
                    "❌ خطا در مرحله ۳: ذخیره زنجیره\n\n"
                    f"موضوع: {topic}\n"
                    f"🔴 {safe_error_text(exc)}"
                ),
            )

        raise

    # ========================================================
    # مرحله 4 — انتشار در Telegram
    # ========================================================

    try:

        await publish_text(
            context.bot,
            text,
        )

        # تغییر وضعیت پست به published
        db.update_post(
            post_id,
            "published",
        )

        # ذخیره آخرین پست در automation
        db.set_last_post(
            post_id
        )

        # اگر این پست مربوط به یک موضوع فرعی بوده،
        # موضوع فعلی استفاده‌شده محسوب می‌شود.
        if parent_node_id:

            db.mark_topic_used(
                parent_node_id
            )

    except Exception as exc:

        log.exception(
            "PUBLISH_FAILED topic=%s",
            topic,
        )

        if notify_chat and context:

            await context.bot.send_message(
                chat_id=notify_chat,
                text=(
                    "❌ خطا در مرحله ۴: "
                    "انتشار در کانال\n\n"
                    f"موضوع: {topic}\n"
                    f"🔴 {safe_error_text(exc)}"
                ),
            )

        raise

    return post_id, children


# ============================================================
# بخش 10 — دستور /start
# ============================================================

async def start(
    u: Update,
    c: ContextTypes.DEFAULT_TYPE,
):

    if (
        not u.effective_user
        or not ok(u.effective_user.id)
    ):
        return

    await u.message.reply_text(
        "سلام! 🤖\n\n"
        "سیستم تولید و انتشار محتوای هوشمند آماده است.\n\n"
        "📌 دستورات اصلی:\n\n"
        "/starttopic موضوع اصلی\n"
        "شروع یک زنجیره جدید\n\n"
        "/newpost موضوع\n"
        "ساخت و انتشار یک پست دستی\n\n"
        "/autostatus\n"
        "وضعیت اتوماسیون\n\n"
        "/stopauto\n"
        "توقف انتشار خودکار\n\n"
        "/status\n"
        "وضعیت سیستم\n\n"
        "/admin\n"
        "پنل مدیریت"
    )


# ============================================================
# بخش 11 — دستور /help
# ============================================================

async def help_command(
    u: Update,
    c: ContextTypes.DEFAULT_TYPE,
):

    if (
        not u.effective_user
        or not ok(u.effective_user.id)
    ):
        return

    await u.message.reply_text(
        "📚 راهنمای ربات\n\n"

        "/starttopic موضوع\n"
        "شروع یک زنجیره جدید.\n\n"

        "/newpost موضوع\n"
        "تولید و انتشار یک پست مستقل.\n\n"

        "/autostatus\n"
        "نمایش وضعیت اتوماسیون.\n\n"

        "/stopauto\n"
        "توقف اتوماسیون.\n\n"

        "/status\n"
        "نمایش وضعیت Gemini، Telegram و Render.\n\n"

        "/admin\n"
        "ورود به پنل مدیریت."
    )


# ============================================================
# بخش 12 — دستور /status
# ============================================================

async def status_command(
    u: Update,
    c: ContextTypes.DEFAULT_TYPE,
):

    if (
        not u.effective_user
        or not ok(u.effective_user.id)
    ):
        return

    webhook = bool(
        os.getenv(
            "RENDER_EXTERNAL_URL"
        )
    )

    state = db.get_automation()

    automation_active = bool(
        state and state[0]
    )

    lines = [
        "🔎 وضعیت ربات",
        "",
        "📱 Telegram",
        (
            "TELEGRAM_BOT_TOKEN: "
            f"{'تنظیم شده' if settings.telegram_bot_token else '❌ خالی'}"
        ),
        (
            "TELEGRAM_CHANNEL_ID: "
            f"{settings.telegram_channel_id}"
        ),
        "",
        "🤖 Gemini",
        (
            "GEMINI_API_KEY: "
            f"{'تنظیم شده' if settings.gemini_api_key else '❌ خالی'}"
        ),
        (
            f"مدل: {settings.gemini_model}"
        ),
        "",
        "⚙️ Automation",
        (
            "وضعیت: "
            f"{'🟢 فعال' if automation_active else '🔴 خاموش'}"
        ),
        "",
        "🖼 تولید تصویر: خاموش",
        (
            "🌐 RENDER_EXTERNAL_URL: "
            f"{'تنظیم شده' if webhook else '❌ پیدا نشد'}"
        ),
    ]

    await u.message.reply_text(
        "\n".join(lines)
    )


# ============================================================
# بخش 13 — شروع زنجیره جدید
# ============================================================

async def start_topic(
    u: Update,
    c: ContextTypes.DEFAULT_TYPE,
):

    if (
        not u.effective_user
        or not ok(u.effective_user.id)
    ):
        return

    topic = " ".join(
        c.args
    ).strip()

    if not topic:

        await u.message.reply_text(
            "مثال:\n"
            "/starttopic گوشی سامسونگ Galaxy S24"
        )

        return

    try:

        # اتوماسیون قبلی متوقف می‌شود.
        db.stop_automation()

        # موضوعات processing قدیمی آزاد می‌شوند.
        db.reset_processing()

        # -----------------------------------------------
        # تولید و انتشار پست اول
        # -----------------------------------------------

        post_id, children = await create_and_publish(
            topic=topic,
            previous_text=None,
            parent_node_id=None,
            depth=0,
            notify_chat=u.effective_chat.id,
            context=c,
        )

        # -----------------------------------------------
        # دریافت تنظیمات فعلی اتوماسیون
        # -----------------------------------------------

        state = db.get_automation()

        start_time = (
            state[4]
            if state and state[4]
            else "09:00"
        )

        interval_hours = (
            state[5]
            if state and state[5]
            else 4
        )

        # -----------------------------------------------
        # محاسبه اجرای بعدی
        # -----------------------------------------------

        next_run = calculate_next_run(
            start_time,
            interval_hours,
        )

        # -----------------------------------------------
        # ذخیره تنظیمات اتوماسیون
        # -----------------------------------------------

        db.start_automation(
            root_topic=topic,
            next_run_at=next_run.isoformat(),
            start_time=start_time,
            interval_hours=interval_hours,
        )

        # -----------------------------------------------
        # فعال کردن Scheduler
        # -----------------------------------------------

        schedule_automation(
            c.application
        )

        await u.message.reply_text(
            "✅ زنجیره با موفقیت شروع شد.\n\n"

            f"📌 موضوع اصلی:\n{topic}\n\n"

            f"📝 پست اول: #{post_id}\n"
            "📤 منتشر شد.\n\n"

            f"🌱 موضوعات فرعی ساخته‌شده: "
            f"{len(children)}\n\n"

            f"🕐 ساعت شروع: {start_time}\n"
            f"⏱ فاصله انتشار: "
            f"هر {interval_hours} ساعت\n\n"

            f"📅 اجرای بعدی:\n"
            f"{next_run.isoformat()}\n\n"

            "🤖 از اینجا به بعد انتشار خودکار انجام می‌شود."
        )

    except Exception as exc:

        log.exception(
            "START_TOPIC_FAILED topic=%s",
            topic,
        )

        # خطا قبلاً ممکن است برای کاربر ارسال شده باشد،
        # ولی اینجا یک پیام کلی هم می‌فرستیم.
        try:

            await u.message.reply_text(
                "❌ شروع زنجیره انجام نشد.\n\n"
                f"{safe_error_text(exc)}"
            )

        except Exception:
            log.exception(
                "START_TOPIC_ERROR_MESSAGE_FAILED"
            )


# ============================================================
# بخش 14 — ساخت پست دستی
# ============================================================

async def new_post(
    u: Update,
    c: ContextTypes.DEFAULT_TYPE,
):

    if (
        not u.effective_user
        or not ok(u.effective_user.id)
    ):
        return

    topic = " ".join(
        c.args
    ).strip()

    if not topic:

        await u.message.reply_text(
            "مثال:\n"
            "/newpost درباره هوش مصنوعی"
        )

        return

    try:

        previous_text = (
            db.get_last_post_text()
        )

        post_id, children = await create_and_publish(
            topic=topic,
            previous_text=previous_text,
            parent_node_id=None,
            depth=0,
            notify_chat=u.effective_chat.id,
            context=c,
        )

        await u.message.reply_text(
            "✅ پست منتشر شد.\n\n"
            f"📝 شماره پست: #{post_id}\n"
            f"🌱 موضوعات فرعی جدید: {len(children)}"
        )

    except Exception as exc:

        log.exception(
            "MANUAL_POST_FAILED topic=%s",
            topic,
        )

        try:

            await u.message.reply_text(
                "❌ ساخت پست انجام نشد.\n\n"
                f"{safe_error_text(exc)}"
            )

        except Exception:
            log.exception(
                "MANUAL_POST_ERROR_MESSAGE_FAILED"
            )


# ============================================================
# بخش 15 — اجرای یک پست خودکار
# ============================================================

async def automation_job(
    context: ContextTypes.DEFAULT_TYPE,
):

    state = db.get_automation()

    # اگر اتوماسیون خاموش است،
    # هیچ کاری انجام نمی‌دهیم.
    if not state or not state[0]:
        return

    # -----------------------------------------------
    # گرفتن موضوع بعدی
    # -----------------------------------------------

    claimed = db.claim_next_topic()

    if not claimed:

        await context.bot.send_message(
            chat_id=settings.telegram_channel_id,
            text=(
                "ℹ️ زنجیره موضوعات فعلاً تمام شده است.\n\n"
                "برای شروع موضوع جدید از:\n"
                "/starttopic موضوع\n"
                "استفاده کنید."
            ),
        )

        db.stop_automation()

        # Scheduler هم متوقف می‌شود.
        remove_automation_jobs(
            context.application
        )

        return

    node_id, topic, parent_id, depth = claimed

    previous_text = (
        db.get_last_post_text()
    )

    try:

        # -------------------------------------------
        # تولید و انتشار
        # -------------------------------------------

        post_id, children = await create_and_publish(
            topic=topic,
            previous_text=previous_text,
            parent_node_id=node_id,
            depth=depth,
            notify_chat=None,
            context=context,
        )

        # -------------------------------------------
        # تنظیم زمان بعدی
        # -------------------------------------------

        current_state = db.get_automation()

        start_time = (
            current_state[4]
            if current_state and current_state[4]
            else "09:00"
        )

        interval_hours = (
            current_state[5]
            if current_state and current_state[5]
            else 4
        )

        # اجرای بعدی بر اساس فاصله تنظیم‌شده
        next_run = (
            datetime.now(timezone.utc)
            + timedelta(
                hours=int(interval_hours)
            )
        )

        db.set_next_run(
            next_run.isoformat()
        )

        log.info(
            "AUTO_POST_PUBLISHED "
            "post=%s topic=%s children=%s "
            "next=%s start=%s interval=%s",
            post_id,
            topic,
            len(children),
            next_run.isoformat(),
            start_time,
            interval_hours,
        )

    except Exception as exc:

        log.exception(
            "AUTOMATION_JOB_FAILED topic=%s",
            topic,
        )

        try:

            # موضوع processing دوباره pending می‌شود.
            db.reset_processing()

            await context.bot.send_message(
                chat_id=settings.telegram_channel_id,
                text=(
                    "⚠️ انتشار خودکار ناموفق بود.\n\n"
                    f"موضوع: {topic}\n"
                    f"🔴 خطا: {safe_error_text(exc)}\n\n"
                    "موضوع حذف نشده و دوباره قابل پردازش است."
                ),
            )

        except Exception:
            log.exception(
                "AUTO_ERROR_NOTIFICATION_FAILED"
            )


# ==
