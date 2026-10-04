from dataclasses import dataclass
import os

from dotenv import load_dotenv

load_dotenv()


def _csv_ints(value: str | None) -> set[int]:
    if not value:
        return set()

    return {
        int(item.strip())
        for item in value.split(",")
        if item.strip()
    }


@dataclass(frozen=True)
class Settings:
    telegram_bot_token: str
    telegram_channel_id: str
    gemini_api_key: str
    gemini_model: str
    admin_user_ids: set[int]
    timezone: str
    database_path: str
    log_level: str


def load_settings() -> Settings:
    required = {
        "TELEGRAM_BOT_TOKEN": os.getenv("TELEGRAM_BOT_TOKEN"),
        "TELEGRAM_CHANNEL_ID": os.getenv("TELEGRAM_CHANNEL_ID"),
        "GEMINI_API_KEY": os.getenv("GEMINI_API_KEY"),
    }

    missing = [
        key
        for key, value in required.items()
        if not value
    ]

    if missing:
        raise RuntimeError(
            "Missing required environment variables: "
            + ", ".join(missing)
        )

    return Settings(
        telegram_bot_token=required["TELEGRAM_BOT_TOKEN"],
        telegram_channel_id=required["TELEGRAM_CHANNEL_ID"],
        gemini_api_key=required["GEMINI_API_KEY"],
        gemini_model=os.getenv(
            "GEMINI_MODEL",
            "gemini-3.6-flash",
        ),
        admin_user_ids=_csv_ints(
            os.getenv("ADMIN_USER_IDS")
        ),
        timezone=os.getenv(
            "TIMEZONE",
            "UTC",
        ),
        database_path=os.getenv(
            "DATABASE_PATH",
            "data/bot.db",
        ),
        log_level=os.getenv(
            "LOG_LEVEL",
            "INFO",
        ),
    )
