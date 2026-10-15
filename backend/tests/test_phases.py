from __future__ import annotations

from datetime import timedelta

from sqlalchemy import select

from app.core.time import utcnow
from app.demo import CO_ALNOOR, CO_BLUEDUNE, CO_GULFTECH
from app.modules.audit.models import AuditEvent
from app.modules.phases import service
from tests.conftest import sign_in


def _events(db, event_type):
    return list(db.scalars(select(AuditEvent).where(AuditEvent.event_type == event_type)))


# --- gates ------------------------------------------------------------------------------------------


def test_gate_opens_only_with_evidence_and_owner_approval_versioned_and_audited(client, db):
    sign_in(client, "lina")
    gid = "gate_1c_bank_open_finance"
    r = client.post(f"/api/admin/gates/{gid}/status", json={"status": "open", "change_reason": "try"})
    assert r.status_code == 422 and r.json()["error"] == "GATE_EVIDENCE_REQUIRED"
    r = client.post(f"/api/admin/gates/{gid}/status", json={"status": "open", "change_reason": "try", "evidence_ref": "OF-LICENCE-REF-1"})
    assert r.status_code == 422 and r.json()["error"] == "GATE_APPROVAL_REQUIRED"
    r = client.post(f"/api/admin/gates/{gid}/status", json={"status": "evidence_received", "change_reason": "evidence in", "evidence_ref": "OF-LICENCE-REF-1"})
    assert r.status_code == 200 and r.json()["status"] == "evidence_received" and r.json()["panel_status"] == "in_progress"
    r = client.post(f"/api/admin/gates/{gid}/status", json={"status": "open", "change_reason": "owner approved", "approved_by": "uuid-lina-po"})
    assert r.status_code == 200 and r.json()["version"] == 3 and r.json()["panel_label"] == {"en": "Met", "ar": "تحقق"}
    hist = client.get(f"/api/admin/gates/{gid}/history").json()
    assert [h["version"] for h in hist] == [1, 2, 3] and hist[0]["effective_to"] is not None and hist[2]["effective_to"] is None
    ev = _events(db, "GATE_STATUS_CHANGED")[-1]
    assert ev.details["from_status"] == "evidence_received" and ev.details["to_status"] == "open" and ev.details["version"] == 3 and ev.details["gate_id"] == gid
    # roles: DET pilot manager may change (det.phase_switches); DET admin reads only
    sign_in(client, "faisal")
    assert client.post("/api/admin/gates/gate_1d_audit_model/status", json={"status": "evidence_received", "change_reason": "x", "evidence_ref": "MOE-REG-1"}).status_code == 200
    sign_in(client, "sara")
    assert client.get("/api/admin/gates").status_code == 200
    assert client.post("/api/admin/gates/gate_1d_audit_model/status", json={"status": "closed", "change_reason": "x"}).status_code == 403
    sign_in(client, "khalid")
    assert client.get("/api/admin/gates").status_code == 403


def test_phase_map_demo_fixture_and_demo_done_rule(client, db):
    sign_in(client, "lina")
    pm = client.get("/api/admin/phases").json()
    assert [i["id"] for i in pm["increments"]] == ["1A", "1B", "1C", "1D"]
    status = {i["id"]: i["status"] for i in pm["increments"]}
    assert status == {"1A": "live", "1B": "in_build", "1C": "not_started", "1D": "not_started"}
    gates = {g["gate_id"]: g["status"] for i in pm["increments"] for g in i["gates"]}
    assert gates["gate_1a_det_billing"] == "open" and gates["gate_1a_manual_cohort"] == "fallback_active" and gates["gate_1b_fta_format"] == "evidence_received" and gates["gate_1c_bank_open_finance"] == "not_yet_confirmed"
    assert pm["behind_switches"] == {k: False for k in pm["behind_switches"]}
    assert all(s["order"] == n + 1 for i in pm["increments"] for n, s in enumerate(i["stories"]))
    assert _events(db, "FALLBACK_ACTIVATED")
    # release before demo confirmation is refused; demo-done needs all four criteria
    r = client.post("/api/admin/phases/1A/release")
    assert r.status_code == 409 and r.json()["error"] == "DEMO_NOT_CONFIRMED"
    r = client.post("/api/admin/phases/1A/demo-done", json={"criteria": {"a": True, "b": True, "c": True}})
    assert r.status_code == 422 and r.json()["details"]["missing"] == ["d"]
    r = client.post("/api/admin/phases/1A/demo-done", json={"criteria": {"a": True, "b": True, "c": True, "d": True}})
    assert r.status_code == 200 and [g["shown"] for g in r.json()["gated_items_shown_off"]] == ["off", "off"]
    assert client.get("/api/admin/phases").json()["increments"][0]["status"] == "demo_done"
    assert client.post("/api/admin/phases/1A/release").status_code == 200 and _events(db, "INCREMENT_RELEASED")
    sign_in(client, "faisal")
    assert client.post("/api/admin/phases/1B/demo-done", json={"criteria": {"a": True, "b": True, "c": True, "d": True}}).status_code == 403


# --- integration switches ---------------------------------------------------------------------------


def test_switch_cannot_turn_on_unless_row_confirmed_live(client, db):
    assert service.integration_live(db, "manual_upload") is True
    assert service.integration_live(db, "bank_demo_a") is False and service.integration_live(db, "nonexistent") is False
    sign_in(client, "lina")
    r = client.post("/api/admin/integrations/switches/bank_link.bank_demo_a", json={"state": "ON", "reason": "try"})
    assert r.status_code == 403 and r.json()["error"] == "ROW_NOT_CONFIRMED_LIVE"
    assert _events(db, "INTEGRATION_SWITCH_REFUSED")
    rows = {x["row_id"]: x for x in client.get("/api/admin/integrations").json()["rows"]}
    assert rows["bank_demo_a"]["switch_state"] == "OFF" and rows["fta"]["status"] == "not_yet_confirmed" and rows["det_billing"]["switch_state"] == "OFF"
    assert rows["manual_upload"]["switch_state"] == "ON" and rows["uae_pass"]["mock"] is True and rows["det_licence_feed"]["status"] == "confirmed_live"
    assert rows["bank_demo_a"]["progress"] == {"n": 0, "m": 5, "label": {"en": "0 of 5 items have evidence", "ar": "0 من 5 بنود لديها دليل"}, "word": "Not started"}
    # OFF after ON stops new calls, marks in-flight unconfirmed and informs owners
    r = client.post("/api/admin/integrations/switches/manual_upload", json={"state": "OFF", "reason": "incident"})
    assert r.status_code == 200 and r.json()["state"] == "OFF"
    assert _events(db, "INTEGRATION_SWITCH_OFF")[-1].details["in_flight"] == "marked_unconfirmed" and _events(db, "OWNERS_NOTIFIED")
    assert service.integration_live(db, "manual_upload") is False


def test_row_goes_live_only_when_every_item_has_four_fields(client, db):
    sign_in(client, "lina")
    r = client.post("/api/admin/integrations/erp/status", json={"status": "confirmed_live", "change_reason": "x"})
    assert r.status_code == 422 and r.json()["error"] == "ROW_ITEMS_INCOMPLETE"
    r = client.post("/api/admin/integrations/erp/items/company_auth_pdpl/complete", json={"owner_name": "A", "owner_role": "po", "evidence_reference": "PDPL-REC-1", "evidence_date": "2026-10-01"})
    assert r.status_code == 422 and r.json()["message"] == "Missing: approver_identity"
    for item in ("company_auth_pdpl", "processor_contract", "vendor_terms"):
        r = client.post(f"/api/admin/integrations/erp/items/{item}/complete", json={"owner_name": "A", "owner_role": "po", "evidence_reference": f"REF-{item}", "evidence_date": "2026-10-01", "approver_identity": "uuid-lina-po"})
        assert r.status_code == 200, r.text
    assert r.json()["status"] == "evidence_pending" and r.json()["progress"]["word"] == "Complete"
    r = client.post("/api/admin/integrations/erp/status", json={"status": "confirmed_live", "change_reason": "all evidence in"})
    assert r.status_code == 200 and r.json()["status"] == "confirmed_live" and r.json()["version"] == 5
    sign_in(client, "faisal")  # DET pilot manager holds det.phase_switches
    r = client.post("/api/admin/integrations/switches/erp_connector", json={"state": "ON", "reason": "go-live"})
    assert r.status_code == 200 and r.json()["state"] == "ON"
    assert service.integration_live(db, "erp") is True
    hist = client.get("/api/admin/integrations/erp/history").json()
    assert [h["version"] for h in hist] == [1, 2, 3, 4, 5]


def test_evidence_expiry_reopens_row_and_switches_off_automatically(client, db):
    sign_in(client, "lina")
    past = (utcnow() - timedelta(days=1)).isoformat()
    for item in ("company_auth_pdpl", "processor_contract", "vendor_terms"):
        client.post(f"/api/admin/integrations/erp/items/{item}/complete", json={"owner_name": "A", "owner_role": "po", "evidence_reference": f"REF-{item}", "evidence_date": "2026-01-01", "approver_identity": "uuid-lina-po", "evidence_expires_at": past if item == "vendor_terms" else None})
    client.post("/api/admin/integrations/erp/status", json={"status": "confirmed_live", "change_reason": "x"})
    assert client.post("/api/admin/integrations/switches/erp_connector", json={"state": "ON", "reason": "x"}).json()["state"] == "ON"
    out = client.post("/api/admin/integrations/daily-check").json()
    assert out["expired"] == ["erp"] and out["on_without_confirmed_row"] == [] and out["target"] == 0
    row = service.current_row(db, "erp")
    assert row.status == "expired" and service.integration_live(db, "erp") is False
    assert _events(db, "INTEGRATION_EVIDENCE_EXPIRED") and _events(db, "INTEGRATION_SWITCH_OFF")


def test_det_admin_sees_aggregate_only_and_reviewer_read_only(client, db):
    sign_in(client, "sara")
    data = client.get("/api/admin/integrations").json()
    assert data["evidence_detail"] is False and "evidence_reference" not in data["rows"][0]["items"][0]
    assert data["k11"]["headline"] == {"en": "Not yet measurable", "ar": "غير قابل للقياس بعد"} and data["k11"]["secondary"]["en"] == "No bank route available"
    assert data["k12_flags"]["fta_profile_manual_accepted"] is True
    assert client.post("/api/admin/integrations/erp/status", json={"status": "switched_off", "change_reason": "x"}).status_code == 403
    sign_in(client, "noura")
    data = client.get("/api/admin/integrations").json()
    assert data["evidence_detail"] is True
    assert client.post("/api/admin/integrations/switches/manual_upload", json={"state": "OFF", "reason": "x"}).status_code == 403


# --- SC3 'What is live' --------------------------------------------------------------------------------


def test_whats_live_vocabulary_for_owner_delegate_and_refused_roles(client, db):
    sign_in(client, "khalid")
    r = client.get(f"/api/companies/{CO_ALNOOR}/whats-live")
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["panel_title"] == {"en": "What is live in your pilot", "ar": "ما هو متاح في تجربتك"}
    labels = {i["id"]: i["status_label"] for i in data["increments"]}
    assert labels["1A"] == {"en": "Live", "ar": "متاح"} and labels["1B"] == {"en": "In build", "ar": "قيد التطوير"} and labels["1C"] == {"en": "Not started", "ar": "لم يبدأ"}
    inc_b = data["increments"][1]
    assert inc_b["waiting_for"]["en"] == "Waiting for: FTA format agreement for any direct link only"
    assert inc_b["gated_items"][0]["label"]["en"] == "Not yet switched on. We will tell you when it is ready." and inc_b["gated_items"][0]["clickable"] is False
    assert all("evidence_refs" not in g and "approved_by" not in g for i in data["increments"] for g in i["gates"])
    feats = {f["key"]: f for f in data["features"]}
    assert feats["bank_link"]["note"] == {"en": "Bank link: not available yet. You can upload statements yourself.", "ar": "الربط المصرفي: غير متاح بعد. يمكنك رفع كشوف الحساب بنفسك."}
    assert feats["bank_link"]["button"] == {"en": "Upload statements", "ar": "رفع الكشوف"} and feats["bank_link"]["manual_label"]["en"] == "manual, unverified"
    assert feats["fta_submission"]["note"]["en"] == "Tax authority submission: prepared here, filed by you on the FTA portal (EmaraTax)." and feats["fta_submission"]["button"]["en"] == "Open the filing pack"
    assert feats["erp_link"]["button"]["en"] == "Enter figures" and feats["licence_details"]["available"] is True and feats["licence_details"]["note"] is None
    assert feats["payment"]["note"]["en"].startswith("Online payment from this page is not available yet.") and feats["payment"]["button"] is None
    assert data["phase_strip"][0]["marker"] == "Current" and data["phase_strip"][1]["marker"] == "Later"
    assert data["phase_strip_text"]["en"].startswith("Phase 1: manual upload, tax preparation, reminders.")
    # delegate on Gulf Tech (bookkeeping only): 1C/1D not assigned
    sign_in(client, "omar")
    data = client.get(f"/api/companies/{CO_GULFTECH}/whats-live").json()
    status = {i["id"]: i["status"] for i in data["increments"]}
    assert status["1A"] == "live" and status["1B"] == "in_build" and status["1C"] == "not_assigned"
    assert data["increments"][2]["status_label"] == {"en": "Not assigned to you", "ar": "غير مُسند إليك"}
    assert client.get(f"/api/companies/{CO_BLUEDUNE}/whats-live").status_code == 200
    sign_in(client, "layla")
    assert client.get(f"/api/companies/{CO_ALNOOR}/whats-live").status_code == 403
    sign_in(client, "sara")
    assert client.get(f"/api/companies/{CO_ALNOOR}/whats-live").status_code == 403


def test_manual_path_live_when_gate_not_met_but_fallback_built(db):
    inc = db.get(type(service.increments(db)[0]), "1B")
    inc.build_state = "built"
    db.flush()
    assert service.increment_status(db, inc) == "manual_path_live"
    card = next(i for i in service.whats_live(db)["increments"] if i["id"] == "1B")
    assert card["status_label"] == {"en": "Manual path live", "ar": "المسار اليدوي متاح"} and card["until_then"]["en"].startswith("Until then: ")


def test_require_integration_raises_switched_off(db):
    import pytest

    from app.core.errors import SwitchedOff

    with pytest.raises(SwitchedOff) as exc:
        service.require_integration(db, "fta")
    assert exc.value.reason_code == "FEATURE_SWITCHED_OFF" and "manual upload" in str(exc.value)
