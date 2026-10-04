import os
import re

from google import genai


class AIServiceError(RuntimeError):
    """Safe, user-facing error with a stage name."""


class AIService:
    def __init__(self, key=None, text_model=None):
        self.api_key = key or os.getenv("GEMINI_API_KEY", "")
        self.text_model = (
            text_model
            or os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
        )

        if not self.api_key:
            raise AIServiceError(
                "GEMINI_API_KEY تنظیم نشده است."
            )

        self.client = genai.Client(
            api_key=self.api_key
        )

    def _call(self, prompt):
        try:
            response = self.client.models.generate_content(
                model=self.text_model,
                contents=prompt,
            )

            text = (response.text or "").strip()

            if not text:
                raise RuntimeError(
                    "Gemini پاسخ متنی خالی برگرداند."
                )

            return text

        except Exception as exc:
            raise RuntimeError(
                f"Gemini API | مدل: {self.text_model} | "
                f"{type(exc).__name__}: {exc}"
            ) from exc

    def test_connection(self):
        """تست اتصال به Gemini برای پنل مدیریت."""
        return self._call(
            "فقط کلمه OK را پاسخ بده."
        )

    def generate_text(self, topic, previous_text=None):
        context = ""

        if previous_text:
            context = (
                "\nاین پست قبلی است. پست جدید باید درباره موضوع جدید باشد "
                "و تکرار لفظی یا محتوایی آن نباشد:\n"
                "---\n"
                f"{previous_text}\n"
                "---\n"
            )

        prompt = f"""برای کانال تلگرامی فارسی @nova_ip درباره موضوع زیر
یک پست خلاقانه و مستقل بنویس:

موضوع: {topic}
{context}

قوانین قطعی:

- لحن دوستانه، صمیمی و انسانی.
- شروع با یک قلاب ذهنی قوی و کنجکاوکننده.
- متن نسبتاً طولانی، مفید و خوانا باشد.
- پاراگراف‌بندی مناسب داشته باشد.
- از ایموجی به اندازه استفاده کن.
- حتماً @nova_ip داخل متن باشد.
- حتماً یک سؤال مشخص از اعضای کانال بپرس.
- متن اختصاصی و خلاقانه باشد و کلیشه‌ای نباشد.
- اگر موضوع بخشی از یک موضوع بزرگ‌تر است، روی همان بخش تمرکز کن.
- از ادعاهای ساختگی و مشخصات نامطمئن پرهیز کن.
- در پایان 5 تا 10 هشتگ مرتبط با همین موضوع قرار بده.
- فقط متن نهایی را برگردان.

فقط متن نهایی پست را بنویس."""

        try:
            return self._call(prompt)

        except Exception as exc:
            raise AIServiceError(
                f"TEXT_GENERATION | مدل: {self.text_model} | "
                f"{type(exc).__name__}: {exc}"
            ) from exc

    def extract_topics(self, topic, text, count=6):
        prompt = f"""از پست فارسی زیر، {count} موضوع فرعی مشخص و
قابل تبدیل به یک پست مستقل استخراج کن.

موضوع فعلی:
{topic}

پست:
---
{text}
---

قوانین:

- موضوع‌ها باید واقعاً از همین پست یا موضوع آن قابل استخراج باشند.
- کوتاه، مشخص و قابل فهم باشند.
- تکراری یا هم‌معنی نباشند.
- خود موضوع فعلی را دوباره پیشنهاد نده.
- هر خط فقط یک موضوع باشد.
- دقیقاً بین 4 تا {count} موضوع بده.
- هیچ توضیح اضافه، شماره‌گذاری یا علامت خاصی نده.

فقط موضوع‌ها را خط‌به‌خط برگردان."""

        try:
            raw = self._call(prompt)

            items = []

            for line in raw.splitlines():
                line = re.sub(
                    r"^[\s\-\*\d\.\)\:]+",
                    "",
                    line
                ).strip()

                if (
                    4 <= len(line) <= 180
                    and line not in items
                ):
                    items.append(line)

            if len(items) < 4:
                raise RuntimeError(
                    "تعداد موضوعات فرعی استخراج‌شده کمتر از ۴ است."
                )

            return items[:count]

        except Exception as exc:
            raise AIServiceError(
                f"TOPIC_EXTRACTION | مدل: {self.text_model} | "
                f"{type(exc).__name__}: {exc}"
            ) from exc
