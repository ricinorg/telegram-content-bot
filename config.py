from dataclasses import dataclass
import os

from dotenv import load_dotenv

load_dotenv()


def _csv_ints(value: str | None) -> set[int]:
    if not value:
        return set()
    return {int(item.strip()) for item in value.split(",") if item.strip()}


@dataclass(frozen=True)
class Settings:
    telegram_bot_token: str
    telegram_channel_id: str
    openai_api_key: str
    openai_text_model: str
    openai_image_model: str
    admin_user_ids: set[int]
    timezone: str
    database_path: str
    log_level: str


def load_settings() -> Settings:
    required = {
        "TELEGRAM_BOT_TOKEN": os.getenv("TELEGRAM_BOT_TOKEN"),
        "TELEGRAM_CHANNEL_ID": os.getenv("TELEGRAM_CHANNEL_ID"),
        "OPENAI_API_KEY": os.getenv("OPENAI_API_KEY"),
    }
    missing = [key for key, value in required.items() if not value]
    if missing:
        raise RuntimeError(
            "Missing required environment variables: " + ", ".join(missing)
        )

    return Settings(
        telegram_bot_token=required["TELEGRAM_BOT_TOKEN"],
        telegram_channel_id=required["TELEGRAM_CHANNEL_ID"],
        openai_api_key=required["OPENAI_API_KEY"],
        openai_text_model=os.getenv("OPENAI_TEXT_MODEL", "gpt-5.6-mini"),
        openai_image_model=os.getenv("OPENAI_IMAGE_MODEL", "gpt-image-1"),
        admin_user_ids=_csv_ints(os.getenv("ADMIN_USER_IDS")),
        timezone=os.getenv("TIMEZONE", "UTC"),
        database_path=os.getenv("DATABASE_PATH", "data/bot.db"),
        log_level=os.getenv("LOG_LEVEL", "INFO"),
    )
