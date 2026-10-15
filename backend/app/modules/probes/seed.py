"""Probe seeds (E1-S9): configuration, pilot peak-window set, demo probe records for the last 24 h."""

from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import insert, select
from sqlalchemy.orm import Session

from app.core.ids import new_id
from app.core.time import utcnow
from app.modules.config.service import ensure_config, ensure_rule
from app.modules.probes import service
from app.modules.probes.models import CHECK_TYPES, LANGUAGES, ProbeRecord

ORDER = 95


def seed(db: Session) -> None:
    ensure_config(db, "probes.interval_seconds", 60, unit="seconds", owner="Tech Lead", status="provisional")
    ensure_config(db, "probes.timeout_seconds", 5, unit="seconds", owner="Tech Lead", status="provisional", label="down = timeout, 5xx or failed content marker; latency recorded, not down")
    ensure_config(db, "probes.release_window_minutes", 30, unit="minutes", owner="Tech Lead", status="provisional", label="30 consecutive minutes with zero failed probes")
    ensure_config(db, "probes.k26_target_pct", 99.9, unit="%", owner="PM", status="provisional", label="working assumption; reported, not enforced in Phase 0 (E1-S5 Q39 lists 99.5%)")
    ensure_config(db, "probes.unmeasured_threshold", 0.01, unit="share", owner="Domain Data Expert", status="provisional", label="above 1% of window minutes -> 'Incomplete measurement'")
    ensure_config(db, "probes.cohort_peak_ratio", 1.5, unit="x daily mean", owner="Domain Data Expert", status="provisional", label="estimate")
    ensure_config(db, "probes.peak_window_config_version", "peak-v1", owner="Trade Licensing Expert", status="provisional")
    ensure_config(db, "probes.retention_days", None, unit="days", owner="Tech Lead", status="to_be_confirmed", label="open (Q480)")
    ensure_config(db, "probes.alert_below_target", None, owner="Tech Lead", status="to_be_confirmed", label="undefined (Q480 open)")
    ensure_config(db, "probes.peak_window_enforcement", False, owner="PM", status="provisional", label="recorded only in Phase 0")
    ensure_rule(db, "peak-v1", "Pilot peak-window set (Q479 / E1-S5 seed variant)", instrument="E3-S2 calendar reference", status="provisional", owner_role="Trade Licensing Expert", parameters={"vat": "28 Jan/Apr/Jul/Oct +/- 3 working days", "ct": "30 Sep +/- 10 working days", "renewal": "licence-expiry density placeholder (last 5 days of month)"})
    year = utcnow().year
    for y in (year, year + 1):
        for month in (1, 4, 7, 10):
            anchor = date(y, month, 28)
            service.ensure_window(db, code="vat_q_deadline", name_en=f"VAT return due {anchor.strftime('%d %B %Y')}", name_ar=f"استحقاق إقرار ضريبة القيمة المضافة {anchor.isoformat()}", window_type="rule_based", start=service.shift_working_days(anchor, -3), end_exclusive=service.shift_working_days(anchor, 3) + timedelta(days=1), anchor=anchor, lead=3, tail=3, reason="VAT due 28th day after period end, +/- 3 working days (estimate)")
        ct = date(y, 9, 30)
        service.ensure_window(db, code="ct_30sep", name_en=f"Corporate tax return due {ct.strftime('%d %B %Y')}", name_ar=f"استحقاق إقرار ضريبة الشركات {ct.isoformat()}", window_type="rule_based", start=service.shift_working_days(ct, -10), end_exclusive=service.shift_working_days(ct, 10) + timedelta(days=1), anchor=ct, lead=10, tail=10, reason="CT due 30 September for calendar-year companies, +/- 10 working days (estimate)")
    today = utcnow().date()
    first_next = (today.replace(day=1) + timedelta(days=32)).replace(day=1)
    service.ensure_window(db, code="renewal_cohort", name_en="Licence-expiry density days (placeholder)", name_ar="أيام كثافة انتهاء الرخص (مؤقت)", window_type="cohort_derived", start=first_next - timedelta(days=5), end_exclusive=first_next, anchor=None, lead=None, tail=None, reason="placeholder: last 5 days of the month until cohort-derived windows (1.5 x daily mean) are computed", placeholder=True)
    db.flush()


def seed_demo(db: Session) -> None:
    if db.scalar(select(ProbeRecord).where(ProbeRecord.is_demo.is_(True)).limit(1)) is not None:
        return
    now = service.floor_minute(utcnow())
    outage_start = now - timedelta(hours=3)
    outage = {outage_start + timedelta(minutes=i) for i in range(7)}  # 7-minute Arabic dashboard outage
    rows = []
    for i in range(24 * 60, 0, -1):
        m = now - timedelta(minutes=i)
        local = service.local_str(m)
        for check in CHECK_TYPES:
            for lang in LANGUAGES:
                down = lang == "ar" and check == "dashboard" and m in outage
                rows.append({"probe_id": new_id("prb"), "minute_ts": m, "minute_local": local, "check_type": check, "result": "down" if down else "up", "language": lang, "latency_ms": 180 + (i * 7) % 90, "reason": "http_5xx" if down else None, "runner": "uae-runner-1", "is_demo": True, "created_at": m})
    db.execute(insert(ProbeRecord), rows)
    db.flush()
