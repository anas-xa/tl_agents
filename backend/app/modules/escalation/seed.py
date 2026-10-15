"""Escalation seeds (ORDER 80): config keys, rule set v1.0, matter-key rules, SLA table, UAE working calendar
2025-2027, Phase 1 corpus passages, entitlement register rows, demo cases (labelled 'Demo data')."""

from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.time import utcnow
from app.modules.config.service import ensure_config, ensure_rule
from app.modules.escalation.models import (
    CaseAccessGrant,
    CaseEvent,
    CasePause,
    CorpusPassage,
    EscalationCase,
    SpecialistEntitlement,
    WorkingCalendarHoliday,
    WorkingCalendarVersion,
    WorkItem,
)

ORDER = 80
PM = "DET pilot manager"
TL = "Tech Lead"
SPEC = "Pilot tax specialist and licensed auditor (reviewers); Product Manager drafts"


def seed(db: Session) -> None:
    _seed_config(db)
    _seed_rules(db)
    _seed_calendar(db)
    _seed_corpus(db)


def _seed_config(db: Session) -> None:
    c = ensure_config
    c(db, "trigger_rule_set.version", "1.0", owner=SPEC, status="provisional", label="placeholder v1.0; specialists revise without a code release")
    c(db, "case.readback.retries", 3, unit="count", owner=TL, status="provisional", label="configurable, for production")
    c(db, "case.readback.backoff_seconds", [5, 30, 120], unit="seconds", owner=TL, status="provisional", label="configurable, for production")
    c(db, "rule_set.load.retries", 3, unit="count", owner=TL, status="provisional", label="3 retries then alert operations (production)")
    c(db, "trigger.deadline_risk.days.vat", 14, unit="days", owner=SPEC, status="provisional", label="starting value")
    c(db, "trigger.deadline_risk.days.corporate_tax", 30, unit="days", owner=SPEC, status="provisional", label="starting value")
    c(db, "trigger.deadline_risk.days.licence", 30, unit="days", owner=SPEC, status="provisional", label="starting value")
    c(db, "trigger.audit_required.revenue_threshold_fils", 50_000_000 * 100, unit="fils", owner=SPEC, status="provisional", label="AED 50 million from rule 2; confirm instrument before quoting")
    c(db, "priority.deadline_near.days", 14, unit="days", owner=PM, status="provisional", label="filing due date within 14 days")
    c(db, "legal.lawyer_routing.enabled", False, owner="Product / Legal expert", status="to_be_confirmed", label="off until the legal service model is agreed (Legal expert item OPEN)")
    c(db, "legal.wording.enabled", False, owner="Product / Legal expert", status="to_be_confirmed", label="provisional wording marked 'to be confirmed by counsel'")
    c(db, "route_holder.legal", "none", owner="Register owner", status="to_be_confirmed", label="none | licensed_firm_partner; controls the owner-facing legal message")
    c(db, "reject.note.max_chars", 300, unit="chars", owner="UX", status="provisional", label="required only for R5")
    c(db, "escalation.turnaround.targets", {"standard": {"tax": 5, "audit": 7, "compliance": 5, "legal": None}, "deadline_near": {"tax": 2, "audit": 3, "compliance": 2, "legal": None}}, unit="working days", owner=PM, status="provisional", label="proposed by Qeonix product owner; estimates by pilot tax specialist lead and engagement manager; 'expected within N working days', never a guarantee; not shown on SC10 in Phase 1")
    c(db, "ops_alert.escalation_window_hours", 24, unit="hours", owner="Escalation operations (Qeonix)", status="to_be_confirmed", label="value not given in source; after the window the alert goes to the DET pilot manager queue")
    # E8-S2
    c(db, "escalation.tax_specialist_path.enabled", False, owner="Product", status="to_be_confirmed", label="OFF until the FTA position and specialist firm agreements are recorded (brief decision); the demo seed switches it on for the demo environment only")
    c(db, "escalation.lawyer_path.enabled", False, owner="Product", status="to_be_confirmed", label="OFF until Legal Affairs Department position and signed firm agreements are in the route-holder register")
    c(db, "sealed_notes.enabled", False, owner="Legal", status="to_be_confirmed", label="later phase; no placeholder built")
    c(db, "bulk_export.enabled", False, owner=TL, status="provisional", label="disabled by default")
    c(db, "case_access.grant_expiry_days", 90, unit="days", owner="UX", status="provisional", label="per-case access grant expiry; revocable at any time")
    c(db, "consent_wait.reminder_days", [3, 7], unit="days", owner="Product Manager", status="provisional")
    c(db, "consent_wait.ops_alert_day", 7, unit="day", owner="Product Manager", status="provisional")
    c(db, "consent_wait.close_day", 14, unit="day", owner="Product Manager", status="provisional", label="'closed - no consent'")
    c(db, "consent_wait.reopen_window", 30, unit="days", owner="Product Manager", status="provisional", label="same reference")
    c(db, "consent_wait.deadline_near_timeline", None, unit="days", owner="Product Manager", status="to_be_confirmed", label="shortened timeline for deadline-near cases; value not given")
    c(db, "retention.specialist_copies_years", 5, unit="years", owner="Auditor/legal rules + lawyer advice", status="to_be_confirmed", label="illustrative (production)")
    # E8-S3
    c(db, "coverage.threshold.tax", 0.80, unit="score", owner="Specialists (calibrated on the labelled set)", status="provisional")
    c(db, "coverage.threshold.legal", 0.85, unit="score", owner="Specialists", status="provisional", label="0.85 until calibrated; legal matters beyond simple routine refused whatever the score")
    c(db, "coverage.review_band", 0.05, unit="score", owner="Specialists", status="provisional", label="questions within ±0.05 of the threshold are reviewed by specialists")
    c(db, "coverage.threshold.version", "v1", owner="Specialists", status="provisional")
    c(db, "loading.slow_notice_after", 10, unit="seconds", owner="UX", status="provisional")
    c(db, "escalation.create.retries", 3, unit="count", owner=TL, status="provisional", label="illustrative; then ops alert")
    c(db, "escalation.create.backoff_window_hours", 24, unit="hours", owner=TL, status="provisional", label="idempotency key from question ID")
    c(db, "escalation.ops_alert_after_failures", 3, unit="count", owner=TL, status="provisional")
    c(db, "urgency.deadline_window", 5, unit="working days", owner=TL, status="provisional")
    c(db, "legal_qa.enabled", False, owner="Product", status="to_be_confirmed", label="virtual lawyer out of Phase 1")
    c(db, "partly_covered.enabled", False, owner="Product", status="to_be_confirmed", label="Phase 1B")
    c(db, "refusal_cause_display.enabled", False, owner="Product", status="to_be_confirmed", label="Phase 1B")
    c(db, "corpus.authoritative_language", "ar", owner="Trade Licensing Expert", status="confirmed", label="English = unofficial translation")
    # E8-S4
    c(db, "suppression.min_group_size", 10, unit="cases", owner="DET + data protection owner", status="provisional", label="provisional N=10; technique and default N open (Q139)")
    c(db, "refresh.schedule", "weekly", owner="Product", status="provisional")
    c(db, "k21.target", None, owner="DET", status="to_be_confirmed", label="no target line until set")
    c(db, "k22.target", None, owner="DET", status="to_be_confirmed", label="no target line until set")
    c(db, "reconciliation.legal_timestamp_threshold_minutes", 5, unit="minutes", owner=TL, status="provisional", label="differences above reported as data-quality items; never overwrite the log")
    c(db, "working_day.convention", {"weekend": ["sat", "sun"], "day_zero": "opening day", "same_day_close": 0, "granularity": "fractional, one decimal (KPI dictionary variant)", "timezone": "Asia/Dubai", "alternative": "whole days (Q138)"}, owner="Domain Data Expert", status="to_be_confirmed", label="to be confirmed which granularity the dashboard implements (Q138 whole days vs KPI dictionary fractional)")
    c(db, "calendar.id", "uae_working_calendar", owner="DET pilot operations owner", status="provisional", label="per-year load from the official announcement")
    c(db, "timezone", "Asia/Dubai", owner=TL, status="confirmed")
    c(db, "age_bands", ["0-2", "3-7", "8-14", "15+"], unit="working days", owner="UX", status="to_be_confirmed", label="values to be confirmed")


def _seed_rules(db: Session) -> None:
    ensure_rule(db, "trigger_rule_set", "Escalation trigger rule set (placeholder v1.0)", version="1.0", instrument="Qeonix trigger rule set (product rule, not a legal instrument)", status="provisional", owner_role=SPEC, effective_from=date(2026, 1, 1), parameters={
        "change_log": [{"version": "1.0", "changed_by": "Product Manager", "changed_at": "2026-01-01", "note": "placeholder drafted before Phase 1D; reviewed by pilot tax specialist and licensed auditor"}],
        "no_confidence_triggers": True,
        "rules": [
            {"id": "user_raised", "enabled": True, "module": "any", "route": "by module", "condition": "owner or authorised delegate presses 'Ask a human'"},
            {"id": "audit_required", "enabled": True, "module": "audit", "route": "licensed_auditor", "revenue_threshold_fils": 50_000_000 * 100, "condition": "owner-confirmed tax group or QFZP, revenue above threshold, or a flag input missing"},
            {"id": "sign_off_needed", "enabled": True, "module": "audit", "route": "licensed_auditor", "condition": "draft audit working file reaches the signature point"},
            {"id": "filing_blocked", "enabled": True, "module": "tax", "route": "tax_specialist", "condition": "tax calculation blocked by missing, conflicting or stale data after the reminder period; data-check conflict flags"},
            {"id": "deadline_risk", "enabled": True, "module": "compliance", "route": "det_compliance", "days": {"vat": 14, "corporate_tax": 30, "licence": 30}, "condition": "deadline within the configured days with preparation incomplete"},
            {"id": "legal_type_request", "enabled": True, "module": "legal", "route": "none", "condition": "request reads as a legal question; neutral state only, no routing"},
            {"id": "quarantine", "enabled": True, "module": "other", "route": "owner_review", "condition": "delegate rights removed; drafts they touched quarantined"},
        ],
    })
    ensure_rule(db, "matter_key_rules_v1", "Matter key rules v1 (fixed concatenation per source)", version="v1", status="provisional", owner_role=TL, effective_from=date(2026, 1, 1), parameters={
        "agent_output": ["return_type", "tax_period", "rule_id"],
        "audit_exception": ["audit_file_id", "rule_id", "period"],
        "compliance_item": ["licence_number", "requirement_code", "due_period"],
        "user_question": ["linked_item_id", "topic_code"],
        "free_text_never_hashed": True,
    })
    ensure_rule(db, "escalation_sla_v1", "Expected reply per specialist type (illustrative; not shown in Phase 1)", version="v1", status="provisional", owner_role="DET + Qeonix operations", effective_from=date(2026, 1, 1), parameters={"tax": 2, "auditor": 3, "lawyer": 2, "unit": "working days", "displayed_phase_1": False})
    ensure_rule(db, "urgency_rule_v1", "Urgency rule: user flag or named deadline within 5 working days", version="v1", status="provisional", owner_role=TL, parameters={"deadline_window_working_days": 5})


# --- uae_working_calendar ----------------------------------------------------------------------------
FED = "UAE Cabinet / Federal Authority for Government Human Resources annual announcement; Dubai Government Human Resources Department circular"
HOLIDAYS: dict[int, list[tuple[str, str, str, str]]] = {
    2025: [
        ("2025-01-01", "New Year's Day", "رأس السنة الميلادية", "confirmed"),
        ("2025-03-30", "Eid al-Fitr", "عيد الفطر", "confirmed"), ("2025-03-31", "Eid al-Fitr", "عيد الفطر", "confirmed"), ("2025-04-01", "Eid al-Fitr", "عيد الفطر", "confirmed"),
        ("2025-06-05", "Arafat Day", "يوم عرفة", "confirmed"), ("2025-06-06", "Eid al-Adha", "عيد الأضحى", "confirmed"), ("2025-06-07", "Eid al-Adha", "عيد الأضحى", "confirmed"), ("2025-06-08", "Eid al-Adha", "عيد الأضحى", "confirmed"),
        ("2025-06-26", "Islamic New Year", "رأس السنة الهجرية", "confirmed"), ("2025-09-05", "Prophet Muhammad's Birthday", "المولد النبوي الشريف", "confirmed"),
        ("2025-12-01", "Commemoration Day", "يوم الشهيد", "confirmed"), ("2025-12-02", "National Day", "اليوم الوطني", "confirmed"), ("2025-12-03", "National Day", "اليوم الوطني", "confirmed"),
    ],
    2026: [
        ("2026-01-01", "New Year's Day", "رأس السنة الميلادية", "confirmed"),
        ("2026-03-20", "Eid al-Fitr", "عيد الفطر", "provisional"), ("2026-03-21", "Eid al-Fitr", "عيد الفطر", "provisional"), ("2026-03-22", "Eid al-Fitr", "عيد الفطر", "provisional"),
        ("2026-05-26", "Arafat Day", "يوم عرفة", "provisional"), ("2026-05-27", "Eid al-Adha", "عيد الأضحى", "provisional"), ("2026-05-28", "Eid al-Adha", "عيد الأضحى", "provisional"), ("2026-05-29", "Eid al-Adha", "عيد الأضحى", "provisional"),
        ("2026-06-16", "Islamic New Year", "رأس السنة الهجرية", "provisional"), ("2026-08-25", "Prophet Muhammad's Birthday", "المولد النبوي الشريف", "provisional"),
        ("2026-12-01", "Commemoration Day", "يوم الشهيد", "confirmed"), ("2026-12-02", "National Day", "اليوم الوطني", "confirmed"), ("2026-12-03", "National Day", "اليوم الوطني", "confirmed"),
    ],
    2027: [
        ("2027-01-01", "New Year's Day", "رأس السنة الميلادية", "confirmed"),
        ("2027-03-09", "Eid al-Fitr", "عيد الفطر", "provisional"), ("2027-03-10", "Eid al-Fitr", "عيد الفطر", "provisional"), ("2027-03-11", "Eid al-Fitr", "عيد الفطر", "provisional"),
        ("2027-05-15", "Arafat Day", "يوم عرفة", "provisional"), ("2027-05-16", "Eid al-Adha", "عيد الأضحى", "provisional"), ("2027-05-17", "Eid al-Adha", "عيد الأضحى", "provisional"), ("2027-05-18", "Eid al-Adha", "عيد الأضحى", "provisional"),
        ("2027-06-06", "Islamic New Year", "رأس السنة الهجرية", "provisional"), ("2027-08-14", "Prophet Muhammad's Birthday", "المولد النبوي الشريف", "provisional"),
        ("2027-12-01", "Commemoration Day", "يوم الشهيد", "confirmed"), ("2027-12-02", "National Day", "اليوم الوطني", "confirmed"), ("2027-12-03", "National Day", "اليوم الوطني", "confirmed"),
    ],
}


def _seed_calendar(db: Session) -> None:
    for year, rows in HOLIDAYS.items():
        if db.scalar(select(WorkingCalendarVersion).where(WorkingCalendarVersion.calendar_id == "uae_working_calendar", WorkingCalendarVersion.effective_year == year, WorkingCalendarVersion.is_current.is_(True))):
            continue
        version = f"{year}.1"
        db.add(WorkingCalendarVersion(calendar_id="uae_working_calendar", effective_year=year, version=version, source_ref=FED, version_date=date(year - 1, 12, 15), updated_by="seed (DET pilot operations owner)"))
        for d, en, ar, status in rows:
            db.add(WorkingCalendarHoliday(calendar_id="uae_working_calendar", effective_year=year, version=version, holiday_date=date.fromisoformat(d), name_en=en, name_ar=ar, status=status, source_ref=FED))
    db.flush()


# --- Phase 1 corpus (short, realistic; Arabic authoritative, English unofficial; confirm instrument before quoting)
TAX = "Pilot tax specialist (corpus owner: tax)"
COMP = "Compliance content owner named by DET or Qeonix"
AUD = "Licensed auditor (corpus owner: audit profession)"
DP = "DET or Qeonix data-protection lead"
CT = ("Federal Decree-Law No. 47 of 2022 on the Taxation of Corporations and Businesses", "المرسوم بقانون اتحادي رقم 47 لسنة 2022 في شأن الضريبة على الشركات والأعمال")
VAT = ("Federal Decree-Law No. 8 of 2017 on Value Added Tax", "المرسوم بقانون اتحادي رقم 8 لسنة 2017 في شأن ضريبة القيمة المضافة")
VATER = ("Cabinet Decision No. 52 of 2017 (VAT Executive Regulation, as amended)", "قرار مجلس الوزراء رقم 52 لسنة 2017 (اللائحة التنفيذية لضريبة القيمة المضافة وتعديلاتها)")
TP = ("Federal Decree-Law No. 28 of 2022 on Tax Procedures", "المرسوم بقانون اتحادي رقم 28 لسنة 2022 في شأن الإجراءات الضريبية")
PASSAGES: list[dict] = [
    dict(passage_id="ct-47-2022-art3-rate", domain="corporate_tax", instrument=CT[0], instrument_ar=CT[1], article="Article 3", subject="corporate tax rate", rule_type="rate", value="0% up to AED 375,000; 9% above", unit="percent", condition="taxable income", taxpayer_category="all", text_ar="تُفرض ضريبة الشركات على الدخل الخاضع للضريبة بنسبة 0% على الجزء الذي لا يتجاوز 375,000 درهم، وبنسبة 9% على الجزء الذي يتجاوز ذلك.", text_en="Corporate tax is imposed on taxable income at 0% on the portion not exceeding AED 375,000 and at 9% on the portion above that amount.", keywords=["corporate tax", "rate", "9 percent", "9%", "375000", "375,000", "threshold", "taxable income", "ضريبة الشركات", "نسبة", "معدل"], owner_role=TAX, effective_from=date(2023, 6, 1), source_ref="Ministry of Finance / FTA (official text)", rules_ref="ct-rate-v1:rate_percent"),
    dict(passage_id="ct-md73-2023-sbr", domain="corporate_tax", instrument="Ministerial Decision No. 73 of 2023 on Small Business Relief", instrument_ar="القرار الوزاري رقم 73 لسنة 2023 في شأن إعفاء الأعمال الصغيرة", article="Article 2", subject="small business relief threshold", rule_type="threshold", value="AED 3,000,000", unit="AED", condition="revenue in the tax period and all previous periods", taxpayer_category="resident", text_ar="يجوز للشخص المقيم اختيار إعفاء الأعمال الصغيرة إذا لم تتجاوز إيراداته في الفترة الضريبية والفترات السابقة 3,000,000 درهم.", text_en="A resident person may elect small business relief where its revenue in the tax period and all previous tax periods does not exceed AED 3,000,000.", keywords=["small business relief", "sbr", "3 million", "3,000,000", "revenue", "relief", "elect", "إعفاء الأعمال الصغيرة", "إيرادات"], owner_role=TAX, effective_from=date(2023, 6, 1), source_ref="Ministry of Finance"),
    dict(passage_id="ct-md131-2026-sbr-extension", domain="corporate_tax", instrument="Ministerial Decision No. 131 of 2026 (Small Business Relief extension)", instrument_ar="القرار الوزاري رقم 131 لسنة 2026 (تمديد إعفاء الأعمال الصغيرة)", article="Article 1", subject="small business relief period", rule_type="condition", value="tax periods ending on or before 31 December 2029", unit=None, condition="relief election window", taxpayer_category="resident", text_ar="يمتد تطبيق إعفاء الأعمال الصغيرة ليشمل الفترات الضريبية التي تنتهي في 31 ديسمبر 2029 أو قبله، مع بقاء حد الإيرادات 3,000,000 درهم دون تغيير.", text_en="Small business relief applies to tax periods ending on or before 31 December 2029; the AED 3,000,000 revenue threshold is unchanged.", keywords=["small business relief", "extension", "2029", "until when", "period", "إعفاء الأعمال الصغيرة", "تمديد"], owner_role=TAX, effective_from=date(2026, 1, 1), source_ref="Ministry of Finance (confirm instrument)"),
    dict(passage_id="ct-47-2022-art51-registration", domain="corporate_tax", instrument=CT[0], instrument_ar=CT[1], article="Article 51", subject="corporate tax registration", rule_type="procedure", value="registration with the FTA required", unit=None, condition="taxable person", taxpayer_category="all", text_ar="يجب على كل شخص خاضع للضريبة التسجيل لأغراض ضريبة الشركات لدى الهيئة الاتحادية للضرائب والحصول على رقم تسجيل ضريبي.", text_en="Every taxable person must register for corporate tax with the Federal Tax Authority and obtain a tax registration number.", keywords=["corporate tax", "register", "registration", "trn", "tax registration number", "fta", "التسجيل", "ضريبة الشركات", "رقم تسجيل ضريبي"], owner_role=TAX, effective_from=date(2023, 6, 1), source_ref="Ministry of Finance / FTA"),
    dict(passage_id="ct-47-2022-art53-return", domain="corporate_tax", instrument=CT[0], instrument_ar=CT[1], article="Article 53", subject="corporate tax return deadline", rule_type="deadline", value="9 months after the end of the tax period", unit="months", condition="filing and payment", taxpayer_category="all", text_ar="يجب تقديم إقرار ضريبة الشركات وسداد الضريبة المستحقة خلال تسعة أشهر من نهاية الفترة الضريبية المعنية.", text_en="The corporate tax return must be filed, and the tax due paid, within nine months of the end of the relevant tax period.", keywords=["corporate tax", "return", "deadline", "file", "filing", "due", "9 months", "nine months", "payment", "إقرار", "موعد", "تسعة أشهر", "ضريبة الشركات"], owner_role=TAX, effective_from=date(2023, 6, 1), source_ref="Ministry of Finance / FTA"),
    dict(passage_id="ct-md84-2025-audited-fs", domain="corporate_tax", instrument="Ministerial Decision No. 84 of 2025 on audited financial statements (replaces 82/2023)", instrument_ar="القرار الوزاري رقم 84 لسنة 2025 في شأن البيانات المالية المدققة (يحل محل 82/2023)", article="Article 2", subject="audited financial statements requirement", rule_type="threshold", value="revenue above AED 50,000,000, or qualifying free zone person", unit="AED", condition="financial years starting on or after 1 January 2025", taxpayer_category="all", text_ar="يجب على الشخص الخاضع للضريبة الذي تتجاوز إيراداته 50,000,000 درهم، وعلى الشخص المؤهل في المنطقة الحرة، إعداد بيانات مالية مدققة للسنوات المالية التي تبدأ في 1 يناير 2025 أو بعده.", text_en="A taxable person whose revenue exceeds AED 50,000,000, and a qualifying free zone person, must prepare audited financial statements for financial years starting on or after 1 January 2025.", keywords=["audited", "audit", "financial statements", "50 million", "50,000,000", "qualifying free zone", "qfzp", "required", "بيانات مالية مدققة", "تدقيق", "50 مليون"], owner_role=TAX, effective_from=date(2025, 1, 1), source_ref="Ministry of Finance", supersedes="ct-md82-2023-audited-fs"),
    dict(passage_id="ct-md82-2023-audited-fs", domain="corporate_tax", instrument="Ministerial Decision No. 82 of 2023 on audited financial statements", instrument_ar="القرار الوزاري رقم 82 لسنة 2023 في شأن البيانات المالية المدققة", article="Article 2", subject="audited financial statements requirement", rule_type="threshold", value="revenue above AED 50,000,000, or qualifying free zone person", unit="AED", condition="financial years starting before 1 January 2025", taxpayer_category="all", text_ar="يجب على الشخص الخاضع للضريبة الذي تتجاوز إيراداته 50,000,000 درهم، وعلى الشخص المؤهل في المنطقة الحرة، إعداد بيانات مالية مدققة.", text_en="A taxable person whose revenue exceeds AED 50,000,000, and a qualifying free zone person, must prepare audited financial statements.", keywords=["audited financial statements", "50 million"], owner_role=TAX, effective_from=date(2023, 6, 1), effective_to=date(2024, 12, 31), status="superseded", source_ref="Ministry of Finance"),
    dict(passage_id="ct-47-2022-art40-tax-group", domain="corporate_tax", instrument=CT[0], instrument_ar=CT[1], article="Article 40", subject="tax group conditions", rule_type="condition", value="95% ownership, voting rights and entitlement to profits", unit="percent", condition="resident parent and subsidiaries", taxpayer_category="resident", text_ar="يجوز للشركة الأم المقيمة تكوين مجموعة ضريبية مع شركاتها التابعة إذا كانت تملك ما لا يقل عن 95% من رأس المال وحقوق التصويت والحق في الأرباح.", text_en="A resident parent company may form a tax group with its subsidiaries where it holds at least 95% of the share capital, voting rights and entitlement to profits.", keywords=["tax group", "group", "95", "95%", "subsidiary", "parent", "مجموعة ضريبية", "95%"], owner_role=TAX, effective_from=date(2023, 6, 1), source_ref="Ministry of Finance"),
    dict(passage_id="ct-47-2022-art18-qfzp", domain="corporate_tax", instrument=CT[0], instrument_ar=CT[1], article="Article 18", subject="qualifying free zone person rate", rule_type="rate", value="0% on qualifying income", unit="percent", condition="qualifying free zone person conditions met", taxpayer_category="free_zone", text_ar="يخضع الشخص المؤهل في المنطقة الحرة لضريبة الشركات بنسبة 0% على الدخل المؤهل، شريطة استيفاء الشروط المقررة.", text_en="A qualifying free zone person is subject to corporate tax at 0% on qualifying income, provided the prescribed conditions are met.", keywords=["qualifying free zone person", "free zone", "qfzp", "qualifying income", "0%", "منطقة حرة", "شخص مؤهل", "دخل مؤهل"], owner_role=TAX, effective_from=date(2023, 6, 1), source_ref="Ministry of Finance"),
    dict(passage_id="vat-8-2017-art3-rate", domain="vat", instrument=VAT[0], instrument_ar=VAT[1], article="Article 3", subject="VAT standard rate", rule_type="rate", value="5%", unit="percent", condition="taxable supplies and imports", taxpayer_category="all", text_ar="تُفرض ضريبة القيمة المضافة بالنسبة الأساسية 5% على كل توريد خاضع للضريبة واستيراد.", text_en="Value added tax is imposed at the standard rate of 5% on every taxable supply and import.", keywords=["vat", "value added tax", "rate", "standard rate", "5%", "5 percent", "ضريبة القيمة المضافة", "نسبة", "5%"], owner_role=TAX, effective_from=date(2018, 1, 1), source_ref="FTA (official text)", rules_ref="vat-rate-v1:rate_percent"),
    dict(passage_id="vat-8-2017-art13-mandatory-reg", domain="vat", instrument=VAT[0], instrument_ar=VAT[1], article="Article 13", subject="VAT mandatory registration threshold", rule_type="threshold", value="AED 375,000", unit="AED", condition="taxable supplies and imports in the previous 12 months or expected in the next 30 days", taxpayer_category="all", text_ar="يجب التسجيل لضريبة القيمة المضافة إذا تجاوزت التوريدات الخاضعة للضريبة والواردات حد التسجيل الإلزامي البالغ 375,000 درهم خلال الاثني عشر شهراً السابقة أو كان من المتوقع تجاوزه خلال الثلاثين يوماً التالية.", text_en="Registration for VAT is mandatory where taxable supplies and imports exceeded the mandatory registration threshold of AED 375,000 in the previous 12 months or are expected to exceed it in the next 30 days.", keywords=["vat", "registration", "register", "mandatory", "threshold", "375000", "375,000", "تسجيل", "حد التسجيل الإلزامي", "ضريبة القيمة المضافة"], owner_role=TAX, effective_from=date(2018, 1, 1), source_ref="FTA"),
    dict(passage_id="vat-8-2017-art17-voluntary-reg", domain="vat", instrument=VAT[0], instrument_ar=VAT[1], article="Article 17", subject="VAT voluntary registration threshold", rule_type="threshold", value="AED 187,500", unit="AED", condition="taxable supplies, imports or expenses", taxpayer_category="all", text_ar="يجوز التسجيل الاختياري لضريبة القيمة المضافة إذا تجاوزت التوريدات الخاضعة للضريبة أو المصروفات حد التسجيل الاختياري البالغ 187,500 درهم.", text_en="Voluntary VAT registration is available where taxable supplies or expenses exceed the voluntary registration threshold of AED 187,500.", keywords=["vat", "voluntary", "registration", "threshold", "187500", "187,500", "تسجيل اختياري", "حد التسجيل الاختياري"], owner_role=TAX, effective_from=date(2018, 1, 1), source_ref="FTA"),
    dict(passage_id="vat-er-52-2017-art64-return", domain="vat", instrument=VATER[0], instrument_ar=VATER[1], article="Article 64", subject="VAT return deadline", rule_type="deadline", value="28 days after the end of the tax period", unit="days", condition="filing and payment", taxpayer_category="all", text_ar="يجب تقديم الإقرار الضريبي لضريبة القيمة المضافة وسداد الضريبة المستحقة في موعد أقصاه اليوم الثامن والعشرون من الشهر التالي لنهاية الفترة الضريبية.", text_en="The VAT return must be submitted and the tax due paid no later than the 28th day following the end of the tax period.", keywords=["vat", "return", "deadline", "due", "file", "filing", "submit", "28 days", "28th", "payment", "tax period", "إقرار", "موعد", "28", "الفترة الضريبية"], owner_role=TAX, effective_from=date(2018, 1, 1), source_ref="FTA"),
    dict(passage_id="vat-8-2017-art45-zero-rate", domain="vat", instrument=VAT[0], instrument_ar=VAT[1], article="Article 45", subject="zero-rated supplies", rule_type="condition", value="0% (zero-rated)", unit="percent", condition="exports of goods and services outside the implementing states, among others", taxpayer_category="all", text_ar="تخضع لنسبة الصفر توريدات منها تصدير السلع والخدمات إلى خارج الدول المطبِّقة، وفق الشروط المقررة.", text_en="Zero-rated supplies include exports of goods and services to outside the implementing states, subject to the prescribed conditions.", keywords=["zero rated", "zero-rated", "export", "exports", "0%", "zero", "نسبة الصفر", "تصدير"], owner_role=TAX, effective_from=date(2018, 1, 1), source_ref="FTA"),
    dict(passage_id="vat-8-2017-art67-tax-invoice", domain="vat", instrument=VAT[0], instrument_ar=VAT[1], article="Article 67", subject="tax invoice issue deadline", rule_type="deadline", value="14 days from the date of supply", unit="days", condition="taxable supply", taxpayer_category="all", text_ar="يجب على الخاضع للضريبة إصدار فاتورة ضريبية خلال 14 يوماً من تاريخ التوريد.", text_en="A taxable person must issue a tax invoice within 14 days of the date of supply.", keywords=["tax invoice", "invoice", "issue", "14 days", "date of supply", "فاتورة ضريبية", "إصدار", "14 يوماً"], owner_role=TAX, effective_from=date(2018, 1, 1), source_ref="FTA"),
    dict(passage_id="tp-28-2022-art24-records", domain="tax_procedures", instrument=TP[0], instrument_ar=TP[1], article="Article 24", subject="record keeping period", rule_type="condition", value="5 years after the end of the tax period", unit="years", condition="accounting records and commercial books", taxpayer_category="all", text_ar="يجب الاحتفاظ بالسجلات المحاسبية والدفاتر التجارية لمدة خمس سنوات بعد نهاية الفترة الضريبية التي تتعلق بها.", text_en="Accounting records and commercial books must be kept for five years after the end of the tax period to which they relate.", keywords=["records", "record keeping", "keep", "retain", "books", "5 years", "five years", "how long", "سجلات", "الاحتفاظ", "خمس سنوات"], owner_role=TAX, effective_from=date(2023, 3, 1), source_ref="FTA"),
    dict(passage_id="tp-28-2022-art14-voluntary-disclosure", domain="tax_procedures", instrument=TP[0], instrument_ar=TP[1], article="Article 14", subject="voluntary disclosure", rule_type="procedure", value="voluntary disclosure form to the FTA", unit=None, condition="error or omission in a submitted return", taxpayer_category="all", text_ar="إذا تبيّن للخاضع للضريبة وجود خطأ أو إغفال في إقرار ضريبي مقدَّم، يجوز له تقديم إفصاح طوعي إلى الهيئة وفق الضوابط المقررة.", text_en="Where a taxable person discovers an error or omission in a submitted tax return, a voluntary disclosure may be submitted to the Authority under the prescribed rules.", keywords=["voluntary disclosure", "error", "mistake", "correct", "correction", "omission", "amend", "إفصاح طوعي", "خطأ", "تصحيح"], owner_role=TAX, effective_from=date(2023, 3, 1), source_ref="FTA"),
    dict(passage_id="tp-cd40-2017-penalties", domain="tax_procedures", instrument="Cabinet Decision No. 40 of 2017 on administrative penalties (as amended, current schedule)", instrument_ar="قرار مجلس الوزراء رقم 40 لسنة 2017 في شأن الغرامات الإدارية (وتعديلاته، الجدول الحالي)", article="Schedule", subject="administrative penalties", rule_type="condition", value="see the current published schedule", unit=None, condition="late registration, late filing, late payment and other violations", taxpayer_category="all", text_ar="تُطبَّق الغرامات الإدارية على مخالفات مثل التأخر في التسجيل أو تقديم الإقرار أو السداد وفق الجدول المنشور الساري. تُقتبس المبالغ من الجدول الساري فقط.", text_en="Administrative penalties apply to violations such as late registration, late filing and late payment according to the current published schedule. Amounts are quoted only from the schedule in force.", keywords=["penalty", "penalties", "fine", "fines", "late filing", "late payment", "late registration", "administrative", "غرامة", "غرامات", "تأخر"], owner_role=TAX, effective_from=date(2018, 1, 1), source_ref="FTA (penalty amounts OPEN: cite the current schedule, never from memory)"),
    dict(passage_id="einv-md244-2025-timeline", domain="einvoicing", instrument="Ministerial Decision No. 244 of 2025 (e-invoicing implementation timeline)", instrument_ar="القرار الوزاري رقم 244 لسنة 2025 (الجدول الزمني لتطبيق الفوترة الإلكترونية)", article="Article 2", subject="e-invoicing timeline", rule_type="deadline", value="phased by business size; first phase 2026 (dated timeline)", unit=None, condition="businesses in scope per phase", taxpayer_category="all", text_ar="يُطبَّق نظام الفوترة الإلكترونية على مراحل بحسب حجم الأعمال وفق الجدول الزمني المؤرخ في القرار، وتبدأ المرحلة الأولى خلال عام 2026.", text_en="The e-invoicing system applies in phases by business size according to the dated timeline in the Decision; the first phase starts during 2026.", keywords=["e-invoicing", "einvoicing", "electronic invoice", "electronic invoicing", "timeline", "phase", "when", "start", "الفوترة الإلكترونية", "مراحل", "جدول زمني"], owner_role=TAX, effective_from=date(2025, 10, 1), source_ref="Ministry of Finance (confirm dated timeline before quoting)"),
    dict(passage_id="einv-md243-2025-scope", domain="einvoicing", instrument="Ministerial Decision No. 243 of 2025 (e-invoicing system and accredited service providers)", instrument_ar="القرار الوزاري رقم 243 لسنة 2025 (نظام الفوترة الإلكترونية ومزودو الخدمة المعتمدون)", article="Article 3", subject="e-invoicing service providers", rule_type="procedure", value="exchange through accredited service providers", unit=None, condition="businesses in scope", taxpayer_category="all", text_ar="يتم تبادل الفواتير الإلكترونية عبر مزودي خدمة معتمدين من الوزارة وفق المواصفات المعتمدة.", text_en="Electronic invoices are exchanged through service providers accredited by the Ministry according to the approved specifications.", keywords=["e-invoicing", "accredited service provider", "asp", "provider", "exchange", "الفوترة الإلكترونية", "مزود خدمة معتمد"], owner_role=TAX, effective_from=date(2025, 10, 1), source_ref="Ministry of Finance"),
    dict(passage_id="det-renewal-ejari", domain="licence", instrument="DET trade licence renewal requirements (published text)", instrument_ar="متطلبات تجديد الرخصة التجارية (النص المنشور من دائرة الاقتصاد والسياحة)", article="Renewal requirements", subject="licence renewal tenancy requirement", rule_type="condition", value="valid registered tenancy contract (Ejari)", unit=None, condition="mainland licence renewal", taxpayer_category="all", text_ar="يتطلب تجديد الرخصة التجارية للبر الرئيسي عقد إيجار سارياً ومسجلاً في نظام إيجاري.", text_en="Renewal of a mainland trade licence requires a valid tenancy contract registered in the Ejari system.", keywords=["renew", "renewal", "licence", "license", "trade licence", "ejari", "tenancy", "lease", "تجديد", "رخصة", "إيجاري", "عقد إيجار"], owner_role=COMP, effective_from=date(2024, 1, 1), source_ref="DET published renewal requirements (versioned; to be confirmed by DET)"),
    dict(passage_id="det-renewal-chamber", domain="licence", instrument="DET trade licence renewal requirements (published text)", instrument_ar="متطلبات تجديد الرخصة التجارية (النص المنشور من دائرة الاقتصاد والسياحة)", article="Renewal requirements", subject="licence renewal chamber membership", rule_type="condition", value="valid Dubai Chamber membership", unit=None, condition="mainland licence renewal", taxpayer_category="all", text_ar="يتطلب تجديد الرخصة التجارية عضوية سارية في غرفة تجارة دبي.", text_en="Renewal of a trade licence requires a valid Dubai Chamber of Commerce membership.", keywords=["renew", "renewal", "chamber", "chamber of commerce", "membership", "تجديد", "غرفة تجارة", "عضوية"], owner_role=COMP, effective_from=date(2024, 1, 1), source_ref="DET published renewal requirements (to be confirmed by DET)"),
    dict(passage_id="ubo-cd58-2020-register", domain="licence", instrument="Cabinet Decision No. 58 of 2020 on the regulation of beneficial owner procedures", instrument_ar="قرار مجلس الوزراء رقم 58 لسنة 2020 بشأن تنظيم إجراءات المستفيد الحقيقي", article="Article 8", subject="beneficial owner register", rule_type="condition", value="register of beneficial owners maintained and filed with the licensing authority", unit=None, condition="companies licensed in the UAE", taxpayer_category="all", text_ar="يجب على الشركة إعداد سجل للمستفيدين الحقيقيين والاحتفاظ به وتزويد الجهة المرخِّصة ببياناته وتحديثه عند أي تغيير.", text_en="A company must prepare and maintain a register of beneficial owners, file its data with the licensing authority and update it on any change.", keywords=["ubo", "beneficial owner", "beneficial owners", "register", "ultimate", "المستفيد الحقيقي", "سجل"], owner_role=COMP, effective_from=date(2020, 8, 28), source_ref="UAE Cabinet (confirm current instrument)"),
    dict(passage_id="ccl-32-2021-art27-audit", domain="licence", instrument="Federal Decree-Law No. 32 of 2021 on Commercial Companies", instrument_ar="المرسوم بقانون اتحادي رقم 32 لسنة 2021 في شأن الشركات التجارية", article="Article 27", subject="company accounts audit", rule_type="condition", value="annual accounts audited by a licensed auditor", unit=None, condition="joint stock and limited liability companies", taxpayer_category="all", text_ar="يجب على كل شركة مساهمة أو ذات مسؤولية محدودة أن يكون لها مدقق حسابات مرخّص واحد أو أكثر لتدقيق حساباتها سنوياً.", text_en="Every joint stock company and limited liability company must have one or more licensed auditors to audit its accounts annually.", keywords=["commercial companies law", "llc", "accounts", "annual", "auditor", "audit", "licensed auditor", "الشركات التجارية", "مدقق حسابات", "سنوياً"], owner_role=COMP, effective_from=date(2022, 1, 2), source_ref="Ministry of Economy"),
    dict(passage_id="det-late-renewal-fees", domain="licence", instrument="DET published text on expired licences and late renewal", instrument_ar="النص المنشور من دائرة الاقتصاد والسياحة بشأن الرخص المنتهية والتجديد المتأخر", article="Published guidance", subject="late renewal fees", rule_type="condition", value="to be confirmed by DET", unit=None, condition="licence renewed after expiry", taxpayer_category="all", text_ar="تُطبَّق على الرخصة المنتهية رسوم ومهل التجديد المتأخر وفق النص المنشور من دائرة الاقتصاد والسياحة. تُقتبس القيم من النص المنشور فقط.", text_en="An expired licence is subject to the late-renewal fees and grace periods in the text published by DET. Values are quoted only from the published text.", keywords=["expired", "expiry", "late renewal", "late fee", "grace period", "penalty", "fine", "منتهية", "رسوم التأخير", "مهلة"], owner_role=COMP, effective_from=date(2024, 1, 1), source_ref="DET published text (grace/late-fee amounts OPEN; to be confirmed by DET)"),
    dict(passage_id="aud-12-2014-register", domain="audit_profession", instrument="Federal Law No. 12 of 2014 on the regulation of the auditing profession", instrument_ar="القانون الاتحادي رقم 12 لسنة 2014 في شأن تنظيم مهنة مدققي الحسابات", article="Article 4", subject="who may sign an audit report", rule_type="condition", value="auditors registered in the Ministry of Economy register", unit=None, condition="practising auditors", taxpayer_category="all", text_ar="لا يجوز مزاولة مهنة تدقيق الحسابات أو توقيع تقرير تدقيق إلا لمن كان مقيداً في سجل مدققي الحسابات لدى وزارة الاقتصاد.", text_en="Only a person registered in the auditors' register at the Ministry of Economy may practise auditing or sign an audit report.", keywords=["who may sign", "sign", "audit report", "auditor", "registered", "ministry of economy", "register", "licensed", "توقيع", "مدقق", "سجل", "وزارة الاقتصاد"], owner_role=AUD, effective_from=date(2015, 1, 1), source_ref="Ministry of Economy (confirm instrument)"),
    dict(passage_id="pdpl-45-2021-art6-consent", domain="data_protection", instrument="Federal Decree-Law No. 45 of 2021 on the Protection of Personal Data (PDPL)", instrument_ar="المرسوم بقانون اتحادي رقم 45 لسنة 2021 في شأن حماية البيانات الشخصية", article="Article 6", subject="consent conditions", rule_type="condition", value="clear, specific, documented, withdrawable consent", unit=None, condition="processing based on consent", taxpayer_category="all", text_ar="يجب أن تكون الموافقة على معالجة البيانات الشخصية واضحة ومحددة وموثقة، ويحق لصاحب البيانات سحبها في أي وقت.", text_en="Consent to the processing of personal data must be clear, specific and documented, and the data subject may withdraw it at any time.", keywords=["personal data", "consent", "withdraw", "privacy", "data protection", "pdpl", "بيانات شخصية", "موافقة", "سحب"], owner_role=DP, effective_from=date(2022, 1, 2), source_ref="UAE Data Office (executive regulations status OPEN)"),
    dict(passage_id="cbuae-7-2023-open-finance", domain="data_protection", instrument="CBUAE Open Finance Regulation (Circular No. 7 of 2023)", instrument_ar="نظام التمويل المفتوح الصادر عن مصرف الإمارات المركزي (التعميم رقم 7 لسنة 2023)", article="Consent", subject="open finance consent wording", rule_type="condition", value="explicit, time-bound consent for data sharing", unit=None, condition="used only for consent wording, not as an answer source", taxpayer_category="all", text_ar="تتطلب مشاركة بيانات الحسابات موافقة صريحة ومحددة المدة من العميل.", text_en="Sharing of account data requires the customer's explicit, time-bound consent.", keywords=["open finance", "bank data sharing"], owner_role=DP, effective_from=date(2023, 6, 1), source_ref="CBUAE", answer_source=False),
    dict(passage_id="legal-34-2022-practice", domain="legal_practice", instrument="Federal Law No. 34 of 2022 on the regulation of the legal profession", instrument_ar="القانون الاتحادي رقم 34 لسنة 2022 في شأن تنظيم مهنة المحاماة", article="Article 3", subject="who may give legal advice", rule_type="condition", value="licensed advocates and legal consultants only", unit=None, condition="used only for refusal logic", taxpayer_category="all", text_ar="لا يجوز تقديم الاستشارات القانونية أو المرافعة إلا للمحامين والمستشارين القانونيين المرخّصين.", text_en="Only licensed advocates and legal consultants may give legal advice or plead before the courts.", keywords=["legal advice", "lawyer"], owner_role="Legal expert (refusal logic only)", effective_from=date(2023, 1, 1), source_ref="Ministry of Justice", answer_source=False),
]


def _seed_corpus(db: Session) -> None:
    for p in PASSAGES:
        if db.get(CorpusPassage, p["passage_id"]) is None:
            db.add(CorpusPassage(**p))
    db.flush()


# --- demo data ------------------------------------------------------------------------------------------


def seed_demo(db: Session) -> None:
    # Demo environment only: open the tax-specialist path so the escalation journey can be shown end to end.
    from app.modules.config.service import get_config, set_config

    if not get_config(db, "escalation.tax_specialist_path.enabled", False):
        set_config(db, "escalation.tax_specialist_path.enabled", True, changed_by="demo-seed", change_reason="demo environment: tax-specialist path shown with fixture data", label="demo environment only; OFF by default until the FTA position is recorded")
    from app.demo import CO_ALNOOR, CO_BLUEDUNE, CO_GULFTECH, CO_SAFWA, PERSONA_UUIDS
    from app.modules.escalation.calendar import calendar_version_label

    today = date.today()
    ents = [
        dict(identity_uuid=PERSONA_UUIDS["hassan"], specialist_type="tax", register_used="FTA Tax Agent list / operator contract (review-only)", reference_number="TAA-3310", status="active", valid_to=date(today.year + 1, 12, 31), checked_by="Qeonix engagement manager", checked_on=today - timedelta(days=20), jurisdiction="onshore Dubai", firm_agreement_signed=True, review_only=True),
        dict(identity_uuid=PERSONA_UUIDS["mariam"], specialist_type="lawyer", register_used="Legal Affairs Department licence (route switched off)", reference_number="LAD-0871", status="active", valid_to=date(today.year + 1, 6, 30), checked_by="Qeonix engagement manager", checked_on=today - timedelta(days=20), jurisdiction="onshore Dubai", firm_agreement_signed=False, review_only=True),
        dict(identity_uuid=PERSONA_UUIDS["layla"], specialist_type="auditor", register_used="Ministry of Economy auditor register", reference_number="AUD-2201", status="active", valid_to=date(today.year + 1, 12, 31), checked_by="Audit firm engagement manager", checked_on=today - timedelta(days=20), jurisdiction="onshore Dubai", firm_agreement_signed=True, review_only=False),
    ]
    for e in ents:
        if db.scalar(select(SpecialistEntitlement).where(SpecialistEntitlement.identity_uuid == e["identity_uuid"], SpecialistEntitlement.specialist_type == e["specialist_type"])) is None:
            db.add(SpecialistEntitlement(**e))
    db.flush()
    if db.scalar(select(EscalationCase).where(EscalationCase.is_demo.is_(True))) is not None:
        return
    cal = calendar_version_label(db)
    now = utcnow()
    hassan, layla, khalid_key, priya_key = PERSONA_UUIDS["hassan"], PERSONA_UUIDS["layla"], "demo-owner-khalid", "demo-owner-priya"

    def ev(case: EscalationCase, et: str, at, **kw) -> None:
        db.add(CaseEvent(escalation_id=case.case_id, event_type=et, occurred_at=at, rule_version="1.0", actor_key=kw.pop("actor_key", None), actor_role=kw.pop("actor_role", None), reason_code=kw.pop("reason_code", None), details={"demo": True, **kw}))

    def wi(company: str, module: str, period: str, opened_at, opened_by="agent") -> WorkItem:
        w = WorkItem(company_id=company, module=module, case_type=module, period_ref=period, opened_by=opened_by, case_opened_at=opened_at, calendar_version=cal, is_demo=True)
        db.add(w)
        db.flush()
        return w

    def case(company: str, module: str, reason: str, key: str, opened_at, **kw) -> EscalationCase:
        w = kw.pop("work_item", None) or wi(company, module, kw.get("period", None) or key, opened_at, kw.get("opened_by", "user"))
        c = EscalationCase(company_id=company, work_item_id=w.id, module=module, case_type=module, matter_key=key, trigger_rule_id=kw.pop("rule", "user_raised"), trigger_rule_version="1.0", trigger_event_id=kw.pop("event_id", f"demo-{key}-{opened_at.date()}"), idempotency_key=f"{company}|{module}|{key}|demo-{key}-{opened_at.isoformat()}", trigger_source=kw.pop("source", "user_raised"), escalation_reason=reason, status=kw.pop("status", "open"), flags=[], priority=kw.pop("priority", "standard"), queue={"tax": "tax_specialist", "audit": "licensed_auditor", "compliance": "det_compliance", "legal": "legal_queue"}[module], specialist_type={"tax": "tax", "audit": "auditor", "compliance": "compliance", "legal": "lawyer"}[module], opened_by=kw.pop("opened_by", "user"), opened_at=opened_at, escalated_at=opened_at, calendar_version=cal, is_demo=True, details={"demo": True, "label": "Demo data"}, **{k: v for k, v in kw.items() if k not in ("period",)})
        db.add(c)
        db.flush()
        ev(c, "case_created", opened_at, reason_code=reason)
        ev(c, "escalated", opened_at, reason_code=reason)
        return c

    # 1. Al Noor: resolved tax case with two pauses (consent wait 2 days, information wait 2 days).
    t0 = now - timedelta(days=20)
    c1 = case(CO_ALNOOR, "tax", "user_requested", "item:vat_return_2026Q2", t0, title="VAT return draft - question on reverse charge entry", linked_item_id="vat_return_2026Q2", opened_by_key=khalid_key, status="resolved", assigned_to=hassan, assigned_role_label="Tax specialist lead", accepted_at=t0 + timedelta(days=1), first_response_at=t0 + timedelta(days=3, hours=12), resolved_at=t0 + timedelta(days=8), consent_requested_at=t0 + timedelta(days=1), consent_decision="granted", resolution_outcome="a")
    c1.details = {**c1.details, "requested_scope": [{"module": "tax", "data_class": "return", "period_from": "2026-04-01", "period_to": "2026-06-30"}], "purpose": "review of the VAT return draft"}
    ev(c1, "assigned", t0 + timedelta(hours=4), actor_role="escalation_ops")
    ev(c1, "accepted", t0 + timedelta(days=1), actor_role="tax_specialist")
    ev(c1, "consent_requested", t0 + timedelta(days=1), actor_role="tax_specialist")
    ev(c1, "pause", t0 + timedelta(days=1), reason_code="awaiting_owner_consent")
    db.add(CasePause(case_id=c1.case_id, reason_code="awaiting_owner_consent", started_at=t0 + timedelta(days=1), ended_at=t0 + timedelta(days=3)))
    ev(c1, "consent_granted", t0 + timedelta(days=3), actor_role="owner")
    ev(c1, "resume", t0 + timedelta(days=3), reason_code="awaiting_owner_consent")
    db.add(CaseAccessGrant(case_id=c1.case_id, company_id=CO_ALNOOR, recipient_uuid=hassan, purpose="review of the VAT return draft", scope=[{"module": "tax", "data_class": "return", "period_from": "2026-04-01", "period_to": "2026-06-30"}], granted_by_key=khalid_key, granted_by_role="owner", granted_at=t0 + timedelta(days=3), expires_at=t0 + timedelta(days=93)))
    ev(c1, "first_response", t0 + timedelta(days=3, hours=12), actor_role="tax_specialist")
    ev(c1, "information_requested", t0 + timedelta(days=4), actor_role="tax_specialist", reason_code="supplier_invoice_copy")
    ev(c1, "pause", t0 + timedelta(days=4), reason_code="awaiting_owner_information")
    db.add(CasePause(case_id=c1.case_id, reason_code="awaiting_owner_information", started_at=t0 + timedelta(days=4), ended_at=t0 + timedelta(days=6)))
    ev(c1, "owner_information_received", t0 + timedelta(days=6), actor_role="owner")
    ev(c1, "resume", t0 + timedelta(days=6), reason_code="awaiting_owner_information")
    ev(c1, "resolved", t0 + timedelta(days=8), actor_role="tax_specialist", reason_code="outcome_a")
    # 2. Al Noor: audit case awaiting consent, day 5 (reminder day 3 sent).
    t1 = now - timedelta(days=5)
    c2 = case(CO_ALNOOR, "audit", "audit_signoff_required", "audit_file_2025|audit_required|FY2025", t1, rule="audit_required", source="audit_exception", opened_by="agent", status="awaiting_consent", assigned_to=layla, assigned_role_label="Licensed auditor firm", accepted_at=t1 + timedelta(hours=6), consent_requested_at=t1, title=None, period="FY2025")
    c2.details = {**c2.details, "requested_scope": [{"module": "audit", "data_class": "audit file", "period_from": "2025-01-01", "period_to": "2025-12-31"}, {"module": "audit", "data_class": "bank statement", "period_from": "2025-01-01", "period_to": "2025-12-31"}], "purpose": "audit-required check (owner-confirmed flag inputs)"}
    ev(c2, "assigned", t1 + timedelta(hours=2), actor_role="escalation_ops")
    ev(c2, "accepted", t1 + timedelta(hours=6), actor_role="licensed_auditor")
    ev(c2, "consent_requested", t1, actor_role="licensed_auditor")
    ev(c2, "pause", t1, reason_code="awaiting_owner_consent")
    db.add(CasePause(case_id=c2.case_id, reason_code="awaiting_owner_consent", started_at=t1, ended_at=None))
    ev(c2, "reminder_sent", t1 + timedelta(days=3), day=3, to="owner_and_signatories", text_key="consent_wait.reminder")
    # 3. Al Noor: deadline-near compliance case, open, unassigned (VAT return due in 10 days).
    t2 = now - timedelta(days=2)
    case(CO_ALNOOR, "compliance", "deadline_risk", "DET-1023456|VAT_RETURN|2026Q3", t2, rule="deadline_risk", source="compliance_item", opened_by="agent", priority="deadline_near", due_date=today + timedelta(days=10), title=None, period="2026Q3")
    # 4. Blue Dune: closed - no consent (requested 20 days ago, closed day 14, reopen within 30 days).
    t3 = now - timedelta(days=20)
    c4 = case(CO_BLUEDUNE, "tax", "user_requested", "topic:corporate_tax_registration", t3, title="Corporate tax registration timing", topic_code="corporate_tax_registration", opened_by_key=priya_key, status="closed_no_consent", assigned_to=hassan, assigned_role_label="Tax specialist lead", accepted_at=t3 + timedelta(hours=5), consent_requested_at=t3, closed_at=t3 + timedelta(days=14), resolution_outcome="d", reopen_until=(t3 + timedelta(days=44)).date())
    c4.details = {**c4.details, "requested_scope": [{"module": "tax", "data_class": "tax profile", "period_from": "2025-01-01", "period_to": "2025-12-31"}], "purpose": "registration timing review"}
    ev(c4, "consent_requested", t3, actor_role="tax_specialist")
    ev(c4, "pause", t3, reason_code="awaiting_owner_consent")
    db.add(CasePause(case_id=c4.case_id, reason_code="awaiting_owner_consent", started_at=t3, ended_at=t3 + timedelta(days=14)))
    ev(c4, "reminder_sent", t3 + timedelta(days=3), day=3)
    ev(c4, "reminder_sent", t3 + timedelta(days=7), day=7)
    ev(c4, "closed", t3 + timedelta(days=14), reason_code="no_consent", outcome="d")
    # 5. Al Noor: legal-type request showing the neutral state (no stored text, not routed).
    case(CO_ALNOOR, "legal", "legal_matter", "topic:legal_request", now - timedelta(days=1), rule="legal_type_request", source="user_question", title=None, topic_code="legal_request", legal_route_status="not_routed", opened_by_key=khalid_key)
    # 6. Synthetic workflow-log rows for the K21/K22 demo (two monthly periods): tax 24 items (6 escalated),
    #    audit 14 items (11 escalated), compliance 12 items (11 escalated), legal 3 (separate, suppressed at N=10).
    import random

    rng = random.Random(8)
    companies = [CO_SAFWA, CO_GULFTECH, CO_ALNOOR, CO_BLUEDUNE]
    k = 0

    def synth(module: str, items: int, escalated: int, reasons: list[str], st: str) -> None:
        nonlocal k
        for i in range(items):
            k += 1
            opened = now - timedelta(days=rng.randint(3, 55), hours=rng.randint(0, 20))
            w = wi(companies[k % 4], module, f"P{k}", opened, "agent")
            if i >= escalated:
                continue
            esc_at = opened + timedelta(hours=rng.randint(1, 30))
            c = EscalationCase(company_id=w.company_id, work_item_id=w.id, module=module, case_type=module, matter_key=f"synthetic|{module}|P{k}", trigger_rule_id="synthetic", trigger_rule_version="1.0", trigger_event_id=f"synthetic-{k}", idempotency_key=f"{w.company_id}|{module}|synthetic|{k}", trigger_source="agent_output", escalation_reason=reasons[i % len(reasons)], status="open", flags=[], priority="deadline_near" if i % 4 == 0 else "standard", queue={"tax": "tax_specialist", "audit": "licensed_auditor", "compliance": "det_compliance", "legal": "legal_queue"}[module], specialist_type=st, opened_by="agent", opened_at=opened, escalated_at=esc_at, calendar_version=cal, is_demo=True, kpi_only=True, details={"demo": True, "label": "Demo data", "kpi_only": True})
            db.add(c)
            db.flush()
            ev(c, "case_created", esc_at)
            ev(c, "escalated", esc_at)
            if i % 7 == 6:
                c.status, c.rejected_at, c.closed_at, c.reject_reason_code = "rejected", esc_at + timedelta(days=1), esc_at + timedelta(days=1), "R4"
                ev(c, "case_rejected", esc_at + timedelta(days=1), reason_code="R4")
                continue
            if i % 5 == 4:
                continue  # stays open (age bands)
            fr = esc_at + timedelta(hours=rng.randint(4, 60))
            res = fr + timedelta(days=rng.randint(1, 6), hours=rng.randint(0, 12))
            c.first_response_at, c.resolved_at, c.status, c.resolution_outcome = fr, res, "resolved", "c" if i % 6 == 5 else "a"
            c.assigned_to, c.assigned_role_label = "synthetic-specialist", {"tax": "Tax specialist lead", "auditor": "Licensed auditor firm", "lawyer": "Licensed lawyer route", "compliance": "DET compliance"}[st]
            ev(c, "first_response", fr)
            if i % 3 == 0:
                ps = fr + timedelta(hours=2)
                pe = min(ps + timedelta(days=1), res)
                db.add(CasePause(case_id=c.case_id, reason_code="awaiting_owner_information", started_at=ps, ended_at=pe))
                ev(c, "pause", ps, reason_code="awaiting_owner_information")
                ev(c, "resume", pe, reason_code="awaiting_owner_information")
            ev(c, "resolved", res, reason_code=f"outcome_{c.resolution_outcome}")

    synth("tax", 24, 12, ["complex_tax", "user_requested"], "tax")
    synth("audit", 14, 11, ["audit_signoff_required"], "auditor")
    synth("compliance", 12, 11, ["deadline_risk"], "compliance")
    synth("legal", 3, 3, ["legal_matter"], "lawyer")
    db.flush()
