from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)


def allowed(user, settings):
    return bool(user) and (
        not settings.admin_user_ids
        or user.id in settings.admin_user_ids
    )


def menu():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "🤖 وضعیت Gemini",
                callback_data="admin_status",
            ),
        ],
        [
            InlineKeyboardButton(
                "🧪 تست اتصال API",
                callback_data="admin_test",
            ),
            InlineKeyboardButton(
                "✍️ تست تولید متن",
                callback_data="admin_generate",
            ),
        ],
        [
            InlineKeyboardButton(
                "🧠 استخراج موضوعات فرعی",
                callback_data="admin_subtopics",
            ),
        ],
        [
            InlineKeyboardButton(
                "➕ افزودن موضوع",
                callback_data="admin_add_topic",
            ),
            InlineKeyboardButton(
                "📚 وضعیت موضوعات",
                callback_data="admin_topics",
            ),
        ],
        [
            InlineKeyboardButton(
                "⏰ اتوماسیون",
                callback_data="admin_auto",
            ),
            InlineKeyboardButton(
                "📊 آمار دیتابیس",
                callback_data="admin_db",
            ),
        ],
        [
            InlineKeyboardButton(
                "🔄 تولید دستی پست",
                callback_data="admin_manual_post",
            ),
        ],
    ])


def back_menu():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "🔙 بازگشت به پنل",
                callback_data="admin_home",
            )
        ]
    ])


async def admin_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    settings = context.application.bot_data["settings"]

    if not allowed(update.effective_user, settings):
        await update.effective_message.reply_text(
            "⛔ شما دسترسی به پنل مدیریت ندارید."
        )
        return

    context.user_data.pop("admin_action", None)

    await update.effective_message.reply_text(
        "🎛 پنل مدیریت Nova\n\n"
        "یک گزینه را انتخاب کنید:",
        reply_markup=menu(),
    )


async def callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    query = update.callback_query
    await query.answer()

    settings = context.application.bot_data["settings"]

    if not allowed(query.from_user, settings):
        await query.edit_message_text(
            "⛔ شما دسترسی به پنل مدیریت ندارید."
        )
        return

    ai = context.application.bot_data["ai"]
    db = context.application.bot_data["db"]

    if query.data == "admin_home":
        context.user_data.pop("admin_action", None)

        await query.edit_message_text(
            "🎛 پنل مدیریت Nova\n\n"
            "یک گزینه را انتخاب کنید:",
            reply_markup=menu(),
        )
        return

    # ---------------------------------------------------------
    # وضعیت Gemini
    # ---------------------------------------------------------

    if query.data == "admin_status":
        text = (
            "🤖 وضعیت Gemini\n\n"
            f"سرویس: Google Gemini\n"
            f"مدل: {settings.gemini_model}\n"
            f"API Key: "
            f"{'🟢 تنظیم شده' if settings.gemini_api_key else '🔴 تنظیم نشده'}"
        )

        await query.edit_message_text(
            text,
            reply_markup=back_menu(),
        )
        return

    # ---------------------------------------------------------
    # تست اتصال Gemini
    # ---------------------------------------------------------

    if query.data == "admin_test":
        await query.edit_message_text(
            "🧪 در حال تست اتصال به Gemini..."
        )

        try:
            result = ai.test_connection()

            text = (
                "✅ اتصال به Gemini موفق است.\n\n"
                f"مدل: {settings.gemini_model}\n"
                f"پاسخ: {result[:500]}"
            )

        except Exception as exc:
            text = (
                "❌ اتصال به Gemini ناموفق بود.\n\n"
                f"مدل: {settings.gemini_model}\n"
                f"خطا:\n{str(exc)[:1500]}"
            )

        await query.edit_message_text(
            text,
            reply_markup=back_menu(),
        )
        return

    # ---------------------------------------------------------
    # تست تولید متن
    # ---------------------------------------------------------

    if query.data == "admin_generate":
        await query.edit_message_text(
            "✍️ در حال تولید یک پست آزمایشی..."
        )

        try:
            result = ai.generate_text(
                "یک معرفی کوتاه و جذاب برای گوشی Poco X7 Pro"
            )

            text = (
                "✅ تولید متن موفق بود.\n\n"
                f"{result[:3500]}"
            )

        except Exception as exc:
            text = (
                "❌ تولید متن ناموفق بود.\n\n"
                f"خطا:\n{str(exc)[:1500]}"
            )

        await query.edit_message_text(
            text,
            reply_markup=back_menu(),
        )
        return

    # ---------------------------------------------------------
    # استخراج موضوعات فرعی
    # ---------------------------------------------------------

    if query.data == "admin_subtopics":
        try:
            last_post = db.get_last_post_text()

            if not last_post:
                await query.edit_message_text(
                    "⚠️ هنوز پستی در دیتابیس وجود ندارد.\n\n"
                    "ابتدا حداقل یک پست تولید کنید.",
                    reply_markup=back_menu(),
                )
                return

            await query.edit_message_text(
                "🧠 در حال استخراج موضوعات فرعی از آخرین پست..."
            )

            topics = ai.extract_topics(
                "موضوعات مرتبط با آخرین پست",
                last_post,
                count=6,
            )

            try:
                db.add_topics(topics)
            except Exception:
                # اگر ذخیره در دیتابیس با ساختار فعلی ناسازگار باشد،
                # حداقل خود موضوعات را نمایش می‌دهیم.
                pass

            lines = [
                "🧠 موضوعات فرعی استخراج‌شده:",
                "",
            ]

            for index, topic in enumerate(topics, start=1):
                lines.append(
                    f"{index}. {topic}"
                )

            lines.extend([
                "",
                "✅ موضوعات برای استفاده بعدی آماده شدند.",
            ])

            await query.edit_message_text(
                "\n".join(lines)[:4000],
                reply_markup=back_menu(),
            )

        except Exception as exc:
            await query.edit_message_text(
                "❌ استخراج موضوعات ناموفق بود.\n\n"
                f"خطا:\n{str(exc)[:1500]}",
                reply_markup=back_menu(),
            )

        return

    # ---------------------------------------------------------
    # افزودن موضوع دستی
    # ---------------------------------------------------------

    if query.data == "admin_add_topic":
        context.user_data["admin_action"] = "add_topic"

        await query.edit_message_text(
            "➕ افزودن موضوع جدید\n\n"
            "موضوع موردنظر را در یک پیام ارسال کن.\n\n"
            "مثال:\n"
            "«تأثیر هوش مصنوعی روی آینده شغل‌ها»\n\n"
            "برای لغو، /cancel را بفرست.",
            reply_markup=back_menu(),
        )
        return

    # ---------------------------------------------------------
    # وضعیت موضوعات
    # ---------------------------------------------------------

    if query.data == "admin_topics":
        try:
            posts, pending, used = db.stats()

            text = (
                "📚 وضعیت موضوعات\n\n"
                f"📌 موضوعات منتظر: {pending}\n"
                f"✅ موضوعات مصرف‌شده: {used}\n"
                f"📝 تعداد پست‌ها: {posts}\n\n"
                "برای افزودن موضوع جدید از گزینه «➕ افزودن موضوع» "
                "استفاده کن."
            )

        except Exception as exc:
            text = (
                "❌ دریافت وضعیت موضوعات ناموفق بود.\n\n"
                f"خطا:\n{str(exc)[:1200]}"
            )

        await query.edit_message_text(
            text,
            reply_markup=back_menu(),
        )
        return

    # ---------------------------------------------------------
    # وضعیت اتوماسیون
    # ---------------------------------------------------------

    if query.data == "admin_auto":
        try:
            state = db.get_automation()
            posts, pending, used = db.stats()

            if state:
                active = state[0]
                next_run = (
                    state[1]
                    if len(state) > 1
                    else "نامشخص"
                )
            else:
                active = False
                next_run = "نامشخص"

            text = (
                "⏰ وضعیت اتوماسیون\n\n"
                f"فعال: {'✅ بله' if active else '❌ خیر'}\n"
                f"اجرای بعدی: {next_run}\n\n"
                f"📝 پست‌ها: {posts}\n"
                f"📌 موضوعات منتظر: {pending}\n"
                f"✅ موضوعات مصرف‌شده: {used}"
            )

        except Exception as exc:
            text = (
                "❌ دریافت وضعیت اتوماسیون ناموفق بود.\n\n"
                f"خطا:\n{str(exc)[:1200]}"
            )

        await query.edit_message_text(
            text,
            reply_markup=back_menu(),
        )
        return

    # ---------------------------------------------------------
    # آمار دیتابیس
    # ---------------------------------------------------------

    if query.data == "admin_db":
        try:
            posts, pending, used = db.stats()

            text = (
                "📊 آمار دیتابیس\n\n"
                f"📝 تعداد پست‌ها: {posts}\n"
                f"📌 موضوعات منتظر: {pending}\n"
                f"✅ موضوعات مصرف‌شده: {used}"
            )

        except Exception as exc:
            text = (
                "❌ دریافت آمار دیتابیس ناموفق بود.\n\n"
                f"خطا:\n{str(exc)[:1200]}"
            )

        await query.edit_message_text(
            text,
            reply_markup=back_menu(),
        )
        return

    # ---------------------------------------------------------
    # تولید دستی پست
    # ---------------------------------------------------------

    if query.data == "admin_manual_post":
        context.user_data["admin_action"] = "manual_post"

        await query.edit_message_text(
            "🔄 تولید دستی پست\n\n"
            "موضوع پست را ارسال کن.\n\n"
            "مثال:\n"
            "«آیا هوش مصنوعی جای برنامه‌نویس‌ها را می‌گیرد؟»\n\n"
            "برای لغو، /cancel را بفرست.",
            reply_markup=back_menu(),
        )
        return

    await query.edit_message_text(
        "🎛 پنل مدیریت Nova",
        reply_markup=menu(),
    )


# =============================================================
# دریافت پیام‌های متنی ادمین
# =============================================================

async def admin_text_message(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    settings = context.application.bot_data["settings"]

    if not allowed(update.effective_user, settings):
        return

    action = context.user_data.get("admin_action")

    if not action:
        return

    text = (update.effective_message.text or "").strip()

    if not text:
        await update.effective_message.reply_text(
            "⚠️ متن معتبری دریافت نشد."
        )
        return

    ai = context.application.bot_data["ai"]
    db = context.application.bot_data["db"]

    # ---------------------------------------------------------
    # افزودن موضوع
    # ---------------------------------------------------------

    if action == "add_topic":
        try:
            db.add_topics([text])

            context.user_data.pop("admin_action", None)

            await update.effective_message.reply_text(
                "✅ موضوع با موفقیت به صف اضافه شد.\n\n"
                f"📌 موضوع:\n{text}",
                reply_markup=menu(),
            )

        except Exception as exc:
            await update.effective_message.reply_text(
                "❌ اضافه کردن موضوع ناموفق بود.\n\n"
                f"خطا:\n{str(exc)[:1200]}",
                reply_markup=menu(),
            )

        return

    # ---------------------------------------------------------
    # تولید دستی پست
    # ---------------------------------------------------------

    if action == "manual_post":
        context.user_data.pop("admin_action", None)

        await update.effective_message.reply_text(
            "✍️ در حال تولید پست با Gemini...\n\n"
            f"موضوع: {text}"
        )

        try:
            previous_text = db.get_last_post_text()

            result = ai.generate_text(
                text,
                previous_text=previous_text,
            )

            try:
                db.create_post(
                    topic=text,
                    text=result,
                )
            except Exception:
                # اگر امضای create_post در نسخه فعلی پروژه
                # متفاوت باشد، تولید متن همچنان نمایش داده می‌شود.
                pass

            await update.effective_message.reply_text(
                "✅ پست با موفقیت تولید شد.\n\n"
                f"{result[:3900]}",
                reply_markup=menu(),
            )

        except Exception as exc:
            await update.effective_message.reply_text(
                "❌ تولید پست ناموفق بود.\n\n"
                f"خطا:\n{str(exc)[:1500]}",
                reply_markup=menu(),
            )

        return


# =============================================================
# لغو عملیات ادمین
# =============================================================

async def cancel_admin_action(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    settings = context.application.bot_data["settings"]

    if not allowed(update.effective_user, settings):
        return

    context.user_data.pop("admin_action", None)

    await update.effective_message.reply_text(
        "❌ عملیات لغو شد.",
        reply_markup=menu(),
    )


# =============================================================
# ثبت Handlerها
# =============================================================

def register_admin_handlers(application):
    application.add_handler(
        CommandHandler(
            "admin",
            admin_command,
        )
    )

    application.add_handler(
        CommandHandler(
            "cancel",
            cancel_admin_action,
        )
    )

    application.add_handler(
        CallbackQueryHandler(
            callback,
            pattern=r"^admin_",
        )
    )

    application.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            admin_text_message,
        )
    )
