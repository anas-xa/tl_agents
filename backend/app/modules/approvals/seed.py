"""Approval seeds (ORDER 60): configuration keys and rule-register entries; demo approval states.

Demo (all tagged is_demo, tolerant of missing upstream demo data):
- Al Noor: the open quarter's VAT pack (ready for owner review) has an open approval request sent by the delegate;
  the previous quarter's pack carries a historic approval and a 'Filed outside platform (self-declared)' record.
- Blue Dune: an approval request whose link expired.
- Safwa: authority 'unclear' (DET record says any one partner, MOA signing clause says two together) blocks
  approval.
"""

from __future__ import annotations

import copy
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.time import utcnow
from app.demo import CO_ALNOOR, CO_BLUEDUNE, CO_SAFWA, PERSONA_UUIDS, demo_ct_year, demo_vat_quarters
from app.modules.approvals import service as svc
from app.modules.approvals.models import (
    Approval,
    ApprovalRequest,
    ApprovalStatusEvent,
    AuthorityHolder,
    GateDecision,
    ManualFilingRecord,
)
from app.modules.approvals.monitoring import DEFAULT_ROUTING
from app.modules.approvals.strings import DECLARATION_WORDING, DECLARATION_WORDING_VERSION
from app.modules.config.service import ensure_config, ensure_rule

ORDER = 60
PO = "Qeonix product owner"


def seed(db: Session) -> None:
    c = ensure_config
    # E6-S1
    c(db, "approval.flow_enabled", True, owner="DET pilot manager + Qeonix product owner", status="confirmed", label="return-pack approval flow; switched off automatically on a severity 1 approval exception (pilot stop)")
    c(db, "approval.wave_exit.blocked", False, owner="DET pilot manager", status="confirmed", label="set while a severity 1 approval exception has no recorded root cause and fix")
    c(db, "approval.submission_types_enabled", ["return_pack"], owner=PO, status="confirmed", label="only tax return packs (VAT, CT) have an approval flow in Phase 1")
    c(db, "approval.validity_days", 7, unit="calendar days", owner="pilot tax specialist (production: product with DET)", status="provisional", label="Phase 1 demo parameter, configurable 1 to 30, capped at the due date [OPEN]")
    c(db, "approval.validity_days.min", 1, unit="days", owner=PO, status="confirmed", label="package decision: 1 to 30")
    c(db, "approval.validity_days.max", 30, unit="days", owner=PO, status="confirmed", label="package decision: 1 to 30")
    c(db, "approval.request_link_days", 3, unit="days", owner=PO, status="confirmed", label="approval request link expiry (package decision)")
    c(db, "approval.step_up_max_age_minutes", None, unit="minutes", owner="Tech Lead", status="to_be_confirmed", label="Open (Q437): step-up session age; until set a fresh UAE PASS confirmation is asked at every approval")
    c(db, "approval.identity_assurance_by_action", {"approve_return": "SOP3", "grant_delegate_rights": "SOP3"}, owner="product/counsel", status="to_be_confirmed", label="UAE PASS level per action; enforced via identity.approval_min_assurance_level")
    c(db, "approval.reminder_interval_hours", None, unit="hours", owner=PO, status="to_be_confirmed", label="not given in source; reminders only, never auto-approve")
    c(db, "approval.remind_owner_rate_hours", 24, unit="hours", owner="UX", status="confirmed", label="'Remind the owner': 1 per request per 24 hours")
    c(db, "approval.uaepass_failure_help_threshold", 3, unit="count", owner="UX", status="confirmed", label="3 consecutive failures show 'Need help? Contact support'")
    c(db, "approval.reason_min_chars", 5, unit="chars", owner="UX", status="confirmed", label="after trimming")
    c(db, "approval.reason_max_chars", 500, unit="chars", owner="UX", status="confirmed", label="after trimming")
    c(db, "approval.joint_window_days", 7, unit="days", owner=PO, status="to_be_confirmed", label="joint approval window: value not given in source")
    c(db, "approval.retention", {"approval_records": "legal hold; longest counsel period", "identity_assertions": "legal hold; longest counsel period", "years": None}, owner="counsel/FTA", status="to_be_confirmed", label="no hard-coded year count [OPEN]")
    c(db, "approval.declaration_wording_version", DECLARATION_WORDING_VERSION, owner="counsel/FTA", status="to_be_confirmed", label="bilingual wording shown at approval; not a filing declaration")
    # E6-S2
    c(db, "delegate_rights.approve_submissions.enabled", False, owner="product + FTA written confirmation + legal expert", status="to_be_confirmed", label="Phase B delegate approval: OFF and hard-blocked in Phase 1")
    c(db, "approval.phase_b.enabled_companies", [], owner="product + FTA written confirmation + legal expert", status="to_be_confirmed", label="per-company Phase B switch (empty = OFF for every company)")
    c(db, "approval.delegate_grant.max_days", 365, unit="days", owner=PO, status="confirmed", label="product rule, not legal")
    c(db, "approval.delegate_grant.default_days", 90, unit="days", owner=PO, status="confirmed", label="form pre-fill")
    c(db, "approval.delegate_grant.reminder_days", 14, unit="days", owner=PO, status="confirmed", label="in-portal reminder before the grant end (package decision)")
    c(db, "approval.delegate_grant.default_scope", "single_return", owner="PM", status="confirmed", label="Option A single return by default (Q112)")
    c(db, "approval.delegate_grant.max_amount_field", "net payable amount", owner="Tech Lead", status="to_be_confirmed", label="Open (Q111/Q442): which field the optional maximum amount is compared with")
    c(db, "approval.delegate_grant.revocation_propagation", "immediate on next request", owner="Tech Lead", status="to_be_confirmed", label="Open (Q111)")
    # E6-S3
    c(db, "filing.live_adapter.enabled", False, owner=PO, status="confirmed", label="send switch OFF until the E1-S8 FTA row is confirmed live; no live EmaraTax adapter")
    c(db, "filing.submit_control_rendered", False, owner="UX", status="confirmed", label="Submit control hidden (not disabled) while the FTA row is incomplete")
    c(db, "filing.authority_due_dates", {}, owner="tax specialist", status="confirmed", label="authority's due date always prevails over the computed date; no-roll rule")
    c(db, "filing.roll_rule", "no_roll", owner="tax specialist", status="confirmed", label="changes only on FTA written confirmation")
    c(db, "filing.receipt_upload_max_mb", 10, unit="MB", owner="UX", status="confirmed", label="PDF, PNG, JPG; 'Attached by you, not verified'; demo only")
    c(db, "filing.idempotency_key_fields", ["approval_id", "pack_hash"], owner="engineering", status="to_be_confirmed", label="Open (Q414); Q119 proposal TRN + type + period + approval")
    c(db, "filing.read_back.schedule", None, owner="engineering", status="to_be_confirmed", label="Open (Q118/Q413): schedule, retries, limits")
    # E6-S4
    c(db, "approval.k23_target_pct", 100, unit="%", owner=PO, status="confirmed", label="any value below 100% is a breach")
    c(db, "approval.k24_target_hours", None, unit="hours", owner=PO, status="to_be_confirmed", label="no pass/fail until the product owner sets a target")
    c(db, "approval.compliance_job.schedule", {"k23": "daily", "k24": "weekly"}, owner="platform", status="confirmed", label="settled")
    c(db, "approval.compliance_job.stale_hours", 24, unit="hours", owner="platform", status="provisional", label="stale when the last successful run is older than one cycle")
    c(db, "approval.alert_routing", DEFAULT_ROUTING, owner="DET pilot manager", status="provisional", label="interim routing for pilot waves 1a-1c (Q127), placeholder")
    c(db, "approval.sla", {"sev1": {"ack_working_hours": 4, "contain_working_days": 1}, "sev2": {"ack_working_days": 1, "resolve_working_days": 3}}, owner="DET pilot manager", status="provisional", label="placeholders, adjustable by the DET pilot manager")
    c(db, "approval.alert_channels", ["in_portal", "role_mailbox_email"], owner=PO, status="confirmed", label="no SMS, no WhatsApp; IDs and codes only")
    r = ensure_rule
    r(db, "approval-validity-v1", "Approval validity window and voiding", version="v1", instrument="product-integrity control, not an FTA rule", source="package decision (lines 206-210)", effective_from=date(2025, 1, 1), status="provisional", owner_role="pilot tax specialist", parameters={"days": 7, "min": 1, "max": 30, "cap": "filing due date", "void_on": ["pack hash change", "rule version superseded", "source data refreshed or re-uploaded"]})
    r(db, "approval-authority-v1", "Authority-evidence model (Q110)", version="v1", instrument="configurable check, not a legal test; counsel to confirm", source="Q110", effective_from=date(2025, 1, 1), status="to_be_confirmed", owner_role="legal expert", parameters={"sources_in_order": ["DET licence/company record", "attested POA or company resolution (human-reviewed)", "trade licence/MOA signing clause"], "rule_types": ["any_one", "two_together", "unclear"], "unclear": "block and route to a reviewer", "delegates_count_toward_quorum": False})
    r(db, "filing-read-back-match-v1", "Read-back match rules and authority status map", version="v1", instrument="product control, to be confirmed with the FTA", source="Q119", effective_from=date(2025, 1, 1), status="to_be_confirmed", owner_role="Tech Lead", parameters={"exact": ["trn", "return_type", "period_start", "period_end", "reference", "amounts"], "status_map_version": "asm-v1", "unknown_status": "mismatch"})
    r(db, "filing-due-date-precedence-v1", "Due-date precedence (authority prevails, no roll)", version="v1", instrument="FDL 8/2017 (VAT +28 days), FDL 47/2022 (CT +9 months); confirm instruments", source="Q119", effective_from=date(2025, 1, 1), status="to_be_confirmed", owner_role="tax specialist", parameters={"precedence": ["authority", "computed (cross-check only)"], "roll_rule": "no_roll", "recommended_submit_by": "last working day before the statutory date"})


class _Actor:
    def __init__(self, uuid: str, name: str) -> None:
        self.identity_uuid, self.display_name, self.actor_key = uuid, name, None


def _demo_pack(db: Session, company_id: str, tax_type: str, period_id: str, template, *, created_days_ago: int, review_status: str = "under_review", locked: bool = False, filing_reference: str | None = None):
    from app.modules.drafts.models import DraftPack, DraftStatusHistory

    existing = db.scalar(select(DraftPack).where(DraftPack.company_id == company_id, DraftPack.tax_type == tax_type, DraftPack.period_id == period_id).limit(1))
    if existing is not None:
        return existing
    lines = copy.deepcopy(template.lines) if template is not None else [{"key": "tax" if tax_type == "ct" else "net_vat", "term": {"en": "Corporate tax" if tax_type == "ct" else "Net VAT payable or refundable", "ar": "ضريبة الشركات" if tax_type == "ct" else "صافي الضريبة المستحقة أو القابلة للاسترداد"}, "gloss": {"en": "", "ar": ""}, "value_fils": 0, "line_class": "calculated", "source_refs": [{"source": "Demo data"}], "no_source": False}]
    p = DraftPack(company_id=company_id, tax_type=tax_type, period_id=period_id, version=1, data_version=f"demo-{company_id}-{period_id}", rule_version=template.rule_version if template is not None else None, assumptions=copy.deepcopy(template.assumptions) if template is not None else [{"text": "Demo data", "citation": "E6 demo"}], lines=lines, sources=copy.deepcopy(template.sources) if template is not None else [], basis=copy.deepcopy(template.basis) if template is not None else {}, review_status=review_status, locked=locked, filing_reference=filing_reference, created_by_name="Demo data", created_at=utcnow() - timedelta(days=created_days_ago), is_demo=True)
    db.add(p)
    db.flush()
    db.add(DraftStatusHistory(pack_id=p.id, from_status=None, to_status="not_reviewed", system=True, at=p.created_at))
    db.add(DraftStatusHistory(pack_id=p.id, from_status="not_reviewed", to_status=review_status, actor_name="Demo data", system=False, at=p.created_at + timedelta(days=1)))
    db.flush()
    return p


def seed_demo(db: Session) -> None:
    if db.scalar(select(ApprovalRequest).where(ApprovalRequest.is_demo.is_(True)).limit(1)) is not None:
        return
    try:
        from app.modules.drafts import service as drafts
    except ImportError:  # pragma: no cover
        return
    now = utcnow()
    quarters, ct = demo_vat_quarters(), demo_ct_year()
    omar = _Actor(PERSONA_UUIDS["omar"], "Omar Haddad")
    # Al Noor: open approval request on the open quarter's VAT pack, ready for owner review (sent by the delegate).
    q_open = drafts.latest_pack(db, CO_ALNOOR, "vat", quarters.open.period_id)
    if q_open is None:
        try:
            q_open = drafts.create_pack(db, CO_ALNOOR, "vat", quarters.open.period_id, actor=omar, run_calculation=False, is_demo=True)
        except Exception:
            q_open = None
    if q_open is not None and not q_open.superseded and not q_open.locked:
        svc._new_request(db, q_open, requested_by=omar, role="delegate", is_demo=True)
    # Al Noor: the previous quarter's real pack carries a historic approval and a 'Filed outside platform
    # (self-declared)' record (approved and filed before its due date).
    holders = [h for h in svc.ensure_authority(db, CO_ALNOOR) if h.display_name == "Khalid Al Mansoori"]
    holder = holders[0] if holders else None
    if holder is not None and holder.identity_uuid is None:
        holder.identity_uuid = PERSONA_UUIDS["khalid"]
    q_prev = drafts.latest_pack(db, CO_ALNOOR, "vat", quarters.previous.period_id)
    if q_prev is not None and not q_prev.superseded and not q_prev.locked:
        _historic_approval(db, q_prev, quarters.previous, holder)
    # Blue Dune: request link expired.
    ct_template = drafts.latest_pack(db, CO_ALNOOR, "ct", ct.period_id)
    bd = _demo_pack(db, CO_BLUEDUNE, "ct", ct.period_id, ct_template, created_days_ago=6)
    req_bd = svc._new_request(db, bd, requested_by=omar, role="delegate", is_demo=True)
    req_bd.created_at, req_bd.link_expires_at = now - timedelta(days=5), now - timedelta(days=2)
    db.add(ApprovalStatusEvent(request_id=req_bd.id, from_status=req_bd.status, to_status="expired", reason_code="LINK_EXPIRED", at=req_bd.link_expires_at))
    req_bd.status, req_bd.status_reason = "expired", "LINK_EXPIRED"
    # Safwa: authority unclear (conflicting documents) blocks approval.
    svc.ensure_authority(db, CO_SAFWA)
    if db.scalar(select(AuthorityHolder).where(AuthorityHolder.company_id == CO_SAFWA, AuthorityHolder.is_demo.is_(True)).limit(1)) is None:
        db.add(AuthorityHolder(company_id=CO_SAFWA, display_name="Khalid Al Mansoori", capacity="partner", source_document="MOA signing clause (uploaded, human-reviewed) (Demo data)", rule_type="two_together", quorum_n=2, determination_note="conflicts with the DET licence record (any one partner): unclear", is_demo=True))
        db.flush()
    sf = _demo_pack(db, CO_SAFWA, "vat", quarters.open.period_id, q_open, created_days_ago=2)
    svc._new_request(db, sf, requested_by=None, role="system", is_demo=True, route=False)
    db.flush()


def _historic_approval(db: Session, pack, period, holder: AuthorityHolder | None) -> None:
    """Request (sent by the delegate), owner approval, release and manual filing record on a real pack, dated
    along the quarter's own timeline; the pack ends 'Filed (user-confirmed)' and locked, like the live flow."""
    from app.modules.drafts import service as drafts

    khalid = _Owner(PERSONA_UUIDS["khalid"], "Khalid Al Mansoori")
    created = pack.created_at + timedelta(days=1)
    decided = created + timedelta(hours=30)
    filed_at = decided + timedelta(days=3)
    h = drafts.pack_hash(pack)
    req = ApprovalRequest(company_id=CO_ALNOOR, pack_id=pack.id, return_type="vat", period_id=period.period_id, period_start=period.start, period_end=period.end, due_date=period.due, due_date_source="computed", amounts=svc.pack_amounts(pack), rule_version=pack.rule_version, human_review_status=pack.review_status, draft_content_hash=h, pack_version=pack.version, authority_rule_type="any_one", quorum_n=1, entitled_approvers=[{"name": "Khalid Al Mansoori", "capacity": "owner", "kind": "authority_holder"}], status="decided", status_reason="APPROVED", requested_by_name="Omar Haddad", requested_by_role="delegate", created_at=created, link_expires_at=created + timedelta(days=3), decided_at=decided, is_demo=True)
    db.add(req)
    db.flush()
    a = Approval(id="APV-DEMO-ALNOOR-PREV", request_id=req.id, company_id=CO_ALNOOR, pack_id=pack.id, decision="approve", approver_uuid=PERSONA_UUIDS["khalid"], approver_name="Khalid Al Mansoori", assurance_level="SOP3", capacity="owner", display_role="Owner", authority_evidence_ref=holder.id if holder else None, action_approved="release_for_manual_filing", data_version_hash=h, pack_version=pack.version, rule_version_ids=svc.rule_version_ids(pack), ai_generated_label="AI-generated draft: not a filed return", human_review_status=pack.review_status, declaration_wording_version_id=DECLARATION_WORDING_VERSION, declaration_wording=DECLARATION_WORDING, channel="web/UAE PASS click-to-approve", device_family="desktop", decided_at=decided, valid_until=decided + timedelta(days=7), validity_days=7, status="active", is_demo=True)
    db.add(a)
    for path, at in (("manual_release", decided + timedelta(days=1)), ("manual_filing_record", filed_at)):
        db.add(GateDecision(company_id=CO_ALNOOR, pack_id=pack.id, data_version_hash=h, approval_id=a.id, path=path, caller_type="user", outcome="pass", tax_type="vat", at=at))
    reference = "FTA" + period.period_id.replace("-", "") + "A7731"
    db.add(ManualFilingRecord(id="MFR-DEMO-ALNOOR-PREV", company_id=CO_ALNOOR, pack_id=pack.id, request_id=req.id, approval_id=a.id, data_version_hash=h, tax_type="vat", state="filed_outside_self_declared", filed_date=filed_at.date(), authority_reference=reference, self_filed_confirmed=True, recorded_by_uuid=PERSONA_UUIDS["khalid"], recorded_by_name="Khalid Al Mansoori", recorded_by_role="owner", recorded_at=filed_at + timedelta(hours=2), is_demo=True))
    db.flush()
    drafts.set_approval_status(db, pack.id, "approved_for_submission", actor=khalid, expected_hash=h)
    drafts.set_approval_status(db, pack.id, "filed_user_confirmed", actor=khalid, expected_hash=h, filing_reference=reference)
    from app.modules.drafts.models import DraftStatusHistory

    for row in db.scalars(select(DraftStatusHistory).where(DraftStatusHistory.pack_id == pack.id, DraftStatusHistory.to_status.in_(("approved_for_submission", "filed_user_confirmed")))):
        row.at = decided if row.to_status == "approved_for_submission" else filed_at + timedelta(hours=2)
    db.flush()


class _Owner(_Actor):
    """Owner actor for the drafts status hook (it reads the company role)."""

    def __init__(self, uuid: str, name: str) -> None:
        from app.modules.companies.models import CompanyRole

        super().__init__(uuid, name)
        self.session_id, self.staff_roles = "demo-seed-session", []
        self._roles = [CompanyRole(identity_uuid=uuid, company_id=CO_ALNOOR, role="owner", functions=["all"])]

    def roles_for(self, company_id: str):
        return self._roles

    def primary_role(self):
        return self._roles[0].role
