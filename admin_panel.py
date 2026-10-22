import logging
import asyncio
import html
import re
from datetime import datetime, timedelta, timezone

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import CallbackQueryHandler, CommandHandler, ContextTypes

logger = logging.getLogger("telegram-content-bot.admin")


def allowed(user, settings):
    return bool(user) and bool(settings.admin_user_ids) and user.id in settings.admin_user_ids


def _btn(label, data):
    return InlineKeyboardButton(label, callback_data=data)


def menu():
    return InlineKeyboardMarkup([
        [_btn("📊 داشبورد", "admin_dashboard"), _btn("🤖 هوش مصنوعی", "admin_ai")],
        [_btn("📅 زمان‌بندی", "admin_schedule"), _btn("🖼️ تصاویر", "admin_images")],
        [_btn("✍️ محتوا و موضوعات", "admin_content"), _btn("📚 صف و آمار", "admin_db")],
        [_btn("🧪 تست اتصال API", "admin_test"), _btn("✍️ تولید آزمایشی", "admin_generate")],
        [_btn("🧠 استخراج موضوعات", "admin_subtopics"), _btn("➕ افزودن موضوع", "admin_add_topic")],
        [_btn("🔄 تولید دستی پست", "admin_manual_post")],
        [_btn("💬 گفت‌وگوی مستقیم با هوش مصنوعی", "admin_chat")],
        [_btn("🛑 توقف/فعال‌سازی اتوماسیون", "admin_toggle_auto")],
    ])


def back_menu():
    return InlineKeyboardMarkup([[_btn("🔙 پنل اصلی", "admin_home")]])


def _automation_text(db):
    state = db.get_automation()
    if not state:
        return "اطلاعات اتوماسیون موجود نیست."
    active, root, _last, next_run, start_time, interval = state
    return ("📅 تنظیمات زمان‌بندی\n\n"
            f"وضعیت: {'🟢 فعال' if active else '🔴 متوقف'}\n"
            f"موضوع ریشه: {root or 'تنظیم نشده'}\n"
            f"ساعت شروع: {start_time or 'تنظیم نشده'}\n"
            f"فاصله اجرا: {interval or 4} ساعت\n"
            f"اجرای بعدی: {next_run or 'نامشخص'}")


def _schedule_keyboard():
    return InlineKeyboardMarkup([
        [_btn("⏱ تغییر فاصله (ساعت)", "admin_set_interval"), _btn("🕒 تغییر ساعت شروع", "admin_set_start")],
        [_btn("🗂 تغییر موضوع ریشه", "admin_set_root")],
        [_btn("▶️/⏸ تغییر وضعیت", "admin_toggle_auto")],
        [_btn("🔙 پنل اصلی", "admin_home")],
    ])


async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    settings = context.application.bot_data["settings"]
    if not allowed(update.effective_user, settings):
        await update.effective_message.reply_text("⛔ دسترسی به پنل مدیریت ندارید.")
        return
    context.user_data.pop("admin_action", None)
    await update.effective_message.reply_text("🎛 پنل مدیریت Nova\n\nیک بخش را انتخاب کنید:", reply_markup=menu())


async def callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    settings = context.application.bot_data["settings"]
    if not allowed(query.from_user, settings):
        await query.answer("دسترسی ندارید.", show_alert=True)
        return
    await query.answer()
    db = context.application.bot_data["db"]
    ai = context.application.bot_data["ai"]
    data = query.data or ""

    if data == "admin_chat":
        context.user_data["ai_chat_mode"] = True
        context.user_data.pop("admin_action", None)
        history = context.user_data.get("ai_chat_history", [])
        await query.edit_message_text(
            "💬 گفت‌وگوی مستقیم با هوش مصنوعی\n\n"
            "پیامت را بفرست تا با همان مدل DeepSeek پاسخ بدهم. "
            "کدها در بلوک‌های جداگانه نمایش داده می‌شوند تا راحت کپی شوند.\n\n"
            f"تاریخچه این گفت‌وگو: {'فعال' if history else 'خالی'}\n"
            "دستورها: /clearchat پاک‌کردن تاریخچه، /exitchat خروج از چت، /cancel لغو حالت فعلی.",
            reply_markup=InlineKeyboardMarkup([
                [_btn("🧹 پاک‌کردن تاریخچه", "admin_chat_clear")],
                [_btn("🔙 پنل اصلی", "admin_home")],
            ]),
        )
    elif data == "admin_chat_clear":
        context.user_data["ai_chat_history"] = []
        context.user_data["ai_chat_mode"] = True
        await query.edit_message_text(
            "🧹 تاریخچه گفت‌وگو پاک شد. پیام بعدی را بفرست.",
            reply_markup=InlineKeyboardMarkup([[_btn("🔙 پنل اصلی", "admin_home")]]),
        )
    elif data == "admin_home":
        context.user_data.pop("ai_chat_mode", None)
        context.user_data.pop("admin_action", None)
        await query.edit_message_text("🎛 پنل مدیریت Nova\n\nیک بخش را انتخاب کنید:", reply_markup=menu())
    elif data == "admin_dashboard":
        try:
            published, pending, used, processing, drafts = db.stats()
            auto = db.get_automation()
            text = ("📊 داشبورد ربات\n\n"
                    f"🤖 مدل: {settings.deepseek_model}\n"
                    f"📢 پست‌های منتشرشده: {published}\n"
                    f"📝 پیش‌نویس‌ها: {drafts}\n"
                    f"⏳ موضوعات منتظر: {pending}\n"
                    f"⚙️ موضوعات در حال پردازش: {processing}\n"
                    f"✅ موضوعات مصرف‌شده: {used}\n"
                    f"📅 اتوماسیون: {'فعال' if auto and auto[0] else 'متوقف'}")
        except Exception as exc:
            text = f"❌ دریافت داشبورد ناموفق بود: {exc}"
        await query.edit_message_text(text, reply_markup=back_menu())
    elif data == "admin_ai":
        text = ("🤖 تنظیمات هوش مصنوعی\n\n"
                f"ارائه‌دهنده: DeepSeek-compatible API\nمدل: {settings.deepseek_model}\n"
                f"Base URL: {settings.deepseek_base_url}\n"
                f"سبک محتوا: {db.get_setting('content_style', 'حرفه‌ای و صمیمی')}\n"
                f"طول محتوا: {db.get_setting('content_length', 'متوسط')}\n\n"
                "کلید API در پنل نمایش داده نمی‌شود.")
        kb = InlineKeyboardMarkup([
            [_btn("✍️ تغییر سبک محتوا", "admin_set_style"), _btn("📏 طول پست", "admin_set_length")],
            [_btn("🧪 تست اتصال", "admin_test")], [_btn("🔙 پنل اصلی", "admin_home")],
        ])
        await query.edit_message_text(text, reply_markup=kb)
    elif data == "admin_schedule":
        await query.edit_message_text(_automation_text(db), reply_markup=_schedule_keyboard())
    elif data == "admin_images":
        enabled = db.get_setting("image_enabled", "0") == "1"
        style = db.get_setting("image_style", "مدرن و مینیمال")
        ratio = db.get_setting("image_ratio", "4:5")
        text = ("🖼️ تنظیمات تصویر\n\n"
                f"وضعیت: {'🟢 فعال' if enabled else '🔴 غیرفعال'}\n"
                f"سبک: {style}\nنسبت تصویر: {ratio}\n\n"
                "توجه: این بخش فعلاً تنظیمات را ذخیره می‌کند؛ تولید و ارسال تصویر تا اتصال سرویس تصویری فعال نمی‌شود.")
        kb = InlineKeyboardMarkup([
            [_btn("🟢/🔴 فعال یا غیرفعال", "admin_toggle_images")],
            [_btn("🎨 تغییر سبک", "admin_set_image_style"), _btn("📐 تغییر نسبت", "admin_set_image_ratio")],
            [_btn("🔙 پنل اصلی", "admin_home")],
        ])
        await query.edit_message_text(text, reply_markup=kb)
    elif data == "admin_content":
        try:
            published, pending, used, processing, drafts = db.stats()
            text = ("✍️ مدیریت محتوا\n\n"
                    f"موضوعات منتظر: {pending}\nموضوعات مصرف‌شده: {used}\n"
                    f"پیش‌نویس‌ها: {drafts}\nسبک: {db.get_setting('content_style', 'حرفه‌ای و صمیمی')}\n"
                    f"طول: {db.get_setting('content_length', 'متوسط')}")
        except Exception as exc:
            text = f"❌ دریافت اطلاعات ناموفق بود: {exc}"
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup([
            [_btn("➕ افزودن موضوع", "admin_add_topic"), _btn("🧠 استخراج موضوعات", "admin_subtopics")],
            [_btn("✍️ تغییر سبک", "admin_set_style"), _btn("📏 طول پست", "admin_set_length")],
            [_btn("🔙 پنل اصلی", "admin_home")],
        ]))
    elif data == "admin_toggle_auto":
        state = db.get_automation()
        if not state:
            await query.edit_message_text("❌ رکورد اتوماسیون پیدا نشد.", reply_markup=back_menu())
            return
        if state[0]:
            db.stop_automation()
            msg = "🔴 اتوماسیون متوقف شد."
        else:
            interval = int(state[5] or 4)
            next_run = (datetime.now(timezone.utc) + timedelta(hours=interval)).isoformat()
            db.start_automation(state[1] or "موضوعات کانال", next_run, state[4], interval)
            msg = "🟢 اتوماسیون فعال شد. اجرای خودکار به صف موضوعات موجود نیاز دارد."
        await query.edit_message_text(msg + "\n\n" + _automation_text(db), reply_markup=_schedule_keyboard())
    elif data == "admin_set_interval":
        context.user_data["admin_action"] = "set_interval"
        await query.edit_message_text("⏱ عدد فاصله اجرا را به ساعت بفرست (۱ تا ۲۴).", reply_markup=back_menu())
    elif data == "admin_set_start":
        context.user_data["admin_action"] = "set_start"
        await query.edit_message_text("🕒 ساعت شروع را با قالب 09:30 بفرست.", reply_markup=back_menu())
    elif data == "admin_set_root":
        context.user_data["admin_action"] = "set_root"
        await query.edit_message_text("🗂 موضوع اصلی اتوماسیون را بفرست.", reply_markup=back_menu())
    elif data == "admin_set_style":
        context.user_data["admin_action"] = "set_style"
        await query.edit_message_text("✍️ سبک محتوا را بنویس؛ مثال: آموزشی، صمیمی، دقیق و بدون اغراق.", reply_markup=back_menu())
    elif data == "admin_set_length":
        kb = InlineKeyboardMarkup([
            [_btn("کوتاه", "admin_length_short"), _btn("متوسط", "admin_length_medium"), _btn("بلند", "admin_length_long")],
            [_btn("🔙 پنل اصلی", "admin_home")],
        ])
        await query.edit_message_text("📏 طول پیش‌فرض پست را انتخاب کن:", reply_markup=kb)
    elif data.startswith("admin_length_"):
        length = data.removeprefix("admin_length_")
        db.set_setting("content_length", {"short":"کوتاه", "medium":"متوسط", "long":"بلند"}.get(length, "متوسط"))
        await query.edit_message_text("✅ طول محتوا ذخیره شد.", reply_markup=back_menu())
    elif data == "admin_toggle_images":
        enabled = db.get_setting("image_enabled", "0") != "1"
        db.set_setting("image_enabled", "1" if enabled else "0")
        await query.edit_message_text(f"✅ تنظیم تصویر {'فعال' if enabled else 'غیرفعال'} شد.\nتولید واقعی تصویر نیازمند اتصال سرویس تصویری است.", reply_markup=back_menu())
    elif data in ("admin_set_image_style", "admin_set_image_ratio"):
        context.user_data["admin_action"] = "set_image_style" if data.endswith("style") else "set_image_ratio"
        prompt = "سبک تصویر را بفرست (مثلاً مینیمال، واقع‌گرایانه، سه‌بعدی)." if data.endswith("style") else "نسبت تصویر را بفرست (مثلاً 1:1، 4:5 یا 16:9)."
        await query.edit_message_text(prompt, reply_markup=back_menu())
    elif data == "admin_test":
        await query.edit_message_text("🧪 در حال تست اتصال به API...")
        try:
            result = await __import__('asyncio').to_thread(ai.test_connection)
            text = f"✅ اتصال موفق بود.\nمدل: {settings.deepseek_model}\nپاسخ: {result[:300]}"
        except Exception as exc:
            text = f"❌ تست اتصال ناموفق بود.\nمدل: {settings.deepseek_model}\nخطا: {str(exc)[:1200]}"
        await query.edit_message_text(text, reply_markup=back_menu())
    elif data == "admin_generate":
        await query.edit_message_text("✍️ در حال تولید متن آزمایشی...")
        try:
            result = await __import__('asyncio').to_thread(ai.generate_text, "یک پست کوتاه و کاربردی درباره ابزارهای هوش مصنوعی")
            await query.edit_message_text("✅ تولید موفق بود:\n\n" + result[:3500], reply_markup=back_menu())
        except Exception as exc:
            await query.edit_message_text(f"❌ تولید ناموفق بود:\n{str(exc)[:1200]}", reply_markup=back_menu())
    elif data == "admin_subtopics":
        try:
            last_post = db.get_last_post_text()
            if not last_post:
                await query.edit_message_text("هنوز پستی برای استخراج موضوعات وجود ندارد.", reply_markup=back_menu()); return
            await query.edit_message_text("🧠 در حال استخراج موضوعات...")
            topics = await __import__('asyncio').to_thread(ai.extract_topics, "موضوعات مرتبط", last_post, 6)
            if topics:
                db.add_topics(topics)
            await query.edit_message_text("🧠 موضوعات استخراج‌شده:\n\n" + "\n".join(f"• {x}" for x in topics)[:3500], reply_markup=back_menu())
        except Exception as exc:
            await query.edit_message_text(f"❌ خطا: {str(exc)[:1200]}", reply_markup=back_menu())
    elif data == "admin_add_topic":
        context.user_data["admin_action"] = "add_topic"
        await query.edit_message_text("➕ موضوع جدید را در پیام بعدی بفرست. برای لغو /cancel را بزن.", reply_markup=back_menu())
    elif data == "admin_manual_post":
        context.user_data["admin_action"] = "manual_post"
        await query.edit_message_text("🔄 موضوع پست را بفرست. برای لغو /cancel را بزن.", reply_markup=back_menu())
    elif data == "admin_db":
        try:
            published, pending, used, processing, drafts = db.stats()
            text = ("📚 آمار و صف\n\n" f"منتشرشده: {published}\nپیش‌نویس: {drafts}\nموضوعات منتظر: {pending}\nدر حال پردازش: {processing}\nمصرف‌شده: {used}")
        except Exception as exc:
            text = f"❌ خطا در آمار: {exc}"
        await query.edit_message_text(text, reply_markup=back_menu())
    else:
        await query.edit_message_text("گزینه ناشناخته است.", reply_markup=menu())


def _format_chat_answer(text: str):
    """Render Markdown fenced code blocks as Telegram HTML for easy copying."""
    parts = []
    pattern = re.compile(r"```([\w.+#-]*)\s*\n?(.*?)```", re.DOTALL)
    cursor = 0
    for match in pattern.finditer(text):
        before = text[cursor:match.start()].strip()
        if before:
            # Escape text to avoid Telegram HTML parsing errors. Preserve line breaks.
            parts.append(html.escape(before).replace("\n", "\n"))
        language = match.group(1).strip()
        code = match.group(2).strip("\n")
        lang_attr = f' class="language-{html.escape(language, quote=True)}"' if language else ""
        parts.append(f"<pre><code{lang_attr}>{html.escape(code)}</code></pre>")
        cursor = match.end()
    tail = text[cursor:].strip()
    if tail:
        parts.append(html.escape(tail))
    if not parts:
        parts = [html.escape(text)]
    # Telegram messages are limited to 4096 chars; keep each formatted block under limit.
    chunks = []
    for part in parts:
        if len(part) <= 3900:
            chunks.append(part)
        else:
            # Large code/text chunks are split safely as escaped plain text.
            plain = re.sub(r"<[^>]+>", "", part)
            for start in range(0, len(plain), 3500):
                chunks.append(html.escape(plain[start:start + 3500]))
    return chunks or ["(پاسخی دریافت نشد)"]


async def admin_text_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    settings = context.application.bot_data["settings"]
    if not allowed(update.effective_user, settings):
        return
    if not update.effective_message or not update.effective_message.text:
        return

    incoming = update.effective_message.text.strip()
    if incoming == "/exitchat":
        context.user_data.pop("ai_chat_mode", None)
        await update.effective_message.reply_text("از گفت‌وگوی مستقیم خارج شدی.", reply_markup=menu())
        return
    if incoming == "/clearchat":
        context.user_data["ai_chat_history"] = []
        context.user_data["ai_chat_mode"] = True
        await update.effective_message.reply_text("🧹 تاریخچه گفت‌وگو پاک شد.")
        return

    if context.user_data.get("ai_chat_mode"):
        if incoming.startswith("/"):
            return
        ai = context.application.bot_data["ai"]
        history = context.user_data.setdefault("ai_chat_history", [])
        history = history[-10:]
        prompt_parts = [
            "تو دستیار گفت‌وگویی مستقیم کاربر هستی. به فارسی پاسخ بده مگر اینکه کاربر زبان دیگری بخواهد.",
            "برای کدها از بلوک‌های Markdown سه‌تایی با برچسب زبان استفاده کن، مانند ```python. توضیح را بیرون بلوک کد بنویس.",
            "اگر کاربر کد موجودی فرستاد، دقیق به آن توجه کن. چیزی را که نمی‌دانی قطعی جلوه نده.",
            "",
        ]
        for item in history:
            prompt_parts.append(f"{item['role']}: {item['content']}")
        prompt_parts.extend([f"user: {incoming}", "assistant:"])
        await update.effective_message.reply_text("⏳ در حال فکر کردن...")
        try:
            answer = await asyncio.to_thread(
                ai._call,
                "\n\n".join(prompt_parts),
                temperature=0.7,
                max_output_tokens=3500,
                retries=2,
            )
            history.extend([
                {"role": "user", "content": incoming},
                {"role": "assistant", "content": answer},
            ])
            context.user_data["ai_chat_history"] = history[-20:]
            chunks = _format_chat_answer(answer)
            for chunk in chunks:
                await update.effective_message.reply_text(chunk, parse_mode="HTML")
        except Exception as exc:
            logger.exception("Direct AI chat failed")
            await update.effective_message.reply_text(
                "❌ دریافت پاسخ از هوش مصنوعی ناموفق بود.\n" + html.escape(str(exc)[:900]),
                parse_mode="HTML",
            )
        return

    action = context.user_data.get("admin_action")
    if not action:
        return
    value = incoming
    value = update.effective_message.text.strip()
    db = context.application.bot_data["db"]
    try:
        if action == "add_topic":
            db.add_topics([value]); message = "✅ موضوع به صف اضافه شد."
        elif action == "manual_post":
            context.user_data.pop("admin_action", None)
            ai = context.application.bot_data["ai"]
            await update.effective_message.reply_text("⏳ در حال تولید پست...")
            result = await __import__('asyncio').to_thread(ai.generate_text, value, None, None, db.get_setting("content_style", ""))
            post_id = db.create_post(prompt=value, text=result)
            message = f"✅ پیش‌نویس #{post_id} ساخته شد:\n\n{result[:3500]}"
        elif action == "set_interval":
            hours = int(value)
            db.set_interval_hours(hours)
            state = db.get_automation()
            if state and state[0]:
                next_run = (datetime.now(timezone.utc) + timedelta(hours=hours)).isoformat()
                db.set_next_run(next_run)
            message = f"✅ فاصله اتوماسیون روی {hours} ساعت ذخیره شد."
        elif action == "set_start":
            datetime.strptime(value, "%H:%M")
            db.set_start_time(value)
            message = f"✅ ساعت شروع روی {value} ذخیره شد. (منطقه زمانی فعلی زمان‌بند در نسخه فعلی UTC است.)"
        elif action == "set_root":
            state = db.get_automation()
            interval = int(state[5] or 4) if state else 4
            active = bool(state and state[0])
            next_run = (datetime.now(timezone.utc) + timedelta(hours=interval)).isoformat() if active else None
            db.set_automation_schedule(state[4] if state else None, interval, next_run, active, value)
            db.add_topic(value, parent_id=None, depth=0)
            message = "✅ موضوع ریشه ذخیره و به صف موضوعات اضافه شد."
        elif action == "set_style":
            db.set_setting("content_style", value); message = "✅ سبک محتوای پیش‌فرض ذخیره شد."
        elif action == "set_image_style":
            db.set_setting("image_style", value); message = "✅ سبک تصویر ذخیره شد."
        elif action == "set_image_ratio":
            if value not in {"1:1", "4:5", "16:9", "9:16", "3:2"}:
                raise ValueError("نسبت مجاز: 1:1، 4:5، 16:9، 9:16، 3:2")
            db.set_setting("image_ratio", value); message = "✅ نسبت تصویر ذخیره شد."
        else:
            message = "⚠️ عملیات شناخته نشد."
    except Exception as exc:
        message = f"❌ انجام عملیات ناموفق بود: {str(exc)[:700]}"
    finally:
        context.user_data.pop("admin_action", None)
    await update.effective_message.reply_text(message, reply_markup=menu())


async def cancel_admin_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not allowed(update.effective_user, context.application.bot_data["settings"]):
        return
    context.user_data.pop("admin_action", None)
    await update.effective_message.reply_text("عملیات لغو شد.", reply_markup=menu())


async def _exit_chat_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not allowed(update.effective_user, context.application.bot_data["settings"]):
        return
    context.user_data.pop("ai_chat_mode", None)
    await update.effective_message.reply_text("از گفت‌وگوی مستقیم خارج شدی.", reply_markup=menu())


async def _clear_chat_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not allowed(update.effective_user, context.application.bot_data["settings"]):
        return
    context.user_data["ai_chat_history"] = []
    context.user_data["ai_chat_mode"] = True
    await update.effective_message.reply_text("🧹 تاریخچه پاک شد. می‌توانی ادامه بدهی.")


def register_admin_handlers(application):
    application.add_handler(CommandHandler("admin", admin_command))
    application.add_handler(CommandHandler("exitchat", _exit_chat_command))
    application.add_handler(CommandHandler("clearchat", _clear_chat_command))
    application.add_handler(CallbackQueryHandler(callback, pattern=r"^admin_"))
