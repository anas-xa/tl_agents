"""E2-S5 cohort configuration (waves, caps, modes, eligibility placeholders, suppression) and demo register."""

from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.time import utcnow
from app.modules.cohorts.models import Cohort, CohortInterest, CohortMembership
from app.modules.config.service import ensure_config, ensure_rule

ORDER = 15
PM = "DET pilot manager"


def seed(db: Session) -> None:
    ensure_config(db, "cohort.waves", [
        {"code": "1a", "label_en": "Wave 1a: Internal and DET staff test", "label_ar": "الموجة 1أ: اختبار داخلي وموظفي الدائرة", "phase": "phase1", "cap": None, "billing": False, "data": "synthetic"},
        {"code": "1b", "label_en": "Wave 1b: Pilot wave 1", "label_ar": "الموجة 1ب: الموجة التجريبية 1", "phase": "phase1", "cap": 100, "billing": True, "data": "live"},
        {"code": "1c", "label_en": "Wave 1c: Pilot wave 2", "label_ar": "الموجة 1ج: الموجة التجريبية 2", "phase": "phase1", "cap": 300, "billing": True, "data": "live", "note": "only after the wave 1 exit review; 300 is a planning figure"},
    ], owner=PM, status="provisional", label="exact wave labels stored as configuration; changeable without code")
    ensure_config(db, "cohort.phases", {"phase1": "Phase 1 Dubai pilot", "phase2": "Phase 2 Dubai launch", "phase3": "Phase 3 Other emirates", "phase4": "Phase 4 Federal level"}, owner=PM, status="provisional")
    ensure_config(db, "cohort.wave1_cap", 100, unit="licences", owner=PM, status="provisional", label="enforced cap; planning range 50-100, at least 10 on the audit-preparation path; raise only via versioned change with reason")
    ensure_config(db, "cohort.wave2_cap", 300, unit="licences", owner=PM, status="provisional", label="planning figure, confirmed at the wave 1 review")
    ensure_config(db, "cohort.enrolment_mode", "opt_in", unit="enum", owner=PM, status="to_be_confirmed", label="opt_in until the signed DET-Qeonix agreement names legal basis, contracting party and refund terms")
    ensure_config(db, "cohort.default_on_mode.enabled", False, owner=PM, status="to_be_confirmed", label="default_on_with_opt_out may be switched on only after the signed DET-Qeonix agreement; opt_in fallback")
    ensure_config(db, "cohort.allow_shift_default", False, owner=PM, status="provisional", label="late approval applies at approval time only when 'allow shift' is ticked")
    ensure_config(db, "cohort.stale_block_threshold_hours", 36, unit="hours", owner=PM, status="provisional", label="blocks confirmation of enrol/remove/wave; preview still allowed (AC/Q59)")
    ensure_config(db, "sc14.stale_warning_hours", 24, unit="hours", owner="Qeonix product owner", status="provisional", label="illustrative warning banner with Refresh; the 36 h value governs the block")
    ensure_config(db, "det.pull_interval_hours", 24, unit="hours", owner=PM, status="provisional", label="assumption; push triggers an immediate refresh if offered")
    ensure_config(db, "cohort.reconciliation_at_effective_at", {"lookback_hours": 24, "writes": "audit log for DET pilot manager", "changes_billing": False}, owner=PM, status="provisional", label="re-check subscriptions created in the previous 24 h; never changes billing")
    # superseded by det_dashboard.min_group_size (one platform-wide N, kpis.suppression)
    # ensure_config(db, "suppression.N", 10, unit="licences", owner=PM, status="provisional", label="provisional, set by DET; complementary suppression applies to UI, exports, API and reports")
    ensure_config(db, "scale.target_licences", 100000, unit="licences", owner="Qeonix product owner", status="provisional", label="sized and tested for")
    ensure_config(db, "usage.definition", {"version": "usage-v1", "counts": ["sign_in", "dashboard_view", "draft_or_document_generated", "consent_granted_or_withdrawn", "reminder_acknowledged", "escalation_opened", "approval_recorded"], "excludes": ["reminders_sent", "background_pulls"], "measures": ["active_licences", "events_by_type"]}, owner=PM, status="provisional", label="versioned usage definition shown on the tile in both languages")
    ensure_config(db, "location.values", ["in UAE", "outside UAE", "not declared"], owner=PM, status="provisional", label="optional self-declared field; never inferred from IP, passport or UAE PASS for reporting")
    ensure_config(db, "cohort.notice_version", "notice-v1", owner="DET communications", status="provisional", label="sample text in demo; reviewed by DET communications before a real pilot")
    ensure_config(db, "cohort.phase_modules", {"phase1": ["tax", "audit_preparation", "compliance", "reminders", "escalation"], "never_by_cohort": ["aml", "virtual_lawyer", "remote_services_agent"]}, owner="Qeonix product owner", status="provisional", label="modules follow the phase plan; AML, virtual lawyer and remote-services agent cannot be enabled by a cohort setting")
    ensure_config(db, "cohort.exclusion_categories", [
        {"code": "government_entity", "mode": "review", "keywords": ["government", "semi-government"], "label": "government / semi-government entities"},
        {"code": "regulated_financial", "mode": "review", "keywords": ["bank", "insurer", "insurance", "exchange house"], "label": "activities with their own regulator"},
        {"code": "regulated_profession", "mode": "review", "keywords": ["law firm", "legal consultancy", "auditing"], "label": "regulated professional practices"},
        {"code": "non_profit", "mode": "review", "keywords": ["non-profit", "charity", "charitable"], "label": "non-profit, civil, charitable"},
    ], owner=PM, status="to_be_confirmed", label="pending DET confirmation; neutral reason codes, no claim about tax status; any category DET excludes is also excluded from billing")
    ensure_rule(db, "cohort_eligibility_v1", "Pilot cohort eligibility (placeholder field names and value sets)", instrument="DET selection criteria (to be confirmed)", status="to_be_confirmed", owner_role=PM, parameters={
        "version": "cohort_eligibility_v1",
        "mainland_rule": "licensing authority is DET; free-zone authorities excluded as not_det_licensed",
        "status_mapping": {"active": "eligible", "expired": "excluded", "suspended": "excluded", "cancelled": "excluded", "under_renewal": "excluded", "unknown": "excluded"},
        "mandatory_fields": {"licence_number": "missing_licence_number", "licence_status": "missing_status", "licence_type_or_authority": "missing_authority", "legal_form": "missing_legal_form", "issue_date": "missing_issue_date", "expiry_date": "missing_expiry_date", "activity_code": "missing_activity", "ejari_number": "no_ejari", "owner_with_emirates_id": "no_owner_with_emirates_id"},
        "owner_location": "never an eligibility condition; messaging only",
        "note": "nothing here is DET fact",
    })


def seed_demo(db: Session) -> None:
    from app.demo import CO_ALNOOR, CO_BLUEDUNE, CO_GULFTECH, CO_SAFWA

    if db.scalar(select(Cohort).where(Cohort.code == "PILOT1")) is not None:
        return
    today = date.today()
    now = utcnow()
    c1a = Cohort(code="TEST1A", name="Wave 1a internal test (Demo data)", wave="1a", phase="phase1", size_limit=None, start_date=today - timedelta(days=120), modules=["tax", "compliance", "reminders"], selection_criteria={"mainland_only": True}, enrolment_mode="opt_in", status="active", created_by="seed", reason="Demo data", is_demo=True)
    c1b = Cohort(cohort_id="coh_pilot1", code="PILOT1", name="Pilot wave 1 (opt-in)", wave="1b", phase="phase1", size_limit=100, start_date=today - timedelta(days=400), modules=["tax", "audit_preparation", "compliance", "reminders", "escalation"], selection_criteria={"mainland_only": True, "legal_form": ["LLC", "Sole establishment"]}, enrolment_mode="opt_in", status="active", created_by="seed", reason="Demo data", is_demo=True)
    # Fixture-only state: a default-on cohort exists only as demo data; the API refuses it while the switch is off.
    cdo = Cohort(cohort_id="coh_pilot1_do", code="PILOT1D", name="Pilot wave 1 default-on (Demo data, fixture only)", wave="1b", phase="phase1", size_limit=100, start_date=today - timedelta(days=400), modules=["tax", "audit_preparation", "compliance", "reminders", "escalation"], selection_criteria={"mainland_only": True}, enrolment_mode="default_on_with_opt_out", status="active", created_by="seed", reason="Demo data: default_on_with_opt_out shown as fixture; blocked by cohort.default_on_mode.enabled", is_demo=True)
    for c in (c1a, c1b, cdo):
        c.created_at = now - timedelta(days=400)
    db.add_all([c1a, c1b, cdo])
    db.flush()
    db.add_all([
        CohortMembership(cohort_id="coh_pilot1", licence_number="DET-1023456", company_id=CO_ALNOOR, status="active", effective_at=now - timedelta(days=390), enrolled_at=now - timedelta(days=390), owner_opted_in_at=now - timedelta(days=395), cohort_version_at_change=1, last_notice_event="enrolled", last_notice_at=now - timedelta(days=390), notice_version="notice-v1"),
        CohortMembership(cohort_id="coh_pilot1", licence_number="DET-3067890", company_id=CO_SAFWA, status="active", effective_at=now - timedelta(days=390), enrolled_at=now - timedelta(days=390), owner_opted_in_at=now - timedelta(days=392), cohort_version_at_change=1, last_notice_event="enrolled", last_notice_at=now - timedelta(days=390), notice_version="notice-v1"),
        CohortMembership(cohort_id="coh_pilot1_do", licence_number="DET-2045678", company_id=CO_BLUEDUNE, status="active", effective_at=now - timedelta(days=200), enrolled_at=now - timedelta(days=200), cohort_version_at_change=1, last_notice_event="enrolled", last_notice_at=now - timedelta(days=200), notice_version="notice-v1"),
        CohortInterest(company_id=CO_GULFTECH, licence_number="DET-4089012", registered_by_key="demo-owner-gulftech", registered_at=now - timedelta(days=12), status="candidate", language="en"),
    ])
    db.flush()
