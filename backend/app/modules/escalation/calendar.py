"""uae_working_calendar: versioned reference table and working-day arithmetic (E8-S4 Q138).

Convention (versioned config ``working_day.convention``): Dubai-local date; weekend Saturday and Sunday;
opening day = day 0; same-day close = 0; fractional working days to one decimal (1.0 per working day
00:00-24:00 GST); opened on a non-working day → count starts at the next working day; closed on a
non-working day → elapsed stops at the end of the last working day before. Raw timestamps are never changed.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.time import DUBAI
from app.modules.escalation.models import WorkingCalendarHoliday, WorkingCalendarVersion

WEEKEND = (5, 6)  # Saturday, Sunday
CALENDAR_ID = "uae_working_calendar"


def _to_dubai(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(DUBAI).replace(tzinfo=None)


def holidays_between(db: Session, start: date, end: date) -> dict[date, WorkingCalendarHoliday]:
    rows = db.scalars(select(WorkingCalendarHoliday).where(WorkingCalendarHoliday.calendar_id == CALENDAR_ID, WorkingCalendarHoliday.holiday_date >= start, WorkingCalendarHoliday.holiday_date <= end))
    out: dict[date, WorkingCalendarHoliday] = {}
    for r in rows:
        current = db.scalar(select(WorkingCalendarVersion).where(WorkingCalendarVersion.calendar_id == CALENDAR_ID, WorkingCalendarVersion.effective_year == r.effective_year, WorkingCalendarVersion.is_current.is_(True)))
        if current is None or current.version == r.version:
            out[r.holiday_date] = r
    return out


def calendar_versions(db: Session) -> list[WorkingCalendarVersion]:
    return list(db.scalars(select(WorkingCalendarVersion).where(WorkingCalendarVersion.calendar_id == CALENDAR_ID, WorkingCalendarVersion.is_current.is_(True)).order_by(WorkingCalendarVersion.effective_year)))


def calendar_version_label(db: Session) -> str:
    versions = calendar_versions(db)
    if not versions:
        return "missing"
    return ";".join(f"{v.effective_year}:{v.version}" for v in versions)


def calendar_coverage(db: Session, start: date, end: date) -> dict:
    """Whether the calendar covers the range and whether any provisional holiday falls in it."""
    years = {y for y in range(start.year, end.year + 1)}
    covered = {v.effective_year for v in calendar_versions(db)}
    hol = holidays_between(db, start, end)
    return {
        "calendar_missing": bool(years - covered),
        "missing_years": sorted(years - covered),
        "provisional": any(h.status == "provisional" for h in hol.values()),
        "provisional_dates": sorted(d.isoformat() for d, h in hol.items() if h.status == "provisional"),
        "version": calendar_version_label(db),
    }


def is_working_day(db: Session, d: date, holidays: dict[date, WorkingCalendarHoliday] | None = None) -> bool:
    if d.weekday() in WEEKEND:
        return False
    hol = holidays if holidays is not None else holidays_between(db, d, d)
    return d not in hol


def next_working_day(db: Session, d: date, holidays: dict | None = None) -> date:
    while not is_working_day(db, d, holidays):
        d += timedelta(days=1)
    return d


def working_days_between(db: Session, start: datetime | date, end: datetime | date) -> float:
    """Fractional working days (one decimal) between two instants under the day-0 convention.

    Dates are taken as 00:00 Dubai time. Negative spans return 0.0. The calendar is applied only in the
    calculation; a year without a calendar version falls back to calendar weekdays (caller shows a notice).
    """
    s = _to_dubai(start) if isinstance(start, datetime) else datetime.combine(start, datetime.min.time())
    e = _to_dubai(end) if isinstance(end, datetime) else datetime.combine(end, datetime.min.time())
    if e <= s:
        return 0.0
    hol = holidays_between(db, s.date() - timedelta(days=1), e.date() + timedelta(days=1))
    total = 0.0
    day = s.date()
    while day <= e.date():
        if is_working_day(db, day, hol):
            day_start = datetime.combine(day, datetime.min.time())
            day_end = day_start + timedelta(days=1)
            lo = max(day_start, s)
            hi = min(day_end, e)
            if hi > lo:
                total += (hi - lo).total_seconds() / 86400.0
        day += timedelta(days=1)
    return round(total, 1)


def age_band(days: float) -> str:
    """Age bands for open cases (values to be confirmed with UX): 0-2, 3-7, 8-14, 15+ working days."""
    if days <= 2:
        return "0-2"
    if days <= 7:
        return "3-7"
    if days <= 14:
        return "8-14"
    return "15+"
