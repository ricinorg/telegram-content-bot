# Telegram Content Bot

ربات مدیریت محتوای تلگرام با Python و Telegram Bot API.

## قابلیت‌های نسخه پایه

- مدیریت از داخل Telegram
- تولید متن فارسی با AI
- Preview قبل از انتشار
- تأیید / رد پست
- انتشار مستقیم در کانال
- ذخیره پست‌ها در SQLite
- کنترل دسترسی ادمین
- آماده برای اضافه شدن تولید تصویر و زمان‌بندی

## نصب

Python 3.11 یا جدیدتر لازم است.

```bash
python -m venv .venv
```

فعال‌سازی محیط مجازی:

Linux/macOS:
```bash
source .venv/bin/activate
```

Windows:
```powershell
.venv\Scripts\activate
```

سپس:

```bash
pip install -r requirements.txt
```

## تنظیمات

`.env.example` را به `.env` تبدیل کنید و مقادیر لازم را وارد کنید:

```env
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHANNEL_ID=
OPENAI_API_KEY=
ADMIN_USER_IDS=
TIMEZONE=UTC
DATABASE_PATH=data/bot.db
```

**Token و API Key را داخل GitHub یا چت ارسال نکنید.**

`ADMIN_USER_IDS` اختیاری است، ولی برای استفاده واقعی بهتر است شناسه عددی Telegram ادمین‌ها در آن قرار گیرد.

## اجرای ربات

```bash
python -m src.bot
```

## روند استفاده

1. `/start`
2. `/newpost موضوع`
3. ربات متن را تولید می‌کند.
4. Preview نمایش داده می‌شود.
5. روی «انتشار» یا «رد» بزنید.
6. در صورت انتشار، پیام به کانال ارسال می‌شود.

## اتصال کانال

ربات باید در کانال به عنوان Administrator اضافه شود و اجازه ارسال پیام داشته باشد.

## امنیت

- `.env` در `.gitignore` قرار دارد.
- Secretها در سورس‌کد قرار داده نشده‌اند.
- برای محیط production بهتر است Secretها در سرویس deployment نگهداری شوند.

## مراحل بعدی

- تولید تصویر AI و اتصال تصویر به پست
- زمان‌بندی انتشار
- صف محتوا
- ویرایش Preview
- مدیریت چند کانال
- Webhook برای production
- Docker
- تست‌های کامل
- لاگ حرفه‌ای
- استقرار 24/7
