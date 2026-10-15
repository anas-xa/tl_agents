"""Time helpers. All timestamps are stored in UTC; Asia/Dubai is the display zone."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

DUBAI = ZoneInfo("Asia/Dubai")


def utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def to_dubai(dt: datetime) -> datetime:
    return dt.replace(tzinfo=UTC).astimezone(DUBAI)


def dubai_today() -> date:
    return to_dubai(utcnow()).date()


def days_between(a: date, b: date) -> int:
    return (b - a).days


def plus_days(d: date, n: int) -> date:
    return d + timedelta(days=n)
