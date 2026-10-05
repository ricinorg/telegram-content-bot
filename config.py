import os
from dataclasses import dataclass
from typing import Set

from dotenv import load_dotenv

load_dotenv()


def _csv_ints(value: str | None) -> Set[int]:
    if not value:
        return set()

    result: Set[int] = set()

    for item in value.split(","):
        item = item.strip()

        if not item:
            continue

        try:
            result.add(int(item))
        except ValueError as exc:
            raise ValueError(
                f"Invalid integer in ADMIN_USER_IDS: {item}"
            ) from exc

    return result


def _env_bool(
    name: str,
    default: bool = False,
) -> bool:
    value = os.getenv(name)

    if value is None:
        return default

    value = value.strip().lower()

    if value in {"1", "true", "yes", "on"}:
        return True

    if value in {"0", "false", "no", "off"}:
        return False

    raise ValueError(
        f"Invalid boolean value for {name}: {value}"
    )


def _env_required(name: str) -> str:
    value = os.getenv(name, "").strip()

    if not value:
        raise RuntimeError(
            f"Missing required environment variable: {name}"
        )

    return value


@dataclass(frozen=True)
class Settings:
    telegram_bot_token: str
    telegram_channel_id: str
    gemini_api_key: str
    gemini_model: str
    admin_user_ids: Set[int]
    timezone: str
    database_path: str
    log_level: str
    ayrshare_api_key: str
    research_enabled: bool
    approval_required: bool


def load_settings() -> Settings:
    return Settings(
        telegram_bot_token=_env_required(
            "TELEGRAM_BOT_TOKEN"
        ),
        telegram_channel_id=_env_required(
            "TELEGRAM_CHANNEL_ID"
        ),
        gemini_api_key=_env_required(
            "GEMINI_API_KEY"
        ),
        gemini_model=(
            os.getenv(
                "GEMINI_MODEL",
                "gemini-3.6-flash",
            ).strip()
            or "gemini-3.6-flash"
        ),
        admin_user_ids=_csv_ints(
            os.getenv("ADMIN_USER_IDS")
        ),
        timezone=(
            os.getenv(
                "TIMEZONE",
                "UTC",
            ).strip()
            or "UTC"
        ),
        database_path=(
            os.getenv(
                "DATABASE_PATH",
                "data/bot.db",
            ).strip()
            or "data/bot.db"
        ),
        log_level=(
            os.getenv(
                "LOG_LEVEL",
                "INFO",
            ).strip().upper()
            or "INFO"
        ),
        ayrshare_api_key=(
            os.getenv(
                "AYRSHARE_API_KEY",
                "",
            ).strip()
        ),
        research_enabled=_env_bool(
            "RESEARCH_ENABLED",
            default=False,
        ),
        approval_required=_env_bool(
            "APPROVAL_REQUIRED",
            default=False,
        ),
    )
