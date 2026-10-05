import os
import re
import time
from typing import Optional

from google import genai
from google.genai import types


class AIServiceError(RuntimeError):
    """Custom error for AI service."""


class AIService:
    DEFAULT_MODEL = "gemini-3.6-flash"
    DEFAULT_MAX_RETRIES = 3

    def __init__(
        self,
        key: Optional[str] = None,
        text_model: Optional[str] = None,
        max_retries: int = 3,
    ):
        self.api_key = (
            key or os.getenv("GEMINI_API_KEY", "")
        ).strip()

        self.text_model = (
            text_model
            or os.getenv(
                "GEMINI_MODEL",
                self.DEFAULT_MODEL,
            )
        ).strip()

        self.max_retries = max(1, int(max_retries))

        if not self.api_key:
            raise AIServiceError(
                "GEMINI_API_KEY تنظیم نشده است."
            )

        try:
            self.client = genai.Client(
                api_key=self.api_key
            )
        except Exception as exc:
            raise AIServiceError(
                f"ساخت Gemini Client ناموفق بود: {exc}"
            ) from exc

    # --------------------------------------------------
    # Helpers
    # --------------------------------------------------

    @staticmethod
    def _clean_text(text: Optional[str]) -> str:
        if not text:
            return ""

        text = str(text).strip()

        # Remove accidental markdown code fences
        text = re.sub(
            r"^```(?:text|markdown)?\s*",
            "",
            text,
            flags=re.IGNORECASE,
        )

        text = re.sub(
            r"\s*```$",
            "",
            text,
        )

        return text.strip()

    @staticmethod
    def _is_retryable_error(exc: Exception) -> bool:
        error_text = (
            f"{type(exc).__name__}: {exc}"
        ).upper()

        retryable_errors = (
            "429",
            "RESOURCE_EXHAUSTED",
            "RATE_LIMIT",
            "503",
            "UNAVAILABLE",
            "SERVICE_UNAVAILABLE",
            "500",
            "INTERNAL",
            "TIMEOUT",
            "DEADLINE",
        )

        return any(
            item in error_text
            for item in retryable_errors
        )

    @staticmethod
    def _retry_delay(
        attempt: int,
        exc: Exception,
    ) -> int:
        error_text = str(exc).upper()

        if (
            "429" in error_text
            or "RESOURCE_EXHAUSTED" in error_text
            or "RATE_LIMIT" in error_text
        ):
            return min(30, 5 * (2 ** attempt))

        return min(20, 2 * (2 ** attempt))

    # --------------------------------------------------
    # Gemini API
    # --------------------------------------------------

    def _call(
        self,
        prompt: str,
        temperature: float = 0.8,
        max_output_tokens: int = 4096,
    ) -> str:

        if not prompt or not prompt.strip():
            raise AIServiceError(
                "Prompt نمی‌تواند خالی باشد."
            )

        last_error = None

        for attempt in range(self.max_retries):
            try:
                response = (
                    self.client.models.generate_content(
                        model=self.text_model,
                        contents=prompt,
                        config=types.GenerateContentConfig(
                            temperature=temperature,
                            max_output_tokens=max_output_tokens,
                        ),
                    )
                )

                text = self._clean_text(
                    getattr(response, "text", None)
                )

                if not text:
                    raise RuntimeError(
                        "Gemini پاسخ متنی خالی برگرداند."
                    )

                return text

            except Exception as exc:
                last_error = exc

                is_last_attempt = (
                    attempt >= self.max_retries - 1
                )

                if (
                    is_last_attempt
                    or not self._is_retryable_error(exc)
                ):
                    break

                delay = self._retry_delay(
                    attempt,
                    exc,
                )

                time.sleep(delay)

        raise AIServiceError(
            "Gemini API خطا داد | "
            f"مدل: {self.text_model} | "
            f"{type(last_error).__name__}: "
            f"{last_error}"
        ) from last_error

    # --------------------------------------------------
    # Test connection
    # --------------------------------------------------

    def test_connection(self) -> str:
        return self._call(
            "فقط کلمه OK را پاسخ بده.",
            temperature=0,
            max_output_tokens=10,
        )

    # --------------------------------------------------
    # Generate text
    # --------------------------------------------------

    def generate_text(
        self,
        topic: str,
        previous_text: Optional[str] = None,
        research: Optional[str] = None,
        style_instruction: Optional[str] = None,
    ) -> str:

        if not topic or not topic.strip():
            raise AIServiceError(
                "موضوع پست نمی‌تواند خالی باشد."
            )

        context_parts = []

        if previous_text:
            context_parts.append(
                """
پست قبلی:

---
%s
---

پست جدید نباید تکرار، کپی یا بازنویسی سطحی آن باشد.
"""
                % previous_text.strip()
            )

        if research:
            context_parts.append(
                """
اطلاعات تحقیقاتی:

---
%s
---

فقط از اطلاعات قابل اتکا استفاده کن.
"""
                % research.strip()
            )

        if style_instruction:
            context_parts.append(
                """
دستور سبک:

%s
"""
                % style_instruction.strip()
            )

        context = "\n".join(context_parts)

        prompt = """
برای کانال تلگرامی فارسی @nova_ip
درباره موضوع زیر یک پست حرفه‌ای، جذاب و خلاقانه بنویس.

موضوع:
%s

%s

قوانین:

- فارسی روان، طبیعی و انسانی بنویس.
- لحن دوستانه، صمیمی و حرفه‌ای باشد.
- با یک قلاب قوی شروع کن.
- متن مفید و نسبتاً کامل باشد.
- پاراگراف‌بندی خوانا داشته باشد.
- ایموجی را به اندازه و طبیعی استفاده کن.
- حتماً @nova_ip داخل متن باشد.
- در پایان یک سؤال مشخص از مخاطب بپرس.
- از تکرار پست قبلی خودداری کن.
- اطلاعات ساختگی تولید نکن.
- اگر اطلاعات کافی نیست، ادعای قطعی نساز.
- در پایان 5 تا 10 هشتگ مرتبط قرار بده.
- از عنوان‌های کلیشه‌ای و بیش از حد تبلیغاتی پرهیز کن.
- فقط متن نهایی پست را برگردان.
""" % (
            topic.strip(),
            context,
        )

        try:
            return self._call(
                prompt,
                temperature=0.85,
                max_output_tokens=4096,
            )

        except Exception as exc:
            raise AIServiceError(
                f"TEXT_GENERATION | {exc}"
            ) from exc

    # --------------------------------------------------
    # Regenerate
    # --------------------------------------------------

    def regenerate(
        self,
        topic: str,
        old_text: str,
        instruction: Optional[str] = None,
        previous_text: Optional[str] = None,
    ) -> str:

        if not old_text or not old_text.strip():
            raise AIServiceError(
                "متن فعلی برای بازتولید خالی است."
            )

        instruction = (
            instruction.strip()
            if instruction
            else
            "متن را جذاب‌تر، طبیعی‌تر و متفاوت‌تر کن."
        )

        previous_context = ""

        if previous_text:
            previous_context = """
پست قبلی برای جلوگیری از تکرار:

---
%s
---
""" % previous_text.strip()

        prompt = """
این پست را برای کانال @nova_ip بازنویسی کن.

موضوع:
%s

پست فعلی:
---
%s
---

دستور بازتولید:
%s

%s

قوانین:

- مفهوم اصلی حفظ شود.
- متن جدید کپی یا بازنویسی سطحی نباشد.
- ساختار و جمله‌بندی را تغییر بده.
- فارسی روان و انسانی باشد.
- شروع جذاب داشته باشد.
- مفید و خوانا باشد.
- @nova_ip داخل متن باشد.
- یک سؤال مشخص از مخاطب داشته باشد.
- 5 تا 10 هشتگ مرتبط در پایان داشته باشد.
- اطلاعات ساختگی اضافه نکن.
- فقط متن نهایی را برگردان.
""" % (
            topic.strip(),
            old_text.strip(),
            instruction,
            previous_context,
        )

        try:
            return self._call(
                prompt,
                temperature=0.9,
                max_output_tokens=4096,
            )

        except Exception as exc:
            raise AIServiceError(
                f"REGENERATE | {exc}"
            ) from exc

    # --------------------------------------------------
    # Edit text
    # --------------------------------------------------

    def edit_text(
        self,
        topic: str,
        old_text: str,
        instruction: str,
    ) -> str:

        if not old_text or not old_text.strip():
            raise AIServiceError(
                "متن برای ویرایش خالی است."
            )

        if not instruction or not instruction.strip():
            raise AIServiceError(
                "دستور ویرایش نمی‌تواند خالی باشد."
            )

        prompt = """
پست زیر را ویرایش کن.

موضوع:
%s

متن:
---
%s
---

دستور ادمین:
%s

قوانین:

- مفهوم اصلی حفظ شود.
- دستور ادمین دقیقاً اعمال شود.
- فارسی روان و طبیعی باشد.
- اطلاعات جدید و ساختگی اضافه نکن.
- فقط نسخه نهایی ویرایش‌شده را برگردان.
""" % (
            topic.strip(),
            old_text.strip(),
            instruction.strip(),
        )

        try:
            return self._call(
                prompt,
                temperature=0.6,
                max_output_tokens=4096,
            )

        except Exception as exc:
            raise AIServiceError(
                f"EDIT | {exc}"
            ) from exc

    # --------------------------------------------------
    # Extract topics
    # --------------------------------------------------

    def extract_topics(
        self,
        topic: str,
        text: str,
        count: int = 6,
    ) -> list[str]:

        count = max(
            4,
            min(int(count), 10),
        )

        if not text or not text.strip():
            raise AIServiceError(
                "متن برای استخراج موضوع خالی است."
            )

        prompt = """
از پست فارسی زیر %d موضوع فرعی قابل تبدیل
به پست مستقل استخراج کن.

موضوع فعلی:
%s

پست:
---
%s
---

قوانین:

- موضوع‌ها واقعاً مرتبط باشند.
- کوتاه و مشخص باشند.
- تکراری نباشند.
- خود موضوع فعلی نباشند.
- هر خط فقط یک موضوع باشد.
- بین 4 تا %d موضوع بده.
- شماره‌گذاری نکن.
- توضیح اضافه نده.

فقط موضوع‌ها را خط‌به‌خط برگردان.
""" % (
            count,
            topic.strip(),
            text.strip(),
            count,
        )

        try:
            raw = self._call(
                prompt,
                temperature=0.5,
                max_output_tokens=1000,
            )

            items = []

            for line in raw.splitlines():
                line = line.strip()

                if not line:
                    continue

                line = re.sub(
                    r"^(?:[-*•]|\d+[\.\)\-:])\s*",
                    "",
                    line,
                ).strip()

                line = line.strip("`*_# ")

                if not (4 <= len(line) <= 180):
                    continue

                normalized = line.casefold()

                if not any(
                    normalized == item.casefold()
                    for item in items
                ):
                    items.append(line)

            if len(items) < 4:
                raise RuntimeError(
                    "تعداد موضوعات فرعی کمتر از ۴ است."
                )

            return items[:count]

        except Exception as exc:
            raise AIServiceError(
                f"TOPIC_EXTRACTION | {exc}"
            ) from exc

    # --------------------------------------------------
    # Create image prompt
    # --------------------------------------------------

    def create_image_prompt(
        self,
        topic: str,
        text: str,
    ) -> str:

        prompt = """
Create a short, high-quality English prompt
for generating a social-media image.

Topic:
%s

Post:
%s

The image must be:

- professional
- modern
- visually engaging
- strongly related to the topic
- suitable for Telegram and Instagram
- no text
- no logos
- no watermark
- clean composition

Return only the English image-generation prompt.
""" % (
            topic.strip(),
            text.strip(),
        )

        try:
            return self._call(
                prompt,
                temperature=0.7,
                max_output_tokens=500,
            )

        except Exception as exc:
            raise AIServiceError(
                f"IMAGE_PROMPT | {exc}"
            ) from exc

    # --------------------------------------------------
    # Research summary
    # --------------------------------------------------

    def research_summary(
        self,
        topic: str,
        sources_text: str,
    ) -> str:

        if not sources_text or not sources_text.strip():
            raise AIServiceError(
                "متن منابع تحقیقاتی خالی است."
            )

        prompt = """
بر اساس منابع زیر یک خلاصه دقیق
برای نویسنده محتوا بساز.

موضوع:
%s

منابع:
---
%s
---

قوانین:

- فقط اطلاعات موجود در منابع را استفاده کن.
- ادعای بدون منبع نساز.
- نکات مهم را استخراج کن.
- تناقض‌ها را مشخص کن.
- موارد نامطمئن را جدا کن.
- اطلاعات را منظم و قابل استفاده ارائه بده.
- خروجی برای استفاده در تولید پست باشد.
- اگر منابع برای یک ادعا کافی نیستند، آن را قطعی بیان نکن.

فقط خلاصه تحقیق را برگردان.
""" % (
            topic.strip(),
            sources_text.strip(),
        )

        try:
            return self._call(
                prompt,
                temperature=0.2,
                max_output_tokens=3000,
            )

        except Exception as exc:
            raise AIServiceError(
                f"RESEARCH_SUMMARY | {exc}"
            ) from exc
