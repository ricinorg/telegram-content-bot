from openai import OpenAI
import json
import re


class AIServiceError(RuntimeError):
    """Safe, user-facing error with a stage name."""


class AIService:
    def __init__(self, key, text_model):
        self.client = OpenAI(
            api_key=key,
            base_url="https://api.gapgpt.app/v1"
        )
        self.text_model = text_model

    def _call(self, prompt):
        r = self.client.chat.completions.create(
            model=self.text_model,
            messages=[
                {
                    "role": "user",
                    "content": prompt
                }
            ],
        )
        text = (r.choices[0].message.content or "").strip()

        if not text:
            raise RuntimeError("OpenAI پاسخ متنی خالی برگرداند.")
        return text

    def generate_text(self, topic, previous_text=None):
        context = ""
        if previous_text:
            context = (
                "\nاین پست قبلی است. پست جدید باید درباره موضوع جدید باشد و "
                "تکرار لفظی یا محتوایی آن نباشد:\n---\n"
                f"{previous_text}\n---\n"
            )
        prompt = f"""برای کانال تلگرامی فارسی @nova_ip درباره موضوع زیر یک پست خلاقانه و مستقل بنویس:
موضوع: {topic}
{context}
قوانین قطعی:
- لحن دوستانه، صمیمی و انسانی.
- شروع با قلاب ذهنی قوی و کنجکاوکننده.
- متن نسبتاً طولانی، مفید و خوانا، با پاراگراف‌های مناسب و ایموجی متعادل.
- حتماً @nova_ip داخل متن باشد.
- حتماً یک سؤال مشخص از اعضای کانال بپرس.
- متن اختصاصی و خلاقانه باشد و کلیشه‌ای نباشد.
- اگر موضوع بخشی از یک موضوع بزرگ‌تر است، روی همان بخش تمرکز کن.
- از ادعاهای ساختگی و مشخصات نامطمئن پرهیز کن.
- در پایان 5 تا 10 هشتگ مرتبط با همین موضوع قرار بده.
فقط متن نهایی را برگردان."""
        try:
            return self._call(prompt)
        except Exception as exc:
            raise AIServiceError(
                f"TEXT_GENERATION | مدل: {self.text_model} | {type(exc).__name__}: {exc}"
            ) from exc

    def extract_topics(self, topic, text, count=6):
        prompt = f"""از پست فارسی زیر، {count} موضوع فرعی مشخص و قابل تبدیل به یک پست مستقل استخراج کن.
موضوع فعلی: {topic}

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
- هیچ توضیح اضافه، شماره‌گذاری یا علامت خاصی نده."""
        try:
            raw = self._call(prompt)
            items = []
            for line in raw.splitlines():
                line = re.sub(r"^[\s\-\*\d\.\)\:]+", "", line).strip()
                if 4 <= len(line) <= 180 and line not in items:
                    items.append(line)
            if len(items) < 4:
                raise RuntimeError("تعداد موضوعات فرعی استخراج‌شده کمتر از ۴ است.")
            return items[:count]
        except Exception as exc:
            raise AIServiceError(
                f"TOPIC_EXTRACTION | مدل: {self.text_model} | {type(exc).__name__}: {exc}"
            ) from exc
