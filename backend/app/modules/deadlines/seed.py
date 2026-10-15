"""Seeds for the Rule and Calendar Reference (E3-S2): rule rows, per-jurisdiction holiday calendars (reusing the
escalation module's uae_working_calendar data), configuration, and demo fixtures for the four demo companies."""

from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.time import dubai_today
from app.demo import CO_ALNOOR, CO_GULFTECH, CO_SAFWA
from app.modules.config.service import ensure_config, ensure_rule
from app.modules.deadlines.models import AuthorityDate, CalendarEntry, CalendarVersion, DeadlineRule, FiledEvidence, Obligation, RuleChange
from app.modules.deadlines.service import DEFAULT_AUTHORITY_CALENDAR, DEFAULT_FUNCTION_MAP

ORDER = 40

VAT_INSTR = "Federal Decree-Law No. 8 of 2017 on Value Added Tax and its Executive Regulation (Cabinet Decision No. 52 of 2017); Federal Decree-Law No. 28 of 2022 on Tax Procedures"
CT_INSTR = "Federal Decree-Law No. 47 of 2022 on the Taxation of Corporations and Businesses (financial years starting on or after 1 June 2023)"
SBR_INSTR = "Ministerial Decision No. 73 of 2023 on Small Business Relief, as extended by Ministerial Decision No. 131 of 2026"
AUDIT_INSTR = "Ministerial Decision No. 84 of 2025 on audited financial statements (replaced No. 82 of 2023 for financial years from 1 January 2025)"
EINV_INSTR = "Ministerial Decisions No. 243 and No. 244 of 2025 on electronic invoicing"
WEEK_INSTR = "UAE federal working week (Saturday-Sunday weekend, short Friday) [READ]; confirm FTA and DET pattern"
FED = "UAE Cabinet / Federal Authority for Government Human Resources annual announcement"
DXB = "Dubai Government Human Resources Department circular"

RULES: list[dict] = [
    {"key": "vat.deadline_offset_days", "value": 28, "legal_instrument": VAT_INSTR, "source_type": "statutory", "confirmation_status": "confirmed", "confirmed_by": "Pilot tax specialist (rule owner)", "label": "period end + 28 calendar days"},
    {"key": "ct.deadline_offset_months", "value": 9, "legal_instrument": CT_INSTR, "source_type": "statutory", "confirmation_status": "confirmed", "confirmed_by": "Pilot tax specialist (rule owner)", "label": "period end + 9 months"},
    {"key": "ct.month_end_rule", "value": "last-day", "legal_instrument": CT_INSTR, "source_type": "internal estimate", "label": "assumption on the last-day reading (changeable by value only)"},
    {"key": "nonworking_day_treatment.FTA.vat_return", "value": "no_roll", "legal_instrument": VAT_INSTR, "source_type": "internal estimate", "display_status": "internal recommendation", "label": "unconfirmed, source: none"},
    {"key": "nonworking_day_treatment.FTA.ct_return", "value": "no_roll", "legal_instrument": CT_INSTR, "source_type": "internal estimate", "display_status": "internal recommendation", "label": "unconfirmed, source: none"},
    {"key": "nonworking_day_treatment.DET.licence_renewal", "value": "no_roll", "legal_instrument": "DET licence renewal procedure", "source_type": "internal estimate", "display_status": "internal recommendation", "label": "unconfirmed, source: none"},
    {"key": "nonworking_day_treatment.EJARI.ejari_renewal", "value": "no_roll", "legal_instrument": "Ejari rules of Dubai Land Department / RERA", "source_type": "internal estimate", "display_status": "internal recommendation", "label": "unconfirmed, source: none"},
    {"key": "nonworking_day_treatment.CHAMBERS.other", "value": "no_roll", "legal_instrument": "Dubai Chambers membership rules", "source_type": "internal estimate", "display_status": "internal recommendation", "label": "unconfirmed, source: none"},
    {"key": "working_week.UAE-FEDERAL", "value": {"weekend": [5, 6], "short_friday": True}, "legal_instrument": WEEK_INSTR, "source_type": "internal estimate", "label": "[READ] confirm"},
    {"key": "working_week.DUBAI-GOV", "value": {"weekend": [5, 6], "short_friday": True}, "legal_instrument": WEEK_INSTR, "source_type": "internal estimate", "label": "[READ] confirm with DET"},
    {"key": "working_week.FTA", "value": {"weekend": [5, 6], "short_friday": True}, "legal_instrument": WEEK_INSTR, "source_type": "internal estimate", "label": "[READ] confirm with the FTA"},
    {"key": "working_week.DET", "value": {"weekend": [5, 6], "short_friday": True}, "legal_instrument": WEEK_INSTR, "source_type": "internal estimate", "label": "[READ] confirm with DET"},
    {"key": "vat.rate_percent", "value": 5, "legal_instrument": VAT_INSTR, "source_type": "statutory", "confirmation_status": "confirmed", "confirmed_by": "Pilot tax specialist (rule owner)"},
    {"key": "ct.rate", "value": {"rate_percent": 9, "threshold_aed": 375000}, "legal_instrument": CT_INSTR, "source_type": "statutory", "confirmation_status": "confirmed", "confirmed_by": "Pilot tax specialist (rule owner)"},
    {"key": "sbr.threshold_aed", "value": 3000000, "legal_instrument": SBR_INSTR, "source_type": "statutory", "applicability_basis": "period_end_date"},
    {"key": "sbr.period_end_cutoff", "value": "2029-12-31", "legal_instrument": SBR_INSTR, "source_type": "statutory", "applicability_basis": "event_date", "label": "periods ending on or before 31 December 2029 (Q311); never assume a further extension"},
    {"key": "audit.revenue_threshold_aed", "value": 50000000, "legal_instrument": AUDIT_INSTR, "source_type": "statutory"},
    {"key": "audit.near_threshold_band_percent", "value": 10, "legal_instrument": "team assumption, in configuration", "source_type": "internal estimate"},
    {"key": "einvoicing.dates", "value": ["2027-01-01", "2027-07-01"], "legal_instrument": EINV_INSTR, "source_type": "statutory", "applicability_basis": "event_date"},
    {"key": "trn.length", "value": 15, "legal_instrument": "FTA TRN format (format check only)", "source_type": "internal estimate"},
    {"key": "ct.period_max_months", "value": 18, "legal_instrument": CT_INSTR, "source_type": "statutory"},
    {"key": "vat.period_max_length", "value": {"monthly": 1, "quarterly": 3, "annual": 12}, "legal_instrument": VAT_INSTR, "source_type": "internal estimate"},
    {"key": "filing_frequency", "value": ["monthly", "quarterly", "annual"], "legal_instrument": VAT_INSTR, "source_type": "internal estimate"},
    {"key": "recommended_submit_by.offset", "value": {"working_days": 0, "default": "last working day on or before the statutory date"}, "legal_instrument": "internal recommendation (not a legal date)", "source_type": "internal estimate", "display_status": "internal recommendation"},
]

RULE_VERSION = "2026.10"


def seed(db: Session) -> None:
    today = date.today()
    for r in RULES:
        if db.scalar(select(DeadlineRule).where(DeadlineRule.key == r["key"], DeadlineRule.version == RULE_VERSION)) is not None:
            continue
        row = DeadlineRule(
            key=r["key"], value=r["value"], legal_instrument=r["legal_instrument"], effective_from=date(2023, 6, 1), effective_to=None, version=RULE_VERSION,
            applicability_basis=r.get("applicability_basis", "period_end_date"), entered_by="seed: rule reference maintainer", entered_date=today, status="active",
            confirmation_status=r.get("confirmation_status", "unconfirmed, source: none"), confirmed_by=r.get("confirmed_by"), source_type=r.get("source_type", "statutory"),
            display_status=r.get("display_status", "statutory date"), label=r.get("label"), last_checked=today,
        )
        db.add(row)
        db.add(RuleChange(key=row.key, version=row.version, changed_by="seed: rule reference maintainer", old_value=None, new_value=row.value, source=row.legal_instrument, confirmed_by=row.confirmed_by, action="activated"))
    _seed_calendars(db, today)
    _seed_config(db)
    for rid, title, instr, status, params in (
        ("deadline-vat-v1", "VAT return due date: period end + 28 calendar days (no roll)", VAT_INSTR, "confirmed", {"days_after_period_end": 28, "rule_key": "vat.deadline_offset_days"}),
        ("deadline-ct-v1", "Corporate tax return due date: period end + 9 months, month-end rule 'last-day'", CT_INSTR, "provisional", {"months_after_period_end": 9, "month_end_rule": "last-day"}),
        ("deadline-roll-v1", "Non-working-day treatment per authority and obligation: no roll", "unconfirmed, source: none", "to_be_confirmed", {"default": "no_roll"}),
        ("licence-renewal-det-v1", "Licence renewal date: DET expiry date as given (never recomputed)", "DET licence renewal procedure", "confirmed", {}),
        ("ejari-renewal-v1", "Ejari validity: expiry as received from DET/Ejari", "Ejari rules of Dubai Land Department / RERA", "confirmed", {}),
        ("chambers-membership-v1", "Dubai Chambers membership for renewal", "Dubai Chambers membership rules", "confirmed", {}),
    ):
        ensure_rule(db, rid, title, instrument=instr, status=status, owner_role="Rule reference maintainer (E3-S2)", parameters=params, effective_from=date(2023, 6, 1))
    db.flush()


def _seed_calendars(db: Session, today: date) -> None:
    try:  # reuse the escalation module's versioned uae_working_calendar reference data
        from app.modules.escalation.seed import HOLIDAYS
    except ImportError:  # pragma: no cover
        HOLIDAYS = {}
    for jurisdiction, src in (("UAE-FEDERAL", FED), ("DUBAI-GOV", DXB)):
        for year, rows in HOLIDAYS.items():
            if db.scalar(select(CalendarVersion).where(CalendarVersion.jurisdiction == jurisdiction, CalendarVersion.year == year)) is not None:
                continue
            version = f"{year}.1"
            db.add(CalendarVersion(jurisdiction=jurisdiction, year=year, version=version, source_reference=src, checked_at=today, loaded_by="seed: calendar maintainer (DET pilot manager's compliance configuration owner)", approved_by="seed: second approver"))
            for d, en, ar, status in rows:
                dd = date.fromisoformat(d)
                db.add(CalendarEntry(calendar_id=jurisdiction, jurisdiction=jurisdiction, name_en=en, name_ar=ar, start_date=dd, end_date=dd, status=status, source_reference=src, publication_date=date(year - 1, 12, 15),
                                     confirmation_date=date(year - 1, 12, 15) if status == "confirmed" else None, entered_by="seed: calendar maintainer", approved_by="seed: second approver", approval_state="approved", loaded_by="manual reviewed file import", version=version))
    db.flush()


def _seed_config(db: Session) -> None:
    items = [
        ("deadlines.days_left_tiers", {"attention_max": 30, "urgent_max": 7}, "provisional", "UX choice, versioned: > 30 neutral; 8-30 attention; 0-7 urgent; overdue critical", "days"),
        ("deadlines.due_soon_days", 30, "provisional", "illustrative", "days"),
        ("deadlines.function_map", DEFAULT_FUNCTION_MAP, "provisional", "delegate functions that show each obligation type", None),
        ("deadlines.calendar_for_authority", DEFAULT_AUTHORITY_CALENDAR, "to_be_confirmed", "FTA deadlines use the federal calendar; DET the Dubai calendar; FTA's own holiday calendar [OPEN]", None),
        ("deadlines.calendar.stale_check_days", 30, "provisional", "assumption", "days"),
        ("deadlines.recommended_submit_by.offset_working_days", 0, "provisional", "default = last working day on or before the statutory date", "working days"),
        ("deadlines.earlier_reminder_offset_working_days", 2, "provisional", "illustrative", "working days"),
        ("deadlines.moved_to_next_working_day.enabled", False, "to_be_confirmed", "feature flag OFF until the FTA confirms in writing", None),
        ("deadlines.batch.retries", 3, "provisional", "configurable", "count"),
        ("deadlines.batch.backoff_minutes", [1, 4, 16], "provisional", "configurable", "minutes"),
        ("deadlines.batch.escalation_after_hours", 24, "provisional", "default", "hours"),
        ("deadlines.batch.held_reminder_send_within_hours", 24, "provisional", "configurable", "hours"),
        ("deadlines.batch.priority_window_days", 30, "provisional", "deadline within 30 days first, then nearest, then rest", "days"),
        ("deadlines.recalc.hold_limit_hours", 2, "provisional", "illustrative", "hours"),
        ("deadlines.notify_owner.rate_limit_hours", 24, "provisional", "illustrative", "hours"),
        ("deadlines.date_updated_chip.lifetime_days", 14, "confirmed", "settled: 14 days or until the deadline is opened", "days"),
        ("deadlines.hijri_display.enabled", False, "provisional", "Hijri display off by default (E1-S5)", None),
        ("deadlines.obligations.cache_seconds", 60, "confirmed", "ETag cache <= 60 s (Q357)", "seconds"),
        ("deadlines.perf.full_recalc", {"licences": 10000, "minutes": 15}, "provisional", "configurable; 100,000 = about 150 min", None),
        ("deadlines.perf.single_company_recalc_p95_seconds", 2, "provisional", "configurable", "seconds"),
        ("deadlines.dataset", {"launch": 100000, "pilot": 5000}, "provisional", "default", "licences"),
        ("deadlines.accessibility_standard", "WCAG 2.1 AA", "to_be_confirmed", "DET to confirm", None),
        ("deadlines.numeral_system_default", "western", "provisional", "configurable", None),
        ("deadlines.rule_version_label", "Rules version {version} – checked {date}", "provisional", "configurable", None),
    ]
    for key, value, status, label, unit in items:
        ensure_config(db, key, value, status=status, label=label, unit=unit, owner="Tech Lead (E3-S2)")


def seed_demo(db: Session) -> None:
    today = dubai_today()
    if db.scalar(select(Obligation).where(Obligation.is_demo.is_(True)).limit(1)) is not None:
        return
    # Al Noor VAT Q3 2026 (owner-entered period in the datalinks profile): a draft is ready for owner review (Demo data).
    db.add(Obligation(company_id=CO_ALNOOR, obligation_key="vat_return:2026-07-01_2026-09-30", obligation_type="vat_return", authority="FTA", readiness_fixture="draft_ready", is_demo=True, history=[]))
    # Safwa CT FY2025: owner declared it filed without a receipt (owner-declared, unverified; reminders stop; not in K7/K8).
    db.add(FiledEvidence(company_id=CO_SAFWA, obligation_key="ct_return:2025-01-01_2025-12-31", source="owner_declaration", recorded_by_role="owner", is_demo=True))
    # Gulf Tech: labelled placeholder FTA-extension case (Q318 demo fixture) on the previous monthly VAT period.
    first = today.replace(day=1)
    prev_end = first - timedelta(days=1)
    prev_start = prev_end.replace(day=1)
    db.add(AuthorityDate(company_id=CO_GULFTECH, obligation_key=f"vat_return:{prev_start.isoformat()}_{prev_end.isoformat()}", kind="fta_extension", stated_date=prev_end + timedelta(days=30), instrument_reference="Demo data: placeholder FTA extension notice (not a real decision)", evidence_ref="DEMO-FTA-EXT-001", entered_by_role="compliance_reviewer", label="authority extension", is_demo=True))
    db.flush()
