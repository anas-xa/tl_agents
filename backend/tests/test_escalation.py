"""E8 Human escalation: triggers, cases, specialist handling with consent, corpus refusal, K21/K22."""

from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest
from sqlalchemy import select

from app.core.time import dubai_date, dubai_today
from app.demo import CO_ALNOOR, CO_BLUEDUNE, PERSONA_UUIDS
from app.modules.audit.models import AuditEvent
from app.modules.escalation import service as svc
from app.modules.escalation.calendar import working_days_between
from app.modules.escalation.metrics import compute_aggregates
from app.modules.escalation.models import CaseEvent, EscalationCase, OpsAlert, SpecialistEntitlement
from app.modules.escalation.strings import STRINGS
from tests.conftest import sign_in

BANNED = ("audit certificate", "sent to a lawyer", "sent to lawyer", "Tax Agent", "a lawyer will review this", "you owe", "you qualify", "you are exempt", "consultation", "low confidence")


def _events(db, event_type: str) -> list[AuditEvent]:
    return list(db.scalars(select(AuditEvent).where(AuditEvent.event_type == event_type)))


# --- E8-S1 triggers and cases ---------------------------------------------------------------------


def test_rule_set_v1_triggers_route_by_module_and_record_version(db):
    r = svc.evaluate_triggers(db, CO_ALNOOR, {"event_id": "e1", "user_raised": True, "module": "tax", "linked_item_id": "vat_2026Q3", "actor_key": "k"})
    c = db.get(EscalationCase, r["case_id"])
    assert r["decision"] == "escalate" and c.queue == "tax_specialist" and c.trigger_rule_version == "1.0" and c.escalation_reason == "user_requested"
    r2 = svc.evaluate_triggers(db, CO_ALNOOR, {"event_id": "e2", "revenue_fils": 50_000_001 * 100, "audit_file_id": "af1", "period": "FY2025"})
    assert db.get(EscalationCase, r2["case_id"]).queue == "licensed_auditor" and "audit_required" in r2["fired"]
    r3 = svc.evaluate_triggers(db, CO_ALNOOR, {"event_id": "e3", "audit_flag_input_missing": True, "audit_file_id": "af2", "period": "FY2025"})
    assert db.get(EscalationCase, r3["case_id"]).escalation_reason == "audit_signoff_required"
    r4 = svc.evaluate_triggers(db, CO_ALNOOR, {"event_id": "e4", "filing_blocked": True, "return_type": "VAT", "tax_period": "2026Q3"})
    assert db.get(EscalationCase, r4["case_id"]).module == "tax"
    due = (dubai_today() + timedelta(days=10)).isoformat()
    r5 = svc.evaluate_triggers(db, CO_ALNOOR, {"event_id": "e5", "deadline_type": "vat", "due_date": due, "licence_number": "DET-1023456", "requirement_code": "VAT_RETURN", "due_period": "2026Q3"})
    c5 = db.get(EscalationCase, r5["case_id"])
    assert c5.module == "compliance" and c5.queue == "det_compliance" and c5.priority == "deadline_near"
    far = (dubai_today() + timedelta(days=20)).isoformat()
    assert svc.evaluate_triggers(db, CO_ALNOOR, {"event_id": "e6", "deadline_type": "vat", "due_date": far, "licence_number": "x", "requirement_code": "y", "due_period": "z"})["decision"] == "no_trigger"
    assert svc.evaluate_triggers(db, CO_ALNOOR, {"event_id": "e7", "deadline_type": "corporate_tax", "due_date": far, "licence_number": "x", "requirement_code": "CT", "due_period": "FY2025"})["decision"] == "escalate"
    r8 = svc.evaluate_triggers(db, CO_ALNOOR, {"event_id": "e8", "legal_type_request": True, "title": "should not be stored", "topic_code": "legal_request"})
    c8 = db.get(EscalationCase, r8["case_id"])
    assert c8.module == "legal" and c8.title is None and c8.legal_route_status == "not_routed"
    r9 = svc.evaluate_triggers(db, CO_ALNOOR, {"event_id": "e9", "quarantine": True})
    assert db.get(EscalationCase, r9["case_id"]).escalation_reason == "quarantine_review"
    assert all(e.details.get("rule_version") == "1.0" for e in _events(db, "TRIGGER_EVALUATED"))
    assert not any("confidence" in (e.details or {}) for e in _events(db, "TRIGGER_EVALUATED"))


def test_rule_set_load_failure_fails_closed_without_blocking_licence_flows(db, monkeypatch):
    def boom(_db):
        raise svc.RuleSetUnavailable("simulated")

    monkeypatch.setattr(svc, "load_rule_set", boom)
    r = svc.evaluate_triggers(db, CO_ALNOOR, {"event_id": "held1", "module": "tax"})
    c = db.get(EscalationCase, r["case_id"])
    assert r["decision"] == "held_not_checked" and r["licence_flows_blocked"] is False
    assert r["message"]["en"] == STRINGS["held_for_review"]["en"] and r["message"]["ar"] == STRINGS["held_for_review"]["ar"]
    assert "manual_review_key_incomplete" in c.flags and "not_checked" in c.flags and c.matter_key == "unkeyed:held1"
    assert _events(db, "RULE_SET_LOAD_FAILED") and _events(db, "OUTPUT_HELD_NOT_CHECKED")
    assert db.scalar(select(OpsAlert).where(OpsAlert.alert_type == "rule_set_load_failure"))


def test_dedupe_idempotency_linking_and_unkeyed(db):
    common = dict(company_id=CO_ALNOOR, module="tax", reason_code="complex_tax", matter_key="VAT|2026Q3|filing_blocked", opened_by="agent")
    a = svc.open_case(db, event_id="ev-1", **common)
    assert svc.open_case(db, event_id="ev-1", **common).case_id == a.case_id  # replayed event id → no second case
    b = svc.open_case(db, event_id="ev-2", details={"severity": "normal"}, **common)
    assert b.case_id == a.case_id  # same open key → attached
    attached = db.scalars(select(CaseEvent).where(CaseEvent.escalation_id == a.case_id, CaseEvent.event_type == "event_attached")).all()
    assert len(attached) == 1 and attached[0].rule_version == "1.0"
    notes = db.scalars(select(CaseEvent).where(CaseEvent.escalation_id == a.case_id, CaseEvent.event_type == "notification_sent")).all()
    assert len(notes) == 1  # no second notification without severity/action change
    svc.open_case(db, event_id="ev-3", details={"severity": "high"}, **common)
    assert len(db.scalars(select(CaseEvent).where(CaseEvent.escalation_id == a.case_id, CaseEvent.event_type == "notification_sent")).all()) == 2
    other = svc.open_case(db, event_id="ev-4", **{**common, "matter_key": "VAT|2026Q4|filing_blocked"})
    assert other.case_id != a.case_id  # different period → different key
    a.status, a.resolved_at = "resolved", datetime.utcnow()
    db.flush()
    c = svc.open_case(db, event_id="ev-5", **common)
    assert c.case_id != a.case_id and c.linked_case_id == a.case_id and db.get(EscalationCase, a.case_id).status == "resolved"
    u1 = svc.open_case(db, event_id="ev-6", **{**common, "matter_key": "unkeyed:ev-6"})
    u2 = svc.open_case(db, event_id="ev-7", **{**common, "matter_key": "unkeyed:ev-7"})
    assert u1.case_id != u2.case_id and "manual_review_key_incomplete" in u1.flags
    build = svc.build_matter_key(db, "agent_output", {"return_type": "VAT", "event_id": "x"})
    assert build[0] == "unkeyed:x" and build[1] is False


def test_readback_failure_gives_setup_state_ops_alert_and_no_duplicate(db, monkeypatch, client):
    monkeypatch.setattr(svc, "_read_back", lambda *_a, **_k: False)
    with pytest.raises(svc.CaseSetupPending):
        svc.open_case(db, company_id=CO_ALNOOR, module="tax", reason_code="complex_tax", matter_key="k|p|r", event_id="rb-1", opened_by="agent")
    assert db.scalar(select(OpsAlert).where(OpsAlert.alert_type == "readback_failure"))
    assert len(_events(db, "READBACK_RETRY")) == 4  # 3 retries + first attempt
    assert db.scalar(select(EscalationCase).where(EscalationCase.idempotency_key == f"{CO_ALNOOR}|tax|k|p|r|rb-1")) is not None
    db.commit()
    sign_in(client, "khalid")
    r = client.post(f"/api/companies/{CO_ALNOOR}/cases", json={"module": "tax", "topic_code": "vat_general"})
    assert r.status_code == 201 and r.json()["status"] == "setting_up" and r.json()["message"]["en"] == STRINGS["case_setup_pending"]["en"]


def test_owner_ask_a_human_list_and_reject_flow(client, db):
    sign_in(client, "khalid")
    r = client.post(f"/api/companies/{CO_ALNOOR}/cases", json={"module": "tax", "title": "Question on input VAT", "linked_item_id": "vat_2026Q3"})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["status"] == "open" and body["handler_type"] == "ai_draft" and body["next_step"]["ar"] == STRINGS["next_step.tax"]["ar"]
    case_id = body["case_id"]
    lst = client.get(f"/api/companies/{CO_ALNOOR}/cases").json()
    assert lst["information_label"] == STRINGS["information_not_advice"] and lst["can_reject"] is True
    assert any(c["case_id"] == case_id for c in lst["cases"]) and all(not c.get("kpi_only") for c in lst["cases"])
    assert "amounts" in lst["never_shared_before_consent"]
    r = client.post(f"/api/companies/{CO_ALNOOR}/cases/{case_id}/reject", json={"reason_code": "R9"})
    assert r.status_code == 422 and r.json()["error"] == "REJECT_REASON_REQUIRED"
    r = client.post(f"/api/companies/{CO_ALNOOR}/cases/{case_id}/reject", json={"reason_code": "R5"})
    assert r.status_code == 422 and r.json()["error"] == "REJECT_NOTE_REQUIRED"
    r = client.post(f"/api/companies/{CO_ALNOOR}/cases/{case_id}/reject", json={"reason_code": "R5", "note": "x" * 301})
    assert r.status_code == 422
    r = client.post(f"/api/companies/{CO_ALNOOR}/cases/{case_id}/reject", json={"reason_code": "R3"})
    assert r.status_code == 200 and r.json()["status"] == "rejected" and r.json()["message"] == STRINGS["case_rejected"] and r.json()["read_only"] is True
    # reopen after rejection → new linked case, old stays rejected
    r = client.post(f"/api/companies/{CO_ALNOOR}/cases/{case_id}/reopen")
    assert r.status_code == 200 and r.json()["linked_case_id"] == case_id and r.json()["case_id"] != case_id
    assert db.get(EscalationCase, case_id).status == "rejected"
    # delegate: may open, cannot reject
    sign_in(client, "omar")
    r = client.post(f"/api/companies/{CO_ALNOOR}/cases", json={"module": "audit", "topic_code": "audit_general"})
    assert r.status_code == 201 and db.get(EscalationCase, r.json()["case_id"]).opened_by == "delegate"
    lst = client.get(f"/api/companies/{CO_ALNOOR}/cases").json()
    assert lst["can_reject"] is False and lst["reject_disabled_reason"] == STRINGS["only_owner_can_reject"]
    r = client.post(f"/api/companies/{CO_ALNOOR}/cases/{r.json()['case_id']}/reject", json={"reason_code": "R1"})
    assert r.status_code == 403 and r.json()["error"] == "ONLY_OWNER_CAN_REJECT"
    # company isolation
    assert client.get(f"/api/companies/{CO_BLUEDUNE}/cases").status_code in (200, 403)
    sign_in(client, "priya")
    assert client.get(f"/api/companies/{CO_ALNOOR}/cases").status_code == 403


def test_demo_fixture_states_present(client):
    sign_in(client, "khalid")
    cases = client.get(f"/api/companies/{CO_ALNOOR}/cases").json()["cases"]
    statuses = {c["module"]: c for c in cases if c["is_demo"]}
    assert statuses["tax"]["status"] == "resolved" and statuses["tax"]["handler_type"] == "licensed_human"
    assert statuses["audit"]["status"] == "awaiting_consent" and statuses["audit"]["consent_notice"] == STRINGS["consent_needed"]
    assert statuses["compliance"]["priority"] == "deadline_near" and statuses["compliance"]["status"] == "open"
    assert statuses["legal"]["title"] is None and statuses["legal"]["legal_route_status"] == "not_routed" and statuses["legal"]["next_step"] == STRINGS["licensed_professional_can_review"]
    sign_in(client, "priya")
    bd = client.get(f"/api/companies/{CO_BLUEDUNE}/cases").json()["cases"]
    closed = [c for c in bd if c["closed_no_consent"]]
    assert closed and closed[0]["status"] == "closed" and closed[0]["reopen_until"] and closed[0]["resolution_outcome"] == "d"
    text = str(cases) + str(bd)
    assert not any(b in text for b in BANNED)


# --- E8-S2 specialist handling with consent ---------------------------------------------------------


def _open_tax_case(client) -> str:
    sign_in(client, "khalid")
    r = client.post(f"/api/companies/{CO_ALNOOR}/cases", json={"module": "tax", "title": "Reverse charge question", "linked_item_id": "vat_2026Q3_rc"})
    assert r.status_code == 201, r.text
    return r.json()["case_id"]


SCOPE = [{"module": "tax", "data_class": "return", "period_from": "2026-07-01", "period_to": "2026-09-30"}]


def test_specialist_queue_accept_consent_access_and_logging(client, db):
    case_id = _open_tax_case(client)
    sign_in(client, "hassan")
    q = client.get("/api/cases/queue").json()
    assert q["mode"] == "specialist" and any(c["case_id"] == case_id for c in q["unassigned"])
    assert all("title" not in c for c in q["unassigned"])  # metadata only in the queue
    r = client.post(f"/api/cases/{case_id}/accept", json={"requested_scope": SCOPE, "purpose": "review the return draft"})
    assert r.status_code == 200 and r.json()["status"] == "awaiting_consent" and r.json()["assigned"] is True
    # pre-consent summary: fixed fields only, locked items, view logged
    s = client.get(f"/api/cases/{case_id}").json()
    assert set(s) >= {"case_id", "case_type", "escalation_reason", "deadline", "priority", "company_ref", "title", "ai_label", "locked_items"}
    assert s["locked_items"][0]["locked"] is True and "value" not in s["locked_items"][0]
    assert _events(db, "CASE_SUMMARY_VIEWED")
    # access without a grant → refused and logged
    r = client.get(f"/api/cases/{case_id}/items/return")
    assert r.status_code == 403 and r.json()["error"] == "DENIED_NO_CONSENT"
    assert _events(db, "CASE_DATA_ACCESS_DENIED")
    # owner sees awaiting consent with the notice, grants
    sign_in(client, "khalid")
    v = client.get(f"/api/companies/{CO_ALNOOR}/cases/{case_id}").json()
    assert v["status"] == "awaiting_consent" and v["status_label"] == STRINGS["status.awaiting_consent"] and v["waiting_label"]
    assert v["access_log"][0]["result"] == "Denied"
    r = client.post(f"/api/companies/{CO_ALNOOR}/cases/{case_id}/consent", json={"decision": "grant", "purpose": "review"})
    assert r.status_code == 200 and r.json()["case"]["status"] == "with_specialist" and r.json()["case"]["handler_type"] == "licensed_human"
    assert _events(db, "CONSENT_GRANTED")
    # specialist reads in scope, denied out of scope, first response, info request pauses the clock
    sign_in(client, "hassan")
    assert client.get(f"/api/cases/{case_id}/items/return").status_code == 200
    r = client.get(f"/api/cases/{case_id}/items/bank_statement")
    assert r.status_code == 403 and r.json()["error"] == "DENIED_NOT_IN_SCOPE"
    assert client.post(f"/api/cases/{case_id}/first-response", json={}).json()["first_response_at"]
    r = client.post(f"/api/cases/{case_id}/request-info", json={"request_code": "supplier_invoice"})
    assert r.json()["turnaround"]["paused_now"] is True
    sign_in(client, "khalid")
    v = client.get(f"/api/companies/{CO_ALNOOR}/cases/{case_id}").json()
    assert v["waiting_for_you"] is True and v["waiting_label"] == STRINGS["status.waiting_for_you"]
    assert client.post(f"/api/companies/{CO_ALNOOR}/cases/{case_id}/answer", json={"answer_ref": "doc-1"}).json()["waiting_for_you"] is False
    # revoke → specialist denied with 'consent ended', case back to awaiting consent
    client.post(f"/api/companies/{CO_ALNOOR}/cases/{case_id}/consent/revoke")
    sign_in(client, "hassan")
    r = client.get(f"/api/cases/{case_id}/items/return")
    assert r.status_code == 403 and r.json()["error"] == "DENIED_CONSENT_ENDED"
    assert _events(db, "CONSENT_WITHDRAWN")
    # resolve with (a) needs an active grant; owner refuses → only (c) with the limitation label
    r = client.post(f"/api/cases/{case_id}/resolve", json={"outcome": "a"})
    assert r.status_code == 403 and r.json()["error"] == "NO_ACCESS_GRANT"
    sign_in(client, "khalid")
    client.post(f"/api/companies/{CO_ALNOOR}/cases/{case_id}/consent", json={"decision": "refuse"})
    sign_in(client, "hassan")
    assert client.post(f"/api/cases/{case_id}/resolve", json={"outcome": "a"}).status_code == 422
    r = client.post(f"/api/cases/{case_id}/resolve", json={"outcome": "c"})
    assert r.status_code == 200 and "not an audit opinion" in r.json()["output_label"]["en"] and r.json()["ai_label"] == STRINGS["ai_label"]
    assert "audit certificate" not in r.json()["output_label"]["en"]
    meta = r.json()["case"]
    assert meta["status"] == "resolved" and meta["turnaround"]["active_working_days"] <= meta["turnaround"]["raw_working_days"]


def test_entitlement_fail_closed_at_assignment_and_access(client, db):
    case_id = _open_tax_case(client)
    ent = db.scalar(select(SpecialistEntitlement).where(SpecialistEntitlement.identity_uuid == PERSONA_UUIDS["hassan"]))
    ent.status = "expired"
    db.commit()
    sign_in(client, "yusuf")
    r = client.post(f"/api/cases/{case_id}/assign", json={"assignee_uuid": PERSONA_UUIDS["hassan"]})
    assert r.status_code == 403 and r.json()["error"] == "ENTITLEMENT_EXPIRED"
    assert _events(db, "ENTITLEMENT_CHECK_FAILED") and db.scalar(select(OpsAlert).where(OpsAlert.alert_type == "entitlement_lapsed"))
    ent.status = "unclear"
    db.commit()
    sign_in(client, "hassan")
    r = client.post(f"/api/cases/{case_id}/accept", json={})
    assert r.status_code == 403 and r.json()["error"] == "ENTITLEMENT_UNCLEAR"
    ent.status, ent.valid_to = "active", dubai_today() - timedelta(days=1)
    db.commit()
    assert client.post(f"/api/cases/{case_id}/accept", json={}).json()["error"] == "ENTITLEMENT_EXPIRED"
    ent.valid_to = dubai_today() + timedelta(days=365)
    db.commit()
    assert client.post(f"/api/cases/{case_id}/accept", json={}).status_code == 200
    # ops assigns/reassigns (metadata only) and every ops view is logged; a non-assigned specialist is refused
    sign_in(client, "yusuf")
    q = client.get("/api/cases/queue").json()
    assert q["mode"] == "ops" and all("title" not in c for c in q["cases"]) and _events(db, "CASE_METADATA_VIEWED")
    sign_in(client, "layla")
    assert client.get(f"/api/cases/{case_id}").status_code == 403
    # tax path switch off → refused as switched off
    from app.modules.config.service import set_config

    set_config(db, "escalation.tax_specialist_path.enabled", False, changed_by="test")
    db.commit()
    sign_in(client, "hassan")
    r = client.get(f"/api/cases/{case_id}/items/return")
    assert r.status_code == 403 and r.json()["error"] == "TAX_PATH_SWITCHED_OFF"


def test_legal_path_switched_off_and_lawyer_route_blocked(client, db):
    sign_in(client, "khalid")
    r = client.post(f"/api/companies/{CO_ALNOOR}/cases", json={"module": "legal", "title": "Can I sue my supplier?"})
    assert r.status_code == 201 and r.json()["title"] is None and r.json()["legal_route_status"] == "not_routed"
    case_id = r.json()["case_id"]
    sign_in(client, "yusuf")
    r = client.post(f"/api/cases/{case_id}/assign", json={"assignee_uuid": PERSONA_UUIDS["mariam"]})
    assert r.status_code == 403 and r.json()["error"] == "LAWYER_ROUTING_OFF"
    sign_in(client, "mariam")
    q = client.get("/api/cases/queue").json()
    assert q["mode"] == "specialist" and q["cases"] == [] and q["lawyer_path_enabled"] is False


def test_consent_wait_timeline_closes_day_14_and_reopens_within_30(client, db):
    case_id = _open_tax_case(client)
    sign_in(client, "hassan")
    client.post(f"/api/cases/{case_id}/accept", json={"requested_scope": SCOPE})
    case = db.get(EscalationCase, case_id)
    t0 = case.consent_requested_at
    r = svc.run_consent_wait(db, now=t0 + timedelta(days=2), case_id=case_id)
    assert r == {"reminders": 0, "ops_alerts": 0, "closed": 0}
    r = svc.run_consent_wait(db, now=t0 + timedelta(days=3), case_id=case_id)
    assert r["reminders"] == 1
    r = svc.run_consent_wait(db, now=t0 + timedelta(days=7, hours=1), case_id=case_id)
    assert r["reminders"] == 1 and r["ops_alerts"] == 1
    assert svc.run_consent_wait(db, now=t0 + timedelta(days=8), case_id=case_id)["reminders"] == 0  # idempotent
    r = svc.run_consent_wait(db, now=t0 + timedelta(days=14), case_id=case_id)
    db.commit()
    db.refresh(case)
    assert r["closed"] == 1 and case.status == "closed_no_consent" and case.resolution_outcome == "d" and case.reopen_until == dubai_date(t0 + timedelta(days=44))
    assert case.assigned_to is not None  # never auto-reassigned
    sign_in(client, "khalid")
    v = client.get(f"/api/companies/{CO_ALNOOR}/cases/{case_id}").json()
    assert v["status"] == "closed" and v["closed_no_consent_notice"]["en"].startswith("This case was closed because no consent was given")
    r = client.post(f"/api/companies/{CO_ALNOOR}/cases/{case_id}/reopen")
    assert r.status_code == 200 and r.json()["case_id"] == case_id and r.json()["status"] == "awaiting_consent"
    case = db.get(EscalationCase, case_id)
    db.refresh(case)
    case.status, case.reopen_until = "closed_no_consent", dubai_today() - timedelta(days=1)
    db.commit()
    r = client.post(f"/api/companies/{CO_ALNOOR}/cases/{case_id}/reopen")
    assert r.status_code == 409 and r.json()["error"] == "REOPEN_WINDOW_PASSED"


# --- E8-S3 refusal when the corpus does not cover the question ----------------------------------------


def test_covered_question_answers_with_citations_and_labels(client):
    sign_in(client, "khalid")
    r = client.post(f"/api/companies/{CO_ALNOOR}/ask", json={"question": "What is the VAT standard rate?"})
    assert r.status_code == 200, r.text
    b = r.json()
    assert b["decision"] == "answer_as_information" and b["case_id"] is None
    assert b["label_order"] == ["status_chip", "label", "body"] and b["status_chip"] == STRINGS["qa.status_chip"] and b["label"] == STRINGS["qa.label"]
    c = b["citations"][0]
    assert c["instrument"].startswith("Federal Decree-Law No. 8 of 2017") and c["article"] == "Article 3" and c["authoritative_language"] == "ar" and c["corpus_version"] and c["effective_from"]
    assert b["tax_disclaimer"] == STRINGS["qa.tax_disclaimer"] and b["unofficial_translation_note"] == STRINGS["qa.unofficial_translation"]
    assert b["value_status"] == "confirm instrument before quoting" and b["claims"][0]["passage_id"] == c["passage_id"]
    ar = client.post(f"/api/companies/{CO_ALNOOR}/ask", json={"question": "ما هي نسبة ضريبة القيمة المضافة؟"}).json()
    assert ar["decision"] == "answer_as_information" and ar["language"] == "ar" and ar["unofficial_translation_note"] is None
    text = str(b) + str(ar)
    assert not any(t in text for t in BANNED)


def test_uncovered_question_refuses_with_fixed_line_and_opens_case(client, db):
    sign_in(client, "khalid")
    r = client.post(f"/api/companies/{CO_ALNOOR}/ask", json={"question": "What are the goAML registration steps for designated non-financial businesses?"})
    b = r.json()
    assert b["decision"] in ("refuse_and_route", "out_of_corpus_refuse") and b["case_id"] and b["citations"] == []
    assert b["body"] == STRINGS["qa.refusal_line"] and b["summary"] == STRINGS["qa.not_answered"] and b["told_when_ready"] == STRINGS["qa.told_when_ready"]
    assert "general_rule" in b and b["general_rule"] is None and "cause_code" not in b
    case = db.get(EscalationCase, b["case_id"])
    assert case.module == "tax" and case.queue == "tax_specialist" and case.title is None
    # the stored answer record carries the internal cause code and versions; never shown
    from app.modules.escalation.models import AnswerRecord

    rec = db.get(AnswerRecord, b["question_id"])
    assert rec.cause_code in ("below_threshold", "unsupported_claim") and rec.threshold_version == "v1" and rec.escalation_status == "created"
    # partly covered → whole question refused
    r2 = client.post(f"/api/companies/{CO_ALNOOR}/ask", json={"question": "What is the VAT rate and how do I register a trademark in another emirate?"}).json()
    assert r2["decision"] == "refuse_and_route"


def test_threshold_and_review_band_are_config(client, db):
    from app.modules.config.service import set_config

    set_config(db, "coverage.threshold.tax", 0.99, changed_by="test")
    db.commit()
    sign_in(client, "khalid")
    r = client.post(f"/api/companies/{CO_ALNOOR}/ask", json={"question": "When is the VAT return due and what about Ejari?"}).json()
    assert r["decision"] == "refuse_and_route"
    set_config(db, "coverage.threshold.tax", 0.75, changed_by="test")
    db.commit()
    r = client.post(f"/api/companies/{CO_ALNOOR}/ask", json={"question": "When is the VAT return due and what about Ejari?"}).json()
    assert r["decision"] == "answer_as_information" and r["review_band"] is True  # score 0.75 within ±0.05 of 0.75
    from app.modules.escalation.models import AnswerRecord

    assert db.get(AnswerRecord, r["question_id"]).review_band is True


def test_own_tax_position_refused_with_general_rule_and_routed(client, db):
    sign_in(client, "khalid")
    general = client.post(f"/api/companies/{CO_ALNOOR}/ask", json={"question": "What is the small business relief revenue threshold?"}).json()
    assert general["decision"] == "answer_as_information"
    own = client.post(f"/api/companies/{CO_ALNOOR}/ask", json={"question": "Do I qualify for small business relief with my revenue?"}).json()
    assert own["decision"] == "refuse_and_route" and own["case_id"] and own["routed_to"] == "tax_specialist"
    assert own["general_rule"]["note"] == STRINGS["qa.own_position_general_rule"] and "Small Business Relief" in own["general_rule"]["citations"][0]["instrument"]
    assert "you qualify" not in own["general_rule"]["body"]["en"]
    assert db.get(EscalationCase, own["case_id"]).specialist_type == "tax"


def test_legal_question_gets_neutral_message_with_no_stored_text_and_no_case(client, db):
    from app.modules.escalation.models import AnswerRecord

    sign_in(client, "khalid")
    r = client.post(f"/api/companies/{CO_ALNOOR}/ask", json={"question": "Can I sue my supplier for breach of contract?"}).json()
    assert r["decision"] == "legal_neutral" and r["case_id"] is None and r["citations"] == []
    assert r["body"] == STRINGS["qa.legal_neutral"] and r["send_button"] == STRINGS["qa.send_to_licensed_person"] and r["label_legal"]["en"] == "general information, not legal advice"
    assert "consult a licensed lawyer of your own choice" in r["own_choice"]["en"] and r["legal_route_status"] == "not_routed"
    rec = db.get(AnswerRecord, r["question_id"])
    assert rec.question_text is None and rec.escalation_status == "not_needed"
    assert "supplier" not in str(rec.__dict__)
    assert not any(b in str(r) for b in BANNED)


def test_conflict_rules(db):
    from app.modules.escalation.corpus import detect_conflict
    from app.modules.escalation.models import CorpusPassage

    def p(pid, value, cat="all", ef=date(2020, 1, 1), et=None, status="in_force", sup=None):
        return CorpusPassage(passage_id=pid, domain="vat", instrument="X", instrument_ar="س", article="1", subject="t", rule_type="rate", value=value, taxpayer_category=cat, text_ar="أ", text_en="a", keywords=[], owner_role="o", effective_from=ef, effective_to=et, status=status, supersedes=sup)

    a = p("a", "5")
    assert detect_conflict(a, [a, p("b", "5")]) is False  # same value in two instruments
    assert detect_conflict(a, [a, p("c", "7")]) is True  # same period different values
    assert detect_conflict(a, [a, p("d", "7", cat="free_zone")]) is False  # different category
    old = p("old", "5", ef=date(2018, 1, 1), et=date(2019, 12, 31))
    assert detect_conflict(p("new", "7", ef=date(2020, 1, 1)), [old]) is False  # amended later date
    assert detect_conflict(a, [a, p("f", "7", sup="a")]) is False  # curated supersedes link
    assert detect_conflict(p("g", "5", status="superseded"), []) is True  # superseded without successor


def test_escalation_creation_failure_after_refusal_is_pending_and_retried(client, db, monkeypatch):
    from app.modules.escalation.models import AnswerRecord

    monkeypatch.setattr(svc, "_read_back", lambda *_a, **_k: False)
    sign_in(client, "khalid")
    r = client.post(f"/api/companies/{CO_ALNOOR}/ask", json={"question": "goAML obligations for dealers in precious metals?"}).json()
    assert r["case_id"] is None and r["escalation_status"] == "pending_escalation" and r["case_message"] == STRINGS["qa.case_retrying"] and r["body"] == STRINGS["qa.refusal_line_minimal"]
    qid = r["question_id"]
    monkeypatch.undo()
    assert client.post(f"/api/companies/{CO_ALNOOR}/ask/{qid}/retry").json()["created"] == [qid]
    rec = db.get(AnswerRecord, qid)
    assert rec.case_id and rec.escalation_status == "created"
    assert db.scalar(select(EscalationCase).where(EscalationCase.trigger_event_id == qid)) is not None
    assert len(db.scalars(select(EscalationCase).where(EscalationCase.trigger_event_id == qid)).all()) == 1


# --- E8-S4 tracking ---------------------------------------------------------------------------------


def test_working_days_weekend_and_provisional_holiday(db):
    # Thu 11 Jun 2026 12:00 Dubai → Wed 17 Jun 2026 12:00 Dubai; Tue 16 Jun = Islamic New Year (provisional)
    s, e = datetime(2026, 6, 11, 8, 0), datetime(2026, 6, 17, 8, 0)
    assert working_days_between(db, s, e) == 3.0
    assert working_days_between(db, date(2026, 6, 11), date(2026, 6, 11)) == 0.0  # same day = 0
    assert working_days_between(db, date(2026, 6, 13), date(2026, 6, 16)) == 1.0  # opened Saturday → starts Monday (day 0), Tue holiday
    assert working_days_between(db, date(2026, 6, 15), date(2026, 6, 22)) == 4.0  # Mon→Mon with one holiday
    from app.modules.escalation.calendar import calendar_coverage

    cov = calendar_coverage(db, date(2026, 6, 1), date(2026, 6, 30))
    assert cov["provisional"] is True and "2026-06-16" in cov["provisional_dates"] and cov["calendar_missing"] is False
    assert calendar_coverage(db, date(2031, 1, 1), date(2031, 1, 31))["calendar_missing"] is True


def _seed_metrics(db, n_compliance: int, extras: bool = True):
    from app.modules.escalation.service import record_work_item

    esc_at = datetime(2026, 6, 11, 8, 0)
    for i in range(n_compliance):
        wi = record_work_item(db, company_id=CO_ALNOOR, module="compliance", period_ref=f"T{i}", opened_at=datetime(2026, 6, 2, 8, 0))
        c = svc.open_case(db, company_id=CO_ALNOOR, module="compliance", reason_code="deadline_risk", matter_key=f"m|{i}", event_id=f"met-{i}", opened_by="agent", work_item_id=wi.id, occurred_at=esc_at)
        c.first_response_at = esc_at + timedelta(days=1)
        svc.start_pause(db, c, "awaiting_owner_information", at=datetime(2026, 6, 12, 8, 0))
        svc.end_pause(db, c, at=datetime(2026, 6, 15, 8, 0))  # Fri→Mon: 1.0 working day paused
        c.status, c.resolved_at = "resolved", datetime(2026, 6, 17, 8, 0)
        db.add(CaseEvent(escalation_id=c.case_id, event_type="resolved", occurred_at=c.resolved_at))
    for i in range(5):  # unescalated work items in the cohort
        record_work_item(db, company_id=CO_ALNOOR, module="compliance", period_ref=f"U{i}", opened_at=datetime(2026, 6, 3, 8, 0))
    if not extras:
        db.flush()
        return None
    w = svc.open_case(db, company_id=CO_ALNOOR, module="compliance", reason_code="user_requested", matter_key="withdrawn", event_id="met-w", opened_by="user", occurred_at=esc_at, period_ref="W")
    w.status, w.closed_at = "rejected", esc_at + timedelta(days=1)
    o = svc.open_case(db, company_id=CO_ALNOOR, module="compliance", reason_code="user_requested", matter_key="open", event_id="met-o", opened_by="user", occurred_at=esc_at, period_ref="O")
    bad = svc.open_case(db, company_id=CO_ALNOOR, module="compliance", reason_code="user_requested", matter_key="bad", event_id="met-b", opened_by="user", occurred_at=esc_at, period_ref="B")
    bad.status, bad.resolved_at = "resolved", esc_at - timedelta(days=1)  # closed before opened → data quality
    db.add(CaseEvent(escalation_id=bad.case_id, event_type="resolved", occurred_at=bad.resolved_at))
    db.flush()
    return o


def test_k21_k22_maths_pauses_withdrawn_open_and_data_quality(db):
    _seed_metrics(db, 12)
    agg = compute_aggregates(db, period_from=date(2026, 6, 1), period_to=date(2026, 6, 30), module="compliance", now=datetime(2026, 6, 24, 8, 0))
    k21 = agg["k21"]["by_module"]["compliance"]
    assert k21["total"] == 12 + 5 + 3 and k21["escalated"] == 15 and k21["rate_per_100"] == 75.0 and k21["suppressed"] is False
    k22 = agg["k22"]["headline"]
    assert k22["raw_working_days"] == 3.0 and k22["active_working_days"] == 2.0 and k22["first_response_working_days"] == 1.0 and k22["resolved"] == 12
    assert agg["k22"]["withdrawn_count"] == {"suppressed": True, "fewer_than": 10}
    assert agg["k22"]["open"]["count"] == {"suppressed": True, "fewer_than": 10}
    assert agg["data_quality"]["counter"] == 1 and agg["data_quality"]["closed_before_opened"] == 1
    assert agg["calendar"]["provisional"] is True and agg["calendar"]["version"].startswith("2025:")
    assert agg["k21"]["mandatory_vs_discretionary"]["other"]["escalated"] == 12
    assert agg["k22"]["by_role_label"]["DET compliance"]["active_working_days"] == 2.0
    assert "Al Noor" not in str(agg) and CO_ALNOOR not in str(agg)
    empty = compute_aggregates(db, period_from=date(2024, 1, 1), period_to=date(2024, 1, 31), now=datetime(2026, 6, 24))
    assert empty["empty"] is True and empty["k21"]["by_module"]["tax"]["note"] == "not_applicable" and empty["k22"]["headline"]["no_data"] is True


def test_suppression_below_n_is_complementary(db):
    _seed_metrics(db, 9, extras=False)  # a module with 9 escalated cases at N=10
    agg = compute_aggregates(db, period_from=date(2026, 6, 1), period_to=date(2026, 6, 30), now=datetime(2026, 6, 24, 8, 0))
    bm = agg["k21"]["by_module"]
    assert bm["compliance"] == {"suppressed": True, "fewer_than": 10} and bm["tax"]["total"] == 0 and bm["tax"]["note"] == "not_applicable"
    assert bm["total"] == {"suppressed": True, "fewer_than": 10} and agg["k21"]["headline"]["suppressed"] is True  # complementary
    k22 = agg["k22"]["by_module"]
    assert k22["compliance"] == {"suppressed": True, "fewer_than": 10} and k22["total"] == {"suppressed": True, "fewer_than": 10} and agg["k22"]["headline"]["suppressed"] is True
    _seed_metrics(db, 1)  # one more escalation and the extras push the module over N
    agg = compute_aggregates(db, period_from=date(2026, 6, 1), period_to=date(2026, 6, 30), now=datetime(2026, 6, 24, 8, 0))
    assert agg["k21"]["by_module"]["compliance"]["suppressed"] is False and agg["k21"]["headline"]["suppressed"] is False
    # exactly one visible breakdown cell with a visible total would allow subtraction → total hidden
    cells = {"a": {"escalated": 3}, "b": {"escalated": 30}, "total": {"escalated": 33}}
    from app.modules.escalation.metrics import _suppress_cells

    out = _suppress_cells(cells, 10)
    assert out["a"]["suppressed"] is True and out["total"]["suppressed"] is True and out["b"]["suppressed"] is False


def test_dashboard_access_matrix_and_logging(client, db):
    sign_in(client, "sara")
    r = client.get("/api/det/escalations")
    assert r.status_code == 200, r.text
    b = r.json()
    assert b["titles"]["k21"] == STRINGS["k21.title"] and b["suppression"]["min_group_size"] == 10 and b["calendar"]["version"]
    assert "case_id" not in str(b["k21"]) and "trade_name" not in str(b)
    assert _events(db, "DASHBOARD_VIEW")
    sign_in(client, "noura")
    assert client.get("/api/det/escalations", params={"module": "tax"}).status_code == 200
    for persona in ("hassan", "khalid", "faisal", "yusuf"):
        sign_in(client, persona)
        r = client.get("/api/det/escalations")
        assert r.status_code == 403 and "DET administrators" in r.json()["message"]
    assert len(_events(db, "DASHBOARD_NOACCESS_ATTEMPT")) == 4
    sign_in(client, "sara")
    cal = client.get("/api/admin/calendar", params={"year": 2026}).json()
    assert any(h["status"] == "provisional" for h in cal["holidays"]) and cal["weekend"] == ["saturday", "sunday"]
    assert client.get("/api/admin/calendar/working-days", params={"start": "2026-06-11", "end": "2026-06-17"}).json()["working_days"] == 3.0
    sign_in(client, "khalid")
    assert client.get("/api/admin/calendar").status_code == 403


def test_bilingual_strings_present_and_banned_terms_absent():
    for key, item in STRINGS.items():
        assert item["en"].strip() and item["ar"].strip(), key
        for lang in ("en", "ar"):
            assert not any(b.lower() in item[lang].lower() for b in ("audit certificate", "sent to a lawyer", "you owe", "you qualify", "you are exempt")), key
    assert STRINGS["status.rejected"]["ar"] == "مرفوضة من قِبلك" and STRINGS["qa.refusal_line"]["ar"].startswith("مصادرنا لا تدعم")
