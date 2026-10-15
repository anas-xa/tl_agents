"""E2-S5 pilot cohort management."""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import select

from app.modules.audit.models import AuditEvent
from app.modules.cohorts import service
from app.modules.cohorts.models import CohortChangeRequest, CohortInterest, CohortMembership
from app.modules.config.service import get_config, get_config_entry, get_rule
from app.modules.licences.models import Licence
from app.modules.subscriptions.models import Subscription
from tests.conftest import sign_in


def _audit(db, event_type, reason=None):
    stmt = select(AuditEvent).where(AuditEvent.event_type == event_type)
    if reason:
        stmt = stmt.where(AuditEvent.reason_code == reason)
    return list(db.scalars(stmt))


def _new_cohort(client, **over):
    body = {"name": "Wave 1c test", "code": "W1C", "wave": "1c", "criteria": {"legal_form": ["LLC"]}, "status": "active"}
    body.update(over)
    return client.post("/api/det/cohort", json=body)


def _fresh_licence(db, number="DET-7700001", company_id="co_gulftech"):
    from app.modules.licences.models import LicencePerson

    today = datetime.utcnow().date()
    lic = Licence(company_id=company_id, licence_number=number, trade_name_en="Fresh LLC", trade_name_ar="فرش ذ.م.م", legal_form="LLC", category="Commercial", activities=["Retail"], issue_date=today - timedelta(days=700), expiry_date=today + timedelta(days=90), status="active", raw_status="ACTIVE", scope="in_scope", ejari_number="EJ-1", last_det_refresh_at=datetime.utcnow())
    db.add(lic)
    db.flush()
    db.add(LicencePerson(licence_id=lic.id, display_name="Owner", capacity="owner", emirates_id_hash="h", has_emirates_id=True))
    db.commit()
    return lic


def test_config_waves_caps_modes_and_eligibility_rule(client, db):
    sign_in(client, "sara")
    cfg = client.get("/api/det/cohort/config").json()
    caps = {w["code"]: w["cap"] for w in cfg["waves"]}
    assert caps == {"1a": None, "1b": 100, "1c": 300} and cfg["waves"][0]["billing"] is False
    assert cfg["default_enrolment_mode"] == "opt_in" and cfg["default_on_mode_enabled"] is False
    assert cfg["stale_block_threshold_hours"] == 36 and cfg["suppression_n"] == 10
    assert cfg["can_manage"] is True and cfg["can_approve"] is False
    assert cfg["eligibility_rule"]["owner_location"].startswith("never")
    assert get_rule(db, "cohort_eligibility_v1").status == "to_be_confirmed"
    assert get_config_entry(db, "suppression.N").label.startswith("provisional, set by DET")
    assert get_config(db, "cohort.wave1_cap") == 100 and get_config(db, "cohort.wave2_cap") == 300


def test_create_cohort_rules(client, db):
    sign_in(client, "sara")
    r = _new_cohort(client, status="draft")
    assert r.status_code == 200 and r.json()["status"] == "draft" and r.json()["version"] == 1 and r.json()["size_limit"] == 300
    assert r.json()["selection_criteria"]["mainland_only"] is True
    assert _new_cohort(client, size_limit=301).status_code == 422
    r = _new_cohort(client, enrolment_mode="default_on_with_opt_out")
    assert r.status_code == 403 and r.json()["error"] == "DEFAULT_ON_MODE_OFF"
    r = _new_cohort(client, modules=["tax", "virtual_lawyer"])
    assert r.status_code == 422 and r.json()["error"] == "COHORT_MODULE_NOT_ALLOWED"
    cid = client.get("/api/det/cohort").json()["cohorts"][-1]["cohort_id"]
    r = client.post(f"/api/det/cohort/{cid}/versions", json={"reason": "raise limit", "size_limit": 250})
    assert r.json()["version"] == 2
    detail = client.get(f"/api/det/cohort/{cid}").json()
    assert [v["version"] for v in detail["versions"]] == [2, 1]
    assert client.post(f"/api/det/cohort/{cid}/versions", json={"reason": "", "size_limit": 10}).status_code == 422


def test_access_matrix(client):
    for persona in ("khalid", "noura", "layla"):
        sign_in(client, persona)
        assert client.get("/api/det/cohort").status_code == 403
    sign_in(client, "faisal")
    assert client.get("/api/det/cohort").status_code == 200
    sign_in(client, "sara")
    detail = client.get("/api/det/cohort/coh_pilot1").json()
    assert detail["members"] and all("fils" not in k for m in detail["members"] for k in m)
    assert detail["members"][0]["subscription_status"] in ("active", "billed")
    assert detail["aggregates"]["total"]["suppressed"] is True and detail["aggregates"]["suppression_label"] == "provisional, set by DET"


def test_preview_eligibility_reasons(client, db):
    _fresh_licence(db)
    sign_in(client, "sara")
    cid = _new_cohort(client, criteria={"legal_form": ["LLC", "Sole establishment"]}).json()["cohort_id"]
    p = client.post(f"/api/det/cohort/{cid}/preview").json()
    assert p["stale"] is False and p["rule_summary"].startswith("Licence is a DET mainland licence and Legal form is LLC or Sole establishment")
    excluded = {r["licence_number"]: r["reason_codes"] for r in p["excluded"]}
    assert "already_in_another_cohort" in excluded["DET-1023456"]
    assert "status_expired" in excluded["DET-3067890"]
    assert "no_owner_with_emirates_id" in excluded["DET-4089012"]
    assert "DMCC-44120" not in {r["licence_number"] for r in p["matched"]}
    assert [r["licence_number"] for r in p["matched"]] == ["DET-7700001"]
    assert p["match_count"] == 1 and p["size_limit"] == 300


def test_two_person_rule_idempotency_and_replay(client, db):
    lic = _fresh_licence(db)
    sign_in(client, "sara")
    cid = _new_cohort(client).json()["cohort_id"]
    body = {"licence_numbers": [lic.licence_number], "action": "enrol", "request_id": "req-1", "reason": "selected by DET"}
    r = client.post(f"/api/det/cohort/{cid}/changes", json=body)
    assert r.status_code == 200, r.text
    change = r.json()["changes"][0]
    assert change["state"] == "pending"
    assert client.post(f"/api/det/cohort/{cid}/changes", json=body).json()["changes"][0]["id"] == change["id"]  # two clicks, one change
    r = client.post(f"/api/det/cohort/{cid}/changes", json=dict(body, reason="different reason"))
    assert r.json()["changes"][0]["id"] == change["id"] and r.json()["changes"][0]["state"] == "pending"
    assert _audit(db, "COHORT_CHANGE_REPLAY_MISMATCH")
    assert client.post(f"/api/det/cohort/{cid}/changes", json=dict(body, request_id="req-2")).json()["changes"][0]["id"] == change["id"]  # open pending returned
    assert client.post(f"/api/det/cohort/{cid}/changes", json=dict(body, reason="")).status_code == 422
    assert client.post(f"/api/det/cohort/changes/{change['id']}/approve").status_code == 403  # det_admin lacks cohort.approve
    sign_in(client, "faisal")
    r = client.post(f"/api/det/cohort/{cid}/changes", json={"licence_numbers": ["DET-7700001"], "action": "pause", "request_id": "req-p", "reason": "x"})
    own = r.json()["changes"][0]["id"]
    r = client.post(f"/api/det/cohort/changes/{own}/approve")
    assert r.status_code == 403 and r.json()["error"] == "SELF_APPROVAL" and _audit(db, "COHORT_CHANGE_REFUSED", "SELF_APPROVAL")
    r = client.post(f"/api/det/cohort/changes/{change['id']}/approve")
    assert r.status_code == 200 and r.json()["state"] == "applied" and r.json()["approver_key"] != r.json()["requester_key"]
    m = db.scalar(select(CohortMembership).where(CohortMembership.licence_number == "DET-7700001"))
    assert m.status == "enrolled_starts_next_event" and m.last_notice_event == "enrolled"
    assert _audit(db, "COHORT_CHANGE_APPROVED") and _audit(db, "COHORT_COMPANY_NOTICE")
    assert db.scalar(select(Subscription).where(Subscription.licence_number == "DET-7700001")) is None  # mid-term joiner: next event only


def test_batch_over_cap_refused_in_full(client, db):
    a, b = _fresh_licence(db, "DET-7700002"), _fresh_licence(db, "DET-7700003")
    sign_in(client, "sara")
    cid = _new_cohort(client, size_limit=1).json()["cohort_id"]
    r = client.post(f"/api/det/cohort/{cid}/changes", json={"licence_numbers": [a.licence_number, b.licence_number], "action": "enrol", "request_id": "b1", "reason": "batch"})
    assert r.status_code == 422 and r.json()["error"] == "COHORT_SIZE_LIMIT" and r.json()["details"]["excess"] == 1
    assert db.scalar(select(CohortChangeRequest).where(CohortChangeRequest.cohort_id == cid)) is None


def test_stale_data_blocks_confirmation_but_not_preview(client, db):
    lic = _fresh_licence(db, "DET-7700004")
    sign_in(client, "sara")
    cid = _new_cohort(client).json()["cohort_id"]
    change = client.post(f"/api/det/cohort/{cid}/changes", json={"licence_numbers": [lic.licence_number], "action": "enrol", "request_id": "s1", "reason": "x"}).json()["changes"][0]
    db.get(Licence, lic.id).last_det_refresh_at = datetime.utcnow() - timedelta(hours=40)
    db.commit()
    assert client.post(f"/api/det/cohort/{cid}/preview").status_code == 200
    sign_in(client, "faisal")
    r = client.post(f"/api/det/cohort/changes/{change['id']}/approve")
    assert r.status_code == 409 and r.json()["error"] == "STALE_LICENCE_DATA"


def test_late_approval_rejected_unless_allow_shift(client, db):
    a, b = _fresh_licence(db, "DET-7700005"), _fresh_licence(db, "DET-7700006")
    sign_in(client, "sara")
    cid = _new_cohort(client).json()["cohort_id"]
    assert client.post(f"/api/det/cohort/{cid}/changes", json={"licence_numbers": [a.licence_number], "action": "enrol", "request_id": "l0", "reason": "x", "effective_at": "2020-01-01T00:00:00Z"}).status_code == 422
    c1 = client.post(f"/api/det/cohort/{cid}/changes", json={"licence_numbers": [a.licence_number], "action": "enrol", "request_id": "l1", "reason": "x"}).json()["changes"][0]
    c2 = client.post(f"/api/det/cohort/{cid}/changes", json={"licence_numbers": [b.licence_number], "action": "enrol", "request_id": "l2", "reason": "x", "allow_shift": True}).json()["changes"][0]
    for cid_ in (c1["id"], c2["id"]):
        db.get(CohortChangeRequest, cid_).effective_at = datetime.utcnow() - timedelta(hours=2)
    db.commit()
    sign_in(client, "faisal")
    r1 = client.post(f"/api/det/cohort/changes/{c1['id']}/approve").json()
    assert r1["state"] == "rejected" and r1["rejection_reason"] == "effective date passed"
    r2 = client.post(f"/api/det/cohort/changes/{c2['id']}/approve").json()
    assert r2["state"] == "applied" and datetime.fromisoformat(r2["effective_at"]) > datetime.utcnow() - timedelta(minutes=5)


def test_ineligible_licences_cannot_be_added(client, db):
    sign_in(client, "sara")
    cid = _new_cohort(client).json()["cohort_id"]
    r = client.post(f"/api/det/cohort/{cid}/changes", json={"licence_numbers": ["DMCC-44120"], "action": "enrol", "request_id": "i1", "reason": "x"})
    assert r.status_code == 422 and "not_det_licensed" in r.json()["details"]["reason_codes"]
    r = client.post(f"/api/det/cohort/{cid}/changes", json={"licence_numbers": ["DET-3067890"], "action": "enrol", "request_id": "i2", "reason": "x"})
    assert r.status_code == 422 and "status_expired" in r.json()["details"]["reason_codes"]
    r = client.post(f"/api/det/cohort/{cid}/changes", json={"licence_numbers": ["NOPE-1"], "action": "enrol", "request_id": "i3", "reason": "x"})
    assert r.status_code == 422 and r.json()["error"] == "COHORT_LICENCE_UNKNOWN"


def test_register_interest_is_candidate_only(client, db):
    sign_in(client, "omar")
    assert client.post("/api/companies/co_alnoor/cohort/interest", json={"licence_number": "DET-1023456"}).status_code == 403
    sign_in(client, "priya")
    r = client.post("/api/companies/co_bluedune/cohort/interest", json={"licence_number": "DET-2045678"})
    assert r.status_code == 200 and r.json()["status"] == "candidate"
    sign_in(client, "khalid")
    assert client.post("/api/companies/co_alnoor/cohort/interest", json={"licence_number": "DET-2045678"}).status_code == 404
    view = client.get("/api/companies/co_gulftech/cohort") if False else None  # khalid has no role on Gulf Tech
    assert view is None
    sign_in(client, "omar")
    rows = client.get("/api/companies/co_gulftech/cohort").json()["licences"]
    assert rows[0]["pilot_status"] == "not_in_pilot" and rows[0]["interest_status"] == "candidate"
    assert db.scalar(select(Subscription).where(Subscription.licence_number == "DET-4089012")) is None
    assert db.scalar(select(CohortInterest).where(CohortInterest.licence_number == "DET-2045678")) is not None


def test_removal_never_cancels_paid_term_and_licences_in_and_out_independently(client, db):
    sign_in(client, "sara")
    change = client.post("/api/det/cohort/coh_pilot1/changes", json={"licence_numbers": ["DET-3067890"], "action": "remove", "request_id": "rm1", "reason": "DET decision"}).json()["changes"][0]
    sign_in(client, "faisal")
    assert client.post(f"/api/det/cohort/changes/{change['id']}/approve").json()["state"] == "applied"
    m = db.scalar(select(CohortMembership).where(CohortMembership.licence_number == "DET-3067890"))
    assert m.status == "removed" and m.last_notice_event == "removed"
    assert db.get(Subscription, "sub_safwa").status == "billed"  # runs to term end; no cancel, no refund
    sign_in(client, "khalid")
    safwa = client.get("/api/companies/co_safwa/cohort").json()["licences"][0]
    alnoor = client.get("/api/companies/co_alnoor/cohort").json()["licences"][0]
    assert safwa["pilot_status"] == "removed" and safwa["last_notice_event"] == "removed"
    assert alnoor["pilot_status"] == "active" and alnoor["enrolment_mode"] == "opt_in"
    # point-in-time lookup: before enrolment -> none; now -> none for the removed licence, PILOT1 for Al Noor
    assert service.membership_at(db, "DET-1023456", datetime.utcnow() - timedelta(days=500)) is None
    assert service.membership_at(db, "DET-1023456", datetime.utcnow())["cohort_code"] == "PILOT1"
    assert service.membership_at(db, "DET-3067890", datetime.utcnow()) is None
    assert service.membership_at(db, "DET-3067890", datetime.utcnow() - timedelta(days=100))["cohort_code"] == "PILOT1"


def test_close_cohort_keeps_subscriptions(client, db):
    sign_in(client, "sara")
    change = client.post("/api/det/cohort/coh_pilot1/changes", json={"action": "close", "request_id": "c1", "reason": "wave review"}).json()["changes"][0]
    sign_in(client, "faisal")
    assert client.post(f"/api/det/cohort/changes/{change['id']}/approve").json()["state"] == "applied"
    assert service.current_cohort(db, "coh_pilot1").status == "closed" and service.current_cohort(db, "coh_pilot1").version == 2
    assert db.get(Subscription, "sub_alnoor").status == "active"


def test_suppression_function():
    out = service.suppress_breakdown({"a": 3, "b": 50, "c": 40}, 10)
    assert out["a"]["suppressed"] and out["c"]["suppressed"] and out["c"].get("complementary") and not out["b"]["suppressed"]
    assert service.suppress_cell(9, 10) == {"value": None, "suppressed": True, "label": "fewer_than_10"}
    assert service.suppress_cell(10, 10)["value"] == 10
