"""E3-S3 compliance agent: statuses, precedence, evidence states, conflicts, prepared drafts and K15."""

from __future__ import annotations

from datetime import timedelta

from conftest import sign_in

from app.core.time import dubai_today
from app.demo import CO_ALNOOR, CO_BLUEDUNE, CO_GULFTECH, CO_SAFWA
from app.modules.compliance import service as cs
from app.modules.compliance.models import ApprovalRecord, ConflictLog


def _card(ev: dict, rtype: str) -> dict:
    return next(c for c in ev["cards"] if c["requirement_type"] == rtype)


def test_status_precedence_helpers():
    assert cs.worst("met", "due_soon", "at_risk", "overdue") == "overdue"
    assert cs.worst("met", "at_risk") == "at_risk"
    assert cs.worst("due_soon", "met") == "due_soon"
    assert cs.worst("unknown") == "unknown"
    assert cs.status_from_days(None, 60, 30) == "unknown"
    assert cs.status_from_days(-1, 60, 30) == "overdue"
    assert cs.status_from_days(30, 60, 30) == "at_risk"
    assert cs.status_from_days(45, 60, 30) == "due_soon"
    assert cs.status_from_days(61, 60, 30) == "met"


def test_alnoor_ejari_dependency_at_risk_and_banner(db):
    ev = cs.evaluate(db, CO_ALNOOR)
    ej = _card(ev, "ejari_expiry")
    assert ej["status"] == "at_risk" and ej["gap_days"] == 15 and ej["source_label"] == "Ejari"
    assert ej["source_line"]["en"].startswith("Ejari status as last received from DET, refreshed on")
    lic = _card(ev, "licence_expiry")
    assert lic["status"] == "due_soon" and lic["days_left"] == 45 and lic["evidence"] == "verified"
    banner = next(b for b in ev["banners"] if b["kind"] == "ejari_at_risk")
    assert banner["text"]["en"] == "Ejari at risk: it expires 15 days before your licence expires. Next step: renew your Ejari, then your licence renewal can go ahead."
    assert "ينتهي قبل انتهاء رخصتك بـ 15 يومًا" in banner["text"]["ar"]
    assert ev["all_clear"] is False and ev["all_clear_label"] is None


def test_safwa_overdue_beats_at_risk_and_lapsed_banner(db):
    ev = cs.evaluate(db, CO_SAFWA)
    assert _card(ev, "licence_expiry")["status"] == "overdue"
    assert _card(ev, "ejari_expiry")["status"] == "overdue"  # both overdue and at risk -> overdue
    kinds = {b["kind"] for b in ev["banners"]}
    assert {"licence_expired", "ejari_lapsed"} <= kinds
    assert ev["overall_status"] == "overdue"


def test_owner_declared_never_met_or_valid(db):
    ev = cs.evaluate(db, CO_BLUEDUNE)
    ej = _card(ev, "ejari_expiry")
    assert ej["evidence"] == "owner_declared" and ej["chip"] != "met" and ej["check_icon"] is False
    assert ej["chip"] in ("owner_declared", "at_risk", "due_soon", "overdue")
    assert any(n["en"] == "based on your declared dates" for n in ej["notes"])
    ch = _card(ev, "chambers_membership")
    assert ch["status"] == "unknown" and ch["chip_label"]["en"] == "Cannot confirm"
    assert ev["summary"]["unverified"] >= 1 and ev["summary"]["met"] == 1  # only the DET-read licence expiry is Met
    # never a 'valid' or 'Compliant' mark anywhere in the payload
    text = str(ev)
    assert all(c["chip_label"]["en"] not in ("Met", "Valid") for c in ev["cards"] if c["evidence"] != "verified")
    assert "Compliant" not in text


def test_to_be_confirmed_rows_outside_totals(db):
    ev = cs.evaluate(db, CO_SAFWA)
    codes = {t["code"] for t in ev["to_be_confirmed"]}
    assert {"ubo_declaration", "renewal_grace_period", "civil_defence_approval"} <= codes  # Safwa trades foodstuff
    assert all(t["status"] == "to_be_confirmed" and t["chip_label"]["en"] == "to be confirmed by DET" for t in ev["to_be_confirmed"])
    total = ev["summary"]["met"] + ev["summary"]["unverified"] + ev["summary"]["attention"] + ev["summary"]["cannot_confirm"]
    assert total <= len(ev["cards"]) == 3
    gt = cs.evaluate(db, CO_GULFTECH)
    assert "civil_defence_approval" not in {t["code"] for t in gt["to_be_confirmed"]}


def test_sources_differ_earlier_date_and_conflict_logged(db):
    ej_det = cs.evaluate(db, CO_GULFTECH)
    before = _card(ej_det, "ejari_expiry")["due_date"]
    earlier = dubai_today() + timedelta(days=100)
    cs.record_source_read(db, CO_GULFTECH, "ejari_expiry", earlier, source_label="Ejari", reference="EJ-55-2024-4477")
    ev = cs.evaluate(db, CO_GULFTECH)
    ej = _card(ev, "ejari_expiry")
    assert ej["due_date"] == earlier.isoformat() != before
    assert any(n["en"] == "Sources differ" for n in ej["notes"])
    assert db.query(ConflictLog).filter_by(company_id=CO_GULFTECH, kind="sources_differ").count() >= 1


def test_source_read_replaces_owner_value_with_history(client, db):
    sign_in(client, "khalid")
    r = client.post(f"/api/companies/{CO_ALNOOR}/compliance/declare", json={"requirement_type": "chambers_membership", "value_date": (dubai_today() + timedelta(days=20)).isoformat()})
    assert r.status_code == 200, r.text
    ch = _card(r.json(), "chambers_membership")
    assert ch["source_label"] == "DET" and any(n["en"] == "Source differs from your entry" for n in ch["notes"]) and ch["history"]


def test_api_permissions_and_remote_owner_read_only(client):
    sign_in(client, "priya")
    r = client.get(f"/api/companies/{CO_BLUEDUNE}/compliance")
    assert r.status_code == 200 and r.json()["can_prepare"] is False and r.json()["prepare_disabled_reason"]
    assert client.post(f"/api/companies/{CO_BLUEDUNE}/compliance/packs", json={}).status_code == 403
    assert client.get(f"/api/companies/{CO_ALNOOR}/compliance").status_code == 403
    client.cookies.clear()
    sign_in(client, "omar")  # no licence/compliance function on Al Noor: not shared
    r = client.get(f"/api/companies/{CO_ALNOOR}/compliance")
    assert r.status_code == 403 and r.json()["error"] == "FUNCTION_NOT_ASSIGNED"


def test_prepared_pack_review_edit_and_k15(client, db):
    sign_in(client, "khalid")
    d = client.post(f"/api/companies/{CO_ALNOOR}/compliance/packs", json={"output_type": "renewal_checklist"}).json()
    assert d["ai_prepared"] and d["review_status"] == "draft_not_reviewed" and d["ai_label"]["en"] == "AI-prepared, not reviewed"
    assert d["footer"]["en"] == "Draft only. Nothing has been sent to DET or Ejari." and d["content"]["ar"]["licence_number"] == d["content"]["en"]["licence_number"]
    r = client.post(f"/api/companies/{CO_ALNOOR}/compliance/packs/{d['id']}/review").json()
    assert r["review_status"] == "reviewed" and r["ai_label"]["en"].startswith("AI-prepared, reviewed by you")
    r = client.post(f"/api/companies/{CO_ALNOOR}/compliance/packs/{d['id']}/edit", json={"changes": [{"field": "wording.intro", "new": "Hello"}]}).json()
    assert r["review_status"] == "draft_not_reviewed"  # edit after review resets
    out = client.post(f"/api/companies/{CO_ALNOOR}/compliance/packs/{d['id']}/approve").json()
    assert out["k15"]["classification"] == "accepted_with_non_material_change" and out["approval_record"]["external_write"] is False
    assert out["draft"]["footer"]["en"].endswith("Nothing has been sent to DET or Ejari.")
    d2 = client.post(f"/api/companies/{CO_ALNOOR}/compliance/packs", json={}).json()
    out2 = client.post(f"/api/companies/{CO_ALNOOR}/compliance/packs/{d2['id']}/approve").json()
    assert out2["k15"]["classification"] == "accepted_without_material_change"
    d3 = client.post(f"/api/companies/{CO_ALNOOR}/compliance/packs", json={}).json()
    client.post(f"/api/companies/{CO_ALNOOR}/compliance/packs/{d3['id']}/edit", json={"changes": [{"field": "items.ejari_expiry.due_date", "new": "2030-01-01"}]})
    out3 = client.post(f"/api/companies/{CO_ALNOOR}/compliance/packs/{d3['id']}/approve").json()
    assert out3["k15"]["classification"] == "accepted_with_material_change"
    assert db.query(ApprovalRecord).filter_by(company_id=CO_ALNOOR).count() == 3


def test_material_fields_fail_closed_for_unknown_type():
    assert cs.classify_change("renewal_checklist", "licence_number")
    assert not cs.classify_change("renewal_checklist", "wording.title")
    assert cs.classify_change("unknown_type", "anything.at.all")
    assert not cs.classify_change("unknown_type", "translation.ar")


def test_delegate_cannot_approve(client):
    sign_in(client, "khalid")
    d = client.post(f"/api/companies/{CO_ALNOOR}/compliance/packs", json={}).json()
    client.cookies.clear()
    sign_in(client, "omar")
    r = client.post(f"/api/companies/{CO_ALNOOR}/compliance/packs/{d['id']}/approve")
    assert r.status_code == 403 and r.json()["error"] == "APPROVAL_NOT_PERMITTED"


def test_reminder_control_states_on_cards(client):
    sign_in(client, "khalid")
    ev = client.get(f"/api/companies/{CO_ALNOOR}/compliance").json()
    ej = _card(ev, "ejari_expiry")
    assert ej["reminder_control"]["state"] == "available" and ej["reminder_control"]["default_lead_days"] == 7
    r = client.post(f"/api/companies/{CO_ALNOOR}/reminders/requests", json={"requirement_type": "ejari_expiry", "due_date": ej["due_date"]})
    assert r.status_code == 200 and r.json()["message"]["en"].startswith("Reminder set for")
    ej2 = _card(client.get(f"/api/companies/{CO_ALNOOR}/compliance").json(), "ejari_expiry")
    assert ej2["reminder_control"]["state"] == "scheduled"
