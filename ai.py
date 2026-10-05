import os
import re
import time
from typing import Optional

from google import genai
from google.genai import types


class AIServiceError(RuntimeError):
    """خطای اختصاصی سرویس هوش مصنوعی."""
    pass


class AIService:
    """
    سرویس ارتباط با Google Gemini برای تولید و پردازش محتوا.
    """

    DEFAULT_MODEL = "gemini-3.6-flash"
    DEFAULT_MAX_RETRIES = 3

    def __init__(
        self,
        key: Optional[str] = None,
        text_model: Optional[str] = None,
        max_retries: int = DEFAULT_MAX_RETRIES,
    ):
        self.api_key = (
            key
            or os.getenv("GEMINI_API_KEY", "")
        ).strip()

        self.text_model = (
            text_model
            or os.getenv(
                "GEMINI_MODEL",
                self.DEFAULT_MODEL,
            )
        ).strip()

        self.max_retries = max(
            1,
            int(max_retries),
        )

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
                "ساخت Gemini Client ناموفق بود: "
                f"{type(exc).__name__}: {exc}"
            ) from exc

    # ---------------------------------------------------------
    # Internal helpers
    # ---------------------------------------------------------

    @staticmethod
    def _clean_text(text: Optional[str]) -> str:
        """پاک‌سازی ساده خروجی مدل."""
        if not text:
            return ""

        text = str(text).strip()

        # حذف code fence در صورتی که مدل اشتباهی اضافه کرده باشد
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
        """
        تشخیص خطاهایی که ارزش retry کردن دارند.
        """

        error_text = (
            f"{type(exc).__name__}: {exc}"
        ).upper()

        retryable_patterns = (
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
            pattern in error_text
            for pattern in retryable_patterns
        )

    @staticmethod
    def _retry_delay(
        attempt: int,
        exc: Exception,
    ) -> int:
        """
        محاسبه زمان انتظار قبل از retry.
        """

        error_text = str(exc).upper()

        # Rate limit معمولاً به زمان بیشتری نیاز دارد.
        if (
            "429" in error_text
            or "RESOURCE_EXHAUSTED" in error_text
            or "RATE_LIMIT" in error_text
        ):
            return min(
                30,
                5 * (2 ** attempt),
            )

        # خطاهای موقت سرور
        return min(
            20,
            2 * (2 ** attempt),
        )

    def _call(
        self,
        prompt: str,
        *,
        temperature: float = 0.8,
        max_output_tokens: int = 4096,
    ) -> str:
        """
        ارسال درخواست به Gemini با retry.
        """

        if not prompt or not prompt.strip():
            raise ValueError(
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
                    attempt
                    >= self.max_retries - 1
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
            f"Gemini API خطا داد | "
            f"مدل: {self.text_model} | "
            f"{type(last_error).__name__}: "
            f"{last_error}"
        ) from last_error

    # ---------------------------------------------------------
    # Connection
    # ---------------------------------------------------------

    def test_connection(self) -> str:
        """تست اتصال به Gemini."""

        return self._call(
            "فقط کلمه OK را پاسخ بده.",
            temperature=0,
            max_output_tokens=10,
        )

    # ---------------------------------------------------------
    # Generate post
    # ---------------------------------------------------------

    def generate_text(
        self,
        topic: str,
        previous_text: Optional[str] = None,
        research: Optional[str] = None,
        style_instruction: Optional[str] = None,
    ) -> str:
        """تولید پست فارسی برای کانال."""

        if not topic or not topic.strip():
            raise AIServiceError(
                "موضوع پست نمی‌تواند خالی باشد."
            )

        context_parts = []

        if previous_text:
            context_parts.append(
                f"""
این پست قبلی است.
پست جدید نباید تکرار، کپی یا بازنویسی سطحی آن باشد:

---
{previous_text.strip()}
---
"""
            )

        if research:
            context_parts.append(
                f"""
اطلاعات تحقیقاتی زیر را در نظر بگیر.
فقط از اطلاعات قابل اتکا استفاده کن:

---
{research.strip()}
---
"""
            )

        if style_instruction:
            context_parts.append(
                f"""
دستور سبک اضافی:

{style_instruction.strip()}
"""
            )

        context = "\n".join(context_parts)

        prompt = f"""
برای کانال تلگرامی فارسی @nova_ip
درباره موضوع زیر یک پست حرفه‌ای، جذاب و خلاقانه بنویس.

موضوع:
{topic.strip()}

{context}

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
- از عنوان‌های کلیشه‌ای و بیش‌ازحد تبلیغاتی پرهیز کن.
- فقط متن نهایی پست را برگردان.
"""

        try:
            return self._call(
                prompt,
                temperature=0.85,
                max_output_tokens=4096,
            )

        except Exception as exc:
            if isinstance(
                exc,
                AIServiceError,
            ):
                raise AIServiceError(
                    "TEXT_GENERATION | "
                    f"{exc}"
                ) from exc

            raise AIServiceError(
                "TEXT_GENERATION | "
                f"مدل: {self.text_model} | "
                f"{type(exc).__name__}: {exc}"
            ) from exc

    # ---------------------------------------------------------
    # Regenerate
    # ---------------------------------------------------------

    def regenerate(
        self,
        topic: str,
        old_text: str,
        instruction: Optional[str] = None,
        previous_text: Optional[str] = None,
    ) -> str:
        """بازنویسی کامل یک پست."""

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
            previous_context = f"""
برای جلوگیری از تکرار، این پست قبلی را نیز در نظر بگیر:

---
{previous_text.strip()}
---
"""

        prompt = f"""
این پست را برای کانال @nova_ip بازنویسی کن.

موضوع:
{topic.strip()}

پست فعلی:
---
{old_text.strip()}
---

دستور بازتولید:
{instruction}

{previous_context}

قوانین:

- مفهوم اصلی حفظ شود.
- متن جدید کپی یا بازنویسی سطحی متن قبلی نباشد.
- ساختار و جمله‌بندی را تا حد زیادی تغییر بده.
- فارسی روان و انسانی باشد.
- شروع جذاب داشته باشد.
- مفید و خوانا باشد.
- @nova_ip داخل متن باشد.
- یک سؤال مشخص از مخاطب داشته باشد.
- 5 تا 10 هشتگ مرتبط در پایان داشته باشد.
- اطلاعات ساختگی اضافه نکن.
- فقط متن نهایی را برگردان.
"""

        try:
            return self._call(
                prompt,
                temperature=0.9,
                max_output_tokens=4096,
            )

        except Exception as exc:
            raise AIServiceError(
                "REGENERATE | "
                f"مدل: {self.text_model} | "
                f"{type(exc).__name__}: {exc}"
            ) from exc

    # ---------------------------------------------------------
    # Edit
    # ---------------------------------------------------------

    def edit_text(
        self,
        topic: str,
        old_text: str,
        instruction: str,
    ) -> str:
        """ویرایش یک پست طبق دستور ادمین."""

        if not old_text or not old_text.strip():
            raise AIServiceError(
                "متن برای ویرایش خالی است."
            )

        if not instruction or not instruction.strip():
            raise AIServiceError(
                "دستور ویرایش نمی‌تواند خالی باشد."
            )

        prompt = f"""
پست زیر را ویرایش کن.

موضوع:
{topic.strip()}

متن:
---
{old_text.strip()}
---

دستور ادمین:
{instruction.strip()}

قوانین:

- مفهوم اصلی حفظ شود.
- دستور ادمین دقیقاً اعمال شود.
- فارسی روان و طبیعی باشد.
- اطلاعات جدید و ساختگی اضافه نکن.
- ساختار متن را فقط در صورت نیاز تغییر بده.
- فقط نسخه نهایی ویرایش‌شده را برگردان.
"""

        try:
            return self._call(
                prompt,
                temperature=0.6,
                max_output_tokens=4096,
            )

        except Exception as exc:
            raise AIServiceError(
                "EDIT | "
                f"مدل: {self.text_model} | "
                f"{type(exc).__name__}: {exc}"
            ) from exc

    # ---------------------------------------------------------
    # Topic extraction
    # ---------------------------------------------------------

    def extract_topics(
        self,
        topic: str,
        text: str,
        count: int = 6,
    ) -> list[str]:
        """استخراج موضوعات فرعی از یک پست."""

        count = max(
            4,
            min(int(count), 10),
        )

        if not text or not text.strip():
            raise AIServiceError(
                "متن برای استخراج موضوع خالی است."
            )

        prompt = f"""
از پست فارسی زیر {count} موضوع فرعی قابل تبدیل
به پست مستقل استخراج کن.

موضوع فعلی:
{topic.strip()}

پست:
---
{text.strip()}
---

قوانین:

- موضوع‌ها واقعاً مرتبط باشند.
- کوتاه و مشخص باشند.
- تکراری نباشند.
- خود موضوع فعلی نباشند.
- هر خط فقط یک موضوع باشد.
- بین 4 تا {count} موضوع بده.
- شماره‌گذاری نکن.
- توضیح اضافه نده.

فقط موضوع‌ها را خط‌به‌خط برگردان.
"""

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

                # حذف شماره‌گذاری و bullet
                line = re.sub(
                    r"^(?:[-*•]|\d+[\.\)\-:])\s*",
                    "",
                    line,
                ).strip()

                # حذف Markdown
                line = line.strip(
                    "`*_# "
                )

                if not (
                    4
                    <= len(line)
                    <= 180
                ):
                    continue

                # جلوگیری از تکرار بدون حساسیت به حروف
                normalized = line.casefold()

                if not any(
                    normalized
                    == item.casefold()
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
                "TOPIC_EXTRACTION | "
                f"مدل: {self.text_model} | "
                f"{type(exc).__name__}: {exc}"
            ) from exc

    # ---------------------------------------------------------
    # Image prompt
    # ---------------------------------------------------------

    def create_image_prompt(
        self,
        topic: str,
        text: str,
    ) -> str:
        """تولید prompt انگلیسی برای تصویر."""

        prompt = f"""
Create a short, high-quality English prompt
for generating a social-media image.

Topic:
{topic.strip()}

Post:
{text.strip()}

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
"""

        try:
            return self._call(
                prompt,
                temperature=0.7,
                max_output_tokens=500,
            )

        except Exception as exc:
            raise AIServiceError(
                "IMAGE_PROMPT | "
                f"مدل: {self.text_model} | "
                f"{type(exc).__name__}: {exc}"
            ) from exc

    # ---------------------------------------------------------
    # Research summary
    # ---------------------------------------------------------

    def research_summary(
        self,
        topic: str,
        sources_text: str,
    ) -> str:
        """خلاصه‌سازی منابع تحقیقاتی."""

        if not sources_text or not sources_text.strip():
            raise AIServiceError(
                "متن منابع تحقیقاتی خالی است."
            )

        prompt = f"""
بر اساس منابع زیر یک خلاصه دقیق
برای نویسنده محتوا بساز.

موضوع:
{topic.strip()}

منابع:
---
{sources_text.strip()}
---

قوانین:

- فقط اطلاعات موجود در منابع را استفاده کن.
- ادعای بدون منبع نساز.
- نکات مهم را استخراج کن.
- تناقض‌ها را مشخص کن.
- موارد نامطمئن را جدا کن.
- اطلاعات را به شکل منظم و قابل استفاده ارائه بده.
- خروجی برای استفاده در تولید پست باشد.
- اگر منابع برای یک ادعا کافی نیستند، آن را قطعی بیان نکن.

فقط خلاصه تحقیق را برگردان.
"""

        try:
            return self._call(
                prompt,
                temperature=0.2,
                max_output_tokens=3000,
            )

        except Exception as exc:
            raise AIServiceError(
                "RESEARCH_SUMMARY | "
                f"مدل: {self.text_model} | "
                f"{type(exc).__name__}: {exc}"
            ) from exc

برای نصب/آپدیت SDK هم از پکیج رسمی "google-genai" استفاده کن:

pip install -U google-genai

و متغیر محیطی را تنظیم کن:

export GEMINI_API_KEY="YOUR_API_KEY"

در ویندوز:

$env:GEMINI_API_KEY="YOUR_API_KEY"

یا می‌توانی مدل را تغییر بدهی:

GEMINI_MODEL=gemini-3.6-flash

API رسمی Google همین الگوی "genai.Client()" و "client.models.generate_content()" را برای Python نشان می‌دهد.

تغییرات مهمی که انجام دادم:

- تمام خطاهای Syntax و indentation برطرف شد.
- """""های خراب و Markdownهای واردشده داخل کد حذف شدند.
- retry به‌صورت عمومی‌تر برای "429"، "503"، timeout و خطاهای موقت انجام می‌شود.
- زمان retry به‌صورت exponential backoff تنظیم شده.
- "temperature" و "max_output_tokens" قابل کنترل هستند.
- ورودی‌های خالی کنترل می‌شوند.
- خروجی مدل پاک‌سازی می‌شود.
- استخراج Topic مقاوم‌تر شده و موارد تکراری حذف می‌شوند.
- خطاها با "AIServiceError" به شکل منظم‌تر مدیریت می‌شوند.
- "previous_text" در "regenerate" واقعاً استفاده می‌شود.
- promptها کوتاه‌تر و منظم‌تر شده‌اند.

اگر این کلاس را داخل یک ربات تلگرام استفاده می‌کنی، کد اصلی رباتت را هم بفرست؛ می‌توانم کل بخش Gemini + تولید پست + تحقیق + تولید تصویر + ذخیره تاریخچه + retry + Telegram را یکپارچه و production-ready کنم.
