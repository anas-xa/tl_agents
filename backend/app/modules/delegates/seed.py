"""Configuration keys (E1-S6 §3, E1-S2 §3) and demo fixtures for delegation, grants, quarantine and hold states."""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.time import utcnow
from app.modules.config.service import ensure_config, ensure_rule

ORDER = 12


def seed(db: Session) -> None:
    owner_tl = "Qeonix tech lead"
    ensure_config(db, "delegates.invitation_validity_days", 7, unit="days", owner=owner_tl, status="provisional", label="withdrawable; resend resets the clock")
    ensure_config(db, "delegates.max_delegates_per_company", 10, unit="count", owner=owner_tl, status="provisional", label="active or pending")
    ensure_config(db, "delegates.max_companies_per_delegate", 50, unit="count", owner=owner_tl, status="provisional")
    ensure_config(db, "delegates.phase_b_switch", False, owner="Legal / PM", status="to_be_confirmed", label="OPEN: release per right only after a licensed UAE law firm and the relevant authorities confirm; never auto-enabled")
    ensure_config(db, "delegates.rights_cache_ttl_seconds", 30, unit="seconds", owner=owner_tl, status="provisional", label="revocation p95 5 s, never > 60 s; client background check interval")
    ensure_config(db, "delegates.det_authority_cache_hours", 24, unit="hours", owner=owner_tl, status="provisional", label="DET record pulled at session start and company switch; daily full reconciliation")
    ensure_config(db, "delegates.det_authority_stale_hours", 48, unit="hours", owner=owner_tl, status="provisional", label="older data: view and prepare only; consent, delegation, approval, subscription change blocked")
    ensure_config(db, "delegates.sc15_page_size", 50, unit="rows", owner=owner_tl, status="provisional")
    ensure_config(db, "delegates.sc15_retention_months", 24, unit="months", owner="Legal", status="to_be_confirmed", label="illustrative, for production")
    ensure_config(db, "delegates.record_retention_years", 5, unit="years", owner="Counsel", status="to_be_confirmed", label="OPEN: >= 5 years after end of delegation or relevant tax period; confirm before go-live")
    # superseded by det_dashboard.min_group_size (one platform-wide N, kpis.suppression)
    # ensure_config(db, "delegates.sc14_min_group_size", 10, unit="companies", owner="Domain data", status="provisional", label="estimate, versioned; Q9/Q22 say 5 - conflict, story AC default 10 used")
    ensure_config(db, "delegates.sc14_refresh", "daily 02:00 Asia/Dubai", owner="Domain data", status="provisional")
    ensure_config(db, "delegates.case_grant_expiry_days", 90, unit="days", owner="Legal", status="to_be_confirmed", label="illustrative, for production")
    ensure_config(db, "delegates.signatory_change_max_hold_days", 30, unit="days", owner=owner_tl, status="provisional", label="then alert DET operations; never auto-released")
    ensure_config(db, "delegates.delegate_dormancy_flag_days", 180, unit="days", owner="Platform product owner", status="provisional", label="flagged to the owner for confirmation; stays active")
    ensure_config(db, "delegates.staff_dormancy_suspend_days", 90, unit="days", owner="Platform product owner", status="provisional", label="suspended, re-approval needed")
    ensure_config(db, "delegates.separation_of_duties_scope", "submissions", owner="PM", status="provisional", label="configurable default: prepare/approve separation on submissions only")
    ensure_config(db, "delegates.queued_job_fail_after_hours", 24, unit="hours", owner=owner_tl, status="provisional", label="for production")
    ensure_config(db, "delegates.firewall_rule_version", "firewall-v1", owner="Qeonix product owner", status="provisional", label="DET related-entity links are a conservative first screen only")
    ensure_config(db, "delegates.authorisation_evidence_expiry_default_days", 365, unit="days", owner="DET verifier", status="to_be_confirmed", label="default for production; per record")
    ensure_rule(db, "auditor-firewall-v1", "Auditor firewall: related-entity screen from DET licence records", instrument="Federal Law 12/2014 (confirm instrument); IESBA Code / ISA as adopted (confirm version)", status="to_be_confirmed", owner_role="Qeonix product owner", parameters={"links": ["related_entity_group", "shared_licence_person"], "result_values": ["conflict_found", "no_conflict_found_in_det_records"], "manual_flags_block": True, "independence_declaration_required": True})
    ensure_rule(db, "delegation-authority-v1", "Delegate authority derives from the granting owner's DET-record authority", instrument="Product rule (not a DET rule); legal confirmation of delegation assumption OPEN", status="to_be_confirmed", owner_role="Legal / PM", parameters={"phase_a_functions": ["view_dashboard", "prepare_data"], "phase_b_locked": ["grant_bank_consent", "approve_submissions", "change_subscription"], "reconfirmation_window_days": 30})


def seed_demo(db: Session) -> None:
    from app.demo import CO_ALNOOR, CO_GULFTECH, CO_SAFWA, PERSONA_UUIDS
    from app.modules.companies.models import CompanyRole
    from app.modules.delegates.models import AccessGrant, DelegateChange, DelegateInvitation, QuarantinedDraft
    from app.modules.delegates.service import set_no_owner_state
    from app.modules.identity.service import hash_emirates_id

    now = utcnow()
    # Change history for Omar's three existing delegations (rights records live on CompanyRole).
    for r in db.scalars(select(CompanyRole).where(CompanyRole.identity_uuid == PERSONA_UUIDS["omar"], CompanyRole.role == "delegate")):
        if db.scalar(select(DelegateChange).where(DelegateChange.subject_ref == r.id, DelegateChange.change_type == "accepted")) is None:
            db.add(DelegateChange(company_id=r.company_id, change_type="accepted", delegate_identity_uuid=r.identity_uuid, delegate_label="Omar Haddad", subject_ref=r.id, after={"toggles": ["prepare_data", "view_dashboard"]}, changed_by_uuid=r.granted_by_uuid, changed_by_role="owner", changed_at=r.granted_at))
        if db.scalar(select(DelegateInvitation).where(DelegateInvitation.company_role_id == r.id)) is None:
            db.add(DelegateInvitation(company_id=r.company_id, emirates_id_hash=hash_emirates_id("784-1990-1111111-3"), entered_name="Omar Haddad", email="omar@example.ae", functions=r.functions, rights=r.rights, token=f"demo-accepted-{r.id}", status="accepted", invited_by_uuid=r.granted_by_uuid or "det_onboarding", invited_at=r.granted_at - timedelta(days=2), expires_at=r.granted_at + timedelta(days=5), accepted_at=r.granted_at, identity_uuid=r.identity_uuid, company_role_id=r.id, is_demo=True))
    # One pending invitation on Safwa (Demo data). The Emirates ID belongs to no mock persona.
    if db.scalar(select(DelegateInvitation).where(DelegateInvitation.token == "demo-pending-safwa")) is None:
        db.add(DelegateInvitation(company_id=CO_SAFWA, emirates_id_hash=hash_emirates_id("784-1992-2424242-7"), entered_name="Fatima Al Zaabi", email="fatima@example.ae", mobile="+971500000000", functions=["bookkeeping", "tax_preparation"], rights=["view", "prepare"], token="demo-pending-safwa", status="pending", invited_by_uuid=PERSONA_UUIDS["khalid"], invited_at=now - timedelta(days=1), expires_at=now + timedelta(days=6), is_demo=True))
        db.add(DelegateChange(company_id=CO_SAFWA, change_type="invited", delegate_label="Fatima Al Zaabi", after={"toggles": ["prepare_data", "view_dashboard"]}, changed_by_uuid=PERSONA_UUIDS["khalid"], changed_by_role="owner", changed_at=now - timedelta(days=1)))
    # One quarantined draft for Gulf Tech (Demo data): a bookkeeping period Omar edited before the no-owner state.
    if db.scalar(select(QuarantinedDraft).where(QuarantinedDraft.draft_ref == "bk_gulftech_2026_09")) is None:
        db.add(QuarantinedDraft(company_id=CO_GULFTECH, draft_type="bookkeeping_period", draft_ref="bk_gulftech_2026_09", delegate_identity_uuid=PERSONA_UUIDS["omar"], touched_action="edited", data_version="v3", quarantined_at=now - timedelta(days=3), is_demo=True))
    # Gulf Tech: its only owner-level person on the DET record has no Emirates ID -> no-owner state.
    set_no_owner_state(db, CO_GULFTECH)
    # A per-case grant for Hassan (tax specialist) on an Al Noor case.
    if db.scalar(select(AccessGrant).where(AccessGrant.case_ref == "case_alnoor_1", AccessGrant.recipient_identity_uuid == PERSONA_UUIDS["hassan"])) is None:
        db.add(AccessGrant(company_id=CO_ALNOOR, case_ref="case_alnoor_1", recipient_identity_uuid=PERSONA_UUIDS["hassan"], recipient_role="specialist", purpose="tax_escalation", data_scope=["tax_profile", "draft_returns"], granted_by_uuid=PERSONA_UUIDS["khalid"], granted_by_capacity="owner", granted_at=now - timedelta(days=2), expires_at=now + timedelta(days=88), is_demo=True))
    db.flush()
