# Telegram Content Bot V5 — Chain Automation

ربات بدون تولید تصویر کار می‌کند و می‌تواند یک زنجیره خودکار از محتوا بسازد.

## منطق V5
1. ادمین یک بار `/starttopic موضوع اصلی` می‌فرستد.
2. ربات پست اول را تولید و در کانال منتشر می‌کند.
3. از همان پست 4 تا 6 موضوع فرعی استخراج و در SQLite ذخیره می‌کند.
4. هر یک ساعت یکی از موضوعات فرعیِ استفاده‌نشده انتخاب می‌شود.
5. ربات درباره آن موضوع پست جدید می‌سازد و منتشر می‌کند.
6. از پست جدید دوباره موضوعات فرعی استخراج می‌شود و به صف اضافه می‌گردد.
7. موضوع استفاده‌شده علامت می‌خورد تا دوباره انتخاب نشود.
8. وضعیت زنجیره در SQLite باقی می‌ماند و بعد از restart دوباره قابل ادامه است.

## دستورات
- `/starttopic سامسونگ Galaxy S24` شروع زنجیره جدید
- `/autostatus` وضعیت زنجیره
- `/stopauto` توقف انتشار خودکار
- `/status` وضعیت تنظیمات
- `/newpost موضوع` انتشار دستی

## Render
Build:
`unzip -o telegram-content-bot-v5-chain.zip && pip install -r telegram-content-bot/requirements.txt`

Start:
`cd telegram-content-bot && python bot.py`

Environment:
`TELEGRAM_BOT_TOKEN`
`TELEGRAM_CHANNEL_ID`
`OPENAI_API_KEY`
`OPENAI_TEXT_MODEL=gpt-5.6-luna`
`ADMIN_USER_IDS` (اختیاری)
`TIMEZONE=UTC`
`DATABASE_PATH=data/bot.db`
`LOG_LEVEL=INFO`

تولید تصویر در V5 خاموش است.
