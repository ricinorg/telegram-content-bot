# Telegram Content Bot — Free Render Web Service

این نسخه برای اجرای رایگان روی **Render Web Service** آماده شده است.

## قابلیت فعلی
- اتصال به Telegram
- دریافت `/newpost`
- تولید متن فارسی با OpenAI
- نمایش پیش‌نمایش
- انتشار یا رد پست
- استفاده از Telegram Webhook به‌جای polling، تا بتواند روی Free Web Service اجرا شود.

## متغیرهای لازم در Render
- `TELEGRAM_BOT_TOKEN` — توکن ربات (فقط داخل Render وارد شود)
- `TELEGRAM_CHANNEL_ID` — برای کانال شما: `@nova_ip`
- `OPENAI_API_KEY` — کلید OpenAI (فقط داخل Render وارد شود)

متغیرهای اختیاری:
- `OPENAI_TEXT_MODEL` — پیش‌فرض `gpt-5.6-luna`
- `OPENAI_IMAGE_MODEL` — پیش‌فرض `gpt-image-2`
- `ADMIN_USER_IDS`
- `TIMEZONE`
- `DATABASE_PATH`
- `LOG_LEVEL`

Render خودش `RENDER_EXTERNAL_URL` و `PORT` را در اختیار سرویس می‌گذارد.

## اجرای Render
نوع سرویس: **Web Service**
پلن: **Free**

Build Command:
```text
unzip -o telegram-content-bot-free.zip && pip install -r telegram-content-bot/requirements.txt
```

Start Command:
```text
cd telegram-content-bot && python -m src.bot
```

Root Directory را خالی بگذارید.

> نکته: Free Web Service روی Render بعد از ۱۵ دقیقه بدون ترافیک ورودی می‌تواند sleep شود و فایل‌های محلی مثل SQLite پایدار نیستند. این نسخه برای شروع و تست رایگان مناسب است؛ برای نسخه دائمی بعداً باید ذخیره‌سازی پایدار اضافه شود.
