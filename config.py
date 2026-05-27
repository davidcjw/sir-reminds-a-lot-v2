from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import time
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv


@dataclass
class BotConfig:
    token: str
    database_path: Path
    reminder_chat_id: int | str | None
    reminder_time: time
    reminder_timezone: ZoneInfo
    reminder_days_before: int


def load_config() -> BotConfig:
    load_dotenv()

    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        raise ValueError("TELEGRAM_BOT_TOKEN is required. Copy .env.example to .env and fill it in.")

    db_path = Path(os.getenv("DATABASE_PATH", "./data/bot.db"))
    db_path.parent.mkdir(parents=True, exist_ok=True)

    raw_chat_id = os.getenv("TELEGRAM_REMINDER_CHAT_ID", "").strip()
    reminder_chat_id: int | str | None = None
    if raw_chat_id:
        try:
            reminder_chat_id = int(raw_chat_id)
        except ValueError:
            reminder_chat_id = raw_chat_id

    tz_name = os.getenv("TELEGRAM_REMINDER_TIMEZONE", "UTC").strip()
    timezone = ZoneInfo(tz_name)

    raw_time = os.getenv("TELEGRAM_REMINDER_TIME", "09:00").strip()
    h, m = (int(x) for x in raw_time.split(":"))
    reminder_time = time(h, m)

    days_before = int(os.getenv("TELEGRAM_REMINDER_DAYS_BEFORE", "3").strip())

    return BotConfig(
        token=token,
        database_path=db_path,
        reminder_chat_id=reminder_chat_id,
        reminder_time=reminder_time,
        reminder_timezone=timezone,
        reminder_days_before=days_before,
    )
