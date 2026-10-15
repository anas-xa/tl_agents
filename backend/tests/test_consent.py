"""E4-S1 / E4-S2: consent store, gate, lifecycle (pause / lapse), withdrawal enforcement, request-right action."""

from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import select

from app.core.time import utcnow
from app.modules.audit.models import AuditEvent
from app.modules.companies.models import CompanyRole
from app.modules.config.service import set_config
from app.modules.consent import service as csvc
from app.modules.consent.models import Consent, ConsentWithdrawal, Notification
from app.modules.consent.strings import STRINGS as CONSENT_STRINGS
from app.modules.datalinks.models import PullJob, StatementUpload
from app.modules.licences.models import Licence
from tests.conftest import sign_in

ALNOOR = "co_alnoor"


@pytest.fixture(autouse=True)
def _clear_gate_cache():
    csvc.invalidate_gate()
    yield
    csvc.invalidate_gate()


BANNED = ("your data is deleted", "all your data will be deleted", "consent remains valid", "Tax Agent", "hosted in the UAE", "certified")


def _events(db, event_type, reason=None):
    stmt = select(AuditEvent).where(AuditEvent.event_type == event_type)
    if reason:
        stmt = stmt.where(AuditEvent.reason_code == reason)
    return list(db.scalars(stmt))


def _expiry(days=200):
    return (utcnow() + timedelta(days=days)).replace(microsecond=0).isoformat()


def _grant_body(**over):
    body = {"consent_type": "ledger_invoice_authorisation", "data_types": ["ledger", "invoices"], "purpose": "vat_return_preparation", "expires_at": _expiry(), "provider_name": "File uploads"}
    body.update(over)
    return body


# --- grant -------------------------------------------------------------------------------------------------------


def test_owner_grants_consent_record_receipt_and_audit(client, db):
    sign_in(client, "khalid")
    r = client.post(f"/api/companies/{ALNOOR}/consents", json=_grant_body())
    assert r.status_code == 201, r.text
    c = r.json()
    assert c["status"] == "active" and c["version"] == 1 and c["created"] is True
    assert c["grantor_role"] == "owner" and c["identity_assurance_level"] == "SOP3" and c["grantor_capacity"] == "authorised_signatory"
    assert c["list_version"] == 1 and c["wording_version"] and c["receipt_ref"] and c["audit_entry_ref"]
    assert c["data_types_not_read"] == ["chart_of_accounts", "trial_balance"]
    ev = _events(db, "CONSENT_GRANTED")
    assert ev and ev[-1].subject_id == c["consent_id"] and ev[-1].log_class == "consent"
    rc = client.get(f"/api/companies/{ALNOOR}/consents/{c['consent_id']}/receipt").json()
    labels = [row["label"] for row in rc["en"]["rows"]]
    assert labels[:3] == ["Company", "Purpose", "Data source"] and "How to withdraw" in labels and "Delegation ID" not in labels
    assert rc["en"]["footer"] == "You can withdraw at any time. Withdrawing stops new data pulls."
    assert rc["ar"]["footer"] == "يمكنك السحب في أي وقت. يوقف السحب أي سحب جديد للبيانات."
    assert rc["en"]["granted_at_utc"] and rc["en"]["granted_at_gulf"] and rc["en"]["identity_assurance_level"] == "SOP3"


def test_duplicate_rejected_and_different_scope_makes_new_version(client, db):
    sign_in(client, "khalid")
    body = _grant_body(idempotency_key="k-1")
    first = client.post(f"/api/companies/{ALNOOR}/consents", json=body).json()
    dup = client.post(f"/api/companies/{ALNOOR}/consents", json=body)
    assert dup.status_code == 201 and dup.json()["created"] is False and dup.json()["duplicate_of"] == first["consent_id"]
    same_no_key = client.post(f"/api/companies/{ALNOOR}/consents", json=_grant_body()).json()
    assert same_no_key["created"] is False and same_no_key["consent_id"] == first["consent_id"]
    assert _events(db, "CONSENT_DUPLICATE_REJECTED")
    wider = client.post(f"/api/companies/{ALNOOR}/consents", json=_grant_body(data_types=["ledger", "invoices", "trial_balance"])).json()
    assert wider["created"] and wider["version"] == 2 and wider["consent_id"] != first["consent_id"]
    db.expire_all()
    old = db.get(Consent, first["consent_id"])
    assert old.status == "superseded" and old.superseded_by == wider["consent_id"]
    hist = client.get(f"/api/companies/{ALNOOR}/consents/{wider['consent_id']}/history").json()["versions"]
    assert [v["version"] for v in hist] == [1, 2] and hist[1]["compare"]["added"] == ["trial_balance"]


def test_missing_or_out_of_list_values_rejected(client, db):
    sign_in(client, "khalid")
    base = _grant_body()
    for bad in ({"purpose": None}, {"purpose": "marketing"}, {"data_types": []}, {"data_types": ["transactions"]}, {"expires_at": None}, {"expires_at": "2020-01-01T00:00:00"}, {"consent_type": "something_else"}):
        r = client.post(f"/api/companies/{ALNOOR}/consents", json={**base, **bad})
        assert r.status_code == 422, (bad, r.text)
    assert client.post(f"/api/companies/{ALNOOR}/consents", json=_grant_body(consent_type="bank_data_open_finance", source="bank", data_types=["transactions"], account_ids=[])).status_code == 422
    assert client.post(f"/api/companies/{ALNOOR}/consents", json=_grant_body(consent_type="auditor_specialist_evidence_access", source="erp")).status_code == 422
    assert db.scalar(select(Consent).where(Consent.purpose == "marketing")) is None


def test_bank_consent_stays_pending_while_route_off_and_route_limit_applies(client, db):
    sign_in(client, "khalid")
    r = client.post(f"/api/companies/{ALNOOR}/consents", json=_grant_body(consent_type="bank_data_open_finance", source="bank", data_types=["transactions"], account_ids=["AE11TEST0000000009999"], purpose="vat_return_preparation", provider_name="Emirates NBD", expires_at=_expiry(900)))
    assert r.status_code == 201, r.text
    c = r.json()
    assert c["status"] == "pending" and c["route_limit_applied"] is True and c["accounts_masked"] == ["•••• 9999"]
    assert csvc.check_consent(db, ALNOOR, "bank_data_open_finance", {"source": "bank", "data_type": "transactions", "account_id": "AE11TEST0000000009999", "purpose": "vat_return_preparation"}).allowed is False
    db.commit()
    cancel = client.post(f"/api/companies/{ALNOOR}/consents/{c['consent_id']}/cancel")
    assert cancel.status_code == 200 and cancel.json()["status_reason"] == "cancelled_before_confirmation"


# --- rights -------------------------------------------------------------------------------------------------


def test_remote_owner_priya_cannot_give_tax_consent_online(client, db):
    sign_in(client, "priya")
    r = client.post("/api/companies/co_bluedune/consents", json=_grant_body(consent_type="tax_data", source="tax_authority", data_types=["tax_profile", "due_dates"], purpose="deadline_compliance"))
    assert r.status_code == 403 and r.json()["error"] == "REMOTE_OWNER_TAX_CONSENT_NOT_AVAILABLE"
    assert r.json()["details"]["path"] == "det_support_help_line"
    ev = _events(db, "CONSENT_GRANT_REFUSED", "REMOTE_OWNER_TAX_CONSENT_NOT_AVAILABLE")
    assert ev and ev[-1].details["authority"] == "unclear authority, action blocked"
    lst = client.get("/api/companies/co_bluedune/consents").json()
    assert lst["rights"]["is_remote_owner"] and lst["rights"]["tax_consent_online"] is False and lst["rights"]["can_grant"] is False
    # a remote owner at SOP2 is refused for other consent types too (no consent.grant without UAE PASS step-up)
    r2 = client.post("/api/companies/co_bluedune/consents", json=_grant_body())
    assert r2.status_code == 403
    assert db.scalar(select(Consent).where(Consent.company_id == "co_bluedune", Consent.consent_type == "tax_data")) is None


def test_delegate_omar_refused_right_switched_off_and_can_request(client, db):
    sign_in(client, "omar")
    r = client.post(f"/api/companies/{ALNOOR}/consents", json=_grant_body())
    assert r.status_code == 403 and r.json()["error"] == "RIGHT_SWITCHED_OFF", r.text
    assert _events(db, "CONSENT_GRANT_REFUSED", "RIGHT_SWITCHED_OFF")
    lst = client.get(f"/api/companies/{ALNOOR}/consents").json()
    rights = lst["rights"]
    assert rights["is_delegate"] and not rights["can_grant"] and not rights["can_withdraw"] and rights["refusal_code"] == "RIGHT_SWITCHED_OFF" and rights["can_request"]
    assert lst["consents"], "view-only delegate still sees the cards"
    req = client.post(f"/api/companies/{ALNOOR}/consents/requests", json={"consent_type": "ledger_invoice_authorisation", "scope": {"purpose": "vat_return_preparation"}})
    assert req.status_code == 201 and req.json()["granted"] is False and req.json()["notified_count"] >= 1
    notes = list(db.scalars(select(Notification).where(Notification.kind == "consent_request", Notification.recipient_identity_uuid == "uuid-khalid-owner")))
    assert notes and "Nothing was granted" in notes[0].body_en and not any(ch.isdigit() for ch in notes[0].body_en.split(" on ")[0])
    assert _events(db, "CONSENT_RIGHT_REQUESTED")
    # expires after the configured period, grants nothing
    assert req.json()["expires_at"] > utcnow().isoformat()
    for _ in range(2):
        client.post(f"/api/companies/{ALNOOR}/consents/requests", json={"consent_type": "ledger_invoice_authorisation"})
    assert client.post(f"/api/companies/{ALNOOR}/consents/requests", json={"consent_type": "ledger_invoice_authorisation"}).status_code == 409
    # withdraw is also refused for the delegate without the right
    active = next(c for c in lst["consents"] if c["status"] == "active")
    w = client.post(f"/api/companies/{ALNOOR}/consents/{active['consent_id']}/withdraw", json={"confirm": True})
    assert w.status_code == 403 and w.json()["error"] == "RIGHT_SWITCHED_OFF"


def test_delegate_with_right_under_phase_b_switch_records_delegation(client, db):
    set_config(db, "delegate_rights.grant_consent.enabled", True, changed_by="test")
    set_config(db, "identity.approval_min_assurance_level", "SOP2", changed_by="test")
    role = db.scalar(select(CompanyRole).where(CompanyRole.identity_uuid == "uuid-omar-delegate", CompanyRole.company_id == ALNOOR))
    role.rights = ["prepare", "view", "grant_consent"]
    db.commit()
    sign_in(client, "khalid")  # creates the owner's identity record so the receipt can name the granting owner
    sign_in(client, "omar")
    r = client.post(f"/api/companies/{ALNOOR}/consents", json=_grant_body())
    assert r.status_code == 201, r.text
    c = r.json()
    assert c["grantor_role"] == "delegate" and c["delegation_id"] == role.id and c["granting_owner_name"] == "Khalid Al Mansoori"
    rc = client.get(f"/api/companies/{ALNOOR}/consents/{c['consent_id']}/receipt").json()
    labels = [row["label"] for row in rc["en"]["rows"]]
    assert "Delegation ID" in labels and "Delegated by" in labels
    assert db.scalar(select(Notification).where(Notification.recipient_identity_uuid == "uuid-khalid-owner", Notification.kind == "delegate_granted_consent")) is not None


def test_people_without_owner_level_role_never_grant(client):
    sign_in(client, "layla")
    assert client.post(f"/api/companies/{ALNOOR}/consents", json=_grant_body()).status_code == 403
    sign_in(client, "sara")
    assert client.post(f"/api/companies/{ALNOOR}/consents", json=_grant_body()).status_code == 403


# --- gate --------------------------------------------------------------------------------------------------------


def test_gate_allows_in_scope_denies_out_of_scope_and_fails_closed(db):
    scope = {"source": "erp", "data_type": "ledger", "purpose": "bookkeeping_classification"}
    d = csvc.check_consent(db, ALNOOR, "ledger_invoice_authorisation", scope)
    assert d.allowed and d.token and (d.token_expires_at - utcnow()) <= timedelta(seconds=60)
    assert csvc.check_consent(db, ALNOOR, "ledger_invoice_authorisation", {**scope, "data_type": "chart_of_accounts"}).reason_code == "DATA_TYPE_OUT_OF_SCOPE"
    assert csvc.check_consent(db, ALNOOR, "ledger_invoice_authorisation", {**scope, "purpose": "audit_preparation"}).reason_code == "PURPOSE_OUT_OF_SCOPE"
    assert csvc.check_consent(db, "co_bluedune", "bank_data_open_finance", {"source": "bank"}).reason_code == "NO_ACTIVE_CONSENT"
    assert csvc.check_consent(db, "co_safwa", "ledger_invoice_authorisation", scope).allowed is False, "paused consent never allows"
    assert _events(db, "CONSENT_GATE_ALLOW") and _events(db, "CONSENT_GATE_DENY", "DATA_TYPE_OUT_OF_SCOPE")
    set_config(db, "consent.gate.simulate_unavailable", True, changed_by="test")
    with pytest.raises(csvc.GateUnavailable) as exc:
        csvc.check_consent(db, ALNOOR, "ledger_invoice_authorisation", scope)
    assert exc.value.reason_code == "GATE_UNAVAILABLE" and exc.value.details["retryable"] is True
    assert csvc.gate_allows(db, ALNOOR, "ledger_invoice_authorisation", scope) is False
    assert _events(db, "CONSENT_GATE_UNAVAILABLE")


def test_removing_a_controlled_list_value_makes_gate_deny(db):
    lists = csvc.controlled_lists(db)
    lists["purposes"] = [p for p in lists["purposes"] if p != "bookkeeping_classification"]
    lists["version"] = 2
    set_config(db, "consent.controlled_lists", lists, changed_by="test")
    d = csvc.check_consent(db, ALNOOR, "ledger_invoice_authorisation", {"source": "erp", "data_type": "ledger", "purpose": "bookkeeping_classification"})
    assert not d.allowed and d.reason_code == "PURPOSE_REMOVED_FROM_LIST"


# --- withdrawal --------------------------------------------------------------------------------------------------


def test_withdraw_stops_pulls_restricts_data_and_writes_receipt_without_deletion_promise(client, db):
    consent = db.scalar(select(Consent).where(Consent.company_id == ALNOOR, Consent.consent_type == "ledger_invoice_authorisation", Consent.status == "active"))
    for _ in range(2):
        db.add(PullJob(company_id=ALNOOR, consent_id=consent.consent_id, source="erp", status="scheduled"))
    db.add(PullJob(company_id=ALNOOR, consent_id=consent.consent_id, source="erp", status="running"))
    db.commit()
    assert csvc.check_consent(db, ALNOOR, "ledger_invoice_authorisation", {"source": "erp", "data_type": "ledger", "purpose": "bookkeeping_classification"}).allowed
    db.commit()
    sign_in(client, "khalid")
    r = client.post(f"/api/companies/{ALNOOR}/consents/{consent.consent_id}/withdraw", json={"confirm": True})
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["status"] == "withdrawn_on_platform" and out["withdrawn_at"]
    tl = out["timeline"]
    assert [s["state"] for s in tl["steps"]] == ["done", "done", "done"] and tl["jobs_cancelled"] == 3 and tl["k13_class"] == "normal" and tl["k13_minutes"] is not None
    assert tl["pulls_stopped_at"] and tl["deletion_scheduled_at"] and tl["withdrawn_by"] == "Khalid Al Mansoori"
    db.expire_all()
    assert all(j.status == "cancelled" and j.cancel_reason == "consent_withdrawn" for j in db.scalars(select(PullJob).where(PullJob.consent_id == consent.consent_id)))
    up = db.scalar(select(StatementUpload).where(StatementUpload.company_id == ALNOOR, StatementUpload.kind == "bank_statement"))
    assert up.data_use_flag == "stopped" and tl["records_restricted"] >= 1
    # gate blocks at once (push invalidation), every denial logged
    assert csvc.check_consent(db, ALNOOR, "ledger_invoice_authorisation", {"source": "erp", "data_type": "ledger", "purpose": "bookkeeping_classification"}).allowed is False
    db.commit()
    # receipt: bilingual, fixed effects statement, no deletion promise, not a legal document
    rc = out["withdrawal_receipt"]
    text = " ".join(str(v) for v in rc["en"].values()).lower()
    assert "records required by law are kept" in text and "new data pulls have stopped" in text
    assert "deleted" not in text and "your data is deleted" not in text and "legal document" in text
    assert rc["ar"]["title"] == "إيصال سحب الموافقة" and rc["template_version"] == "v1" and rc["receipt_number"].startswith("WR-")
    assert "Withdrawing consent stops new data being collected" in rc["en"]["microcopy"]
    # three timestamps and K13 fields on the record
    w = db.scalar(select(ConsentWithdrawal).where(ConsentWithdrawal.consent_id == consent.consent_id))
    assert w.withdrawn_at and w.pulls_stopped_at and w.deletion_done_at is None and w.provider_revocation_status == "confirmed"
    # notices: delegate omar gets an in-portal note only; owner gets receipt + email stub; nothing with figures
    omar_notes = list(db.scalars(select(Notification).where(Notification.recipient_identity_uuid == "uuid-omar-delegate", Notification.kind == "consent_withdrawn_delegate")))
    assert omar_notes and {n.channel for n in omar_notes} == {"portal"} and "drafts marked stale" in omar_notes[0].body_en
    owner_notes = list(db.scalars(select(Notification).where(Notification.recipient_identity_uuid == "uuid-khalid-owner", Notification.kind == "consent_withdrawn_receipt")))
    assert {n.channel for n in owner_notes} == {"portal", "email"}
    assert _events(db, "CONSENT_WITHDRAWN") and _events(db, "CONSENT_ENFORCEMENT_STEPS")
    # withdrawing again is refused; status view keeps the timeline
    assert client.post(f"/api/companies/{ALNOOR}/consents/{consent.consent_id}/withdraw", json={}).status_code == 409
    assert client.get(f"/api/companies/{ALNOOR}/consents/{consent.consent_id}/timeline").json()["timeline"]["steps"][0]["key"] == "withdrawn"


def test_source_revocation_retry_schedule_then_manual_ticket(db):
    consent = db.scalar(select(Consent).where(Consent.company_id == "co_bluedune", Consent.consent_type == "bank_data_open_finance"))
    w = db.scalar(select(ConsentWithdrawal).where(ConsentWithdrawal.consent_id == consent.consent_id))
    assert w.provider_revocation_status == "retrying" and w.revocation_attempt_count == 2
    tl = csvc.timeline(db, consent)
    assert tl["steps"][2]["state"] == "in_progress" and tl["steps"][1]["state"] == "done"
    w.revocation_attempt_count = 0
    gaps = []
    for _ in range(5):
        before = utcnow()
        csvc.retry_source_revocation(db, w)
        gaps.append(round((w.next_retry_at - before).total_seconds() / 60))
        assert w.provider_revocation_status == "retrying"
    assert gaps == [1, 2, 4, 8, 16]
    for _ in range(24):
        csvc.retry_source_revocation(db, w)
        assert w.provider_revocation_status == "retrying"
    csvc.retry_source_revocation(db, w)
    assert w.provider_revocation_status == "failed" and w.manual_ticket_ref and w.next_retry_at is None
    assert csvc.timeline(db, consent)["steps"][2]["state"] == "failed"
    assert _events(db, "SOURCE_REVOCATION_TICKET")


def test_k13_ops_alert_when_pulls_not_stopped(db):
    consent = db.scalar(select(Consent).where(Consent.company_id == ALNOOR, Consent.consent_type == "ledger_invoice_authorisation", Consent.status == "active"))
    w = ConsentWithdrawal(consent_id=consent.consent_id, version=1, company_id=ALNOOR, withdrawn_at=utcnow() - timedelta(minutes=6), pulls_stopped_at=None, provider_revocation_status="pending")
    db.add(w)
    db.commit()
    out = csvc.run_lifecycle(db, ALNOOR)
    assert out["ops_alerts"] >= 1 and w.k13_class == "unenforced_open" and w.ops_alert_raised
    stats = csvc.k13_stats(db)
    assert stats["unenforced_open_count"] == 1 and stats["target_minutes"] == 5


def test_external_revocation_signal_wins(client, db):
    sign_in(client, "khalid")
    pending = db.scalar(select(Consent).where(Consent.company_id == ALNOOR, Consent.consent_type == "bank_data_open_finance", Consent.status == "pending"))
    sign_in(client, "adel")
    r = client.post("/api/consent/provider-events", json={"consent_id": pending.consent_id, "external_status": "revoked"})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "revocation_confirmed_by_provider" and r.json()["status_reason"] == "withdrawn_at_source"
    assert _events(db, "CONSENT_WITHDRAWN_AT_SOURCE")
    sign_in(client, "omar")
    assert client.post("/api/consent/provider-events", json={"consent_id": pending.consent_id}).status_code == 403


# --- lifecycle: pause, lapse, resume, expiry, notices --------------------------------------------------------


def test_pause_on_licence_expiry_then_lapse_after_90_days(client, db):
    consent = db.scalar(select(Consent).where(Consent.company_id == ALNOOR, Consent.consent_type == "ledger_invoice_authorisation", Consent.status == "active"))
    lic = db.scalar(select(Licence).where(Licence.company_id == ALNOOR))
    lic.status = "expired"
    db.commit()
    sign_in(client, "khalid")
    out = client.post(f"/api/companies/{ALNOOR}/consents/lifecycle").json()
    assert out["paused"] >= 1
    db.expire_all()
    assert consent.status == "paused" and consent.status_reason == "licence_expired" and consent.paused_at
    assert csvc.check_consent(db, ALNOOR, "ledger_invoice_authorisation", {"source": "erp", "data_type": "ledger", "purpose": "bookkeeping_classification"}).allowed is False
    db.commit()
    card = next(c for c in client.get(f"/api/companies/{ALNOOR}/consents").json()["consents"] if c["consent_id"] == consent.consent_id)
    assert card["display_status"] == "paused_licence_expired"
    notes = list(db.scalars(select(Notification).where(Notification.kind == "consent_paused", Notification.recipient_identity_uuid == "uuid-khalid-owner")))
    assert notes and "Data pulls are paused" in notes[0].body_en and "deleted" not in notes[0].body_en
    assert not list(db.scalars(select(Notification).where(Notification.kind == "consent_paused", Notification.recipient_identity_uuid == "uuid-omar-delegate"))), "delegates are not notified of pauses"
    # resume refused while the licence is not active
    r = client.post(f"/api/companies/{ALNOOR}/consents/{consent.consent_id}/resume")
    assert r.status_code == 409 and r.json()["error"] == "LICENCE_NOT_ACTIVE"
    # pause lapse: beyond the configured limit -> expired, fresh consent needed
    consent.paused_at = utcnow() - timedelta(days=91)
    db.commit()
    out = client.post(f"/api/companies/{ALNOOR}/consents/lifecycle").json()
    assert out["lapsed"] == 1
    db.expire_all()
    assert consent.status == "expired" and consent.status_reason == "pause_limit_exceeded"
    assert list(db.scalars(select(Notification).where(Notification.kind == "pause_limit_expired")))
    assert client.post(f"/api/companies/{ALNOOR}/consents/{consent.consent_id}/resume").status_code == 409


def test_resume_within_limit_records_act_and_unclear_authority_blocks(client, db):
    consent = db.scalar(select(Consent).where(Consent.company_id == ALNOOR, Consent.consent_type == "ledger_invoice_authorisation", Consent.status == "active"))
    consent.status, consent.status_reason, consent.paused_at = "paused", "licence_expired", utcnow() - timedelta(days=10)
    db.commit()
    sign_in(client, "khalid")
    r = client.post(f"/api/companies/{ALNOOR}/consents/{consent.consent_id}/resume")
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "active" and _events(db, "CONSENT_RESUMED")
    # Safwa: paused demo consent, licence still expired -> cannot resume
    safwa = db.scalar(select(Consent).where(Consent.company_id == "co_safwa"))
    assert client.post(f"/api/companies/co_safwa/consents/{safwa.consent_id}/resume").status_code == 409
    # unclear signing rule blocks Resume with the DET-support path
    from app.modules.licences.models import LicencePerson

    db.expire_all()
    consent.status, consent.status_reason, consent.paused_at = "paused", "licence_expired", utcnow() - timedelta(days=1)
    for p in db.scalars(select(LicencePerson).where(LicencePerson.licence_id == "lic_alnoor")):
        p.signing_rule = "unclear"
    db.commit()
    r = client.post(f"/api/companies/{ALNOOR}/consents/{consent.consent_id}/resume")
    assert r.status_code == 403 and r.json()["error"] == "AUTHORITY_UNCLEAR"


def test_expiry_evaluated_and_reminders_sent_once(client, db):
    consent = db.scalar(select(Consent).where(Consent.company_id == ALNOOR, Consent.consent_type == "ledger_invoice_authorisation", Consent.status == "active"))
    consent.expires_at = utcnow() + timedelta(days=7, hours=2)
    db.commit()
    csvc.run_lifecycle(db, ALNOOR)
    csvc.run_lifecycle(db, ALNOOR)
    db.commit()
    notes = list(db.scalars(select(Notification).where(Notification.kind == "consent_expiry_7d", Notification.recipient_identity_uuid == "uuid-khalid-owner")))
    assert len(notes) == 2 and {n.channel for n in notes} == {"portal", "email"}, "one portal + one email, not repeated"
    consent.expires_at = utcnow() - timedelta(minutes=1)
    db.commit()
    csvc.run_lifecycle(db, ALNOOR)
    assert consent.status == "expired" and consent.status_reason == "period_ended"
    db.commit()
    sign_in(client, "khalid")
    card = next(c for c in client.get(f"/api/companies/{ALNOOR}/consents").json()["consents"] if c["consent_id"] == consent.consent_id)
    assert card["status"] == "expired" and card["days_left"] is None


# --- wording guards -----------------------------------------------------------------------------------------


def test_backend_strings_bilingual_and_free_of_banned_claims():
    for key, item in CONSENT_STRINGS.items():
        assert item["en"].strip() and item["ar"].strip(), key
        low = item["en"].lower()
        for banned in BANNED:
            assert banned.lower() not in low, (key, banned)
        assert "your consent remains valid" not in low


def test_demo_fixtures_present(client):
    sign_in(client, "khalid")
    alnoor = client.get(f"/api/companies/{ALNOOR}/consents").json()
    statuses = {(c["consent_type"], c["status"]) for c in alnoor["consents"]}
    assert ("ledger_invoice_authorisation", "active") in statuses and ("bank_data_open_finance", "pending") in statuses
    assert alnoor["route"]["openfinance_enabled"] is False and alnoor["retention"]["classes"][0]["class"] == "A"
    safwa = client.get("/api/companies/co_safwa/consents").json()
    assert safwa["consents"][0]["display_status"] == "paused_licence_expired"
    sign_in(client, "priya")
    bd = client.get("/api/companies/co_bluedune/consents").json()
    assert bd["consents"][0]["status"] == "withdrawn_on_platform" and bd["consents"][0]["timeline"]["steps"][2]["state"] == "in_progress"
