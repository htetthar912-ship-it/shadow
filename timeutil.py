"""Myanmar display time helpers. DB still stores UTC (naive utcnow)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

MM_TZ = ZoneInfo("Asia/Yangon")  # UTC+06:30
UTC = timezone.utc


def ensure_utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def to_myanmar(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return ensure_utc(dt).astimezone(MM_TZ)


def format_mm(dt: datetime | None, fmt: str = "%d %b %Y, %I:%M %p") -> str:
    """Format for UI / email. Empty string if no datetime."""
    local = to_myanmar(dt)
    if local is None:
        return "—"
    return local.strftime(fmt)


def format_mm_short(dt: datetime | None) -> str:
    return format_mm(dt, "%d/%m/%Y %H:%M")


def format_mm_time(dt: datetime | None) -> str:
    return format_mm(dt, "%I:%M %p")


def now_mm() -> datetime:
    return datetime.now(MM_TZ)


def now_mm_str(fmt: str = "%d %b %Y, %I:%M %p") -> str:
    return now_mm().strftime(fmt)
