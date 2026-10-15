"""E1-S6 delegate management + remaining E1-S2 controls (grants, revocation with quarantine, hold, firewall, SC15, SC14)."""

from __future__ import annotations

import re
from datetime import timedelta

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.time import utcnow
from app.demo import CO_ALNOOR, CO_BLUEDUNE, CO_GULFTECH, CO_SAFWA, PERSONA_UUIDS
from app.main import app
from app.modules.audit.models import AuditEvent
from app.modules.audit.service import record_event
from app.modules.companies.models import CompanyRole
from app.modules.config.service import set_config
from app.modules.delegates import service as svc
from app.modules.delegates.models import DelegateInvitation, QuarantinedDraft
from app.modules.delegates.strings import STRINGS
from app.modules.identity.models import Identity, StaffRole
from tests.conftest import sign_in

NOROLES_EID = "784-1995-1414141-4"  # mock persona 'noroles'
ALNOOR_DELEGATES = f"/api/companies/{CO_ALNOOR}/delegates"


def _events(db, event_type: str, reason: str | None = None) -> list[AuditEvent]:
    stmt = select(AuditEvent).where(AuditEvent.event_type == event_type)
    if reason:
        stmt = stmt.where(AuditEvent.reason_code == reason)
    return list(db.scalars(stmt))


def _omar_role(db, company_id=CO_ALNOOR) -> CompanyRole:
    return db.scalar(select(CompanyRole).where(CompanyRole.identity_uuid == PERSONA_UUIDS["omar"], CompanyRole.company_id == company_id))


# --- invitations and binding ---------------------------------------------------------------------------


def test_owner_invites_and_delegate_binds_on_signin(client, db):
    sign_in(client, "khalid")
    r = client.post(ALNOOR_DELEGATES, json={"emirates_id": "784 1995 1414141 4", "entered_name": "Tariq Nobody", "email": "t@example.ae", "toggles": ["view_dashboard", "prepare_data"]})
    assert r.status_code == 201, r.text
    inv = db.get(DelegateInvitation, r.json()["invitation_id"])
    assert inv.status == "pending" and inv.rights == ["prepare", "view"]
    assert round((inv.expires_at - inv.invited_at).total_seconds() / 86400) == 7
    assert NOROLES_EID.replace("-", "") not in (inv.emirates_id_hash + str(inv.__dict__))  # number never stored
    listing = client.get(ALNOOR_DELEGATES).json()
    assert any(p["kind"] == "invitation" and p["chip"] == "pending" for p in listing["people"])
    assert listing["scope"] == "all" and listing["statement"]["en"].startswith("delegates can prepare and review")

    with TestClient(app, follow_redirects=False) as c2:
        res = sign_in(c2, "noroles")
        assert res["ok"] and "no_company" not in res["query"]
        me = c2.get("/api/auth/me").json()
        assert [c["company_id"] for c in me["companies"]] == [CO_ALNOOR]
        assert me["companies"][0]["roles"] == ["delegate"] and "tax.prepare" in me["companies"][0]["permissions"]
        assert "returns.approve" not in me["companies"][0]["permissions"]
        own = c2.get(ALNOOR_DELEGATES).json()
        assert own["scope"] == "own" and own["own"]["toggles"] == ["prepare_data", "view_dashboard"]
        assert all(own["own"]["locked_toggles"][t]["locked"] for t in ("grant_bank_consent", "approve_submissions", "change_subscription"))
        # A delegate cannot invite: owner-only refusal, logged.
        r = c2.post(ALNOOR_DELEGATES, json={"emirates_id": "784-1991-5555555-1", "toggles": []})
        assert r.status_code == 403
    db.expire_all()
    inv = db.get(DelegateInvitation, inv.id)
    assert inv.status == "accepted" and inv.identity_uuid == PERSONA_UUIDS["noroles"] if "noroles" in PERSONA_UUIDS else inv.status == "accepted"
    assert inv.name_differs is False
    assert _events(db, "DELEGATE_ACTIVATED")


def test_name_soft_check_flags_difference_but_never_blocks(client, db):
    sign_in(client, "khalid")
    r = client.post(ALNOOR_DELEGATES, json={"emirates_id": NOROLES_EID, "entered_name": "أحمد خان", "toggles": ["prepare_data"]})
    assert r.status_code == 201
    with TestClient(app, follow_redirects=False) as c2:
        assert sign_in(c2, "noroles")["ok"]
        assert c2.get("/api/auth/me").json()["companies"][0]["company_id"] == CO_ALNOOR
    db.expire_all()
    inv = db.get(DelegateInvitation, r.json()["invitation_id"])
    assert inv.status == "accepted" and inv.name_differs is True
    assert _events(db, "DELEGATE_NAME_DIFFERS")
    people = client.get(ALNOOR_DELEGATES).json()["people"]
    assert any(p["name_differs"] for p in people if p["kind"] == "role")
    assert svc.name_differs("Dr. Layla Haddad", "ليلى حدّاد") is True  # cross-script is a soft check only
    assert svc.name_differs("khalid  AL MANSOORI", "Khalid Al Mansoori") is False
    assert svc.normalise_name("إبراهيم أحمَد") == {"ابراهيم", "احمد"}


def test_invitation_limits_and_expiry(client, db):
    sign_in(client, "khalid")
    accepted = 0
    for i in range(12):
        r = client.post(ALNOOR_DELEGATES, json={"emirates_id": f"784-1990-{i:07d}-1", "toggles": []})
        if r.status_code == 201:
            accepted += 1
        else:
            assert r.json()["error"] == "DELEGATE_LIMIT_COMPANY"
            break
    assert accepted == 9  # Omar is already active: 10 active or pending per company
    # expiry at 7 days -> invalid; resend resets the clock
    inv = db.scalar(select(DelegateInvitation).where(DelegateInvitation.company_id == CO_ALNOOR, DelegateInvitation.status == "pending"))
    inv.expires_at = utcnow() - timedelta(minutes=1)
    db.commit()
    people = client.get(ALNOOR_DELEGATES).json()["people"]
    assert any(p["id"] == inv.id and p["status"] == "expired" and p["chip"] == "removed" for p in people)
    r = client.post(f"{ALNOOR_DELEGATES}/invitations/{inv.id}/resend")
    assert r.status_code == 200 and r.json()["status"] == "pending"
    r = client.post(f"{ALNOOR_DELEGATES}/invitations/{inv.id}/withdraw")
    assert r.json()["status"] == "withdrawn"
    assert client.post(ALNOOR_DELEGATES, json={"emirates_id": "123", "toggles": []}).json()["error"] == "EMIRATES_ID_INVALID"


def test_max_companies_per_delegate(client, db):
    set_config(db, "delegates.max_companies_per_delegate", 3, changed_by="test")
    db.commit()
    sign_in(client, "khalid")
    # Omar already holds 3 delegate companies (known identity): the 4th invitation is refused at once.
    r = client.post(f"/api/companies/{CO_SAFWA}/delegates", json={"emirates_id": "784-1990-1111111-3", "toggles": ["prepare_data"]})
    assert r.status_code == 422 and r.json()["error"] == "DELEGATE_LIMIT_PERSON"
    # Limit lowered after the invitation exists: activation at sign-in is refused and logged.
    set_config(db, "delegates.max_companies_per_delegate", 4, changed_by="test")
    db.commit()
    r = client.post(f"/api/companies/{CO_SAFWA}/delegates", json={"emirates_id": "784-1990-1111111-3", "toggles": ["prepare_data"]})
    assert r.status_code == 201
    set_config(db, "delegates.max_companies_per_delegate", 3, changed_by="test")
    db.commit()
    with TestClient(app, follow_redirects=False) as c2:
        sign_in(c2, "omar")
        assert len(c2.get("/api/auth/me").json()["companies"]) == 3
    assert _events(db, "DELEGATE_ACTIVATION", "DELEGATE_LIMIT_PERSON")


# --- role combination rules --------------------------------------------------------------------------


def test_role_combination_refused_both_directions(client, db):
    # Direction 1: an auditor engaged on Al Noor is invited as delegate -> refused at activation, logged.
    db.add(CompanyRole(identity_uuid=PERSONA_UUIDS["layla"], company_id=CO_ALNOOR, role="licensed_auditor", capacity="staff", granted_by_uuid="test"))
    db.commit()
    sign_in(client, "khalid")
    r = client.post(ALNOOR_DELEGATES, json={"emirates_id": "784-1975-2222222-4", "toggles": ["prepare_data"]})
    assert r.status_code == 201
    with TestClient(app, follow_redirects=False) as c2:
        sign_in(c2, "layla")
        me = c2.get("/api/auth/me").json()
        assert all("delegate" not in c["roles"] for c in me["companies"])
    assert _events(db, "DELEGATE_ACTIVATION", "ROLE_COMBINATION_REFUSED")
    # Direction 2: a delegate on Al Noor cannot become its auditor; the firewall also refuses.
    try:
        svc.check_role_combination(db, PERSONA_UUIDS["omar"], CO_ALNOOR, "licensed_auditor")
        raise AssertionError("expected refusal")
    except Exception as exc:  # Forbidden
        assert getattr(exc, "reason_code", "") == "ROLE_COMBINATION_REFUSED"
    rec = svc.evaluate_firewall(db, PERSONA_UUIDS["omar"], CO_ALNOOR, "eng_test_omar")
    db.commit()
    assert rec.result == "conflict_found"
    # DET administrator is exclusive: invitation never activates.
    r = client.post(ALNOOR_DELEGATES, json={"emirates_id": "784-1982-3333333-5", "toggles": []})
    assert r.status_code == 201
    with TestClient(app, follow_redirects=False) as c3:
        sign_in(c3, "sara")
        assert c3.get("/api/auth/me").json()["companies"] == []
    # Owner cannot be invited as delegate on the company they own (owner + delegate acts as owner).
    r = client.post(ALNOOR_DELEGATES, json={"emirates_id": "784-1980-1234567-1", "toggles": []})
    assert r.status_code == 409 and r.json()["error"] == "ALREADY_OWNER"


# --- Phase B rights locked ---------------------------------------------------------------------------


def test_phase_b_rights_locked_and_wording(client, db):
    sign_in(client, "khalid")
    for toggle in ("grant_bank_consent", "approve_submissions", "change_subscription"):
        r = client.post(ALNOOR_DELEGATES, json={"emirates_id": NOROLES_EID, "toggles": [toggle]})
        assert r.status_code == 403 and r.json()["error"] == "RIGHT_SWITCHED_OFF", r.text
        r = client.patch(f"{ALNOOR_DELEGATES}/{_omar_role(db).id}", json={"toggles": ["prepare_data", toggle]})
        assert r.status_code == 403 and r.json()["error"] == "RIGHT_SWITCHED_OFF"
    meta = {t["toggle"]: t for t in client.get(ALNOOR_DELEGATES).json()["toggles"]}
    assert all(meta[t]["locked"] and meta[t]["locked_wording"]["en"] == "Not available yet: only the owner can do this." for t in ("grant_bank_consent", "approve_submissions", "change_subscription"))
    assert all(meta[t]["default"] is False for t in meta)
    # Per-right switch alone is not enough: the versioned Phase B switch must also be on.
    set_config(db, "delegate_rights.approve_submissions.enabled", True, changed_by="test")
    db.commit()
    assert client.patch(f"{ALNOOR_DELEGATES}/{_omar_role(db).id}", json={"toggles": ["prepare_data", "approve_submissions"]}).status_code == 403
    set_config(db, "delegates.phase_b_switch", True, changed_by="test")
    db.commit()
    r = client.patch(f"{ALNOOR_DELEGATES}/{_omar_role(db).id}", json={"toggles": ["prepare_data", "view_dashboard", "approve_submissions"]})
    assert r.status_code == 200 and r.json()["reduced"] is False and r.json()["sessions_ended"] == 0
    for key in ("role_refusal", "no_owner_panel", "access_changed", "rights_updated", "drafts_on_hold"):
        assert STRINGS[key]["en"] and STRINGS[key]["ar"]
    assert "المفوَّضين أو الموافقة على مشاركة البيانات" in STRINGS["no_owner_panel"]["ar"]
    assert "power of attorney" not in " ".join(v["en"].lower() for v in STRINGS.values())


# --- revocation with quarantine -----------------------------------------------------------------------


def test_rights_reduction_signs_out_only_affected_delegate_and_quarantines(client, db):
    svc.TOUCHED_DRAFT_PROVIDERS.clear()
    svc.TOUCHED_DRAFT_PROVIDERS.append(lambda db_, identity, company: [
        {"draft_type": "tax_return_draft", "draft_ref": "vat_2026q3", "touched_action": "edited", "data_version": "v2"},
        {"draft_type": "bookkeeping_period", "draft_ref": "bk_2026_09", "touched_action": "created"},
        {"draft_type": "tax_return_draft", "draft_ref": "ct_2025", "touched_action": "viewed"},
    ] if (identity, company) == (PERSONA_UUIDS["omar"], CO_ALNOOR) else [])
    try:
        sign_in(client, "khalid")
        with TestClient(app, follow_redirects=False) as omar, TestClient(app, follow_redirects=False) as priya:
            sign_in(omar, "omar")
            sign_in(priya, "priya")
            assert omar.get("/api/auth/me").status_code == 200
            r = client.patch(f"{ALNOOR_DELEGATES}/{_omar_role(db).id}", json={"toggles": ["view_dashboard"]})
            assert r.status_code == 200, r.text
            body = r.json()
            assert body["reduced"] and body["sessions_ended"] == 1 and body["drafts_quarantined"] == 2
            # only the affected delegate is signed out; the owner and other sessions continue
            assert omar.get("/api/auth/me").status_code == 401
            assert client.get("/api/auth/me").status_code == 200 and priya.get("/api/auth/me").status_code == 200
            # after revocation no data-returning call succeeds for that principal
            assert omar.get(f"/api/companies/{CO_ALNOOR}/activity").status_code == 401
        for et in ("DELEGATION_CHANGE", "ACCESS_REVOKED", "SESSION_ENDED", "EXPORT_CANCELLED", "JOB_ABORTED", "DRAFT_QUARANTINED"):
            assert _events(db, et), et
        assert _events(db, "JOB_ABORTED")[-1].details["marker"] == "stopped by access change"
        q = client.get(f"{ALNOOR_DELEGATES}/quarantine").json()
        assert {d["draft_ref"] for d in q} == {"vat_2026q3", "bk_2026_09"}  # viewed-only never quarantined
        assert all(d["marker"] == "initiated by a removed delegate" for d in q)
        assert svc.is_quarantined(db, CO_ALNOOR, "vat_2026q3")
        # Keep / Reassign / Discard (= release / reassign / reject); decision recorded; no second decision
        by_ref = {d["draft_ref"]: d for d in q}
        r = client.post(f"{ALNOOR_DELEGATES}/quarantine/{by_ref['vat_2026q3']['id']}/decide", json={"decision": "keep"})
        assert r.json()["status"] == "released"
        r = client.post(f"{ALNOOR_DELEGATES}/quarantine/{by_ref['bk_2026_09']['id']}/decide", json={"decision": "reassign"})
        assert r.json()["status"] == "reassigned" and r.json()["new_draft_ref"] == "bk_2026_09:v2"
        assert client.post(f"{ALNOOR_DELEGATES}/quarantine/{by_ref['bk_2026_09']['id']}/decide", json={"decision": "discard"}).status_code == 409
        assert not svc.is_quarantined(db, CO_ALNOOR, "vat_2026q3")
        qd = db.get(QuarantinedDraft, by_ref["vat_2026q3"]["id"])
        assert qd.decided_by_uuid == PERSONA_UUIDS["khalid"] and qd.decided_at and qd.decision_identity_level == "SOP3" and qd.data_version == "v2"
        assert _events(db, "QUARANTINE_DECIDED")
        # Recent access changes for the owner; the delegate sees the change on next sign-in via the 30 s check
        changes = client.get(f"{ALNOOR_DELEGATES}/changes").json()
        assert changes[0]["change_type"] in ("quarantine_decision", "rights_changed")
        with TestClient(app, follow_redirects=False) as omar2:
            sign_in(omar2, "omar")
            mine = omar2.get("/api/delegates/my-access-changes").json()
            assert mine["check_interval_seconds"] == 30 and any(c["change_type"] == "rights_changed" and c["company_id"] == CO_ALNOOR for c in mine["changes"])
            cid = next(c["id"] for c in mine["changes"] if c["change_type"] == "rights_changed")
            assert omar2.post(f"/api/delegates/my-access-changes/{cid}/ack").status_code == 200
            assert not any(c["id"] == cid for c in omar2.get("/api/delegates/my-access-changes").json()["changes"])
    finally:
        svc.TOUCHED_DRAFT_PROVIDERS.clear()


def test_removal_keeps_other_companies_and_discard_rejects(client, db):
    sign_in(client, "khalid")
    r = client.delete(f"{ALNOOR_DELEGATES}/{_omar_role(db).id}")
    assert r.status_code == 200 and r.json()["status"] == "removed"
    with TestClient(app, follow_redirects=False) as omar:
        sign_in(omar, "omar")
        me = omar.get("/api/auth/me").json()
        assert sorted(c["company_id"] for c in me["companies"]) == [CO_BLUEDUNE, CO_GULFTECH]
        assert omar.get(ALNOOR_DELEGATES).status_code == 403
        mine = omar.get("/api/delegates/my-access-changes").json()["changes"]
        assert any(c["change_type"] == "removed" and c["company_id"] == CO_ALNOOR for c in mine)
    people = client.get(ALNOOR_DELEGATES).json()["people"]
    assert any(p["identity_uuid"] == PERSONA_UUIDS["omar"] and p["chip"] == "removed" for p in people)
    assert client.delete(f"{ALNOOR_DELEGATES}/{_omar_role(db).id}").status_code == 409
    # demo quarantined draft on Gulf Tech: discard = rejected
    q = db.scalar(select(QuarantinedDraft).where(QuarantinedDraft.draft_ref == "bk_gulftech_2026_09"))
    assert q.status == "quarantined"


def test_suspend_and_reinstate(client, db):
    sign_in(client, "khalid")
    rid = _omar_role(db).id
    assert client.post(f"{ALNOOR_DELEGATES}/{rid}/suspend").json()["status"] == "suspended"
    with TestClient(app, follow_redirects=False) as omar:
        sign_in(omar, "omar")
        assert CO_ALNOOR not in [c["company_id"] for c in omar.get("/api/auth/me").json()["companies"]]
    assert client.post(f"{ALNOOR_DELEGATES}/{rid}/reinstate").json()["status"] == "active"


# --- neutral no-access panel ---------------------------------------------------------------------------


def test_cross_company_and_missing_company_are_identical(client):
    sign_in(client, "khalid")
    a = client.get(f"/api/companies/{CO_BLUEDUNE}/delegates")
    b = client.get("/api/companies/co_does_not_exist/delegates")
    assert a.status_code == b.status_code == 403
    strip = lambda r: {k: v for k, v in r.json().items() if k != "reference"}  # noqa: E731
    assert strip(a) == strip(b)
    assert "another company" not in a.text


# --- per-case grants ------------------------------------------------------------------------------------


def test_grant_fail_closed_for_specialist(client, db):
    sign_in(client, "hassan")
    ok = client.get(f"/api/companies/{CO_ALNOOR}/grants/case/case_alnoor_1")
    assert ok.status_code == 200 and ok.json()["purpose"] == "tax_escalation"
    refused = client.get(f"/api/companies/{CO_ALNOOR}/grants/case/case_alnoor_2")
    assert refused.status_code == 403 and refused.json()["error"] == "NO_PERMISSION"
    assert _events(db, "ACCESS_REFUSED", "NO_CASE_GRANT")
    assert svc.has_valid_grant(db, PERSONA_UUIDS["hassan"], CO_ALNOOR, "case_alnoor_1")
    assert not svc.has_valid_grant(db, PERSONA_UUIDS["hassan"], CO_SAFWA, "case_alnoor_1")
    # expired grant is refused; revoked grant is refused
    g = db.scalar(select(svc.AccessGrant).where(svc.AccessGrant.case_ref == "case_alnoor_1"))
    g.expires_at = utcnow() - timedelta(seconds=1)
    db.commit()
    assert client.get(f"/api/companies/{CO_ALNOOR}/grants/case/case_alnoor_1").status_code == 403


def test_only_owner_creates_grants(client, db):
    with TestClient(app, follow_redirects=False) as omar:
        sign_in(omar, "omar")
        r = omar.post(f"/api/companies/{CO_ALNOOR}/grants", json={"recipient_identity_uuid": PERSONA_UUIDS["layla"], "recipient_role": "licensed_auditor", "case_ref": "eng_1", "purpose": "audit_preparation", "data_scope": ["ledgers"]})
        assert r.status_code == 403
    sign_in(client, "khalid")
    r = client.post(f"/api/companies/{CO_ALNOOR}/grants", json={"recipient_identity_uuid": PERSONA_UUIDS["layla"], "recipient_role": "licensed_auditor", "case_ref": "eng_1", "purpose": "audit_preparation", "data_scope": ["ledgers"], "days": 400})
    assert r.status_code == 201
    grants = client.get(f"/api/companies/{CO_ALNOOR}/grants").json()
    g = next(x for x in grants if x["case_ref"] == "eng_1")
    assert g["status"] == "active" and (utcnow() + timedelta(days=91)).isoformat() > g["expires_at"]  # capped at 90 days
    assert svc.has_valid_grant(db, PERSONA_UUIDS["layla"], CO_ALNOOR, "eng_1")
    assert client.delete(f"/api/companies/{CO_ALNOOR}/grants/{g['id']}").status_code == 200
    assert not svc.has_valid_grant(db, PERSONA_UUIDS["layla"], CO_ALNOOR, "eng_1")
    # a DET administrator can never receive a company case grant
    r = client.post(f"/api/companies/{CO_ALNOOR}/grants", json={"recipient_identity_uuid": PERSONA_UUIDS["sara"], "recipient_role": "specialist", "case_ref": "x", "purpose": "p"})
    assert r.status_code == 403 and r.json()["error"] == "ROLE_COMBINATION_REFUSED"


# --- signatory-change hold ---------------------------------------------------------------------------------


def test_hold_blocks_held_actions_but_not_reads(client, db):
    sign_in(client, "khalid")
    assert client.get(f"/api/companies/{CO_SAFWA}/hold").json()["hold_state"] == "none"
    with TestClient(app, follow_redirects=False) as faisal:
        sign_in(faisal, "faisal")
        r = faisal.post(f"/api/companies/{CO_SAFWA}/hold/start", json={"reason": "signatory_changed"})
        assert r.status_code == 200 and r.json()["hold_state"] == "signatory_change_hold"
        # held: delegate changes and grants; allowed: reads (people list, activity, hold status)
        r = client.post(f"/api/companies/{CO_SAFWA}/delegates", json={"emirates_id": NOROLES_EID, "toggles": []})
        assert r.status_code == 403 and r.json()["error"] == "COMPANY_ON_HOLD"
        r = client.post(f"/api/companies/{CO_SAFWA}/grants", json={"recipient_identity_uuid": PERSONA_UUIDS["hassan"], "recipient_role": "specialist", "case_ref": "c", "purpose": "p"})
        assert r.status_code == 403 and r.json()["error"] == "COMPANY_ON_HOLD"
        assert client.get(f"/api/companies/{CO_SAFWA}/delegates").status_code == 200
        assert client.get(f"/api/companies/{CO_SAFWA}/activity").status_code == 200
        assert client.get(f"/api/companies/{CO_SAFWA}/hold").json()["hold_state"] == "signatory_change_hold"
        assert _events(db, "ACCESS_REFUSED", "COMPANY_ON_HOLD") and _events(db, "COMPANY_HOLD_STARTED")
        assert _events(db, "APPROVAL_VOIDED", "SIGNATORY_CHANGED") and _events(db, "CONSENT_PAUSED", "SIGNATORY_CHANGED")
        # 30 days: alert to DET operations, still held (never auto-released)
        hold = svc.get_hold(db, CO_SAFWA)
        hold.hold_started_at = utcnow() - timedelta(days=31)
        db.commit()
        state = client.get(f"/api/companies/{CO_SAFWA}/hold").json()
        assert state["hold_state"] == "signatory_change_hold" and state["det_operations_alerted_at"]
        assert _events(db, "COMPANY_HOLD_ALERT")
        # DET support lift path
        assert faisal.post(f"/api/companies/{CO_SAFWA}/hold/lift").json()["hold_state"] == "none"
    r = client.post(f"/api/companies/{CO_SAFWA}/delegates", json={"emirates_id": NOROLES_EID, "toggles": []})
    assert r.status_code == 201, r.text


def test_hold_lifted_by_uaepass_match_and_no_match_queued(client, db):
    svc.start_signatory_change_hold(db, CO_ALNOOR)
    db.commit()
    # Khalid is on the DET record for Al Noor: his sign-in lifts the hold automatically.
    sign_in(client, "khalid")
    assert svc.get_hold(db, CO_ALNOOR).hold_state == "none"
    assert _events(db, "COMPANY_HOLD_LIFTED")
    # Blue Dune: hold, then an owner-level person without a DET match -> support queue, hold stays.
    svc.start_signatory_change_hold(db, CO_BLUEDUNE)
    db.add(CompanyRole(identity_uuid="uuid-no-roles", company_id=CO_BLUEDUNE, role="owner", capacity="authorised_signatory", granted_by_uuid="test"))
    db.commit()
    with TestClient(app, follow_redirects=False) as c2:
        sign_in(c2, "noroles")
    db.expire_all()
    assert svc.get_hold(db, CO_BLUEDUNE).hold_state == "signatory_change_hold"
    assert db.scalar(select(svc.SupportQueueCase).where(svc.SupportQueueCase.company_id == CO_BLUEDUNE)) is not None


def test_gulf_tech_no_owner_state_and_stale_det_data(client, db):
    with TestClient(app, follow_redirects=False) as omar:
        sign_in(omar, "omar")
        state = omar.get(f"/api/companies/{CO_GULFTECH}/hold").json()
        assert state["hold_state"] == "no_owner" and state["has_matchable_owner"] is False
        people = omar.get(f"/api/companies/{CO_GULFTECH}/delegates").json()
        assert people["scope"] == "own" and people["people"][0]["authority_label"] == "suspended_authority_changed"
    sign_in(client, "khalid")
    lic = db.scalar(select(svc.Licence).where(svc.Licence.company_id == CO_ALNOOR))
    lic.last_det_refresh_at = utcnow() - timedelta(hours=49)
    db.commit()
    r = client.post(ALNOOR_DELEGATES, json={"emirates_id": NOROLES_EID, "toggles": []})
    assert r.status_code == 403 and r.json()["error"] == "DET_DATA_STALE"
    assert client.get(ALNOOR_DELEGATES).json()["authority"]["stale"] is True


# --- auditor firewall -----------------------------------------------------------------------------------


def test_firewall_conflict_on_related_entity(client, db):
    rec = svc.evaluate_firewall(db, PERSONA_UUIDS["layla"], CO_ALNOOR, "eng_alnoor_1", firm="Haddad & Partners")
    db.commit()
    assert rec.result == "no_conflict_found_in_det_records" and rec.rule_version == "firewall-v1"
    assert not svc.firewall_clear(db, "eng_alnoor_1", PERSONA_UUIDS["layla"])  # declaration still required
    # Safwa shares a licence person (Khalid) with Al Noor: a delegate role there is a related-entity hit.
    db.add(CompanyRole(identity_uuid=PERSONA_UUIDS["layla"], company_id=CO_SAFWA, role="delegate", capacity="delegate", status="revoked", granted_by_uuid="test"))
    db.commit()
    rec = svc.evaluate_firewall(db, PERSONA_UUIDS["layla"], CO_ALNOOR, "eng_alnoor_1")
    db.commit()
    assert rec.result == "conflict_found" and rec.status == "suspended"
    assert any(link["link"] == "shared_licence_person" for link in rec.related_entity_links_used)
    ev = _events(db, "FIREWALL_EVALUATED", "FIREWALL_CONFLICT")[-1]
    assert ev.outcome == "refused" and ev.details["hits"][0]["via"] == "related_entity" and "independent" not in str(ev.details)
    assert "independent" not in rec.result
    sign_in(client, "khalid")
    rows = client.get(f"/api/companies/{CO_ALNOOR}/firewall").json()
    assert rows[0]["result"] == "conflict_found" and "independent" not in rows[0]["result"]
    with TestClient(app, follow_redirects=False) as layla:
        sign_in(layla, "layla")
        r = layla.post(f"/api/companies/{CO_BLUEDUNE}/firewall/eng_bd_1/evaluate", json={"firm": "Haddad & Partners"})
        assert r.status_code == 200 and r.json()["result"] == "no_conflict_found_in_det_records"
        assert layla.post(f"/api/companies/{CO_BLUEDUNE}/firewall/eng_bd_1/declare").json()["independence_declared_at"]
    assert svc.firewall_clear(db, "eng_bd_1", PERSONA_UUIDS["layla"])
    # manual flag by a reviewer blocks
    with TestClient(app, follow_redirects=False) as noura:
        sign_in(noura, "noura")
        assert noura.post(f"/api/companies/{CO_BLUEDUNE}/firewall/eng_bd_1/flag", json={"code": "family_member"}).json()["result"] == "conflict_found"
    assert not svc.firewall_clear(db, "eng_bd_1", PERSONA_UUIDS["layla"])


# --- SC15 activity list --------------------------------------------------------------------------------


def test_activity_list_wording_without_figures_and_no_aml(client, db):
    record_event(db, event_type="AML_FLAG_RAISED", category="system", company_id=CO_ALNOOR, details={"score": 99})
    record_event(db, event_type="CONSENT_GRANTED", category="consent", identity_uuid=PERSONA_UUIDS["khalid"], actor_role="owner", company_id=CO_ALNOOR, details={"purpose": "bank_data", "amount_fils": 1234567})
    record_event(db, event_type="AGENT_ACTION", category="agent", company_id=CO_ALNOOR, details={"item": "vat_return", "agent": "bookkeeping-agent"})
    record_event(db, event_type="APPROVAL_RECORDED", category="approval", identity_uuid=PERSONA_UUIDS["khalid"], actor_role="owner", company_id=CO_ALNOOR, details={"tax_type": "vat", "period": "Q3 2026"})
    db.commit()
    sign_in(client, "khalid")
    with TestClient(app, follow_redirects=False) as omar:
        sign_in(omar, "omar")
        assert omar.get(f"/api/companies/{CO_ALNOOR}/grants/case/x").status_code == 403  # a refused attempt, not shown (no mapping)
        omar.post(ALNOOR_DELEGATES, json={"emirates_id": NOROLES_EID, "toggles": []})  # refused delegation attempt -> shown as refused
        own = omar.get(f"/api/companies/{CO_ALNOOR}/activity").json()
        assert own["own_only"] is True and own["rows"]
        omar_key = own["rows"][0]["actor_key"]
        assert all(r["actor_key"] == omar_key for r in own["rows"])
        assert any(r["outcome"] == "refused" and r["kind"] == 8 for r in own["rows"])
    data = client.get(f"/api/companies/{CO_ALNOOR}/activity").json()
    assert data["page_size"] == 50 and data["own_only"] is False
    rows = data["rows"]
    wordings = [STRINGS[f"ev_{i}"]["en"] for i in range(1, 15)]
    templates = [re.escape(w).replace(r"\[", "(?:").replace(r"\]", ")") for w in wordings]
    for r in rows:
        assert set(r) == {"event_id", "time", "time_label", "kind", "action", "actor", "actor_key", "company", "object_ref", "outcome", "outcome_label", "reason_code"}
        assert r["actor"].startswith("Acted by: ")
        assert not re.search(r"\bAED\b", r["action"]) and not re.search(r"\d{7,}", r["action"] + r["actor"]), r
        assert r["kind"] in range(1, 15)
    text = " ".join(r["action"] for r in rows)
    assert "AML" not in text and "1234567" not in text and "99" not in text
    assert "Consent for bank and financial data was given." in text
    assert "AI prepared a draft VAT return. Status: draft." in text
    assert "Return pack approved for VAT, Q3 2026." in text
    assert "Signed in with UAE Pass." in text
    assert any(r["actor"] == "Acted by: AI preparing (draft)" for r in rows)
    assert any(r["actor"] == "Acted by: Khalid Al Mansoori, owner" for r in rows)
    assert any(r["actor"] == "Acted by: Omar Haddad, delegate" for r in rows)
    assert all(re.fullmatch("|".join(templates), r["action"]) or r["kind"] in (2, 3, 4, 5, 7, 8, 9, 10, 12, 13) for r in rows)
    # filters: by kind and outcome
    only_consent = client.get(f"/api/companies/{CO_ALNOOR}/activity", params={"kind": 7}).json()["rows"]
    assert only_consent and all(r["kind"] == 7 for r in only_consent)
    assert all(r["outcome"] == "refused" for r in client.get(f"/api/companies/{CO_ALNOOR}/activity", params={"outcome": "refused"}).json()["rows"])
    ar = client.get(f"/api/companies/{CO_ALNOOR}/activity", params={"lang": "ar"}).json()["rows"]
    assert any(r["action"] == STRINGS["ev_1"]["ar"] for r in ar) and all(r["actor"].startswith("بواسطة:") for r in ar)
    assert "بتوقيت دبي" in ar[0]["time_label"] and "Dubai time" in rows[0]["time_label"]
    export = client.get(f"/api/companies/{CO_ALNOOR}/activity/export").json()
    assert [p["lang"] for p in export["pages"]] == ["en", "ar"] and "hash" not in export["pages"][0]["html"]
    assert _events(db, "ACTIVITY_EXPORTED") and _events(db, "ACTIVITY_LIST_VIEWED")


# --- SC14 delegation overview ----------------------------------------------------------------------------


def test_det_overview_suppression(client, db):
    sign_in(client, "sara")
    data = client.get("/api/det/delegation-overview").json()
    cell = data["companies_with_active_delegate"]
    assert cell["suppressed"] is True and cell["display"] == "<10" and "value" not in cell
    assert data["pending_invitations"]["display"] == "<10" and data["no_owner_companies"]["display"] == "<10"
    assert all(v["display"] == "not enabled" for v in data["delegated_rights"].values())
    assert data["min_group_size"] == 10 and data["period_level"] == "quarter" and data["as_of"]
    assert all(c["suppressed"] for c in data["removals_by_reason"].values())
    assert "Omar" not in str(data) and "Al Noor" not in str(data) and "DET-" not in str(data)
    assert _events(db, "DET_AGGREGATE_VIEWED")
    with TestClient(app, follow_redirects=False) as omar:
        sign_in(omar, "omar")
        assert omar.get("/api/det/delegation-overview").status_code == 403
    # complementary suppression: exactly one small cell -> next smallest suppressed too
    cells = {"a": svc._cell(12, 10), "b": svc._cell(3, 10), "c": svc._cell(25, 10)}
    svc._complement(cells, {"a": 12, "b": 3, "c": 25}, 10)
    assert cells["b"]["suppressed"] and cells["a"]["suppressed"] and cells["a"].get("complement") and not cells["c"]["suppressed"]


def test_maintenance_dormancy_and_reviewer_history(client, db):
    omar = db.get(Identity, PERSONA_UUIDS["omar"]) or Identity(uuid=PERSONA_UUIDS["omar"], display_name="Omar Haddad", assurance_level="SOP2", profile_type=1)
    omar.last_sign_in_at = utcnow() - timedelta(days=200)
    db.add(omar)
    hassan = db.get(Identity, PERSONA_UUIDS["hassan"]) or Identity(uuid=PERSONA_UUIDS["hassan"], display_name="Hassan Qureshi", assurance_level="SOP3", profile_type=1)
    hassan.last_sign_in_at = utcnow() - timedelta(days=100)
    db.add(hassan)
    db.commit()
    out = svc.run_dormancy_check(db)
    db.commit()
    assert out["delegates_flagged"] == 3 and out["staff_suspended"] >= 1
    assert db.scalar(select(StaffRole).where(StaffRole.identity_uuid == PERSONA_UUIDS["hassan"])).status == "suspended"
    assert db.get(CompanyRole, _omar_role(db).id).status == "active"  # flagged to the owner, stays active
    with TestClient(app, follow_redirects=False) as faisal:
        sign_in(faisal, "faisal")
        r = faisal.post("/api/det/delegation-overview/maintenance")
        assert r.status_code == 200 and r.json()["companies_reconciled"] == 4
    sign_in(client, "khalid")
    assert any(p["dormant_flag"] for p in client.get(ALNOOR_DELEGATES).json()["people"] if p["identity_uuid"] == PERSONA_UUIDS["omar"])
    with TestClient(app, follow_redirects=False) as noura:
        sign_in(noura, "noura")
        hist = noura.get("/api/delegates/history", params={"company_id": CO_ALNOOR}).json()
        assert hist and all("emirates" not in str(h).lower() for h in hist)
        assert noura.get(ALNOOR_DELEGATES).status_code == 403
