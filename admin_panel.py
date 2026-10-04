from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import CallbackQueryHandler, CommandHandler, ContextTypes

def allowed(user, settings):
    return bool(user) and (not settings.admin_user_ids or user.id in settings.admin_user_ids)

def menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🤖 وضعیت AI", callback_data="admin_status")],
        [InlineKeyboardButton("🧪 تست اتصال API", callback_data="admin_test")],
        [InlineKeyboardButton("✍️ تست تولید متن", callback_data="admin_generate")],
        [InlineKeyboardButton("⏰ وضعیت اتوماسیون", callback_data="admin_auto")],
        [InlineKeyboardButton("📊 وضعیت دیتابیس", callback_data="admin_db")],
    ])

async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    s = context.application.bot_data["settings"]
    if not allowed(update.effective_user, s):
        return
    await update.effective_message.reply_text(
        "🎛 پنل مدیریت Nova\n\nیک گزینه را انتخاب کن:",
        reply_markup=menu()
    )

async def callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    s = context.application.bot_data["settings"]
    if not allowed(q.from_user, s):
        await q.edit_message_text("⛔ دسترسی ندارید.")
        return
    ai = context.application.bot_data["ai"]
    db = context.application.bot_data["db"]

    if q.data == "admin_status":
        text = (
            "🤖 وضعیت AI\n\n"
            "سرویس: OpenAI API\n"
            f"مدل: {s.openai_text_model}\n"
            f"API Key: {'🟢 تنظیم شده' if s.openai_api_key else '🔴 تنظیم نشده'}"
        )
    elif q.data == "admin_test":
        await q.edit_message_text("🧪 در حال تست اتصال OpenAI...")
        try:
            result = ai.test_connection()
            text = f"✅ اتصال موفق است.\n\nمدل: {s.openai_text_model}\nپاسخ: {result[:300]}"
        except Exception as e:
            text = f"❌ اتصال ناموفق است.\n\nمدل: {s.openai_text_model}\nخطا: {str(e)[:1200]}"
    elif q.data == "admin_generate":
        await q.edit_message_text("✍️ در حال تست تولید متن...")
        try:
            result = ai.generate_text("یک معرفی کوتاه و جذاب برای گوشی Poco X7 Pro")
            text = "✅ تولید متن موفق بود.\n\n" + result[:3500]
        except Exception as e:
            text = f"❌ تولید متن ناموفق بود.\n\nخطا: {str(e)[:1400]}"
    elif q.data == "admin_auto":
        state = db.get_automation()
        posts, pending, used = db.stats()
        text = (
            "⏰ وضعیت اتوماسیون\n\n"
            f"فعال: {'✅ بله' if state and state[0] else '❌ خیر'}\n"
            f"پست‌ها: {posts}\nموضوعات منتظر: {pending}\nموضوعات مصرف‌شده: {used}"
        )
    elif q.data == "admin_db":
        posts, pending, used = db.stats()
        text = f"📊 وضعیت دیتابیس\n\nپست‌ها: {posts}\nمنتظر: {pending}\nمصرف‌شده: {used}"
    else:
        await q.edit_message_text("🎛 پنل مدیریت Nova", reply_markup=menu())
        return

    await q.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup(
            [[InlineKeyboardButton("🔙 بازگشت", callback_data="admin_home")]]
        )
    )

def register_admin_handlers(application):
    application.add_handler(CommandHandler("admin", admin_command))
    application.add_handler(CallbackQueryHandler(callback, pattern=r"^admin_"))
