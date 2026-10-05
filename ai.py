import logging
import time

from google import genai
from google.genai import types


logger = logging.getLogger("telegram-content-bot.ai")


class AIServiceError(RuntimeError):
    """خطای مربوط به سرویس Gemini."""


class AIService:
    def __init__(
        self,
        key: str,
        text_model: str,
    ):
        if not key:
            raise AIServiceError(
                "GEMINI_API_KEY تنظیم نشده است."
            )

        if not text_model:
            raise AIServiceError(
                "GEMINI_MODEL تنظیم نشده است."
            )

        self.key = key
        self.text_model = text_model

        try:
            self.client = genai.Client(
                api_key=self.key
            )
        except Exception as exc:
            raise AIServiceError(
                "ساخت Gemini client ناموفق بود: "
                f"{exc}"
            ) from exc

    def _extract_text(self, response):
        """
        استخراج امن متن از پاسخ Gemini.
        """

        if response is None:
            return ""

        text = getattr(
            response,
            "text",
            None,
        )

        if text:
            return text.strip()

        candidates = getattr(
            response,
            "candidates",
            None,
        )

        if not candidates:
            return ""

        parts = []

        for candidate in candidates:
            content = getattr(
                candidate,
                "content",
                None,
            )

            if not content:
                continue

            content_parts = getattr(
                content,
                "parts",
                None,
            )

            if not content_parts:
                continue

            for part in content_parts:
                part_text = getattr(
                    part,
                    "text",
                    None,
                )

                if part_text:
                    parts.append(
                        part_text.strip()
                    )

        return "\n".join(
            part for part in parts if part
        ).strip()

    def _call(
        self,
        prompt: str,
        temperature: float = 0.8,
        max_output_tokens: int = 2048,
        retries: int = 3,
    ):
        if not prompt or not prompt.strip():
            raise AIServiceError(
                "Prompt خالی است."
            )

        last_error = None

        for attempt in range(1, retries + 1):
            try:
                logger.info(
                    "Gemini request | model=%s | attempt=%s/%s",
                    self.text_model,
                    attempt,
                    retries,
                )

                response = self.client.models.generate_content(
                    model=self.text_model,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        temperature=temperature,
                        max_output_tokens=max_output_tokens,
                    ),
                )

                text = self._extract_text(
                    response
                )

                if text:
                    return text

                finish_reason = None

                try:
                    candidates = getattr(
                        response,
                        "candidates",
                        None,
                    )

                    if candidates:
                        finish_reason = getattr(
                            candidates[0],
                            "finish_reason",
                            None,
                        )
                except Exception:
                    pass

                logger.warning(
                    "Gemini returned empty text | "
                    "finish_reason=%s",
                    finish_reason,
                )

                last_error = RuntimeError(
                    "Gemini پاسخ متنی خالی برگرداند."
                )

            except Exception as exc:
                last_error = exc

                error_text = str(exc)

                logger.exception(
                    "Gemini request failed | "
                    "model=%s | attempt=%s/%s | error=%s",
                    self.text_model,
                    attempt,
                    retries,
                    error_text,
                )

                retryable = any(
                    code in error_text
                    for code in (
                        "429",
                        "500",
                        "502",
                        "503",
                        "504",
                        "RESOURCE_EXHAUSTED",
                        "UNAVAILABLE",
                    )
                )

                if not retryable:
                    break

            if attempt < retries:
                time.sleep(
                    2 ** (attempt - 1)
                )

        raise AIServiceError(
            "Gemini API خطا داد | "
            f"مدل: {self.text_model} | "
            f"{last_error}"
        ) from last_error

    def test_connection(self):
        """
        تست ساده اتصال به Gemini.
        """

        text = self._call(
            prompt=(
                "Reply with exactly one short word: "
                "OK"
            ),
            temperature=0,
            max_output_tokens=20,
            retries=2,
        )

        if not text:
            raise AIServiceError(
                "Gemini پاسخ خالی برگرداند."
            )

        logger.info(
            "Gemini connection test successful."
        )

        return text

    def generate_text(
        self,
        topic: str,
        previous_text: str | None = None,
        research: str | None = None,
        style_instruction: str | None = None,
    ):
        if not topic or not topic.strip():
            raise AIServiceError(
                "موضوع محتوا خالی است."
            )

        prompt_parts = [
            "تو یک نویسنده حرفه‌ای فارسی برای یک کانال "
            "تلگرامی هستی.",
            "",
            "برای موضوع زیر یک پست باکیفیت، دقیق، "
            "خواندنی و طبیعی به زبان فارسی تولید کن.",
            "",
            f"موضوع:",
            topic.strip(),
        ]

        if style_instruction:
            prompt_parts.extend(
                [
                    "",
                    "دستور سبک:",
                    style_instruction.strip(),
                ]
            )

        if research:
            prompt_parts.extend(
                [
                    "",
                    "اطلاعات تحقیقاتی:",
                    research.strip(),
                ]
            )

        if previous_text:
            prompt_parts.extend(
                [
                    "",
                    "پست قبلی برای جلوگیری از تکرار:",
                    previous_text.strip(),
                ]
            )

        prompt_parts.extend(
            [
                "",
                "قوانین:",
                "- متن را به فارسی روان بنویس.",
                "- از تکرار و کلیشه پرهیز کن.",
                "- مقدمه جذاب باشد.",
                "- ارزش واقعی به خواننده بده.",
                "- از ادعاهای بی‌پایه و ساختن آمار جعلی خودداری کن.",
                "- اگر موضوع فنی است، ساده و قابل‌فهم توضیح بده.",
                "- متن را برای انتشار مستقیم در Telegram آماده کن.",
                "- از هشتگ‌های زیاد استفاده نکن.",
                "",
                "فقط متن نهایی پست را خروجی بده.",
            ]
        )

        return self._call(
            prompt="\n".join(prompt_parts),
            temperature=0.8,
            max_output_tokens=2048,
            retries=3,
        )

    def regenerate(
        self,
        topic: str,
        old_text: str,
        instruction: str | None = None,
        previous_text: str | None = None,
    ):
        if not old_text:
            raise AIServiceError(
                "متن قبلی برای بازتولید وجود ندارد."
            )

        prompt_parts = [
            "متن زیر یک پیش‌نویس فارسی برای Telegram است.",
            "آن را با کیفیت بالاتر بازنویسی کن.",
            "",
            f"موضوع: {topic}",
            "",
            "متن قبلی:",
            old_text,
        ]

        if instruction:
            prompt_parts.extend(
                [
                    "",
                    "دستور کاربر:",
                    instruction,
                ]
            )

        if previous_text:
            prompt_parts.extend(
                [
                    "",
                    "پست قبلی برای جلوگیری از تکرار:",
                    previous_text,
                ]
            )

        prompt_parts.extend(
            [
                "",
                "فقط نسخه نهایی را خروجی بده.",
                "زبان خروجی فارسی باشد.",
            ]
        )

        return self._call(
            prompt="\n".join(prompt_parts),
            temperature=0.85,
            max_output_tokens=2048,
            retries=3,
        )

    def edit_text(
        self,
        topic: str,
        old_text: str,
        instruction: str,
    ):
        if not old_text:
            raise AIServiceError(
                "متن قبلی وجود ندارد."
            )

        if not instruction:
            raise AIServiceError(
                "دستور ویرایش خالی است."
            )

        prompt = (
            "تو یک ویراستار حرفه‌ای محتوای فارسی هستی.\n\n"
            f"موضوع:\n{topic}\n\n"
            f"متن فعلی:\n{old_text}\n\n"
            f"دستور ویرایش:\n{instruction}\n\n"
            "متن را مطابق دستور کاربر اصلاح کن.\n"
            "معنی اصلی را حفظ کن مگر اینکه کاربر خلاف آن "
            "را خواسته باشد.\n"
            "خروجی فقط نسخه نهایی ویرایش‌شده باشد."
        )

        return self._call(
            prompt=prompt,
            temperature=0.7,
            max_output_tokens=2048,
            retries=3,
        )

    def extract_topics(
        self,
        topic: str,
        text: str,
        count: int = 6,
    ):
        if not text:
            return []

        prompt = (
            "از متن فارسی زیر چند موضوع فرعی مستقل و "
            "قابل تولید محتوا استخراج کن.\n\n"
            f"موضوع اصلی:\n{topic}\n\n"
            f"متن:\n{text}\n\n"
            f"تعداد موضوع‌ها: {count}\n\n"
            "قوانین:\n"
            "- هر موضوع یک خط باشد.\n"
            "- شماره‌گذاری نکن.\n"
            "- موضوع‌ها تکراری نباشند.\n"
            "- موضوع‌ها باید قابلیت تبدیل شدن به یک "
            "پست مستقل را داشته باشند.\n"
            "- فقط فهرست موضوع‌ها را خروجی بده."
        )

        result = self._call(
            prompt=prompt,
            temperature=0.7,
            max_output_tokens=800,
            retries=3,
        )

        topics = []

        for line in result.splitlines():
            cleaned = line.strip()

            if not cleaned:
                continue

            cleaned = cleaned.lstrip(
                "-•*0123456789. )("
            ).strip()

            if cleaned:
                topics.append(cleaned)

        unique_topics = []

        for item in topics:
            if item not in unique_topics:
                unique_topics.append(item)

        return unique_topics[:count]

    def create_image_prompt(
        self,
        topic: str,
        text: str,
    ):
        prompt = (
            "برای تولید یک تصویر حرفه‌ای برای پست "
            "فارسی زیر، یک prompt انگلیسی دقیق بنویس.\n\n"
            f"موضوع:\n{topic}\n\n"
            f"محتوا:\n{text}\n\n"
            "تصویر باید مدرن، حرفه‌ای، مینیمال و مناسب "
            "شبکه‌های اجتماعی باشد.\n"
            "از متن و نوشته داخل تصویر استفاده نکن.\n"
            "فقط prompt انگلیسی تصویر را خروجی بده."
        )

        return self._call(
            prompt=prompt,
            temperature=0.8,
            max_output_tokens=500,
            retries=3,
        )

    def research_summary(
        self,
        topic: str,
        sources: list[str] | None = None,
    ):
        source_text = ""

        if sources:
            source_text = "\n\n".join(
                sources
            )

        prompt = (
            "تو یک دستیار تحقیقاتی برای تولید محتوای فارسی هستی.\n\n"
            f"موضوع:\n{topic}\n\n"
            f"منابع موجود:\n{source_text or 'منبعی ارائه نشده است.'}\n\n"
            "بر اساس اطلاعات موجود یک خلاصه دقیق و "
            "کاربردی برای نویسنده محتوا تهیه کن.\n"
            "اگر اطلاعات کافی نیست، صریحاً بگو.\n"
            "اطلاعات یا منبع جعلی تولید نکن."
        )

        return self._call(
            prompt=prompt,
            temperature=0.4,
            max_output_tokens=1500,
            retries=3,
        )
