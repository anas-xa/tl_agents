"""Versioned rules and deadline engine (E3-S2) and the SC4 Obligation read model (E1-S3 Q357).

Owner of the Rule and Calendar Reference: every rate, offset, roll rule and working-week value used for a deadline
is read from ``DeadlineRule`` rows (never copied into code). Holiday calendars are versioned per jurisdiction with
two-person approval; the federal and Dubai calendars are seeded from the escalation module's
``uae_working_calendar`` reference data (reused, not edited).

Settled rules applied here:
* statutory date = legal due date; NO roll by default ('unconfirmed, source: none'); 'Moved to next working day'
  is feature-flagged OFF; the earlier internal 'recommended submit-by' date drives reminders;
* precedence of the date used: FTA-stated / FTA extension (with evidence) > rule-derived > owner-entered
  (provisional, never overriding); DET and Ejari dates are stored as given;
* CT: period end + 9 months with the 'last-day' month-end rule; VAT: period end + 28 calendar days;
* filed evidence order: FTA status (1C) > receipt with reference + filed date > owner declaration (unverified);
* days left are plain calendar days in Asia/Dubai, computed server-side.
"""

from __future__ import annotations

import calendar as _cal
import hashlib
import json
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import Conflict, Forbidden, NotFound, ValidationFailed
from app.core.time import dubai_today, utcnow
from app.modules.audit.service import record_event
from app.modules.companies.models import Company, CompanyRole
from app.modules.config.service import get_config
from app.modules.deadlines.models import (
    APPLICABILITY_BASES,
    FILED_SOURCES,
    HOLIDAY_STATUSES,
    JURISDICTIONS,
    RULE_MANDATORY_FIELDS,
    AuthorityDate,
    CalendarEntry,
    CalendarVersion,
    DeadlineRule,
    FiledEvidence,
    NotifyOwnerRequest,
    Obligation,
    RecalcBatch,
    RecalcCheckpoint,
    RuleChange,
)
from app.modules.deadlines.strings import bi, s
from app.modules.licences.models import Licence

OWNER_LEVEL = ("owner", "remote_owner")
DEFAULT_FUNCTION_MAP = {
    "vat_return": ["all", "tax_preparation", "deadlines"],
    "ct_return": ["all", "tax_preparation", "deadlines"],
    "audit": ["all", "audit_preparation", "deadlines"],
    "licence_renewal": ["all", "licence", "compliance", "deadlines"],
    "ejari_renewal": ["all", "licence", "compliance", "deadlines"],
    "other": ["all", "licence", "compliance", "deadlines"],
}
DEFAULT_AUTHORITY_CALENDAR = {"FTA": "UAE-FEDERAL", "DET": "DUBAI-GOV", "EJARI": "DUBAI-GOV", "CHAMBERS": "DUBAI-GOV"}
DATE_CHANGE_SOURCE_TAG = {"FTA_NOTICE": "authority date entered by you", "FTA_PORTAL_STATUS": "authority date entered by you", "DET": "DET record", "EJARI": "DET record", "RULE_DERIVED": "standard rule", "OWNER_ENTERED": "authority date entered by you"}


# --- pure date arithmetic (Asia/Dubai calendar dates) ---------------------------------------------------------


def _last_day(y: int, m: int) -> int:
    return _cal.monthrange(y, m)[1]


def add_months(d: date, months: int, *, month_end_rule: str = "last-day") -> date:
    """Add calendar months. 'last-day': a period end on the last day of its month maps to the last day of the
    target month; otherwise the same day clamped to the target month length (target year decides leap February)."""
    y, m = d.year, d.month + months
    y, m = y + (m - 1) // 12, (m - 1) % 12 + 1
    if month_end_rule == "last-day" and d.day == _last_day(d.year, d.month):
        return date(y, m, _last_day(y, m))
    return date(y, m, min(d.day, _last_day(y, m)))


def ct_due_date(period_end: date, months: int = 9, month_end_rule: str = "last-day") -> date:
    return add_months(period_end, months, month_end_rule=month_end_rule)


def vat_due_date(period_end: date, days: int = 28) -> date:
    return period_end + timedelta(days=days)


def days_left(due: date | None, today: date | None = None) -> int | None:
    if due is None:
        return None
    return (due - (today or dubai_today())).days


def days_left_tier(db: Session, n: int | None) -> str:
    if n is None:
        return "unknown"
    tiers = get_config(db, "deadlines.days_left_tiers", {"attention_max": 30, "urgent_max": 7}) or {}
    if n < 0:
        return "critical"
    if n <= int(tiers.get("urgent_max", 7)):
        return "urgent"
    if n <= int(tiers.get("attention_max", 30)):
        return "attention"
    return "neutral"


# --- Rule and Calendar Reference ------------------------------------------------------------------------------


def _as_date(v: Any) -> date | None:
    if v in (None, "", "open"):
        return None
    if isinstance(v, date):
        return v
    try:
        return date.fromisoformat(str(v)[:10])
    except ValueError as exc:
        raise ValidationFailed("dates must be ISO 8601 (YYYY-MM-DD)", reason_code="DATE_INVALID") from exc


def validate_rule_row(payload: dict) -> list[str]:
    """A rule row missing any mandatory field is rejected. effective_to must be present ('open' = no end)."""
    missing = []
    for f in RULE_MANDATORY_FIELDS:
        if f not in payload:
            missing.append(f)
        elif f != "effective_to" and payload[f] in (None, ""):
            missing.append(f)
    if payload.get("applicability_basis") and payload["applicability_basis"] not in APPLICABILITY_BASES:
        missing.append("applicability_basis")
    return missing


def create_rule(db: Session, payload: dict, *, actor_key: str | None = None) -> DeadlineRule:
    missing = validate_rule_row(payload)
    if missing:
        raise ValidationFailed("rule row rejected: mandatory fields missing or invalid", reason_code="RULE_ROW_INCOMPLETE", details={"missing": missing})
    if db.scalar(select(DeadlineRule).where(DeadlineRule.key == payload["key"], DeadlineRule.version == str(payload["version"]))):
        raise Conflict("this key already has that version", reason_code="RULE_VERSION_EXISTS")
    row = DeadlineRule(
        key=payload["key"], value=payload["value"], legal_instrument=payload["legal_instrument"], effective_from=_as_date(payload["effective_from"]),
        effective_to=_as_date(payload["effective_to"]), version=str(payload["version"]), applicability_basis=payload["applicability_basis"],
        entered_by=payload["entered_by"], entered_date=_as_date(payload["entered_date"]), status="draft",
        confirmation_status=payload.get("confirmation_status") or "unconfirmed, source: none", confirmed_by=payload.get("confirmed_by"),
        source_type=payload.get("source_type") or "statutory", display_status=payload.get("display_status") or "statutory date",
        label=payload.get("label"), last_checked=_as_date(payload.get("last_checked")) or date.today(),
    )
    db.add(row)
    db.add(RuleChange(key=row.key, version=row.version, changed_by=row.entered_by, old_value=None, new_value=row.value, source=row.legal_instrument, confirmed_by=row.confirmed_by, action="created"))
    db.flush()
    record_event(db, event_type="DEADLINE_RULE_CREATED", category="config", actor_key=actor_key, subject_type="deadline_rule", subject_id=row.id, details={"key": row.key, "version": row.version, "basis": row.applicability_basis})
    return row


def activate_rule(db: Session, rule_id: str, *, approved_by: str, actor_key: str | None = None) -> DeadlineRule:
    row = db.get(DeadlineRule, rule_id)
    if row is None:
        raise NotFound("rule not found", reason_code="RULE_NOT_FOUND")
    if row.status == "active":
        return row
    if approved_by == row.entered_by:
        raise ValidationFailed("a rule is activated by a second, different person", reason_code="SECOND_APPROVER_REQUIRED")
    prev = list(db.scalars(select(DeadlineRule).where(DeadlineRule.key == row.key, DeadlineRule.status == "active", DeadlineRule.effective_from == row.effective_from)))
    for p in prev:
        p.status = "superseded"
        db.add(RuleChange(key=p.key, version=p.version, changed_by=approved_by, old_value=p.value, new_value=row.value, source=row.legal_instrument, confirmed_by=row.confirmed_by, action="superseded"))
    row.status = "active"
    row.activated_at = utcnow()
    db.add(RuleChange(key=row.key, version=row.version, changed_by=approved_by, old_value=prev[0].value if prev else None, new_value=row.value, source=row.legal_instrument, confirmed_by=row.confirmed_by, action="activated"))
    db.flush()
    record_event(db, event_type="DEADLINE_RULE_ACTIVATED", category="config", actor_key=actor_key, subject_type="deadline_rule", subject_id=row.id, details={"key": row.key, "version": row.version})
    return row


def amend_rule(db: Session, rule_id: str, **fields: Any) -> DeadlineRule:
    """Rows are immutable once active (applicability basis included): a change is a new version."""
    row = db.get(DeadlineRule, rule_id)
    if row is None:
        raise NotFound("rule not found", reason_code="RULE_NOT_FOUND")
    if row.status != "draft":
        raise Conflict("an activated rule cannot be changed; create a new version with a new effective date", reason_code="RULE_IMMUTABLE")
    for k, v in fields.items():
        if k in ("applicability_basis",) and v not in APPLICABILITY_BASES:
            raise ValidationFailed("applicability basis not recognised", reason_code="RULE_ROW_INCOMPLETE")
        setattr(row, k, v)
    db.flush()
    return row


def rule_row(db: Session, key: str, basis_date: date | None = None) -> DeadlineRule | None:
    on = basis_date or dubai_today()
    rows = list(db.scalars(select(DeadlineRule).where(DeadlineRule.key == key, DeadlineRule.status == "active").order_by(DeadlineRule.effective_from.desc())))
    for r in rows:
        if r.effective_from <= on and (r.effective_to is None or on < r.effective_to):
            return r
    return None


def rule_value(db: Session, key: str, basis_date: date | None = None, default: Any = None) -> tuple[Any, str | None]:
    r = rule_row(db, key, basis_date)
    if r is None:
        return default, None
    return r.value, r.version


def list_rules(db: Session) -> list[dict]:
    rows = db.scalars(select(DeadlineRule).order_by(DeadlineRule.key, DeadlineRule.effective_from))
    return [rule_dict(r) for r in rows]


def rule_dict(r: DeadlineRule) -> dict:
    return {
        "id": r.id, "key": r.key, "value": r.value, "legal_instrument": r.legal_instrument, "effective_from": r.effective_from.isoformat(),
        "effective_to": r.effective_to.isoformat() if r.effective_to else None, "version": r.version, "applicability_basis": r.applicability_basis,
        "entered_by": r.entered_by, "entered_date": r.entered_date.isoformat(), "status": r.status, "confirmation_status": r.confirmation_status,
        "confirmed_by": r.confirmed_by, "source_type": r.source_type, "display_status": r.display_status, "label": r.label,
        "last_checked": r.last_checked.isoformat() if r.last_checked else None,
    }


def rule_history(db: Session, key: str | None = None) -> list[dict]:
    stmt = select(RuleChange).order_by(RuleChange.changed_at)
    if key:
        stmt = stmt.where(RuleChange.key == key)
    return [{"key": c.key, "version": c.version, "changed_by": c.changed_by, "changed_at": c.changed_at.isoformat(), "old_value": c.old_value, "new_value": c.new_value, "source": c.source, "confirmed_by": c.confirmed_by, "action": c.action} for c in db.scalars(stmt)]


def rules_version_label(db: Session, lang: str = "en") -> dict:
    rows = list(db.scalars(select(DeadlineRule).where(DeadlineRule.status == "active")))
    version = max((r.version for r in rows), default="none")
    checked = max((r.last_checked for r in rows if r.last_checked), default=None)
    return {"version": version, "checked": checked.isoformat() if checked else None, "label": bi("note.rules_version", version=version, date=checked.isoformat() if checked else "-")}


# --- holiday and working-week calendars -------------------------------------------------------------------------


def calendar_for_authority(db: Session, authority: str) -> str:
    mapping = get_config(db, "deadlines.calendar_for_authority", DEFAULT_AUTHORITY_CALENDAR) or DEFAULT_AUTHORITY_CALENDAR
    return mapping.get(authority, "UAE-FEDERAL")


def working_week(db: Session, jurisdiction: str, on: date | None = None) -> dict:
    value, version = rule_value(db, f"working_week.{jurisdiction}", on, {"weekend": [5, 6], "short_friday": True})
    return {**(value or {}), "version": version}


def holidays(db: Session, jurisdiction: str, start: date, end: date) -> dict[date, CalendarEntry]:
    rows = db.scalars(select(CalendarEntry).where(CalendarEntry.jurisdiction == jurisdiction, CalendarEntry.approval_state == "approved", CalendarEntry.start_date <= end, CalendarEntry.end_date >= start))
    out: dict[date, CalendarEntry] = {}
    for r in rows:
        d = max(r.start_date, start)
        while d <= min(r.end_date, end):
            out[d] = r
            d += timedelta(days=1)
    return out


def calendar_state(db: Session, jurisdiction: str, year: int, today: date | None = None) -> dict:
    """Missing (no entries for the year) or stale (not checked within the configured age) -> working-week only."""
    today = today or dubai_today()
    v = db.scalar(select(CalendarVersion).where(CalendarVersion.jurisdiction == jurisdiction, CalendarVersion.year == year, CalendarVersion.is_current.is_(True)))
    stale_days = int(get_config(db, "deadlines.calendar.stale_check_days", 30) or 30)
    if v is None:
        return {"state": "missing", "version": None, "label": bi("note.holiday_calendar_not_confirmed")}
    if (today - v.checked_at).days > stale_days:
        return {"state": "stale", "version": v.version, "checked_at": v.checked_at.isoformat(), "label": bi("note.holiday_calendar_not_confirmed")}
    return {"state": "current", "version": v.version, "checked_at": v.checked_at.isoformat(), "label": None}


def calendar_version_label(db: Session, jurisdiction: str, year: int) -> str:
    v = db.scalar(select(CalendarVersion).where(CalendarVersion.jurisdiction == jurisdiction, CalendarVersion.year == year, CalendarVersion.is_current.is_(True)))
    return f"{jurisdiction} {v.version}" if v else f"{jurisdiction} missing"


def all_calendar_versions(db: Session) -> str:
    rows = db.scalars(select(CalendarVersion).where(CalendarVersion.is_current.is_(True)).order_by(CalendarVersion.jurisdiction, CalendarVersion.year))
    return ";".join(f"{r.jurisdiction}:{r.year}:{r.version}" for r in rows) or "missing"


def day_flag(db: Session, d: date, jurisdiction: str) -> str:
    """none | weekend | public_holiday (confirmed only) | provisional_holiday. A missing/stale calendar makes no holiday claims."""
    ww = working_week(db, jurisdiction, d)
    if d.weekday() in (ww.get("weekend") or [5, 6]):
        return "weekend"
    if calendar_state(db, jurisdiction, d.year)["state"] != "current":
        return "none"
    h = holidays(db, jurisdiction, d, d).get(d)
    if h is None:
        return "none"
    return "public_holiday" if h.status == "confirmed" else "provisional_holiday"


def is_working_day(db: Session, d: date, jurisdiction: str, *, avoid_provisional: bool = False) -> bool:
    flag = day_flag(db, d, jurisdiction)
    if flag in ("weekend", "public_holiday"):
        return False
    return not (avoid_provisional and flag == "provisional_holiday")


def previous_working_day(db: Session, d: date, jurisdiction: str, *, avoid_provisional: bool = True) -> date:
    d -= timedelta(days=1)
    for _ in range(60):
        if is_working_day(db, d, jurisdiction, avoid_provisional=avoid_provisional):
            return d
        d -= timedelta(days=1)
    return d


def next_working_day(db: Session, d: date, jurisdiction: str) -> date:
    for _ in range(60):
        if is_working_day(db, d, jurisdiction):
            return d
        d += timedelta(days=1)
    return d


def recommended_submit_by(db: Session, statutory: date, jurisdiction: str) -> date:
    """Internal earlier date: the last working day on or before the statutory date (a non-working or provisional
    holiday date moves the recommendation earlier, never the deadline), minus the configured working-day offset."""
    offset = int(get_config(db, "deadlines.recommended_submit_by.offset_working_days", 0) or 0)
    d = statutory if is_working_day(db, statutory, jurisdiction, avoid_provisional=True) else previous_working_day(db, statutory, jurisdiction)
    for _ in range(offset):
        d = previous_working_day(db, d, jurisdiction)
    return d


def add_calendar_entry(db: Session, payload: dict, *, entered_by: str, actor_key: str | None = None) -> CalendarEntry:
    j = payload.get("jurisdiction")
    if j not in JURISDICTIONS:
        raise ValidationFailed("jurisdiction must be UAE-FEDERAL, DUBAI-GOV, FTA or DET", reason_code="JURISDICTION_INVALID")
    status = payload.get("status", "provisional")
    if status not in HOLIDAY_STATUSES:
        raise ValidationFailed("status must be provisional or confirmed", reason_code="HOLIDAY_STATUS_INVALID")
    if not payload.get("source_reference"):
        raise ValidationFailed("a holiday entry needs its announcement reference", reason_code="SOURCE_REFERENCE_REQUIRED")
    start, end = _as_date(payload.get("start_date")), _as_date(payload.get("end_date") or payload.get("start_date"))
    if not start or not end or end < start:
        raise ValidationFailed("start and end dates are required (ISO 8601), end on or after start", reason_code="DATE_INVALID")
    row = CalendarEntry(
        calendar_id=j, jurisdiction=j, name_en=payload.get("name_en") or "", name_ar=payload.get("name_ar") or "", start_date=start, end_date=end,
        hijri_display_date=payload.get("hijri_display_date"), status=status, source_reference=payload["source_reference"],
        publication_date=_as_date(payload.get("publication_date")), confirmation_date=_as_date(payload.get("confirmation_date")),
        entered_by=entered_by, loaded_by=payload.get("loaded_by") or "manual entry", version="pending", approval_state="pending_approval",
    )
    db.add(row)
    db.flush()
    record_event(db, event_type="HOLIDAY_ENTRY_ENTERED", category="config", actor_key=actor_key, subject_type="calendar_entry", subject_id=row.id, details={"jurisdiction": j, "status": status})
    return row


def approve_calendar_entry(db: Session, entry_id: str, *, approved_by: str, actor_key: str | None = None, run_batch: bool = True) -> dict:
    row = db.get(CalendarEntry, entry_id)
    if row is None:
        raise NotFound("calendar entry not found", reason_code="NOT_FOUND")
    if approved_by == row.entered_by:
        raise ValidationFailed("holiday entries need two-person approval: the approver must differ from the person who entered it", reason_code="SECOND_APPROVER_REQUIRED")
    year = row.start_date.year
    cur = db.scalar(select(CalendarVersion).where(CalendarVersion.jurisdiction == row.jurisdiction, CalendarVersion.year == year, CalendarVersion.is_current.is_(True)))
    n = 1
    if cur is not None:
        cur.is_current = False
        try:
            n = int(cur.version.split(".")[-1]) + 1
        except ValueError:
            n = 2
    version = f"{year}.{n}"
    db.add(CalendarVersion(jurisdiction=row.jurisdiction, year=year, version=version, source_reference=row.source_reference, checked_at=dubai_today(), loaded_by=row.loaded_by, approved_by=approved_by))
    row.approved_by, row.approval_state, row.version = approved_by, "approved", version
    if row.status == "confirmed" and row.confirmation_date is None:
        row.confirmation_date = dubai_today()
    db.flush()
    record_event(db, event_type="HOLIDAY_ENTRY_APPROVED", category="config", actor_key=actor_key, subject_type="calendar_entry", subject_id=row.id, details={"jurisdiction": row.jurisdiction, "version": version, "status": row.status})
    batch = run_recalculation_batch(db, reason="calendar_change") if run_batch else None
    return {"entry_id": row.id, "version": version, "batch": batch}


def month_calendar(db: Session, year: int, month: int) -> dict:
    """Holidays for the SC4 month view: confirmed entries only ('Public holiday (official list)'), with the list version date."""
    start = date(year, month, 1)
    end = date(year, month, _last_day(year, month))
    out = []
    for j in ("UAE-FEDERAL", "DUBAI-GOV"):
        for r in db.scalars(select(CalendarEntry).where(CalendarEntry.jurisdiction == j, CalendarEntry.approval_state == "approved", CalendarEntry.status == "confirmed", CalendarEntry.start_date <= end, CalendarEntry.end_date >= start)):
            v = db.scalar(select(CalendarVersion).where(CalendarVersion.jurisdiction == j, CalendarVersion.year == r.start_date.year, CalendarVersion.is_current.is_(True)))
            out.append({"jurisdiction": j, "start_date": r.start_date.isoformat(), "end_date": r.end_date.isoformat(), "name": {"en": r.name_en, "ar": r.name_ar}, "label": bi("note.public_holiday_official"), "list_version": v.version if v else None, "list_version_date": v.checked_at.isoformat() if v else None})
    ww = working_week(db, "DUBAI-GOV", start)
    return {"year": year, "month": month, "weekend_days": ww.get("weekend", [5, 6]), "holidays": out, "hijri_display": bool(get_config(db, "deadlines.hijri_display.enabled", False))}


# --- inputs ------------------------------------------------------------------------------------------------------


def _tax_entity_profile(db: Session, company_id: str):
    try:
        from app.modules.tax.models import TaxEntityProfile

        return db.get(TaxEntityProfile, company_id)  # read only (never the creating getter)
    except ImportError:  # pragma: no cover
        return None


def _datalinks_profiles(db: Session, company_id: str) -> dict[str, Any]:
    try:
        from app.modules.datalinks.models import TaxProfile

        rows = db.scalars(select(TaxProfile).where(TaxProfile.company_id == company_id, TaxProfile.is_current.is_(True)))
        return {r.tax_type: r for r in rows}
    except ImportError:  # pragma: no cover
        return {}


def _step_months(freq: str | None) -> int:
    return {"monthly": 1, "quarterly": 3, "annual": 12}.get(freq or "quarterly", 3)


def _period_after(start: date, end: date, months: int) -> tuple[date, date]:
    ns = end + timedelta(days=1)
    ne = add_months(ns, months, month_end_rule="last-day") - timedelta(days=1) if ns.day == 1 else add_months(end, months)
    return ns, ne


def _period_id(tax_type: str, start: date, end: date, fy_end: tuple[int, int] = (12, 31)) -> str:
    if tax_type == "vat":
        if start.day == 1 and end.day == _last_day(end.year, end.month):
            months = (end.year - start.year) * 12 + end.month - start.month + 1
            if months == 1:
                return f"{start.year}-{start.month:02d}"
            if months == 3 and start.month in (1, 4, 7, 10) and start.year == end.year:
                return f"{start.year}-Q{(start.month - 1) // 3 + 1}"
    elif (end.month, end.day) == fy_end and (end - start).days >= 364:
        return f"FY{end.year}"
    return f"{start.isoformat()}_{end.isoformat()}"


def _ended_and_current(start: date, end: date, months: int, today: date) -> list[tuple[date, date]]:
    """The last period that ended before today and the period running today (anchored on the entered period)."""
    s0, e0 = start, end
    for _ in range(400):
        if e0 >= today:
            break
        ns, ne = _period_after(s0, e0, months)
        if ne >= today:
            return [(s0, e0), (ns, ne)]
        s0, e0 = ns, ne
    out = [(s0, e0)]
    if s0 > today and e0 > today:  # the entered period is in the future: show it alone
        return out
    return out


def _calendar_quarter(today: date, months: int) -> tuple[date, date]:
    m0 = ((today.month - 1) // months) * months + 1
    s0 = date(today.year, m0, 1)
    e0 = add_months(s0, months, month_end_rule="none") - timedelta(days=1)
    return s0, e0


def _fy_bounds(fy_end_year: int, m: int, d: int) -> tuple[date, date]:
    end = date(fy_end_year, m, min(d, _last_day(fy_end_year, m)))
    start = add_months(end, -12, month_end_rule="last-day") + timedelta(days=1)
    return start, end


def _missing(code: str) -> dict:
    return {"code": code, "label_en": s(f"missing.{code}", "en"), "label_ar": s(f"missing.{code}", "ar")}


def _tax_missing_items(db: Session, company_id: str, tax_type: str, start: date, end: date, trn: str | None, prof) -> list[dict]:
    """Read-only completeness (dc-v1 inputs): never writes a check record."""
    items: list[dict] = []
    keys: list[str] = []
    try:
        from app.modules.bookkeeping import service as bk

        keys = [i["key"] for i in bk.dc_v1_inputs(db, "vat" if tax_type == "vat" else "ct") if i.get("mandatory")]
        confirmed = bk.confirmed_transactions(db, company_id, start, end)
        excluded = bk.excluded_transactions(db, company_id, start, end)
        facts = {
            "transactions": bool(confirmed) or bool(excluded),
            "all_reviewed": not excluded,
            "vat_codes": all(c.final_vat_code for c, _ in confirmed),
            "fx_rates": not any(t.fx_missing for _, t in confirmed),
        }
    except Exception:  # bookkeeping absent: only the profile facts
        facts = {}
        keys = ["trn"] if tax_type == "vat" else ["ct_status", "financial_year", "revenue_confirmed"]
    facts["trn"] = bool(trn)
    facts["ct_status"] = bool(prof is not None and getattr(prof, "ct_status", "unclear") != "unclear")
    facts["financial_year"] = True
    facts["revenue_confirmed"] = bool(prof is not None and getattr(prof, "revenue_confirmed_at", None))
    for k in keys:
        if not facts.get(k, False):
            items.append(_missing(k))
    return items


def candidates(db: Session, company_id: str, today: date | None = None) -> list[dict]:
    """Every obligation the engine can see for the company, before precedence and calendar treatment."""
    today = today or dubai_today()
    out: list[dict] = []
    licences = list(db.scalars(select(Licence).where(Licence.company_id == company_id, Licence.scope != "out_of_scope")))
    for lic in licences:
        base = {"licence_number": lic.licence_number, "period_start": None, "period_end": None, "period_id": None, "tax_type": None}
        # licence renewal: DET date stored as given (engine never recomputes expiry)
        out.append({**base, "key": f"licence_renewal:{lic.licence_number}:{lic.expiry_date.isoformat() if lic.expiry_date else 'none'}", "type": "licence_renewal", "subtype": None, "authority": "DET",
                    "statutory_date": lic.expiry_date, "deadline_source": "DET", "is_stated": True, "input_source": "det", "data_basis": "based_on_verified_details",
                    "rule_key": None, "provisional_date": None, "missing_items": [] if lic.expiry_date else [_missing("licence_expiry")], "licence_status": lic.status})
        if lic.ejari_status != "not_applicable":
            verified = lic.ejari_status == "verified"
            out.append({**base, "key": f"ejari_renewal:{lic.licence_number}:{lic.ejari_expiry.isoformat() if lic.ejari_expiry else 'none'}", "type": "ejari_renewal", "subtype": None, "authority": "EJARI",
                        "statutory_date": lic.ejari_expiry if verified else None, "deadline_source": "EJARI" if verified else "OWNER_ENTERED", "is_stated": verified,
                        "input_source": "ejari" if verified else "owner_declared", "data_basis": "based_on_verified_details" if verified else "based_on_details_you_entered",
                        "rule_key": None, "provisional_date": None if verified else lic.ejari_expiry, "missing_items": [] if lic.ejari_expiry else [_missing("ejari_expiry")]})
        if lic.chamber_membership_status or lic.chamber_membership_expiry:
            verified = lic.chamber_membership_status == "verified"
            out.append({**base, "key": f"other:chambers:{lic.licence_number}:{lic.chamber_membership_expiry.isoformat() if lic.chamber_membership_expiry else 'none'}", "type": "other", "subtype": "chambers_membership", "authority": "CHAMBERS",
                        "statutory_date": lic.chamber_membership_expiry if verified else None, "deadline_source": "DET" if verified else "OWNER_ENTERED", "is_stated": verified,
                        "input_source": "det" if verified else "unconfirmed", "data_basis": "based_on_verified_details" if verified else "based_on_details_you_entered",
                        "rule_key": None, "provisional_date": None if verified else lic.chamber_membership_expiry, "missing_items": [] if verified else [_missing("chambers_membership")]})
    lic_no = licences[0].licence_number if licences else None
    prof = _tax_entity_profile(db, company_id)
    dl = _datalinks_profiles(db, company_id)
    company = db.get(Company, company_id)
    fy_m = getattr(prof, "financial_year_end_month", None) or (company.financial_year_end_month if company else 12)
    fy_d = getattr(prof, "financial_year_end_day", None) or (company.financial_year_end_day if company else 31)
    # VAT: owner-entered tax period / frequency (datalinks, Phase 1A path) first, then the tax profile.
    vat_p = dl.get("vat")
    vat_periods: list[tuple[date, date]] = []
    vat_trn = (vat_p.trn if vat_p else None) or (prof.trn if prof else None)
    basis_vat = "based_on_details_you_entered"
    input_vat = "owner_entered"
    if vat_p is not None and vat_p.tax_period_end:
        freq = vat_p.filing_frequency or "quarterly"
        start = vat_p.tax_period_start or add_months(vat_p.tax_period_end + timedelta(days=1), -_step_months(freq), month_end_rule="none")
        vat_periods = _ended_and_current(start, vat_p.tax_period_end, _step_months(freq), today)
        if vat_p.source == "fta_live":
            basis_vat, input_vat = "based_on_verified_details", "FTA"
        elif (vat_p.entered_by_role or "") == "delegate":
            input_vat = "delegate_entered"
    elif prof is not None and prof.vat_registered:
        months = _step_months(prof.vat_period_type)
        s0, e0 = _calendar_quarter(today, months)
        prev_s = add_months(s0, -months, month_end_rule="none")
        vat_periods = [(prev_s, s0 - timedelta(days=1)), (s0, e0)]
    for ps, pe in vat_periods:
        out.append({"key": f"vat_return:{ps.isoformat()}_{pe.isoformat()}", "type": "vat_return", "subtype": None, "authority": "FTA", "licence_number": lic_no, "tax_type": "vat",
                    "period_start": ps, "period_end": pe, "period_id": _period_id("vat", ps, pe), "statutory_date": None, "deadline_source": "RULE_DERIVED", "is_stated": False,
                    "input_source": input_vat, "data_basis": basis_vat, "rule_key": "vat.deadline_offset_days", "provisional_date": None,
                    "missing_items": _tax_missing_items(db, company_id, "vat", ps, pe, vat_trn, prof) if pe < today else ([_missing("trn")] if not vat_trn else []),
                    "owner_due_date": vat_p.due_date_override if vat_p is not None else None})
    # Corporate tax
    ct_p = dl.get("corporate_tax")
    ct_periods: list[tuple[date, date]] = []
    ct_trn = (ct_p.trn if ct_p else None) or (prof.trn if prof else None)
    basis_ct, input_ct, ct_unconfirmed = "based_on_details_you_entered", "owner_entered", False
    if ct_p is not None and ct_p.tax_period_end:
        start = ct_p.tax_period_start or add_months(ct_p.tax_period_end, -12) + timedelta(days=1)
        ct_periods = [(start, ct_p.tax_period_end)]
        if ct_p.tax_period_end < today:
            ns, ne = _period_after(start, ct_p.tax_period_end, 12)
            ct_periods.append((ns, ne))
        if ct_p.source == "fta_live":
            basis_ct, input_ct = "based_on_verified_details", "FTA"
    elif prof is not None:
        if prof.ct_status == "unclear" or prof.first_ct_period_start is None:
            ct_unconfirmed = True
        else:
            year = today.year if (today.month, today.day) <= (fy_m, fy_d) else today.year + 1
            cur = _fy_bounds(year, fy_m, fy_d)
            prev = _fy_bounds(year - 1, fy_m, fy_d)
            if prev[1] >= prof.first_ct_period_start:
                ct_periods.append((max(prev[0], prof.first_ct_period_start), prev[1]))
            ct_periods.append(cur)
    for ps, pe in ct_periods:
        out.append({"key": f"ct_return:{ps.isoformat()}_{pe.isoformat()}", "type": "ct_return", "subtype": None, "authority": "FTA", "licence_number": lic_no, "tax_type": "ct",
                    "period_start": ps, "period_end": pe, "period_id": _period_id("ct", ps, pe, (fy_m, fy_d)), "statutory_date": None, "deadline_source": "RULE_DERIVED", "is_stated": False,
                    "input_source": input_ct, "data_basis": basis_ct, "rule_key": "ct.deadline_offset_months", "provisional_date": None,
                    "missing_items": _tax_missing_items(db, company_id, "ct", ps, pe, ct_trn, prof) if pe < today else [], "owner_due_date": ct_p.due_date_override if ct_p is not None else None})
    if ct_unconfirmed:
        out.append({"key": "ct_return:period_not_confirmed", "type": "ct_return", "subtype": None, "authority": "FTA", "licence_number": lic_no, "tax_type": "ct", "period_start": None, "period_end": None,
                    "period_id": None, "statutory_date": None, "deadline_source": "RULE_DERIVED", "is_stated": False, "input_source": "unconfirmed", "data_basis": "based_on_details_you_entered",
                    "rule_key": "ct.deadline_offset_months", "provisional_date": None, "missing_items": [_missing("ct_status"), _missing("tax_period")], "owner_due_date": None})
    return out


# --- precedence, calendar treatment and persistence ---------------------------------------------------------------


def _rule_date(db: Session, c: dict) -> tuple[date | None, str | None]:
    pe = c.get("period_end")
    if pe is None:
        return None, None
    if c["type"] == "vat_return":
        days, ver = rule_value(db, "vat.deadline_offset_days", pe, None)
        if days is None:
            return None, None
        return vat_due_date(pe, int(days)), ver
    if c["type"] == "ct_return":
        months, ver = rule_value(db, "ct.deadline_offset_months", pe, None)
        rule_end, _ = rule_value(db, "ct.month_end_rule", pe, "last-day")
        if months is None:
            return None, None
        return ct_due_date(pe, int(months), str(rule_end)), ver
    return None, None


def _authority_override(db: Session, company_id: str, key: str) -> AuthorityDate | None:
    return db.scalar(select(AuthorityDate).where(AuthorityDate.company_id == company_id, AuthorityDate.obligation_key == key, AuthorityDate.evidence_ref.is_not(None)).order_by(AuthorityDate.entered_at.desc()).limit(1))


def _filed(db: Session, company_id: str, key: str) -> FiledEvidence | None:
    rows = list(db.scalars(select(FiledEvidence).where(FiledEvidence.company_id == company_id, FiledEvidence.obligation_key == key)))
    for src in FILED_SOURCES:  # source order: FTA status > receipt > owner declaration
        for r in rows:
            if r.source == src and (src != "receipt" or (r.filing_reference and r.filed_date)):
                return r
    return None


def resolve(db: Session, company_id: str, c: dict, today: date) -> dict:
    """Apply precedence, the roll rule (no roll), the calendar flags and the recommended submit-by date."""
    rule_ver = None
    statutory = c.get("statutory_date")
    if c.get("rule_key"):
        statutory, rule_ver = _rule_date(db, c)
    date_used, deadline_source, due_source, is_stated = statutory, c["deadline_source"], None, c["is_stated"]
    date_status = "confirmed" if statutory else "not_confirmed"
    provisional = c.get("provisional_date")
    override = _authority_override(db, company_id, c["key"])
    if override is not None:
        date_used, is_stated, date_status = override.stated_date, True, "confirmed"
        deadline_source = override.kind if override.kind in ("FTA_NOTICE", "FTA_PORTAL_STATUS") else "FTA_NOTICE"
        due_source = "fta_extension" if override.kind == "fta_extension" else "fta_stated"
    elif statutory is None and c.get("owner_due_date"):
        provisional, deadline_source = c["owner_due_date"], "OWNER_ENTERED"  # provisional, never overriding
    if due_source is None:
        due_source = {"RULE_DERIVED": "rule_derived", "DET": "det_record", "EJARI": "ejari_record", "OWNER_ENTERED": "owner_entered", "FTA_NOTICE": "fta_stated", "FTA_PORTAL_STATUS": "fta_stated"}[deadline_source]
    roll, _ = rule_value(db, f"nonworking_day_treatment.{c['authority']}.{c['type']}", date_used, "no_roll")
    jurisdiction = calendar_for_authority(db, c["authority"])
    flag, submit_by, cal_conf = "none", date_used, True
    if date_used is not None:
        flag = day_flag(db, date_used, jurisdiction)
        cal_conf = calendar_state(db, jurisdiction, date_used.year, today)["state"] == "current"
        submit_by = recommended_submit_by(db, date_used, jurisdiction)
        if roll == "next_working_day" and flag in ("weekend", "public_holiday") and bool(get_config(db, "deadlines.moved_to_next_working_day.enabled", False)):
            date_used = next_working_day(db, date_used, jurisdiction)  # flag OFF by default; never used unless confirmed
    filed = _filed(db, company_id, c["key"])
    filed_state, done = None, False
    if filed is not None:
        filed_state = {"fta_status": "filed_fta_status", "receipt": "filed_receipt", "owner_declaration": "owner_declared_unverified"}[filed.source]
        done = True
    return {
        **c, "statutory_date": statutory, "date_used": date_used, "deadline_source": deadline_source, "due_date_source": due_source, "is_stated": is_stated,
        "date_status": date_status, "provisional_date": provisional, "rule_version": rule_ver, "calendar_version": calendar_version_label(db, jurisdiction, (date_used or today).year),
        "nonworking_flag": flag, "holiday_calendar_confirmed": cal_conf, "recommended_submit_by": submit_by, "filed_state": filed_state, "done": done, "jurisdiction": jurisdiction,
    }


def _hash(r: dict) -> str:
    keys = ("statutory_date", "date_used", "deadline_source", "date_status", "rule_version", "calendar_version", "nonworking_flag", "recommended_submit_by", "filed_state", "done", "missing_items", "provisional_date", "holiday_calendar_confirmed", "input_source", "data_basis")
    return hashlib.sha256(json.dumps({k: r.get(k) for k in keys}, sort_keys=True, default=str).encode()).hexdigest()


def _pending_checkpoint(db: Session, company_id: str) -> RecalcCheckpoint | None:
    """The company's latest checkpoint holds reads while it is pending in a running batch or failed (until 'Try again')."""
    cp = db.scalar(select(RecalcCheckpoint).where(RecalcCheckpoint.company_id == company_id).order_by(RecalcCheckpoint.id.desc()).limit(1))
    if cp is None or cp.state == "done":
        return None
    if cp.state == "failed":
        return cp
    batch = db.get(RecalcBatch, cp.batch_id)
    return cp if batch is not None and batch.status == "running" else None


def retry_company(db: Session, company_id: str) -> dict:
    """SC4 'Try again' after a failed recalculation: a one-company batch."""
    return run_recalculation_batch(db, reason="retry", company_ids=[company_id])


def refresh_company(db: Session, company_id: str, *, today: date | None = None, force: bool = False) -> dict:
    """Atomic per company: recompute candidates and upsert obligations. Returns {changed: [...], created, superseded}."""
    today = today or dubai_today()
    if not force and _pending_checkpoint(db, company_id) is not None:
        return {"changed": [], "created": 0, "superseded": 0, "held": True}
    now = utcnow()
    resolved = [resolve(db, company_id, c, today) for c in candidates(db, company_id, today)]
    existing = {o.obligation_key: o for o in db.scalars(select(Obligation).where(Obligation.company_id == company_id))}
    changed, created = [], 0
    seen = set()
    for r in resolved:
        seen.add(r["key"])
        h = _hash(r)
        o = existing.get(r["key"])
        if o is None:
            o = Obligation(company_id=company_id, obligation_key=r["key"], obligation_type=r["type"], history=[])
            db.add(o)
            created += 1
        elif o.input_hash == h and not o.superseded and o.recalc_state == "none":
            continue
        old_used = o.due_date_used
        if o.input_hash and old_used and r["date_used"] and old_used != r["date_used"]:
            o.old_date, o.date_changed_at, o.date_change_source = old_used, now, DATE_CHANGE_SOURCE_TAG.get(r["deadline_source"], "standard rule")
            changed.append({"obligation_key": r["key"], "old": old_used.isoformat(), "new": r["date_used"].isoformat()})
        o.licence_number, o.subtype, o.authority = r.get("licence_number"), r.get("subtype"), r["authority"]
        o.period_start, o.period_end, o.period_id = r.get("period_start"), r.get("period_end"), r.get("period_id")
        o.statutory_date, o.due_date_used = r["statutory_date"], r["date_used"]
        o.deadline_source, o.due_date_source, o.date_status, o.is_stated = r["deadline_source"], r["due_date_source"], r["date_status"], r["is_stated"]
        o.rule_version, o.calendar_version, o.calculation_time = r["rule_version"], r["calendar_version"], now
        o.recommended_submit_by, o.nonworking_flag, o.holiday_calendar_confirmed = r["recommended_submit_by"], r["nonworking_flag"], r["holiday_calendar_confirmed"]
        o.data_basis, o.input_source, o.provisional_date = r["data_basis"], r["input_source"], r["provisional_date"]
        o.filed_state, o.done, o.missing_items = r["filed_state"], r["done"], r["missing_items"]
        o.superseded, o.recalc_state, o.input_hash, o.updated_at = False, "none", h, now
        if r["date_status"] == "confirmed" and r["date_used"]:
            o.last_confirmed_date, o.last_confirmed_at = r["date_used"], now
        o.history = list(o.history or []) + [{"at": now.isoformat(), "statutory_date": r["statutory_date"].isoformat() if r["statutory_date"] else None, "due_date_used": r["date_used"].isoformat() if r["date_used"] else None, "source": r["deadline_source"], "rule_version": r["rule_version"], "calendar_version": r["calendar_version"]}]
    superseded = 0
    for key, o in existing.items():
        if key not in seen and not o.superseded:
            o.superseded, o.updated_at = True, now
            if o.obligation_type in ("licence_renewal", "ejari_renewal", "other") and not o.done:
                o.done = True  # renewed: the source moved the expiry forward (task completed)
            superseded += 1
    db.flush()
    return {"changed": changed, "created": created, "superseded": superseded, "held": False}


# --- readiness ---------------------------------------------------------------------------------------------------

PACK_READINESS = {
    "filed_user_confirmed": ("receipt_recorded", "receipt_recorded"),
    "approved_for_submission": ("owner_approved", "owner_approved"),
    "accepted_by_owner_no_independent_review": ("owner_approved", "owner_approved"),
    "prepared": ("draft_ready", "draft_ready"),
    "under_review": ("draft_ready", "draft_ready"),
    "accepted_by_reviewer": ("draft_ready", "draft_ready"),
    "reviewed_by_specialist": ("draft_ready", "draft_ready"),
    "reviewed_with_changes": ("draft_ready", "draft_ready"),
    "not_reviewed": ("draft_ready", "in_preparation"),
    "stale": ("draft_ready", "in_preparation"),
}


def readiness(db: Session, o: Obligation) -> dict:
    pack_id = pack_status = None
    if o.filed_state in ("filed_fta_status", "filed_receipt"):
        r, detail = "receipt_recorded", "receipt_recorded"
    else:
        r = detail = None
        if o.obligation_type in ("vat_return", "ct_return") and o.period_id:
            try:
                from app.modules.drafts.service import latest_pack

                pack = latest_pack(db, o.company_id, "vat" if o.obligation_type == "vat_return" else "ct", o.period_id)
                if pack is not None and pack.review_status in PACK_READINESS:
                    r, detail = PACK_READINESS[pack.review_status]
                    pack_id, pack_status = pack.id, pack.review_status
            except Exception:  # drafts module absent or unavailable: fall back to the stored state
                pass
        if r is None and o.obligation_type in ("licence_renewal", "ejari_renewal", "other"):
            try:
                from app.modules.compliance.service import pack_readiness

                pr = pack_readiness(db, o.company_id, o.obligation_type)
                if pr:
                    r, detail, pack_id = pr["readiness"], pr["detail"], pr.get("draft_id")
            except Exception:
                pass
        if r is None and o.readiness_fixture:
            r = detail = o.readiness_fixture
        if r is None:
            r = detail = "data_missing" if o.missing_items else "not_started"
    return {"readiness": r, "detail": detail, "label": bi(f"readiness.{detail}") if f"readiness.{detail}" in _labels() else bi(f"readiness.{r}"), "draft_pack_id": pack_id, "draft_status": pack_status}


def _labels() -> set[str]:
    from app.modules.deadlines.strings import STRINGS

    return set(STRINGS)


# --- read model -------------------------------------------------------------------------------------------------


def _name(o: Obligation) -> dict:
    return bi("type.chambers_membership") if o.subtype == "chambers_membership" else bi(f"type.{o.obligation_type}")


def serialize(db: Session, o: Obligation, *, today: date | None = None, company: Company | None = None) -> dict:
    today = today or dubai_today()
    confirmed = o.date_status == "confirmed" and o.recalc_state != "recalculation_failed" and o.due_date_used is not None
    due = o.due_date_used if confirmed else None
    n = days_left(due, today) if not o.done else None
    rd = readiness(db, o)
    chips: list[str] = []
    tax = o.obligation_type in ("vat_return", "ct_return")
    if o.done:
        chips.append("filed_outside_platform" if o.filed_state in ("filed_receipt", "owner_declared_unverified") else "upcoming")
    elif o.recalc_state == "recalculation_pending":
        chips.append("date_being_updated")
    elif not confirmed:
        chips.append("date_not_confirmed")
    elif n is not None and n < 0:
        chips.append("overdue_status_unconfirmed" if tax else "overdue")
    elif n is not None and n <= int(get_config(db, "deadlines.due_soon_days", 30) or 30):
        chips.append("due_soon")
    else:
        chips.append("upcoming")
    if not o.done and o.due_date_used:
        if o.nonworking_flag == "weekend":
            chips.append("falls_on_weekend")
        elif o.nonworking_flag == "public_holiday":
            chips.append("falls_on_public_holiday")
        elif o.nonworking_flag == "provisional_holiday":
            chips.append("date_may_change")
    notes: list[dict] = []
    if not o.is_stated and tax and o.due_date_used:
        notes += [bi("note.calculated"), bi("note.not_confirmed_fta")]
    if o.nonworking_flag in ("weekend", "public_holiday") and o.recommended_submit_by:
        notes.append(bi("note.remind_earlier", date=o.recommended_submit_by.isoformat()))
    if o.nonworking_flag == "provisional_holiday":
        notes += [bi("note.provisional_holiday"), bi("note.holiday_not_announced")]
    if not o.holiday_calendar_confirmed:
        notes.append(bi("note.holiday_calendar_not_confirmed"))
    if o.filed_state == "owner_declared_unverified":
        notes.append(bi("note.owner_declared"))
    if o.deadline_source == "OWNER_ENTERED":
        notes.append(bi("note.owner_entered"))
    if tax and not o.done and n is not None and n < 0:
        notes.append(bi("note.upload_receipt"))
    if o.recalc_state == "recalculation_pending":
        notes.append(bi("state.pending_note"))
    lifetime = int(get_config(db, "deadlines.date_updated_chip.lifetime_days", 14) or 14)
    date_updated = None
    if o.date_changed_at and o.old_date and (utcnow() - o.date_changed_at).days <= lifetime:
        date_updated = {"old_date": o.old_date.isoformat(), "new_date": o.due_date_used.isoformat() if o.due_date_used else None, "change_time": o.date_changed_at.isoformat(), "source_tag": o.date_change_source}
    company = company or db.get(Company, o.company_id)
    return {
        "obligation_id": o.obligation_id,
        "company_id": o.company_id,
        "company_name": {"en": company.trade_name_en, "ar": company.trade_name_ar} if company else None,
        "licence_number": o.licence_number,
        "obligation_type": o.obligation_type,
        "subtype": o.subtype,
        "name": _name(o),
        "period_start": o.period_start.isoformat() if o.period_start else None,
        "period_end": o.period_end.isoformat() if o.period_end else None,
        "period_id": o.period_id,
        "due_date": due.isoformat() if due else None,
        "statutory_date": o.statutory_date.isoformat() if o.statutory_date else None,
        "date_used": o.due_date_used.isoformat() if o.due_date_used else None,
        "due_date_source": o.due_date_source,
        "deadline_source": o.deadline_source,
        "date_status": "confirmed" if confirmed else "not_confirmed",
        "is_stated": o.is_stated,
        "calculated": not o.is_stated,
        "rule_version": o.rule_version,
        "calendar_version": o.calendar_version,
        "calculation_time": o.calculation_time.isoformat() if o.calculation_time else None,
        "recommended_submit_by": o.recommended_submit_by.isoformat() if o.recommended_submit_by else None,
        "nonworking_flag": o.nonworking_flag,
        "readiness": rd["readiness"],
        "readiness_detail": rd["detail"],
        "readiness_label": rd["label"],
        "draft_pack_id": rd["draft_pack_id"],
        "missing_items": list(o.missing_items or []),
        "days_left": n,
        "days_left_tier": days_left_tier(db, n) if n is not None else "unknown",
        "status_chip": chips[0],
        "status_chips": chips,
        "data_basis": o.data_basis,
        "input_source": o.input_source,
        "source_chip": "stated" if o.is_stated else "computed",
        "filed_state": o.filed_state,
        "done": o.done,
        "recalc_state": o.recalc_state,
        "last_confirmed_date": o.last_confirmed_date.isoformat() if o.last_confirmed_date else None,
        "last_confirmed_at": o.last_confirmed_at.isoformat() if o.last_confirmed_at else None,
        "provisional_date": o.provisional_date.isoformat() if o.provisional_date else None,
        "date_updated": date_updated,
        "notes": notes,
        "moved_to_next_working_day_chip": False,
        "updated_at": o.updated_at.isoformat(),
        "is_demo": o.is_demo,
    }


def _sort_key(row: dict) -> tuple:
    n = row["days_left"]
    overdue = n is not None and n < 0
    company = (row.get("company_name") or {}).get("en", "")
    return (0 if overdue else 1, 0 if row["due_date"] else 1, row["due_date"] or "9999-12-31", company, row["obligation_type"])


def obligations_for(db: Session, company_id: str, *, today: date | None = None, refresh: bool = True, include_done: bool = True, include_superseded_done: bool = False) -> list[dict]:
    """SC4 contract rows for one company (all functions; callers filter by role). Soonest first, overdue pinned top."""
    if refresh:
        refresh_company(db, company_id, today=today)
    company = db.get(Company, company_id)
    stmt = select(Obligation).where(Obligation.company_id == company_id)
    rows = []
    for o in db.scalars(stmt):
        if o.superseded and not (include_superseded_done and o.done):
            continue
        if o.done and not include_done:
            continue
        rows.append(serialize(db, o, today=today, company=company))
    rows.sort(key=_sort_key)
    return rows


def next_deadlines(db: Session, company_ids: list[str], limit: int = 5, *, today: date | None = None) -> list[dict]:
    rows: list[dict] = []
    for cid in company_ids:
        rows += [r for r in obligations_for(db, cid, today=today, include_done=False)]
    rows.sort(key=_sort_key)
    return rows[:limit]


def get_obligation(db: Session, company_id: str, obligation_id: str) -> Obligation:
    o = db.get(Obligation, obligation_id)
    if o is None or o.company_id != company_id:
        raise NotFound("deadline not found", reason_code="NOT_FOUND")
    return o


def obligation_detail(db: Session, o: Obligation) -> dict:
    row = serialize(db, o)
    rule = rule_row(db, "vat.deadline_offset_days" if o.obligation_type == "vat_return" else "ct.deadline_offset_months", o.period_end) if o.obligation_type in ("vat_return", "ct_return") else None
    roll = rule_row(db, f"nonworking_day_treatment.{o.authority}.{o.obligation_type}", o.due_date_used)
    row["history"] = o.history or []
    row["how_worked_out"] = {
        "rule": rule_dict(rule) if rule else None,
        "working_day_treatment": {"value": roll.value if roll else "no_roll", "confirmation_status": roll.confirmation_status if roll else "unconfirmed, source: none", "instrument": roll.legal_instrument if roll else None},
        "period": {"start": row["period_start"], "end": row["period_end"]},
        "source": o.deadline_source,
        "statutory_label": bi("note.statutory") if o.obligation_type in ("vat_return", "ct_return") else bi("note.confirm_with_det"),
        "wording": bi("note.as_calculated") if not o.is_stated and o.obligation_type in ("vat_return", "ct_return") else None,
        "nonworking_note": bi("note.nonworking", date=o.due_date_used.isoformat()) if o.nonworking_flag in ("weekend", "public_holiday") and o.due_date_used else None,
    }
    row["filed_evidence"] = [{"source": f.source, "filing_reference": f.filing_reference, "filed_date": f.filed_date.isoformat() if f.filed_date else None, "recorded_by_role": f.recorded_by_role, "recorded_at": f.recorded_at.isoformat(), "is_demo": f.is_demo} for f in db.scalars(select(FiledEvidence).where(FiledEvidence.company_id == o.company_id, FiledEvidence.obligation_key == o.obligation_key))]
    return row


def etag_for(rows: list[dict]) -> str:
    return '"' + hashlib.sha256(json.dumps(rows, sort_keys=True, default=str).encode()).hexdigest()[:32] + '"'


# --- role filtering (delegates see only assigned functions) -----------------------------------------------------


def function_map(db: Session) -> dict:
    return get_config(db, "deadlines.function_map", DEFAULT_FUNCTION_MAP) or DEFAULT_FUNCTION_MAP


def role_functions(principal, company_id: str) -> tuple[str, list[str]]:
    roles = principal.roles_for(company_id)
    names = [r.role for r in roles]
    if any(n in OWNER_LEVEL for n in names):
        return ("remote_owner" if "remote_owner" in names and "owner" not in names else "owner"), ["all"]
    funcs: list[str] = []
    for r in roles:
        funcs += list(r.functions or [])
    return (names[0] if names else "none"), funcs


def visible_types(db: Session, principal, company_id: str) -> set[str]:
    role, funcs = role_functions(principal, company_id)
    if role in OWNER_LEVEL:
        return set(DEFAULT_FUNCTION_MAP)
    fm = function_map(db)
    return {t for t, needed in fm.items() if set(needed) & set(funcs)}


def filter_for_principal(db: Session, principal, company_id: str, rows: list[dict]) -> tuple[list[dict], int]:
    allowed = visible_types(db, principal, company_id)
    visible = [r for r in rows if r["obligation_type"] in allowed]
    return visible, len(rows) - len(visible)


def company_view(db: Session, principal, company_id: str, *, include_done: bool = True, lang: str = "en") -> dict:
    rows = obligations_for(db, company_id, include_done=include_done)
    visible, withheld = filter_for_principal(db, principal, company_id, rows)
    role, funcs = role_functions(principal, company_id)
    has_tax_inputs = any(r["obligation_type"] in ("vat_return", "ct_return") for r in rows)
    pending = any(r["recalc_state"] == "recalculation_pending" for r in rows)
    can_edit_tax = role in ("owner", "remote_owner") or bool(set(funcs) & {"tax_preparation", "all"})
    empty = None
    if not has_tax_inputs:
        if role in OWNER_LEVEL:
            empty = {"title": bi("state.empty_title"), "body": bi("state.empty_body"), "q395": bi("state.empty_owner"), "fields": ["tax_period", "vat_frequency", "trn"], "field_label": bi("note.owner_entered")}
        else:
            empty = {"title": bi("state.empty_title"), "body": bi("state.empty_delegate"), "fields": ["tax_period", "vat_frequency", "trn"] if can_edit_tax else [], "notify_owner": not can_edit_tax}
    return {
        "company_id": company_id,
        "items": visible,
        "withheld_count": withheld,
        "withheld_note": bi("state.withheld") if withheld else None,
        "empty_state": empty,
        "pending": bi("state.pending") if pending else None,
        "rules_version": rules_version_label(db),
        "calendar_versions": all_calendar_versions(db),
        "moved_chip_enabled": False,
        "role": role,
    }


def portfolio_rows(db: Session, principal, *, company_filter: str | None = None, include_done: bool = False) -> dict:
    """/api/me/obligations: every company the caller may see deadlines for, flat list sorted by due date."""
    from app.modules.access.service import permissions_for

    out: list[dict] = []
    withheld_total = 0
    companies = []
    for cid in principal.company_ids():
        if company_filter and cid != company_filter:
            continue
        if "deadlines.view" not in permissions_for(db, principal, cid):
            continue
        rows = obligations_for(db, cid, include_done=include_done)
        visible, withheld = filter_for_principal(db, principal, cid, rows)
        withheld_total += withheld
        out += visible
        co = db.get(Company, cid)
        companies.append({"company_id": cid, "trade_name_en": co.trade_name_en if co else cid, "trade_name_ar": co.trade_name_ar if co else cid, "withheld_count": withheld})
    out.sort(key=_sort_key)
    return {"items": out, "companies": companies, "withheld_count": withheld_total, "withheld_note": bi("state.withheld") if withheld_total else None}


# --- filed evidence and authority dates ---------------------------------------------------------------------------


def record_filed_evidence(db: Session, principal, company_id: str, obligation_id: str, payload: dict) -> dict:
    o = get_obligation(db, company_id, obligation_id)
    src = payload.get("source")
    if src not in ("receipt", "owner_declaration"):
        raise ValidationFailed("filed evidence is a receipt (reference and filed date) or an owner declaration; FTA status arrives in Phase 1C", reason_code="FILED_SOURCE_INVALID")
    if src == "receipt" and (not payload.get("filing_reference") or not payload.get("filed_date")):
        raise ValidationFailed("a receipt needs the filing reference and the filed date", reason_code="RECEIPT_FIELDS_REQUIRED")
    if src == "owner_declaration" and not any(r.role in OWNER_LEVEL for r in principal.roles_for(company_id)):
        raise Forbidden("only the owner can declare a return filed", reason_code="OWNER_ONLY")
    ev = FiledEvidence(company_id=company_id, obligation_key=o.obligation_key, source=src, filing_reference=payload.get("filing_reference"), filed_date=_as_date(payload.get("filed_date")), recorded_by_key=principal.actor_key, recorded_by_role=principal.primary_role())
    db.add(ev)
    db.flush()
    record_event(db, event_type="FILED_EVIDENCE_RECORDED", category="data_access", actor_key=principal.actor_key, actor_role=principal.primary_role(), company_id=company_id, subject_type="obligation", subject_id=o.obligation_id, details={"source": src, "k7k8_measurable": src == "receipt"})
    refresh_company(db, company_id, force=True)
    _reminders_hook("cancel_for_obligation", db, company_id, o.obligation_key, "filed_evidence_recorded")
    return serialize(db, o)


def record_authority_date(db: Session, principal, company_id: str, obligation_id: str, payload: dict) -> dict:
    o = get_obligation(db, company_id, obligation_id)
    kind = payload.get("kind", "FTA_NOTICE")
    if kind not in ("FTA_NOTICE", "FTA_PORTAL_STATUS", "fta_extension"):
        raise ValidationFailed("kind must be FTA_NOTICE, FTA_PORTAL_STATUS or fta_extension", reason_code="AUTHORITY_KIND_INVALID")
    if not payload.get("evidence_ref"):
        raise ValidationFailed("an authority date needs held evidence (document or recorded reference)", reason_code="EVIDENCE_REQUIRED")
    if kind == "fta_extension" and not payload.get("instrument_reference"):
        raise ValidationFailed("an authority extension cites its instrument", reason_code="INSTRUMENT_REQUIRED")
    db.add(AuthorityDate(company_id=company_id, obligation_key=o.obligation_key, kind=kind, stated_date=_as_date(payload.get("stated_date")), instrument_reference=payload.get("instrument_reference"), evidence_ref=payload["evidence_ref"], entered_by_key=principal.actor_key, entered_by_role=principal.primary_role(), label="authority extension" if kind == "fta_extension" else None))
    db.flush()
    record_event(db, event_type="AUTHORITY_DATE_RECORDED", category="data_access", actor_key=principal.actor_key, actor_role=principal.primary_role(), company_id=company_id, subject_type="obligation", subject_id=o.obligation_id, details={"kind": kind})
    res = refresh_company(db, company_id, force=True)
    if res["changed"]:
        _reminders_hook("schedule_for_company", db, company_id)
        _reminders_hook("notice_dates_changed", db, company_id, res["changed"])
    return serialize(db, o)


def notify_owner(db: Session, principal, company_id: str, item_code: str) -> dict:
    hours = int(get_config(db, "deadlines.notify_owner.rate_limit_hours", 24) or 24)
    last = db.scalar(select(NotifyOwnerRequest).where(NotifyOwnerRequest.company_id == company_id, NotifyOwnerRequest.item_code == item_code, NotifyOwnerRequest.requested_by_key == principal.actor_key).order_by(NotifyOwnerRequest.requested_at.desc()).limit(1))
    if last is not None and utcnow() - last.requested_at < timedelta(hours=hours):
        raise Conflict("the owner was already notified about this item in the last 24 hours", reason_code="NOTIFY_RATE_LIMITED", details={"next_allowed_at": (last.requested_at + timedelta(hours=hours)).isoformat()})
    db.add(NotifyOwnerRequest(company_id=company_id, item_code=item_code, requested_by_key=principal.actor_key))
    record_event(db, event_type="NOTIFY_OWNER_REQUESTED", category="reminder", actor_key=principal.actor_key, actor_role=principal.primary_role(), company_id=company_id, details={"item_code": item_code})
    db.flush()
    return {"sent": True, "item_code": item_code}


def due_date_for(db: Session, company_id: str, tax_type: str, period_end: date) -> dict | None:
    """Hook used by the tax module: the date used for a tax period (authority date > rule-derived)."""
    t = "vat_return" if tax_type == "vat" else "ct_return"
    key_prefix = f"{t}:"
    o = db.scalar(select(Obligation).where(Obligation.company_id == company_id, Obligation.obligation_type == t, Obligation.period_end == period_end, Obligation.obligation_key.like(key_prefix + "%")))
    if o is not None and o.due_date_used:
        return {"date": o.due_date_used, "source": "authority" if o.is_stated else "computed"}
    d, _ = _rule_date(db, {"type": t, "period_end": period_end})
    return {"date": d, "source": "computed"} if d else None


# --- recalculation batch ----------------------------------------------------------------------------------------


def _reminders_hook(fn: str, *args: Any) -> Any:
    try:
        from app.modules.reminders import service as rem

        return getattr(rem, fn)(*args)
    except ImportError:  # pragma: no cover
        return None


def _priority(db: Session, company_ids: list[str], today: date) -> list[str]:
    window = int(get_config(db, "deadlines.batch.priority_window_days", 30) or 30)

    def nearest(cid: str) -> int:
        ds = [o.due_date_used for o in db.scalars(select(Obligation).where(Obligation.company_id == cid, Obligation.done.is_(False), Obligation.superseded.is_(False))) if o.due_date_used and o.due_date_used >= today]
        return min(((d - today).days for d in ds), default=10**6)

    scored = sorted(company_ids, key=lambda c: (0 if nearest(c) <= window else 1, nearest(c), c))
    return scored


def run_recalculation_batch(db: Session, *, reason: str, company_ids: list[str] | None = None, fail_companies: set[str] | None = None, stop_after: int | None = None, today: date | None = None) -> dict:
    """Create a batch (priority: due within 30 days first, then nearest, then rest) and process it."""
    today = today or dubai_today()
    ids = company_ids or [c for c in db.scalars(select(Company.id))]
    cal = all_calendar_versions(db)
    order = _priority(db, ids, today)
    batch = RecalcBatch(calendar_version=cal, reason=reason, company_order=order)
    db.add(batch)
    db.flush()
    for cid in order:
        db.add(RecalcCheckpoint(batch_id=batch.batch_id, company_id=cid, calendar_version=cal))
        for o in db.scalars(select(Obligation).where(Obligation.company_id == cid, Obligation.done.is_(False), Obligation.superseded.is_(False))):
            o.recalc_state = "recalculation_pending"
    db.flush()
    record_event(db, event_type="RECALC_BATCH_STARTED", category="system", subject_type="recalc_batch", subject_id=batch.batch_id, details={"reason": reason, "companies": len(order), "calendar_version": cal})
    return resume_batch(db, batch.batch_id, fail_companies=fail_companies, stop_after=stop_after, today=today)


def resume_batch(db: Session, batch_id: str, *, fail_companies: set[str] | None = None, stop_after: int | None = None, today: date | None = None) -> dict:
    """Resume at the first unfinished company; finished companies are never re-applied; each company is atomic."""
    batch = db.get(RecalcBatch, batch_id)
    if batch is None:
        raise NotFound("batch not found", reason_code="NOT_FOUND")
    retries = int(get_config(db, "deadlines.batch.retries", 3) or 3)
    backoff = list(get_config(db, "deadlines.batch.backoff_minutes", [1, 4, 16]) or [1, 4, 16])
    processed, done, failed = 0, [], []
    order = {cid: i for i, cid in enumerate(batch.company_order or [])}
    cps = sorted(db.scalars(select(RecalcCheckpoint).where(RecalcCheckpoint.batch_id == batch_id)), key=lambda c: order.get(c.company_id, 10**6))
    for cp in cps:
        if cp.state in ("done", "failed"):
            continue
        if stop_after is not None and processed >= stop_after:
            return batch_status(db, batch_id)  # simulated crash / window exceeded: the rest stays pending
        processed += 1
        ok = False
        while cp.attempts < retries and not ok:
            cp.attempts += 1
            sp = db.begin_nested()
            try:
                if fail_companies and cp.company_id in fail_companies:
                    raise RuntimeError("rule data unavailable")
                _reminders_hook("cancel_unsent_for_company", db, cp.company_id, "deadline_superseded")  # 1 cancel old reminders
                res = refresh_company(db, cp.company_id, today=today, force=True)  # 2 write new deadlines
                _reminders_hook("schedule_for_company", db, cp.company_id)  # 3 rebuild reminder sets
                if res["changed"]:
                    _reminders_hook("notice_dates_changed", db, cp.company_id, res["changed"])  # 4 one consolidated notice
                sp.commit()
                ok = True
            except Exception as exc:  # noqa: BLE001 - per-company atomic: roll back the savepoint only
                sp.rollback()
                cp.last_error = type(exc).__name__
                cp.next_attempt_at = utcnow() + timedelta(minutes=int(backoff[min(cp.attempts - 1, len(backoff) - 1)]))
        if ok:
            cp.state, cp.finished_at = "done", utcnow()
            done.append(cp.company_id)
        else:
            cp.state, cp.failed_at = "failed", utcnow()
            failed.append(cp.company_id)
            for o in db.scalars(select(Obligation).where(Obligation.company_id == cp.company_id, Obligation.done.is_(False), Obligation.superseded.is_(False))):
                o.recalc_state = "recalculation_failed"
            record_event(db, event_type="RECALC_FAILED", category="system", outcome="failure", reason_code="RECALCULATION_FAILED", company_id=cp.company_id, subject_type="recalc_batch", subject_id=batch_id, details={"attempts": cp.attempts, "alert": "operator"})
        db.flush()
    remaining = [c for c in db.scalars(select(RecalcCheckpoint).where(RecalcCheckpoint.batch_id == batch_id, RecalcCheckpoint.state == "pending"))]
    if not remaining:
        any_failed = db.scalar(select(RecalcCheckpoint).where(RecalcCheckpoint.batch_id == batch_id, RecalcCheckpoint.state == "failed").limit(1)) is not None
        batch.status = "finished_with_failures" if any_failed else "finished"
        batch.finished_at = utcnow()
        record_event(db, event_type="RECALC_BATCH_FINISHED", category="system", subject_type="recalc_batch", subject_id=batch_id, details={"status": batch.status})
    db.flush()
    return batch_status(db, batch_id)


def escalate_failed_recalculations(db: Session, now: datetime | None = None) -> int:
    """After 24 h a failed company recalculation goes to the engine on-call owner and the compliance reviewer queue."""
    now = now or utcnow()
    hours = int(get_config(db, "deadlines.batch.escalation_after_hours", 24) or 24)
    n = 0
    for cp in db.scalars(select(RecalcCheckpoint).where(RecalcCheckpoint.state == "failed", RecalcCheckpoint.escalated.is_(False))):
        if cp.failed_at and now - cp.failed_at >= timedelta(hours=hours):
            cp.escalated = True
            record_event(db, event_type="RECALC_ESCALATED", category="escalation", reason_code="RECALCULATION_FAILED", company_id=cp.company_id, subject_type="recalc_batch", subject_id=cp.batch_id, details={"queues": ["engine_on_call_owner", "compliance_reviewer"]})
            n += 1
    db.flush()
    return n


def batch_status(db: Session, batch_id: str) -> dict:
    batch = db.get(RecalcBatch, batch_id)
    cps = list(db.scalars(select(RecalcCheckpoint).where(RecalcCheckpoint.batch_id == batch_id)))
    return {"batch_id": batch_id, "status": batch.status if batch else None, "order": batch.company_order if batch else [], "calendar_version": batch.calendar_version if batch else None,
            "done": [c.company_id for c in cps if c.state == "done"], "failed": [c.company_id for c in cps if c.state == "failed"], "pending": [c.company_id for c in cps if c.state == "pending"],
            "attempts": {c.company_id: c.attempts for c in cps}}


# --- DET aggregates (counts by type and period; no company rows) ----------------------------------------------


def aggregates(db: Session) -> dict:
    counts: dict[str, dict[str, int]] = {}
    recalc: dict[str, int] = {}
    for o in db.scalars(select(Obligation).where(Obligation.superseded.is_(False))):
        period = o.due_date_used.strftime("%Y-%m") if o.due_date_used else "not_confirmed"
        counts.setdefault(o.obligation_type, {}).setdefault(period, 0)
        counts[o.obligation_type][period] += 1
        recalc[o.recalc_state] = recalc.get(o.recalc_state, 0) + 1
    n = int(get_config(db, "cohorts.suppression_n", 10) or 10)
    suppressed = {t: {p: (c if c >= n else None) for p, c in per.items()} for t, per in counts.items()}
    return {"counts_by_type_and_period": suppressed, "recalc_states": recalc, "min_group_size": n, "note": "Cells below the minimum group size are suppressed ('Fewer than 10')."}


def company_owner_names(db: Session, company_id: str) -> list[str]:
    rows = db.scalars(select(CompanyRole).where(CompanyRole.company_id == company_id, CompanyRole.role.in_(OWNER_LEVEL), CompanyRole.status == "active"))
    return [r.identity_uuid for r in rows if r.identity_uuid]
