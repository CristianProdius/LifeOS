from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


LIFEOS_DEFAULT_TIMEZONE = "Europe/Chisinau"


def lifeos_today(timezone_name: str | None = None) -> date:
    try:
        timezone = ZoneInfo(timezone_name or LIFEOS_DEFAULT_TIMEZONE)
    except ZoneInfoNotFoundError:
        timezone = ZoneInfo(LIFEOS_DEFAULT_TIMEZONE)
    return datetime.now(timezone).date()
