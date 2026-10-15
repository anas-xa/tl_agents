"""Audit agent seeds (ORDER 70): rule register r1, criteria v1, config keys and switches; demo states (Demo data)."""

from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.time import utcnow
from app.demo import CO_ALNOOR, CO_BLUEDUNE, CO_GULFTECH, PERSONA_UUIDS
from app.modules.auditagent import engagement as eng_svc
from app.modules.auditagent import indicator as ind
from app.modules.auditagent import review as rv
from app.modules.auditagent import workfile as wf
from app.modules.auditagent.models import (
    AuditCriteriaVersion,
    AuditInputs,
    AuditRevenueFigure,
    Engagement,
    ExceptionFlag,
    ExceptionRule,
)
from app.modules.config.service import ensure_config, ensure_rule

ORDER = 70
AED = 100
PO = "Qeonix product owner"
TL = "Tech Lead"
DDE = "Data and decision engineering"


def seed(db: Session) -> None:
    c = ensure_config
    # E7-S1
    c(db, "auditagent.consent_gate.batch_max_records", 100, unit="records", owner=TL, status="confirmed", label="settled")
    c(db, "auditagent.consent_gate.batch_max_seconds", 5, unit="s", owner=TL, status="confirmed", label="settled")
    c(db, "auditagent.withdrawal.stop_read_max_latency_seconds", 60, unit="s", owner=TL, status="confirmed", label="settled (design target 10 s)")
    c(db, "auditagent.consent_store.deletion_schedule_hours", 24, unit="h", owner="data owner", status="provisional", label="assumed")
    c(db, "auditagent.decision.reason_min_chars", 10, unit="chars", owner="UX", status="confirmed", label="settled")
    c(db, "auditagent.rule_register.first_version", "r1", owner=PO, status="confirmed", label="settled")
    c(db, "auditagent.backfill.first_cap_per_company", 100, unit="flags", owner=DDE, status="provisional", label="estimate; sorted severity then amount, 'more available' note")
    c(db, "auditagent.list.page_size", 25, unit="rows", owner=DDE, status="provisional", label="demo")
    c(db, "auditagent.list.latency_target_seconds", 2, unit="s", owner=DDE, status="provisional", label="demo")
    c(db, "auditagent.review.accepted_purposes", ["audit_preparation", "bookkeeping_classification"], owner=PO, status="provisional", label="consented purposes under which continuous review may read")
    c(db, "auditagent.review.cycle_trigger", None, owner=TL, status="to_be_confirmed", label="OPEN (Q298): trigger, frequency, max delay, failure handling")
    c(db, "auditagent.alert_fatigue_limits", None, owner="production", status="to_be_confirmed", label="not set")
    c(db, "auditagent.severity_scale", {"pilot": ["High", "Medium", "Low"], "suggested": ["info", "review", "urgent"]}, owner=PO, status="to_be_confirmed", label="scale choice to be confirmed; severity = review priority, not legal seriousness")
    c(db, "auditagent.aml_agent.enabled", False, owner=PO, status="confirmed", label="AML agent switch stays OFF in the MVP")
    # E7-S2
    c(db, "auditagent.criteria.revenue_threshold_fils", 50_000_000 * AED, unit="fils", owner="Reference, confirmed by audit expert", status="to_be_confirmed", label="[REG] confirm; operator strictly 'above'")
    c(db, "auditagent.criteria.instrument", "Ministerial Decision 84/2025 (replaced 82/2023; FY starting on/after 1 Jan 2025)", owner="Trade Licensing Expert", status="to_be_confirmed", label="confirm before quoting")
    c(db, "auditagent.criteria.near_threshold_band_pct", 10, unit="%", owner="product (risk setting)", status="provisional", label="test default, not legal; 45m-55m, edges inclusive")
    c(db, "auditagent.criteria.projection_band_pct", 20, unit="%", owner=PO, status="provisional", label="suggested")
    c(db, "auditagent.revenue.source_tolerance_pct", 5, unit="%", owner=DDE, status="provisional", label="placeholder, 'internal heuristic'")
    c(db, "auditagent.revenue.completeness_min_monthly_closes", 12, unit="of 12", owner=DDE, status="provisional", label="internal rule: partial = missing, not prorated")
    c(db, "auditagent.revenue.short_period_mode", "actual_not_prorated", owner=DDE, status="to_be_confirmed", label="assumption; confirm with FTA; 12-month equivalent shown, cannot determine when sides differ")
    c(db, "auditagent.revenue.account_mapping", "credits to Revenue/Sales class less returns and discounts, excl. output VAT, interest, asset-disposal gains, intercompany", owner=DDE, status="provisional", label="configurable fixture")
    c(db, "auditagent.revenue.stale_after_days", 180, unit="days", owner=DDE, status="provisional", label="placeholder freshness window for 'stale data'")
    c(db, "auditagent.revenue.einvoice_primary_allowed", False, owner=DDE, status="confirmed", label="e-invoice is a cross-check only in Phase 1")
    c(db, "auditagent.recompute.retry_backoff_minutes", [1, 5, 30, 120], unit="minutes", owner=TL, status="confirmed", label="settled; then dead letter + alert")
    c(db, "auditagent.k20.min_cell_size", 10, unit="licences", owner=TL, status="confirmed", label="settled; complementary suppression")
    c(db, "auditagent.qfzp.default_mainland", "not_applicable", owner="Trade Licensing Expert", status="confirmed", label="settled")
    c(db, "auditagent.response_time_shown", None, owner="UX", status="provisional", label="none in PoC (if shown: 'target, not a commitment')")
    c(db, "auditagent.human_review.target_working_days", 3, unit="working days", owner=PO, status="provisional", label="pilot target, not a commitment")
    c(db, "auditagent.ask_auditor_path.enabled", False, owner=PO, status="confirmed", label="neutral 'Ask about a licensed auditor' path; OFF by default; no price, buy button or provider referral")
    # E7-S3
    c(db, "auditagent.auto_issue_without_human_auditor", False, owner=PO, status="confirmed", label="OFF, cannot be turned on in the MVP")
    c(db, "auditagent.completeness_rule_set", "ac-v1", owner="DDE / audit firm", status="provisional", label="checks a-f")
    c(db, "auditagent.reconciliation.unreconciled_threshold", None, unit="count", owner="audit firm", status="to_be_confirmed", label="placeholder; calibrated by licensed auditor in pilot")
    c(db, "auditagent.watermark.opacity_pct", 15, unit="%", owner="UX", status="confirmed", label="settled")
    c(db, "auditagent.watermark.angle_deg", 30, unit="deg", owner="UX", status="confirmed", label="30 degrees rising left to right")
    c(db, "auditagent.watermark.tiling", "once per page; twice on pages longer than A4", owner="UX", status="confirmed")
    c(db, "auditagent.image_export.min_width_px", 800, unit="px", owner="UX", status="confirmed", label="below: refused, PDF offered")
    c(db, "auditagent.image_export.strip_height_pct", 6, unit="%", owner="UX", status="confirmed")
    c(db, "auditagent.data_request.second_reminder_days", 3, unit="days", owner="PM", status="confirmed", label="reminders on due date and +3 days; nothing after")
    c(db, "auditagent.data_request.default_due_days", 7, unit="days", owner="PM", status="provisional")
    c(db, "auditagent.export.numerals", "western", owner="UX", status="confirmed")
    c(db, "auditagent.export.date_format", "full written (14 March 2027 / 14 مارس 2027); Hijri only if user turned on", owner="UX", status="confirmed")
    # E7-S4
    c(db, "audit.signing.enabled", False, owner=PO, status="confirmed", label="OFF until the audit model is agreed; 'Record review' in Phase 1")
    c(db, "auditagent.register.snapshot_max_age_hours", 24, unit="h", owner=TL, status="provisional", label="production")
    c(db, "auditagent.register.live_timeout_seconds", 5, unit="s", owner=TL, status="confirmed")
    c(db, "auditagent.register.retries_seconds", [2, 10, 30], unit="s", owner=TL, status="confirmed")
    c(db, "auditagent.register.refresh", "daily", owner=TL, status="provisional", label="illustrative")
    c(db, "auditagent.register.mock_entries", eng_svc.DEFAULT_MOCK_REGISTER, owner=TL, status="provisional", label="Ministry of Economy register mock (no API assumed); one entry per check outcome")
    c(db, "auditagent.register.simulate_unreachable", False, owner=TL, status="confirmed", label="engineering test hook")
    c(db, "auditagent.reauth.max_age_minutes", 5, unit="min", owner=TL, status="confirmed")
    c(db, "auditagent.return_reason.min_chars", 10, unit="chars", owner="UX", status="confirmed")
    c(db, "auditagent.notification.retries", 3, owner=TL, status="confirmed")
    c(db, "auditagent.audit_trail.retention_years", 10, unit="years", owner="production", status="provisional", label="illustrative")
    c(db, "auditagent.reminders.before_deadline_days", [14, 7, 2], unit="days", owner="DET pilot manager + audit firm", status="provisional", label="placeholders; plus due-date notice")
    c(db, "auditagent.escalation.untouched_working_days", 3, unit="working days", owner="PM", status="provisional", label="placeholder")
    c(db, "auditagent.escalation.not_under_review_at_days", 7, unit="days", owner="PM", status="provisional", label="placeholder")
    c(db, "auditagent.escalation.unsigned_at_days", 2, unit="days", owner="PM", status="provisional", label="placeholder")
    c(db, "auditagent.assignment.who_may_assign", ["qeonix_audit_ops", "det_pilot_manager"], owner="[OPEN]", status="to_be_confirmed", label="DET / company / pool - provisional")
    ensure_rule(db, "audit-exceptions-r1", "Audit exception rule register (AX01-AX08, AX01b; cash rule OFF)", version="r1", instrument="internal heuristics and anchored checks; no legal cash threshold", status="provisional", owner_role=PO, effective_from=date(2025, 1, 1), parameters={"rules": [r["rule_id"] for r in rv.RULES_R1], "phase_1a": ["AX01", "AX01b", "AX02", "AX03", "AX06", "AX07"], "bank_dependent": ["AX04", "AX05", "AX08"], "cash_rule": {"id": rv.CASH_RULE_ID, "enabled": False, "label": "internal review threshold, not a legal limit"}})
    ensure_rule(db, "ac-v1", "Audit working-file completeness rule set (checks a-f)", version="v1", instrument="internal rule set, provisional", status="provisional", owner_role="DDE / audit firm", effective_from=date(2025, 1, 1), parameters={"checks": ["a period coverage", "b trial balance balanced", "c bank data", "d reconciliation", "e supporting registers", "f audit-required inputs owner-confirmed"], "complete_means": "ready for licensed-auditor review, not sufficient to sign"})
    ensure_rule(db, "audit-criteria-v1", "Audit-required indicator criteria v1", version="v1", instrument="Ministerial Decision 84/2025 [REG, confirm]", status="to_be_confirmed", owner_role="tax specialist proposes; licensed audit expert confirms", effective_from=date(2025, 1, 1), parameters={"revenue_threshold_fils": 50_000_000 * AED, "operator": "strictly above", "qfzp": True, "tax_group": True, "other_trigger": None})
    ensure_rule(db, "einvoicing-threshold-v1", "E-invoicing threshold (kept distinct from the audit threshold)", version="v1", instrument="Ministerial Decisions 243/244 of 2025", status="to_be_confirmed", owner_role=PO, parameters={"threshold": "AED 50 million or more"})
    ensure_rule(db, "audit-profession-instrument", "Audit profession instrument (licensed signature)", version="v1", instrument="Federal Law 12/2014 (confirm)", status="to_be_confirmed", owner_role="to be confirmed by the Ministry of Economy and counsel", parameters={})
    ensure_rule(db, "e-signature-standard", "E-signature standard for signed outputs", version="v1", instrument="Federal Decree-Law 46/2021 (confirm)", status="to_be_confirmed", owner_role="to be confirmed by the Ministry of Economy and counsel", parameters={"target": "qualified/reliable e-signature", "uae_pass_assertion": "authenticated approval, not a qualified signature"})
    for r in rv.RULES_R1:
        if db.scalar(select(ExceptionRule).where(ExceptionRule.rule_id == r["rule_id"], ExceptionRule.rule_version == "r1")) is None:
            db.add(ExceptionRule(rule_id=r["rule_id"], rule_version="r1", title_en=r["title_en"], title_ar=r["title_ar"], effective_date=date(2025, 1, 1), change_reason="first version", owner=PO, approved_by_tax_specialist=r.get("approved_by_tax_specialist"), sources_read=r["sources_read"], fields_read=r["fields_read"], default_severity=r["default_severity"], parameters=r["parameters"], bank_dependent=r.get("bank_dependent", False), legal_anchor=r["legal_anchor"], instrument=r.get("instrument"), phase=r["phase"], enabled=r.get("enabled", True), label=r.get("label"), status=r.get("status", "provisional")))
    if db.get(AuditCriteriaVersion, "v1") is None:
        db.add(AuditCriteriaVersion(id="v1", instrument="Ministerial Decision 84/2025, replacing 82/2023 for financial years starting on or after 1 January 2025 [REG, confirm]", effective_date=date(2025, 1, 1), effective_scope="tax periods (financial years) starting on or after 1 January 2025; closed periods not rewritten", triggers={"revenue_threshold_fils": 50_000_000 * AED, "operator": "gt", "revenue_threshold": True, "qfzp": True, "tax_group": True, "other_trigger": None}, status="proposed", proposed_by="Tax specialist (seed proposal)", proposed_by_role="tax_specialist", label="indicative, pending expert confirmation; [REG] confirm before quoting"))
    db.flush()


# --- demo ---------------------------------------------------------------------------------------------------


class _Actor:
    def __init__(self, uuid: str, name: str):
        self.identity_uuid, self.display_name = uuid, name
        from app.modules.audit.service import actor_key_for

        self.actor_key = actor_key_for(uuid)


def _rule(db: Session, rule_id: str) -> ExceptionRule:
    return db.scalar(select(ExceptionRule).where(ExceptionRule.rule_id == rule_id, ExceptionRule.is_current.is_(True)))


def _fixture_row(record_id: str, d: str, amount: int, cp: str, desc: str, **kw) -> dict:
    return {"record_id": record_id, "record_version": 1, "source": kw.pop("source", "supplied_document"), "date": d, "amount_fils": amount, "counterparty": cp, "account_code": kw.get("account_code"), "vat_code": kw.get("vat_code"), "currency": "AED", "invoice_number": kw.get("invoice_number"), "description": desc}


def seed_demo(db: Session) -> None:
    if db.scalar(select(ExceptionFlag.id).where(ExceptionFlag.company_id == CO_ALNOOR, ExceptionFlag.is_demo.is_(True)).limit(1)) is not None:
        return
    today = date.today()
    # --- Al Noor: likely_not_required; three exceptions (New, Confirmed, Dismissed); incomplete working file.
    ind.evaluate(db, CO_ALNOOR, cause="demo_seed", is_demo=True)
    ledger = {r["description"]: r for r in rv.ledger_records(db, CO_ALNOOR)}

    def pick(*needles: str) -> list[dict]:
        return [next(r for d, r in ledger.items() if n in d) for n in needles if any(n in d for d in ledger)]

    period = rv.default_period(db, CO_ALNOOR)[2]
    specs = [
        ("AX02", pick("Purchase PO-2211"), "vat_amount_mismatch", "vat_check", None),
        ("AX01b", pick("Purchase PO-2219", "Purchase PO-2230"), "same_counterparty_amount_within_window", "possible_duplicate", ("confirm", "Two supplier payments look alike; checked with Gulf Supplies, one is a reissue.")),
        ("AX06", pick("Ejari rent Q3 Business Bay"), "round_amount_period_edge", "unusual_pattern", ("dismiss", "Quarterly rent is a fixed contractual amount, not a manual journal.")),
    ]
    khalid = _Actor(PERSONA_UUIDS["khalid"], "Khalid Al Mansoori")
    for rule_id, recs, reason, ftype, decision in specs:
        if not recs:
            continue
        rule = _rule(db, rule_id)
        rows = [rv._evidence_row(r) for r in recs]
        rv.upsert_flag(db, CO_ALNOOR, period, {"rule": rule, "anchors": sorted(r["record_id"] for r in recs), "rows": rows, "reason_code": reason, "flag_type": ftype, "basis": dict(rule.parameters or {}), "severity": rule.default_severity, "amount": max(r["amount_fils"] for r in recs)}, based_on=max(r["date"] for r in recs), is_demo=True)
        fl = db.scalar(select(ExceptionFlag).where(ExceptionFlag.company_id == CO_ALNOOR, ExceptionFlag.rule_id == rule_id).order_by(ExceptionFlag.flagged_at.desc()))
        if decision:
            rv.decide(db, fl, decision=decision[0], reason=decision[1], decided_by_uuid=khalid.identity_uuid, decided_by_name=khalid.display_name, actor_role="owner", role_label=None, actor_key=khalid.actor_key)
    wf.prepare_working_file(db, CO_ALNOOR, is_demo=True)
    f = wf.current_file(db, CO_ALNOOR)
    if f is not None:
        f.is_demo = True
    # --- Gulf Tech: declared tax group -> likely_required; complete_with_exceptions file; engagement for layla.
    fy = (date(today.year - 1, 1, 1), date(today.year - 1, 12, 31))
    if db.get(AuditInputs, CO_GULFTECH) is None:
        db.add(AuditInputs(company_id=CO_GULFTECH, period_start=fy[0], period_end=fy[1], period_confirmed=True, tax_group_member="yes", tax_group_state="self_declared_unverified", qfzp="not_applicable", declared_by="Gulf Tech owner (Demo data)", declared_by_role="owner", declared_at=utcnow(), owner_confirmed=True, is_demo=True))
        db.add(AuditRevenueFigure(company_id=CO_GULFTECH, period_start=fy[0], period_end=fy[1], source="owner_declared", amount_fils=12_400_000 * AED, covers_full_period=True, owner_confirmed=True, entered_by="Gulf Tech owner (Demo data)", is_demo=True))
        db.flush()
    ind.evaluate(db, CO_GULFTECH, cause="demo_seed", is_demo=True)
    gt_period = f"FY{fy[1].year}"
    for rule_id, rows, reason, ftype in (
        ("AX02", [_fixture_row("gt-tb-0142", f"{fy[1].year}-06-30", 1_050_000, "Emirates IT Distribution", "Supplier invoice EID-7781 (supplied trial balance)", vat_code="SR", invoice_number="EID-7781")], "vat_amount_mismatch", "vat_check"),
        ("AX06", [_fixture_row("gt-tb-0388", f"{fy[1].year}-12-30", 5_000_000, "Manual journal", "Year-end accrual JV-2291 (supplied trial balance)", account_code="2100")], "round_amount_period_edge", "unusual_pattern"),
    ):
        rule = _rule(db, rule_id)
        rv.upsert_flag(db, CO_GULFTECH, gt_period, {"rule": rule, "anchors": [r["record_id"] for r in rows], "rows": rows, "reason_code": reason, "flag_type": ftype, "basis": dict(rule.parameters or {}), "severity": rule.default_severity, "amount": rows[0]["amount_fils"]}, based_on=fy[1], is_demo=True)
    for fl in db.scalars(select(ExceptionFlag).where(ExceptionFlag.company_id == CO_GULFTECH)):
        fl.source = "supplied_document"
    wf.prepare_working_file(db, CO_GULFTECH, period=fy, is_demo=True, completeness_override="complete_with_exceptions")
    if db.scalar(select(Engagement.id).where(Engagement.company_id == CO_GULFTECH).limit(1)) is None:
        layla = _Actor(PERSONA_UUIDS["layla"], "Layla Haddad")
        eng = eng_svc.create_engagement(db, company_id=CO_GULFTECH, auditor_uuid=layla.identity_uuid, assigned_by="Qeonix audit operations (Demo data)", firm_name="Haddad & Partners Auditing", engagement_manager="Rana Saleh, Haddad & Partners (firm contact)", review_deadline=today + timedelta(days=20), is_demo=True)
        eng_svc.declare_independence(db, layla, eng)
        eng_svc.activate_engagement(db, eng)
    # --- Blue Dune: near threshold -> cannot_determine (near_threshold) with an escalation case.
    if db.get(AuditInputs, CO_BLUEDUNE) is None:
        db.add(AuditInputs(company_id=CO_BLUEDUNE, period_start=fy[0], period_end=fy[1], period_confirmed=True, tax_group_member="no", tax_group_state="self_declared_unverified", qfzp="not_applicable", declared_by="Priya Raman (Demo data)", declared_by_role="remote_owner", declared_at=utcnow(), owner_confirmed=True, is_demo=True))
        db.add(AuditRevenueFigure(company_id=CO_BLUEDUNE, period_start=fy[0], period_end=fy[1], source="ledger", amount_fils=48_200_000 * AED, covers_full_period=True, months_covered=12, owner_confirmed=True, entered_by="ledger (Demo data)", is_demo=True))
        db.flush()
    ind.evaluate(db, CO_BLUEDUNE, cause="demo_seed", is_demo=True)
    # Safwa: not_yet_assessed (no evaluation stored).
    db.flush()
