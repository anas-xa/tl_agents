"""E6 approval workflow and controlled submission (E6-S1..E6-S4)."""

from __future__ import annotations

import pathlib
import re
from datetime import date, datetime, timedelta

import pytest
from sqlalchemy import select

from app.core.errors import Conflict, Forbidden, SwitchedOff
from app.core.time import dubai_today, utcnow
from app.demo import CO_ALNOOR, CO_BLUEDUNE, CO_GULFTECH, CO_SAFWA, PERSONA_UUIDS
from app.modules.access.service import Principal
from app.modules.approvals import adapter, monitoring
from app.modules.approvals import service as svc
from app.modules.approvals.models import (
    Approval,
    ApprovalRequest,
    AuthorityHolder,
    ComplianceAlert,
    ComplianceException,
    GateDecision,
    ManualFilingEdit,
    ManualFilingRecord,
)
from app.modules.audit.models import AuditEvent
from app.modules.companies.models import CompanyRole
from app.modules.config.service import get_config, set_config
from app.modules.drafts.models import DraftPack
from tests.conftest import sign_in

A = f"/api/companies/{CO_ALNOOR}/approvals"
G = f"/api/companies/{CO_ALNOOR}/delegate-grants"


def _events(db, event_type: str) -> list[AuditEvent]:
    db.expire_all()
    return list(db.scalars(select(AuditEvent).where(AuditEvent.event_type == event_type)))


def _open(client, base: str = A) -> dict:
    body = client.get(base).json()
    return next(r for r in body["awaiting"] if r["status"] == "open")


def _approve(client, req: dict, **kw) -> object:
    payload = {"expected_hash": req["draft_content_hash"], "reviewed_figures": True, "uaepass": "confirmed"} | kw
    return client.post(f"{A}/{req['request_id']}/approve", json=payload)


def _principal(uuid: str, name: str, company_id: str = CO_ALNOOR, role: str = "owner", level: str = "SOP3") -> Principal:
    return Principal(identity_uuid=uuid, actor_key=f"key-{uuid}", display_name=name, assurance_level=level, profile_type=1, language="en", session_id=f"sess-{uuid}", company_roles=[CompanyRole(identity_uuid=uuid, company_id=company_id, role=role, functions=["all"], status="active")], det_match_result="matched")


def _phase_b(db, on: bool, companies: list[str] | None = None) -> None:
    set_config(db, "delegate_rights.approve_submissions.enabled", on, changed_by="test")
    set_config(db, "approval.phase_b.enabled_companies", companies if companies is not None else ([CO_ALNOOR] if on else []), changed_by="test")
    db.commit()


# --- E6-S1 -----------------------------------------------------------------------------------------


def test_demo_states_and_request_contents(client, db):
    sign_in(client, "khalid")
    body = client.get(A).json()
    assert body["role"] == "owner" and body["flow_enabled"] is True and body["phase_b_on"] is False
    req = _open(client)
    assert req["return_type"] == "vat" and req["period_id"] == "2026-Q2" and req["submission_type"] == "return_pack"
    assert req["due_date"] and req["amounts"] and req["rule_version"] and req["ai_label"] == "AI-prepared draft, not yet signed off"
    assert req["human_review_label"]["en"] == "Under review" and req["entitlement"] == {"allowed": True, "reason_code": None}
    assert req["filing"]["state"] == "not_filed" and req["filing"]["submit_control_rendered"] is False and req["filing"]["read_back"] == "Not available"
    hist = next(r for r in body["requests"] if r["period_id"] == "2026-Q1")
    assert hist["approved_by"]["display_role"] == "Owner" and hist["filing"]["state"] == "filed_outside_self_declared"
    assert hist["filing"]["label"]["en"] == "Filed outside platform (self-declared)" and hist["filing"]["not_verified_by_authority"] is True
    assert "Not verified by the tax authority" in hist["filing"]["banner"] and hist["filing"]["submitted_by"] == "Khalid Al Mansoori"
    assert any(r["submission_status"] == "filed_outside_self_declared" for r in body["history"])
    # Safwa: authority unclear blocks approval
    s = client.get(f"/api/companies/{CO_SAFWA}/approvals").json()
    blocked = next(r for r in s["requests"] if r["status"] == "blocked")
    assert blocked["status_reason"] == "AUTHORITY_UNCLEAR" and blocked["authority_rule_type"] == "unclear"
    r = client.post(f"/api/companies/{CO_SAFWA}/approvals/{blocked['request_id']}/approve", json={"expected_hash": blocked["draft_content_hash"], "reviewed_figures": True})
    assert r.status_code == 403 and r.json()["error"] == "AUTHORITY_UNCLEAR"
    client.cookies.clear()
    # Blue Dune: request link expired (remote owner sees requests and history)
    sign_in(client, "priya")
    bd = client.get(f"/api/companies/{CO_BLUEDUNE}/approvals").json()
    assert bd["role"] == "remote_owner" and any(r["status"] == "expired" for r in bd["requests"])


def test_approval_binds_to_hash_records_evidence_and_voids_on_change(client, db):
    sign_in(client, "khalid")
    req = _open(client)
    r = _approve(client, req, expected_hash="0" * 64)
    assert r.status_code == 409 and r.json()["error"] == "HASH_MISMATCH" and "is no longer the latest. Nothing was approved or filed." in r.json()["message"]
    assert _events(db, "HASH_MISMATCH_REFUSED")
    r = _approve(client, req)
    assert r.status_code == 200, r.text
    out = r.json()
    a = out["approval"]
    assert out["status"] == "approved" and a["approval_id"] and a["data_version_hash"] == req["draft_content_hash"] and a["capacity"] == "owner"
    assert a["assurance_level"] == "SOP3" and a["authority_evidence_ref"] and a["action_approved"] == "release_for_manual_filing" and a["rule_version_ids"]
    assert a["declaration_wording_version_id"] == "apw-v1" and a["session_ref"] and a["valid_until"] and a["decided_at"]
    assert out["receipt"]["message"] == "Your decision has been recorded." and "not a filing and not tax advice" in out["receipt"]["validity_line"]
    pack = client.get(f"/api/companies/{CO_ALNOOR}/drafts/{req['pack_id']}").json()
    assert pack["review_status"] == "approved_for_submission"
    again = _approve(client, req)
    assert again.status_code == 409 and again.json()["error"] == "ALREADY_DECIDED"
    # any change to the figures voids the approval immediately; the gate refuses it
    e = client.post(f"/api/companies/{CO_ALNOOR}/drafts/{req['pack_id']}/edit", json={"key": "net_vat", "value_fils": 1, "reason_code": "figure_corrected"})
    assert e.status_code == 200, e.text
    detail = client.get(f"{A}/requests/{req['request_id']}").json()
    assert detail["approval_valid"] is False and detail["approved_by"]["status"] == "superseded"
    f = client.post(f"{A}/{req['request_id']}/filing", json={"filed_date": dubai_today().isoformat(), "self_filed_confirmed": True})
    assert f.status_code == 409 and f.json()["error"] == "GATE_BLOCKED" and f.json()["details"]["cause"] == "data_changed_since_approval"


def test_new_version_supersedes_request_and_raises_new_one_informed_decision(client, db):
    sign_in(client, "khalid")
    old = _open(client)
    new_pack = client.post(f"/api/companies/{CO_ALNOOR}/drafts", json={"tax_type": "vat", "period_id": "2026-Q2", "what_changed": "bank data pulled"}).json()
    body = client.get(A).json()
    old_now = next(r for r in body["requests"] if r["request_id"] == old["request_id"])
    assert old_now["status"] == "superseded" and old_now["superseded_by"]
    new = next(r for r in body["awaiting"] if r["pack_id"] == new_pack["id"])
    assert new["status"] == "open" and new["not_reviewed_by_human"] is True
    r = _approve(client, old)
    assert r.status_code == 409 and r.json()["error"] == "REQUEST_SUPERSEDED"
    r = _approve(client, new)
    assert r.status_code == 422 and r.json()["error"] == "INFORMED_DECISION_REQUIRED"
    r = _approve(client, new, informed_unreviewed=True, reviewed_figures=False)
    assert r.status_code == 422 and r.json()["error"] == "REVIEW_TICK_REQUIRED"
    r = _approve(client, new, informed_unreviewed=True)
    assert r.status_code == 200 and r.json()["approval"]["informed_unreviewed_decision"] is True and r.json()["approval"]["human_review_status"] == "not_reviewed"


def test_validity_window_cap_and_expiry(client, db):
    t0 = datetime(2026, 9, 1, 8, 0, 0)
    set_config(db, "approval.validity_days", 1, changed_by="test")
    v = svc.compute_valid_until(db, t0, None)
    assert v["valid_until"] == t0 + timedelta(days=1) and v["days"] == 1
    set_config(db, "approval.validity_days", 7, changed_by="test")
    v = svc.compute_valid_until(db, t0, date(2026, 9, 30))
    assert v["valid_until"] == t0 + timedelta(days=7) and v["capped_at_due_date"] is False
    v = svc.compute_valid_until(db, t0, date(2026, 9, 3))  # due date closer than the window: capped, warned
    assert v["capped_at_due_date"] is True and v["warn_due_closer"] is True and v["valid_until"] == datetime(2026, 9, 3, 19, 59, 59)
    v = svc.compute_valid_until(db, t0, date(2026, 9, 8))  # exact boundary: window end vs end of due date in GST
    assert v["valid_until"] == t0 + timedelta(days=7) and v["capped_at_due_date"] is False
    set_config(db, "approval.validity_days", 45, changed_by="test")
    assert svc.compute_valid_until(db, t0, None)["days"] == 30  # configurable 1 to 30
    set_config(db, "approval.validity_days", 7, changed_by="test")
    db.commit()
    sign_in(client, "khalid")
    req = _open(client)
    assert _approve(client, req).status_code == 200
    db.expire_all()
    a = db.scalar(select(Approval).where(Approval.request_id == req["request_id"]))
    assert svc.approval_state(db, a, now=a.valid_until - timedelta(seconds=1)) == (True, None)
    assert svc.approval_state(db, a, now=a.valid_until + timedelta(seconds=1)) == (False, "approval_expired")
    assert a.status == "expired"
    db.commit()
    f = client.post(f"{A}/{req['request_id']}/filing", json={"filed_date": dubai_today().isoformat(), "self_filed_confirmed": True})
    assert f.status_code == 409 and f.json()["details"]["cause"] == "approval_expired"
    hist = client.get(A).json()["history"]
    assert hist[0]["needs_attention"] == "approval expired, review and approve again"


def test_request_link_expiry_and_no_auto_approval(client, db):
    sign_in(client, "khalid")
    req = _open(client)
    row = db.get(ApprovalRequest, req["request_id"])
    row.link_expires_at = utcnow() - timedelta(minutes=1)
    db.commit()
    r = _approve(client, req)
    assert r.status_code == 409 and r.json()["error"] == "REQUEST_EXPIRED" and r.json()["message"] == "This approval request has expired. A new request will be raised."
    out = svc.sweep(db)
    db.commit()
    assert db.scalar(select(Approval).where(Approval.request_id == req["request_id"])) is None  # a timeout never counts as approval
    assert isinstance(out, dict)


def test_joint_authority_quorum_and_unclear(client, db):
    holders = svc.ensure_authority(db, CO_ALNOOR)
    for h in holders:
        h.rule_type, h.quorum_n = "two_together", 2
    db.add(AuthorityHolder(company_id=CO_ALNOOR, identity_uuid="uuid-partner-two", display_name="Partner Two", capacity="partner", source_document="attested company resolution", rule_type="two_together", quorum_n=2))
    db.commit()
    khalid = _principal(PERSONA_UUIDS["khalid"], "Khalid Al Mansoori")
    partner = _principal("uuid-partner-two", "Partner Two")
    req = db.scalar(select(ApprovalRequest).where(ApprovalRequest.company_id == CO_ALNOOR, ApprovalRequest.status == "open"))
    out = svc.approve(db, khalid, CO_ALNOOR, req.id, expected_hash=req.draft_content_hash, reviewed_figures=True)
    assert out["status"] == "pending_joint" and out["required"] == 2
    assert db.get(DraftPack, req.pack_id).review_status != "approved_for_submission"
    with pytest.raises(Conflict) as e:
        svc.approve(db, khalid, CO_ALNOOR, req.id, expected_hash=req.draft_content_hash, reviewed_figures=True)
    assert e.value.reason_code == "ALREADY_APPROVED_BY_YOU"
    out = svc.approve(db, partner, CO_ALNOOR, req.id, expected_hash=req.draft_content_hash, reviewed_figures=True)
    assert out["status"] == "approved"
    rows = list(db.scalars(select(Approval).where(Approval.request_id == req.id)))
    assert {r.status for r in rows} == {"active"} and len(rows) == 2
    assert db.get(DraftPack, req.pack_id).review_status == "approved_for_submission"
    db.commit()
    # a delegate never counts toward the quorum
    _phase_b(db, True)
    omar = _principal(PERSONA_UUIDS["omar"], "Omar Haddad", role="delegate")
    req2 = db.scalar(select(ApprovalRequest).where(ApprovalRequest.company_id == CO_SAFWA))
    pack = db.get(DraftPack, req2.pack_id)
    with pytest.raises((Forbidden, SwitchedOff)):
        svc.entitlement(db, omar, req2, pack)
    # conflicting documents -> unclear: request creation is blocked and routed to a reviewer
    db.add(AuthorityHolder(company_id=CO_ALNOOR, display_name="MOA signatory", capacity="manager", source_document="MOA signing clause", rule_type="any_one"))
    db.commit()
    assert svc.authority_rule(db, CO_ALNOOR) == ("unclear", 0)
    new = svc._new_request(db, pack=db.get(DraftPack, req.pack_id), requested_by=khalid, role="owner")
    assert new.status == "blocked" and new.status_reason == "AUTHORITY_UNCLEAR" and new.escalation_case_id
    db.commit()


def test_expired_authority_and_refusals_are_logged(client, db):
    h = next(x for x in svc.ensure_authority(db, CO_ALNOOR) if x.display_name == "Khalid Al Mansoori")
    h.valid_to = dubai_today() - timedelta(days=1)
    db.commit()
    sign_in(client, "khalid")
    req = _open(client)
    r = _approve(client, req)
    assert r.status_code == 403 and r.json()["error"] == "AUTHORITY_UNCLEAR"
    client.cookies.clear()
    for persona in ("layla", "sara", "noura", "hassan"):
        sign_in(client, persona)
        r = _approve(client, req)
        assert r.status_code == 403, persona
        client.cookies.clear()
    sign_in(client, "noeid")
    r = client.get(f"/api/companies/{CO_GULFTECH}/approvals")
    assert r.status_code == 403 and r.json()["error"] == "NO_OWNER_ROLE"
    r = client.post(f"/api/companies/{CO_GULFTECH}/delegate-grants", json={"delegate_uuid": PERSONA_UUIDS["omar"], "tax_types": ["vat"]})
    assert r.status_code == 403 and r.json()["error"] == "NO_OWNER_ROLE"
    assert len(_events(db, "APPROVAL_REFUSED")) >= 2 and _events(db, "ACCESS_REFUSED")


def test_step_up_refusal_for_sop2_remote_owner(client, db):
    sign_in(client, "omar")
    bd = client.get(f"/api/companies/{CO_BLUEDUNE}/approvals").json()
    expired = next(r for r in bd["requests"] if r["status"] == "expired")
    new = client.post(f"/api/companies/{CO_BLUEDUNE}/approvals/requests", json={"pack_id": expired["pack_id"]})
    assert new.status_code == 200 and new.json()["status"] == "open"
    client.cookies.clear()
    sign_in(client, "priya")
    req = new.json()
    r = client.post(f"/api/companies/{CO_BLUEDUNE}/approvals/{req['request_id']}/approve", json={"expected_hash": req["draft_content_hash"], "reviewed_figures": True})
    assert r.status_code == 403 and r.json()["error"] == "LEVEL_TOO_LOW_FOR_ACTION"
    assert _events(db, "STEP_UP_REQUIRED")
    # when the configured level allows SOP2, the owner abroad approves as 'Owner abroad'
    set_config(db, "identity.approval_min_assurance_level", "SOP2", changed_by="test")
    db.commit()
    r = client.post(f"/api/companies/{CO_BLUEDUNE}/approvals/{req['request_id']}/approve", json={"expected_hash": req["draft_content_hash"], "reviewed_figures": True})
    assert r.status_code == 200, r.text
    assert r.json()["approval"]["display_role"] == "Owner abroad"


def test_uaepass_failure_cancel_and_decline(client, db):
    sign_in(client, "khalid")
    req = _open(client)
    for i in range(1, 4):
        r = _approve(client, req, uaepass="failed")
        assert r.status_code == 403 and r.json()["error"] == "REAUTH_FAILED"
        assert r.json()["details"]["show_support"] is (i >= 3)
    r = _approve(client, req, uaepass="cancelled")
    assert r.status_code == 403 and r.json()["error"] == "UAEPASS_CANCELLED" and r.json()["message"] == "Sign-in was cancelled. Your approval was not saved. Nothing has been filed."
    db.expire_all()
    assert db.scalar(select(Approval).where(Approval.request_id == req["request_id"])) is None  # no partial record
    r = client.post(f"{A}/{req['request_id']}/decline", json={"decision": "request_changes", "reason": " ok ", "expected_hash": req["draft_content_hash"]})
    assert r.status_code == 422 and r.json()["message"] == "Please add a reason (at least 5 characters)."
    r = client.post(f"{A}/{req['request_id']}/decline", json={"decision": "request_changes", "reason": "Please re-check the rent invoice", "expected_hash": req["draft_content_hash"]})
    assert r.status_code == 200 and r.json()["status"] == "in_preparation" and r.json()["approval"]["decision"] == "request_changes"
    f = client.post(f"{A}/{req['request_id']}/filing", json={"filed_date": dubai_today().isoformat(), "self_filed_confirmed": True})
    assert f.status_code == 409 and f.json()["details"]["cause"] == "approval_missing"


# --- E6-S2 -----------------------------------------------------------------------------------------


def test_delegate_refused_while_switch_off(client, db):
    sign_in(client, "omar")
    req = _open(client)
    assert req["entitlement"] == {"allowed": False, "reason_code": "RIGHT_SWITCHED_OFF"}
    r = _approve(client, req)
    assert r.status_code == 403 and r.json()["error"] == "RIGHT_SWITCHED_OFF"
    r = client.post(G, json={"delegate_uuid": PERSONA_UUIDS["omar"], "tax_types": ["vat"], "period_id": "2026-Q2"})
    assert r.status_code == 403 and r.json()["error"] == "NOT_OWNER_DELEGATE" and r.json()["message"] == "Only the owner can give approval rights."
    mine = client.get(G).json()
    assert mine["locked"] is True and mine["grants"] == [] and mine["phase_b_off_text"]["en"].startswith("Approval rights are not available yet.")
    f = client.post(f"{A}/{req['request_id']}/filing", json={"filed_date": dubai_today().isoformat(), "self_filed_confirmed": True})
    assert f.status_code == 403 and f.json()["error"] == "NO_FILING_RIGHT"
    client.cookies.clear()
    sign_in(client, "khalid")
    r = client.post(G, json={"delegate_uuid": PERSONA_UUIDS["omar"], "tax_types": ["vat"], "period_id": "2026-Q2"})
    assert r.status_code == 403 and r.json()["error"] == "RIGHT_SWITCHED_OFF"
    assert _events(db, "ENTITLEMENT_REFUSED")


def test_delegate_grant_validation_scope_and_revocation_when_switch_on(client, db):
    _phase_b(db, True)
    set_config(db, "identity.approval_min_assurance_level", "SOP2", changed_by="test")
    db.commit()
    sign_in(client, "khalid")
    g = client.get(G).json()
    today = dubai_today()
    assert g["phase_b_on"] is True and g["defaults"]["default_days"] == 90 and g["defaults"]["max_days"] == 365
    assert g["defaults"]["end_date"] == g["defaults"]["caps"]["licence_expiry"]  # 90-day pre-fill capped at licence expiry
    bad = [
        ({"start_date": today.isoformat(), "end_date": today.isoformat()}, "DATES_INVALID"),
        ({"start_date": (today - timedelta(days=1)).isoformat()}, "START_IN_PAST"),
        ({"end_date": (today + timedelta(days=60)).isoformat()}, "GRANT_END_AFTER_CAP"),
    ]
    for extra, code in bad:
        r = client.post(G, json={"delegate_uuid": PERSONA_UUIDS["omar"], "tax_types": ["vat"], "period_id": "2026-Q2"} | extra)
        assert r.status_code == 422 and r.json()["error"] == code, (code, r.text)
    set_config(db, "approval.delegate_grant.max_days", 10, changed_by="test")
    db.commit()
    r = client.post(G, json={"delegate_uuid": PERSONA_UUIDS["omar"], "tax_types": ["vat"], "period_id": "2026-Q2", "end_date": (today + timedelta(days=20)).isoformat()})
    assert r.status_code == 422 and r.json()["error"] == "GRANT_TOO_LONG"
    set_config(db, "approval.delegate_grant.max_days", 365, changed_by="test")
    db.commit()
    # out-of-scope grant (corporate tax only) does not let the delegate approve a VAT return
    ct = client.post(G, json={"delegate_uuid": PERSONA_UUIDS["omar"], "tax_types": ["ct"], "period_id": "FY2025"})
    assert ct.status_code == 200, ct.text
    assert ct.json()["step_up_proof"]["assurance_level"] == "SOP3"
    assert ct.json()["confirmation_wording_version"] == "grw-v1" and ct.json()["authority_basis"]
    client.cookies.clear()
    sign_in(client, "omar")
    req = _open(client)
    r = _approve(client, req)
    assert r.status_code == 403 and r.json()["error"] == "NO_APPROVAL_RIGHT"
    client.cookies.clear()
    sign_in(client, "khalid")
    vat = client.post(G, json={"delegate_uuid": PERSONA_UUIDS["omar"], "tax_types": ["vat"], "period_id": "2026-Q2"}).json()
    client.cookies.clear()
    sign_in(client, "omar")
    r = _approve(client, req)
    assert r.status_code == 200, r.text
    a = r.json()["approval"]
    assert a["capacity"] == "delegate" and a["display_role"] == "Delegate with owner's delegated right" and a["delegation_basis"]["grant_id"] == vat["grant_id"]
    assert a["delegation_basis"]["granting_owner_name"] == "Khalid Al Mansoori"
    client.cookies.clear()
    sign_in(client, "khalid")
    r = client.post(f"{G}/{vat['grant_id']}/revoke")
    assert r.status_code == 200 and r.json()["status"] == "revoked"
    db.expire_all()
    assert db.get(Approval, a["approval_id"]).status == "withdrawn"
    back = client.get(A).json()
    assert any(x["awaiting_owner"] and x["status"] == "open" for x in back["awaiting"])
    f = client.post(f"{A}/{req['request_id']}/filing", json={"filed_date": dubai_today().isoformat(), "self_filed_confirmed": True})
    assert f.status_code == 409 and f.json()["details"]["cause"] == "approver_no_longer_has_rights"


def test_grant_sweep_reminder_expiry_and_suspension(client, db):
    _phase_b(db, True)
    owner = _principal(PERSONA_UUIDS["khalid"], "Khalid Al Mansoori")
    g = svc.create_grant(db, owner, CO_ALNOOR, delegate_uuid=PERSONA_UUIDS["omar"], tax_types=["vat"], scope_option="time_period", end_date=dubai_today() + timedelta(days=10))
    db.commit()
    out = svc.sweep(db)
    assert out["grant_reminders"] == 1 and g.reminder_sent_at is not None
    holder = db.get(AuthorityHolder, g.granting_authority_ref)
    holder.verification_status = "needs_reverification"  # licence amended at renewal
    svc.sweep(db)
    assert g.status == "suspended"
    g.status, holder.verification_status = "active", "verified"
    g.end_date = dubai_today() - timedelta(days=1)
    svc.sweep(db)
    assert g.status == "expired"
    db.commit()


# --- E6-S3 -----------------------------------------------------------------------------------------


def test_manual_filing_states_labels_and_validation(client, db):
    sign_in(client, "khalid")
    req = _open(client)
    assert _approve(client, req).status_code == 200
    url = f"{A}/{req['request_id']}/filing"
    today = dubai_today()
    r = client.post(url, json={"filed_date": (today + timedelta(days=1)).isoformat(), "authority_reference": "AB-12", "self_filed_confirmed": False, "receipt": {"name": "r.exe", "size_bytes": 11 * 1024 * 1024, "content_type": "application/x-msdownload"}})
    assert r.status_code == 422 and r.json()["error"] == "FORM_INVALID"
    fields = r.json()["details"]["fields"]
    assert fields["filed_date"] == "Enter the date you filed on EmaraTax. It cannot be in the future." and fields["authority_reference"] == "Use letters and numbers only."
    assert "self_filed_confirmed" in fields and "receipt" in fields
    r = client.post(url, json={"filed_date": (today - timedelta(days=30)).isoformat(), "self_filed_confirmed": True})
    assert r.status_code == 422 and "filed_date" in r.json()["details"]["fields"]  # before the approval date
    rel = client.post(f"{A}/{req['request_id']}/release")
    assert rel.status_code == 200 and rel.json()["release"]["approval_id"] and rel.json()["watermark"].startswith("Draft working figures")
    r = client.post(url, json={"filed_date": today.isoformat(), "authority_reference": "FTA123ABC", "figures_as_filed": {"net_vat": 1}, "self_filed_confirmed": True, "receipt": {"name": "ack.pdf", "size_bytes": 2048, "content_type": "application/pdf"}})
    assert r.status_code == 200, r.text
    rec = r.json()
    assert rec["state"] == "filed_outside_values_differ" and rec["differences"][0]["key"] == "net_vat" and rec["not_verified_by_authority"] is True
    assert rec["receipt"]["label"] == "Attached by you, not verified" and rec["read_back"] == "Not available"
    assert rec["confirmation"]["en"] == "Recorded as declared by you. Not verified by the tax authority."
    for t in (rec["banner"], rec["label"]["en"]):
        assert svc.check_wording(t) == [], t
    pack = client.get(f"/api/companies/{CO_ALNOOR}/drafts/{req['pack_id']}").json()
    assert pack["review_status"] == "filed_user_confirmed" and pack["locked"] is True
    e = client.patch(f"{A}/filing/{rec['record_id']}", json={"figures_as_filed": {"net_vat": pack['lines'][2]['value_fils']}})
    assert e.status_code == 200 and e.json()["state"] == "filed_outside_self_declared" and e.json()["edited"]["by"] == "Khalid Al Mansoori"
    db.expire_all()
    assert db.scalar(select(ManualFilingEdit).where(ManualFilingEdit.record_id == rec["record_id"])) is not None
    detail = client.get(f"{A}/requests/{req['request_id']}").json()
    assert detail["approved_by"]["approver_name"] == "Khalid Al Mansoori" and detail["filing"]["submitted_by"] == "Khalid Al Mansoori"
    assert detail["filing"]["state"] == "filed_outside_self_declared" and "Self-declared by Khalid Al Mansoori" in detail["filing"]["banner"]
    assert {g.path for g in db.scalars(select(GateDecision).where(GateDecision.outcome == "pass", GateDecision.pack_id == req["pack_id"]))} == {"manual_release", "manual_filing_record"}


def test_authority_unavailable_state_and_fixtures(client, db):
    sign_in(client, "khalid")
    req = _open(client)
    assert _approve(client, req).status_code == 200
    r = client.post(f"{A}/{req['request_id']}/filing", json={"outcome": "authority_unavailable"})
    assert r.status_code == 200 and r.json()["state"] == "authority_unavailable" and "not responding" in r.json()["banner"]
    fx = client.get(f"{A}/fixtures").json()
    assert fx["tag"] == "Demo data" and all(s["tag"] == "Demo data" for s in fx["states"])
    texts = " ".join(s["banner"] for s in fx["states"])
    assert "Do not file manually yet" not in texts and "Check its status in your EmaraTax account." in texts


def test_adapter_refuses_without_approval_switch_or_live_row(client, db, monkeypatch):
    sign_in(client, "khalid")
    req = _open(client)
    # mandatory negative test: no approval -> nothing sent, logged, counted
    r = client.post(f"{A}/{req['request_id']}/submit")
    assert r.status_code == 409 and r.json()["error"] == "GATE_BLOCKED" and r.json()["details"]["cause"] == "approval_missing"
    with pytest.raises(Conflict):
        adapter.submit(db, company_id=CO_ALNOOR, pack_id=req["pack_id"], approval_id=None, caller_type="agent")
    with pytest.raises(Conflict):
        adapter.submit(db, company_id=CO_ALNOOR, pack_id=req["pack_id"], approval_id="APV-DEMO-ALNOOR-Q1", caller_type="job")  # another version
    db.commit()
    assert _approve(client, req).status_code == 200
    r = client.post(f"{A}/{req['request_id']}/submit")
    assert r.status_code == 403 and r.json()["error"] == "SEND_SWITCHED_OFF"
    set_config(db, "filing.live_adapter.enabled", True, changed_by="test")
    db.commit()
    r = client.post(f"{A}/{req['request_id']}/submit")
    assert r.status_code == 403 and r.json()["error"] == "INTEGRATION_NOT_LIVE"
    import app.modules.phases.service as phases

    monkeypatch.setattr(phases, "integration_live", lambda db, row_id: row_id == "fta")
    r1 = client.post(f"{A}/{req['request_id']}/submit")
    r2 = client.post(f"{A}/{req['request_id']}/submit")
    assert r1.status_code == 200 and r1.json()["status"] == "sending" and r1.json()["attempt_id"] == r2.json()["attempt_id"]
    blocks = list(db.scalars(select(GateDecision).where(GateDecision.outcome == "block", GateDecision.path == "adapter_send")))
    assert {b.reason_code for b in blocks} >= {"approval_missing", "data_changed_since_approval", "SEND_SWITCHED_OFF", "INTEGRATION_NOT_LIVE"} and {b.caller_type for b in blocks} >= {"api", "agent", "job"}


def test_no_path_reaches_the_adapter_unguarded():
    root = pathlib.Path(__file__).resolve().parents[1] / "app"
    for f in root.rglob("*.py"):
        text = f.read_text(encoding="utf-8")
        if f.name == "adapter.py" and f.parent.name == "approvals":
            body = text.split("def submit(", 1)[1].split("\ndef ", 1)[0]
            assert body.index("gate(") < body.index(".transmit("), "gate must run before transmit"
            assert text.count(".transmit(") == 1
            continue
        assert ".transmit(" not in text and "EmaraTaxStubAdapter" not in text, f
    # agents never get a submission tool: nothing outside approvals calls adapter.submit
    callers = [f for f in root.rglob("*.py") if re.search(r"adapter\.submit\(", f.read_text(encoding="utf-8"))]
    assert all(f.parent.name == "approvals" for f in callers), callers


def test_read_back_match_rules():
    exp = {"trn": "100123456700003", "return_type": "vat", "period_start": "2026-04-01", "period_end": "2026-06-30", "reference": "R1", "amounts": {"net_vat": 116833}}
    ok, mism = adapter.match_read_back(exp, exp | {"trn": " 100123456700003 ", "status": "Submitted"})
    assert ok and mism == []
    ok, mism = adapter.match_read_back(exp, exp | {"amounts": {"net_vat": 116834}, "status": "submitted"})
    assert not ok and mism == ["amount:net_vat"]
    ok, mism = adapter.match_read_back(exp, exp | {"status": "processing"})
    assert not ok and mism == ["status"]  # unknown status = mismatch
    assert adapter.match_read_back(exp, None) == (False, ["record_unreadable"])


# --- E6-S4 -----------------------------------------------------------------------------------------


def test_k23_no_data_pass_breach_and_pilot_stop(client, db):
    assert monitoring.k23(db, "2030-01")["display"] == "No data" and monitoring.k23(db, "2030-01")["status"] == "no_data"
    k = monitoring.k23(db)
    assert k["denominator"] == 1 and k["display"] == "100.0%" and k["status"] == "pass" and k["self_reported_count"] == 1 and k["read_back"] == "Not available"
    # a submission recorded without a valid approval (detective control)
    q1 = db.scalar(select(ManualFilingRecord).where(ManualFilingRecord.id == "MFR-DEMO-ALNOOR-Q1"))
    db.add(ManualFilingRecord(company_id=CO_ALNOOR, pack_id=q1.pack_id, approval_id=None, data_version_hash=q1.data_version_hash, tax_type="vat", state="filed_outside_self_declared", filed_date=dubai_today(), self_filed_confirmed=True))
    db.commit()
    out = monitoring.run_compliance_job(db)
    db.commit()
    assert out["k23"]["status"] == "breach" and out["k23"]["display"] == "50.0%" and out["k23"]["breach_count"] == 1
    assert out["k23"]["text"]["en"] == "Below 100%: 1 of 2 submissions have no valid approval. Review the exceptions."
    exc = db.scalar(select(ComplianceException))
    assert exc.severity == 1 and exc.reason_code == "no_valid_approval_found" and exc.case_owner_role == "det_pilot_manager"
    alerts = {(a.recipient_role, a.kind) for a in db.scalars(select(ComplianceAlert))}
    assert alerts == {("det_pilot_manager", "case_owner"), ("qeonix_product_owner", "backup"), ("det_compliance_lead", "notified")}
    assert get_config(db, "approval.flow_enabled") is False and monitoring.wave_exit_blocked(db) is True
    assert _events(db, "CONTROL_FAILURE_INCIDENT_RAISED") and _events(db, "PILOT_STOP_APPLIED")
    assert monitoring.run_compliance_job(db)["exceptions_raised"] == []  # deterministic, raised once
    db.commit()
    sign_in(client, "khalid")
    r = client.post(f"{A}/requests", json={"pack_id": _open(client)["pack_id"]})
    assert r.status_code == 403 and r.json()["error"] == "APPROVAL_FLOW_SWITCHED_OFF"
    client.cookies.clear()
    sign_in(client, "noura")
    v = client.get("/api/det/approval-compliance").json()
    assert v["flow_enabled"] is False and v["wave_exit_blocked"] is True and v["read_only"] is True and v["exceptions"][0]["severity"] == 1
    assert all(s["read_back_status"] == "Not available" for s in v["submissions"])
    assert client.post(f"/api/det/approval-compliance/exceptions/{exc.id}/root-cause", json={"root_cause": "x", "fix": "y"}).status_code == 403
    assert client.post(f"/api/det/approval-compliance/exceptions/{exc.id}/review", json={"status": "acknowledged", "note": "looking"}).status_code == 200
    client.cookies.clear()
    sign_in(client, "faisal")
    r = client.post(f"/api/det/approval-compliance/exceptions/{exc.id}/root-cause", json={"root_cause": "record inserted outside the gate", "fix": "path removed"})
    assert r.status_code == 200 and r.json()["flow_enabled"] is False  # both case owners must record
    client.cookies.clear()
    sign_in(client, "lina")
    r = client.post(f"/api/det/approval-compliance/exceptions/{exc.id}/root-cause", json={"root_cause": "record inserted outside the gate", "fix": "path removed"})
    assert r.status_code == 200 and r.json()["flow_enabled"] is True and r.json()["wave_exit_blocked"] is False
    client.cookies.clear()
    sign_in(client, "omar")
    assert client.get("/api/det/approval-compliance").status_code == 403


def test_k23_grant_revoked_later_still_valid_and_k24_maths(client, db):
    _phase_b(db, True)
    set_config(db, "identity.approval_min_assurance_level", "SOP2", changed_by="test")
    db.commit()
    owner = _principal(PERSONA_UUIDS["khalid"], "Khalid Al Mansoori")
    g = svc.create_grant(db, owner, CO_ALNOOR, delegate_uuid=PERSONA_UUIDS["omar"], tax_types=["vat"], period_id="2026-Q2")
    db.commit()
    omar = _principal(PERSONA_UUIDS["omar"], "Omar Haddad", role="delegate", level="SOP2")
    req = db.scalar(select(ApprovalRequest).where(ApprovalRequest.company_id == CO_ALNOOR, ApprovalRequest.status == "open"))
    svc.approve(db, omar, CO_ALNOOR, req.id, expected_hash=req.draft_content_hash, reviewed_figures=True)
    svc.record_filing(db, owner, CO_ALNOOR, req.id, filed_date=dubai_today(), self_filed_confirmed=True)
    db.commit()
    svc.revoke_grant(db, owner, CO_ALNOOR, g.id)  # grant revoked after the filing: judged at submission time
    db.commit()
    k = monitoring.k23(db)
    assert k["denominator"] == 2 and k["status"] == "pass"
    # K24: mean hours request -> decision over decided requests only; open requests counted separately
    t = datetime(2026, 5, 1, 6, 0)
    for i, hours in enumerate((2, 10)):
        db.add(ApprovalRequest(company_id=CO_SAFWA, pack_id=f"p{i}", return_type="ct", period_id="FY2024", draft_content_hash="h", status="decided", created_at=t, link_expires_at=t + timedelta(days=3), decided_at=t + timedelta(hours=hours)))
    db.commit()
    k24 = monitoring.k24(db, "2026-05", company_id=CO_SAFWA)
    assert k24["mean_hours"] == 6.0 and k24["decided_count"] == 2 and k24["pass"] is None and k24["target_text"]["en"] == "No target has been set for this figure."
    assert k24["by_document_type"] == {"ct": 6.0}
    none = monitoring.k24(db, "2030-01")
    assert none["display"] == "No data" and none["text"]["en"] == "No data. No approval requests have been decided in this period."
    open_n = len(list(db.scalars(select(ApprovalRequest).where(ApprovalRequest.status == "open"))))
    allk = monitoring.k24(db)
    assert allk["undecided_count"] == open_n and allk["waiting_text"]["en"] == f"Waiting for a decision: {open_n}"


def test_records_read_only_and_banned_wording(client, db):
    sign_in(client, "khalid")
    r = client.delete(f"{A}/records/APV-DEMO-ALNOOR-Q1")
    assert r.status_code == 403 and r.json()["message"] == "Records cannot be edited. This attempt has been logged."
    assert _events(db, "EDIT_DELETE_OVERRIDE_ATTEMPT_REFUSED")
    body = client.get(A).json()
    import json

    live = json.dumps({k: v for k, v in body.items() if k != "strings"}) + json.dumps(body["strings"], ensure_ascii=False)
    assert svc.check_wording(live) == [], svc.check_wording(live)
    for key in ("legally binding", "electronic signature", "Tax Agent"):
        assert key.lower() not in live.lower()
    fe = pathlib.Path(__file__).resolve().parents[2] / "frontend" / "src" / "features" / "approvals"
    for f in fe.glob("*.ts*"):
        text = f.read_text(encoding="utf-8")
        assert "Do not file manually yet" not in text and "legally binding" not in text.lower() and "Tax Agent" not in text, f
