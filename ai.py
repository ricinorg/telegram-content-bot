import os
import re
import time

from google import genai

class AIServiceError(RuntimeError):
pass

class AIService:

def __init__(self, key=None, text_model=None):
    self.api_key = (
        key
        or os.getenv("GEMINI_API_KEY", "")
    )

    self.text_model = (
        text_model
        or os.getenv(
            "GEMINI_MODEL",
            "gemini-3.6-flash",
        )
    )

    if not self.api_key:
        raise AIServiceError(
            "GEMINI_API_KEY تنظیم نشده است."
        )

    self.client = genai.Client(
        api_key=self.api_key
    )

def _call(self, prompt):
    last_error = None

    for attempt in range(3):
        try:
            response = (
                self.client.models.generate_content(
                    model=self.text_model,
                    contents=prompt,
                )
            )

            text = (
                response.text
                or ""
            ).strip()

            if not text:
                raise RuntimeError(
                    "Gemini پاسخ متنی خالی برگرداند."
                )

            return text

        except Exception as exc:
            last_error = exc
            error_text = str(exc)

            if (
                "503" in error_text
                or "UNAVAILABLE" in error_text
            ):
                if attempt < 2:
                    time.sleep(
                        5 * (attempt + 1)
                    )
                    continue

            if (
                "429" in error_text
                or "RESOURCE_EXHAUSTED"
                in error_text
            ):
                if attempt < 2:
                    time.sleep(
                        10 * (attempt + 1)
                    )
                    continue

            break

    raise RuntimeError(
        f"Gemini API | مدل: {self.text_model} | "
        f"{type(last_error).__name__}: "
        f"{last_error}"
    ) from last_error

def test_connection(self):
    return self._call(
        "فقط کلمه OK را پاسخ بده."
    )

def generate_text(
    self,
    topic,
    previous_text=None,
    research=None,
    style_instruction=None,
):
    context = ""

    if previous_text:
        context += (
            "\nاین پست قبلی است. "
            "پست جدید نباید تکرار آن باشد:\n"
            "---\n"
            f"{previous_text}\n"
            "---\n"
        )

    if research:
        context += (
            "\nاطلاعات تحقیقاتی زیر را در نظر بگیر. "
            "فقط از اطلاعات قابل اتکا استفاده کن:\n"
            "---\n"
            f"{research}\n"
            "---\n"
        )

    if style_instruction:
        context += (
            "\nدستور سبک اضافی:\n"
            f"{style_instruction}\n"
        )

    prompt = f"""

برای کانال تلگرامی فارسی @nova_ip
درباره موضوع زیر یک پست حرفه‌ای و خلاقانه بنویس.

موضوع:
{topic}

{context}

قوانین:

- فارسی روان و طبیعی.
- لحن دوستانه، صمیمی و انسانی.
- شروع با یک قلاب قوی.
- متن مفید و نسبتاً کامل باشد.
- پاراگراف‌بندی خوانا داشته باشد.
- ایموجی به اندازه استفاده شود.
- حتماً @nova_ip داخل متن باشد.
- در پایان یک سؤال مشخص از مخاطب بپرس.
- از تکرار پست‌های قبلی خودداری کن.
- از ادعاهای ساختگی خودداری کن.
- اگر اطلاعات کافی نیست، ادعای قطعی نساز.
- در پایان 5 تا 10 هشتگ مرتبط قرار بده.
- فقط متن نهایی را برگردان.

فقط متن نهایی پست را بنویس.
"""

    try:
        return self._call(prompt)

    except Exception as exc:
        raise AIServiceError(
            "TEXT_GENERATION | "
            f"مدل: {self.text_model} | "
            f"{type(exc).__name__}: {exc}"
        ) from exc

def regenerate(
    self,
    topic,
    old_text,
    instruction=None,
    previous_text=None,
):
    instruction = (
        instruction
        or "متن را جذاب‌تر، طبیعی‌تر و متفاوت‌تر کن."
    )

    prompt = f"""

این پست را برای کانال @nova_ip بازنویسی کن.

موضوع:
{topic}

پست فعلی:

{old_text}

دستور بازتولید:
{instruction}

قوانین:

- مفهوم اصلی حفظ شود.

- متن جدید نباید کپی یا بازنویسی سطحی متن قبلی باشد.

- فارسی روان و انسانی باشد.

- شروع جذاب داشته باشد.

- مفید و خوانا باشد.

- یک سؤال از مخاطب داشته باشد.

- @nova_ip داخل متن باشد.

- 5 تا 10 هشتگ مرتبط در پایان داشته باشد.

- فقط متن نهایی را برگردان.
  """
  
    return self._call(prompt)
  
  def edit_text(
  self,
  topic,
  old_text,
  instruction,
  ):
  prompt = f"""
  پست زیر را ویرایش کن.

موضوع:
{topic}

متن:

{old_text}

دستور ادمین:
{instruction}

فقط نسخه نهایی ویرایش‌شده را برگردان.
"""

    return self._call(prompt)

def extract_topics(
    self,
    topic,
    text,
    count=6,
):
    prompt = f"""

از پست فارسی زیر {count} موضوع فرعی
قابل تبدیل به پست مستقل استخراج کن.

موضوع فعلی:
{topic}

پست:

{text}

قوانین:

- موضوع‌ها واقعاً مرتبط باشند.
- کوتاه و مشخص باشند.
- تکراری نباشند.
- خود موضوع فعلی نباشند.
- هر خط فقط یک موضوع.
- بین 4 تا {count} موضوع بده.
- شماره‌گذاری نکن.
- توضیح اضافه نده.

فقط موضوع‌ها را خط‌به‌خط برگردان.
"""

    try:
        raw = self._call(prompt)

        items = []

        for line in raw.splitlines():
            line = re.sub(
                r"^[\s\-\*\d\.\)\:]+",
                "",
                line,
            ).strip()

            if (
                4 <= len(line) <= 180
                and line not in items
            ):
                items.append(line)

        if len(items) < 4:
            raise RuntimeError(
                "تعداد موضوعات فرعی کمتر از ۴ است."
            )

        return items[:count]

    except Exception as exc:
        raise AIServiceError(
            "TOPIC_EXTRACTION | "
            f"مدل: {self.text_model} | "
            f"{type(exc).__name__}: {exc}"
        ) from exc

def create_image_prompt(
    self,
    topic,
    text,
):
    prompt = f"""

برای موضوع زیر یک prompt انگلیسی کوتاه
برای تولید تصویر شبکه‌های اجتماعی بنویس.

موضوع:
{topic}

متن:
{text}

تصویر باید:

- حرفه‌ای
- مدرن
- مرتبط با موضوع
- بدون متن روی تصویر
- مناسب پست Telegram و Instagram
  باشد.

فقط prompt انگلیسی را برگردان.
"""

    return self._call(prompt)

def research_summary(
    self,
    topic,
    sources_text,
):
    prompt = f"""

بر اساس منابع زیر یک خلاصه دقیق برای نویسنده محتوا بساز.

موضوع:
{topic}

منابع:

{sources_text}

قوانین:

- فقط اطلاعات موجود در منابع.
- ادعای بدون منبع نساز.
- نکات مهم را استخراج کن.
- تناقض‌ها را مشخص کن.
- موارد نامطمئن را جدا کن.
- خروجی برای استفاده در تولید پست باشد.

فقط خلاصه تحقیق را برگردان.
"""

    return self._call(prompt)
