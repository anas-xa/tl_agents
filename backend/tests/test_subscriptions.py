"""E2-S2/S3/S4 subscription creation, fee schedule, billing hook, opt-out, complaints and welcome."""

from __future__ import annotations

import ast
import pathlib
from datetime import date, datetime, timedelta

import pytest
from sqlalchemy import select

from app.core.errors import Conflict
from app.modules.audit.models import AuditEvent
from app.modules.config.service import get_config, get_config_entry, set_config
from app.modules.subscriptions import service
from app.modules.subscriptions.models import BillingRequest, Case, ReconciliationItem, Subscription
from app.modules.subscriptions.strings import STRINGS, TERMS_SECTIONS
from tests.conftest import sign_in
from tests.test_licences import TODAY, _ev, _post

BANNED = ("Included with your licence", "audit certificate", "Tax Agent", "PDPL-compliant", "hosted in the UAE", "your data is deleted", "penalty applies")


def _audit(db, event_type, reason=None):
    stmt = select(AuditEvent).where(AuditEvent.event_type == event_type)
    if reason:
        stmt = stmt.where(AuditEvent.reason_code == reason)
    return list(db.scalars(stmt))


def _confirm_schedule_and_go_live(db):
    sched = get_config(db, "fee_schedule.schedules")
    sched[0]["status"] = "confirmed"
    set_config(db, "fee_schedule.schedules", sched, changed_by="test", status="confirmed")
    set_config(db, "subscription.billing_live.enabled", True, changed_by="test", approved_by="second", status="confirmed")
    db.commit()


# --- fee arithmetic (spec test table) --------------------------------------------------------------------


@pytest.mark.parametrize(
    "start,end,net,vat,gross",
    [
        (date(2027, 1, 1), date(2027, 12, 31), 60000, 3000, 63000),  # 12 months
        (date(2027, 1, 1), date(2027, 6, 30), 30000, 1500, 31500),  # 6 months
        (date(2027, 3, 1), date(2027, 3, 31), 5000, 250, 5250),  # 1 month
        (date(2027, 1, 1), date(2027, 4, 10), 16438, 822, 17260),  # 100 days
        (date(2027, 1, 1), date(2027, 2, 14), 7397, 370, 7767),  # 45 days
        (date(2027, 1, 1), date(2027, 1, 1), 164, 8, 172),  # 1 day
        (date(2027, 1, 1), date(2028, 12, 31), 120000, 6000, 126000),  # 24 months
        (date(2027, 1, 1), date(2029, 12, 31), 180000, 9000, 189000),  # 36 months
        (date(2026, 1, 15), date(2027, 1, 15), 60164, 3008, 63172),  # 366 days, part term: days/365, no leap special case
    ],
)
def test_fee_table(start, end, net, vat, gross):
    f = service.compute_fee(60000, start, end, vat_rate_bp=500, proration="days")
    assert (f["net_fils"], f["vat_fils"], f["gross_fils"]) == (net, vat, gross)
    assert all(isinstance(f[k], int) for k in ("net_fils", "vat_fils", "gross_fils"))


def test_recognition_remainder_cohort_month_and_allocation_rule():
    assert service.distribute(100, 3) == [33, 33, 34]
    assert service.distribute(10001, 12) == [833] * 11 + [838]
    assert service.distribute(120000, 24) == [5000] * 24
    assert service.cohort_month(datetime(2027, 3, 31, 19, 59)) == "2027-03"  # 23:59 GST
    assert service.cohort_month(datetime(2027, 3, 31, 20, 0)) == "2027-04"  # 00:00 GST next day
    lines = [{"line_id": "L1", "line_type": "licence_fee", "gross_fils": 1050000}, {"line_id": "L2", "line_type": "smart_services_subscription", "gross_fils": 63000}]
    full = service.allocate_platform_derived(1113000, lines)
    assert [a["amount_fils"] for a in full] == [1050000, 63000]
    half = service.allocate_platform_derived(556500, lines)
    assert half[1]["amount_fils"] == 31500 and sum(a["amount_fils"] for a in half) == 556500
    # equal lines: each rounds half-up to 50001; the -1 residual goes to the licence line, never the subscription line
    for order in (["L1", "L2"], ["L2", "L1"]):
        lines2 = {"L1": {"line_id": "L1", "line_type": "licence_fee", "gross_fils": 1000}, "L2": {"line_id": "L2", "line_type": "smart_services_subscription", "gross_fils": 1000}}
        odd = {a["line_id"]: a["amount_fils"] for a in service.allocate_platform_derived(100001, [lines2[k] for k in order])}
        assert odd == {"L1": 50000, "L2": 50001}
    assert service.compute_fee(60000, date(2027, 1, 1), date(2027, 4, 10), proration="none")["net_fils"] == 60000  # PM pilot alternative


def _imports(path: pathlib.Path) -> set[str]:
    tree = ast.parse(path.read_text())
    out: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            out.add(node.module)
            out.update(f"{node.module}.{a.name}" for a in node.names)
        elif isinstance(node, ast.Import):
            out.update(a.name for a in node.names)
    return out


def test_contract_no_code_path_between_handler_and_subscriptions():
    """Contract test (spec E2-S2): the licence-event handler never imports subscription or billing code, and
    subscription code never imports or calls the licence-event handler. Comments may mention the word."""
    root = pathlib.Path(__file__).resolve().parents[1] / "app" / "modules"
    handler_imports = _imports(root / "licences" / "service.py")
    assert not any(m.startswith(("app.modules.subscriptions", "app.modules.cohorts")) for m in handler_imports), handler_imports
    for f in (root / "subscriptions").glob("*.py"):
        imports = _imports(f)
        assert not any(m.startswith("app.modules.licences.service") for m in imports), (f, imports)
        assert "intake_event" not in {m.rsplit(".", 1)[-1] for m in imports}, f
    # the handler only writes an outbox row; downstream consumers are registered on the outbox module
    from app.modules.licences.outbox import OUTBOX_CONSUMERS
    from app.modules.subscriptions.service import consume_outbox

    assert consume_outbox in OUTBOX_CONSUMERS


# --- creation from licence events --------------------------------------------------------------------------


def test_renewal_creates_one_subscription_and_replay_creates_no_duplicate(client, db):
    start = TODAY + timedelta(days=46)
    ev = _ev("EV-S-1", "DET-1023456", "RENEWED", ref="R-S1", effective=start, new_expiry=start + timedelta(days=364))
    assert _post(client, [ev]).status_code == 200
    subs = list(db.scalars(select(Subscription).where(Subscription.licence_number == "DET-1023456")))
    assert len(subs) == 2
    new = next(s for s in subs if s.start_date == start)
    assert new.status == "pending_billing" and new.pending_billing_reason == "fee_schedule_not_confirmed"
    assert new.enrolment_basis == "opted_in" and new.cohort_id.startswith("PILOT1-") and new.term_days == 365
    assert (new.net_amount_fils, new.vat_fils, new.gross_fils) == (60000, 3000, 63000) and new.fee_schedule_version == "fee-v1"
    assert new.det_event_reference == "R-S1" and new.opt_out_refund_config_version == "optout-v1"
    assert db.get(Subscription, "sub_alnoor").renewed_subscription_id == new.id
    _post(client, [ev])
    assert len(list(db.scalars(select(Subscription).where(Subscription.licence_number == "DET-1023456")))) == 2
    assert _audit(db, "INTAKE_EVENT_DUPLICATE_IGNORED")
    hist = [h["to"] for h in service.subscription_dict(db, new)["history"]]
    assert hist == ["created", "pending_billing"]


def test_no_subscription_without_cohort_membership_at_effective_date(client, db):
    start = TODAY + timedelta(days=121)
    _post(client, [_ev("EV-S-2", "DET-4089012", "RENEWED", ref="R-S2", effective=start, new_expiry=start + timedelta(days=364))])
    assert db.scalar(select(Subscription).where(Subscription.licence_number == "DET-4089012")) is None
    assert _audit(db, "SUBSCRIPTION_NOT_CREATED", "NOT_IN_COHORT_AT_EFFECTIVE_DATE")
    # the licence event itself was processed and acknowledged regardless
    from app.modules.licences.models import LicenceEvent

    assert db.scalar(select(LicenceEvent).where(LicenceEvent.event_id == "EV-S-2")).status == "processed"


def test_default_on_company_never_gets_a_second_default_on_subscription(client, db):
    start = TODAY + timedelta(days=201)
    _post(client, [_ev("EV-S-3", "DET-2045678", "RENEWED", ref="R-S3", effective=start, new_expiry=start + timedelta(days=364))])
    assert len(list(db.scalars(select(Subscription).where(Subscription.licence_number == "DET-2045678")))) == 1
    assert _audit(db, "SUBSCRIPTION_NOT_CREATED", "DEFAULT_ON_ALREADY_HELD")


def test_default_on_billing_switch_off_holds_billing(client, db):
    bd = db.get(Subscription, "sub_bluedune")
    bd.status = "ended"
    db.commit()
    _confirm_schedule_and_go_live(db)
    start = TODAY + timedelta(days=201)
    _post(client, [_ev("EV-S-4", "DET-2045678", "RENEWED", ref="R-S4", effective=start, new_expiry=start + timedelta(days=364))])
    new = db.scalar(select(Subscription).where(Subscription.licence_number == "DET-2045678", Subscription.start_date == start))
    assert new.enrolment_basis == "default_on" and new.pending_billing_reason == "default_on_hold"
    sign_in(client, "lina")
    r = client.post(f"/api/subscriptions/{new.id}/billing/request")
    assert r.status_code == 403 and r.json()["error"] == "DEFAULT_ON_HOLD"
    assert get_config(db, "subscription.default_on_billing.enabled") is False
    assert get_config(db, "subscription.consent_required_before_billing.enabled") is True


def test_state_machine_rejects_other_transitions(db):
    sub = db.get(Subscription, "sub_alnoor")
    with pytest.raises(Conflict):
        service.transition(db, sub, "pending_billing", actor_key=None, reason_code="x")
    assert sub.status == "active" and _audit(db, "SUBSCRIPTION_TRANSITION_REJECTED")


# --- billing hook ------------------------------------------------------------------------------------------


def _pending_sub(client, db):
    start = TODAY + timedelta(days=46)
    _post(client, [_ev("EV-B-1", "DET-1023456", "RENEWED", ref="R-B1", effective=start, new_expiry=start + timedelta(days=364))])
    return db.scalar(select(Subscription).where(Subscription.licence_number == "DET-1023456", Subscription.start_date == start))


def test_no_billing_request_while_billing_live_off_or_schedule_unconfirmed(client, db):
    sub = _pending_sub(client, db)
    sign_in(client, "lina")
    r = client.post(f"/api/subscriptions/{sub.id}/billing/request")
    assert r.status_code == 403 and r.json()["error"] == "FEATURE_SWITCHED_OFF"
    set_config(db, "subscription.billing_live.enabled", True, changed_by="test", approved_by="second")
    db.commit()
    r = client.post(f"/api/subscriptions/{sub.id}/billing/request")
    assert r.status_code == 403 and r.json()["error"] == "FEE_SCHEDULE_NOT_CONFIRMED"
    assert db.scalar(select(BillingRequest).where(BillingRequest.subscription_id == sub.id)) is None


def test_billing_request_readback_payment_cycle(client, db):
    sub = _pending_sub(client, db)
    _confirm_schedule_and_go_live(db)
    sign_in(client, "lina")
    r = client.post(f"/api/subscriptions/{sub.id}/billing/request")
    assert r.status_code == 200, r.text
    req = r.json()
    assert req["status"] == "requested" and req["separate_line"] is True and req["net_fils"] == 60000 and req["vat_fils"] == 3000
    assert client.post(f"/api/subscriptions/{sub.id}/billing/request").status_code == 409  # already billing_requested
    db.expire_all()
    assert db.get(Subscription, sub.id).status == "billing_requested"
    key = db.get(BillingRequest, req["id"]).idempotency_key
    assert key == f"DET-1023456+{sub.id}+{sub.start_date.isoformat()}|{sub.end_date.isoformat()}"
    # empty read-back = pending confirmation, never failed, never billed
    r = client.post(f"/api/subscriptions/billing/{req['id']}/read-back", json={"det_record": None})
    assert r.json()["status"] == "pending_confirmation"
    # off by one fils -> mismatch + reconciliation item, no tolerance
    bad = {"invoice_id": "INV-1", "invoice_date": "2027-03-31", "lines": [{"reference": key, "licence_number": "DET-1023456", "period": f"{sub.start_date}|{sub.end_date}", "net_fils": 60001, "billing_line_id": "BL-1"}]}
    r = client.post(f"/api/subscriptions/billing/{req['id']}/read-back", json={"det_record": bad})
    assert r.json()["status"] == "mismatch"
    assert db.scalar(select(ReconciliationItem).where(ReconciliationItem.type == "mismatch")) is not None
    good = {"invoice_id": "INV-1", "invoice_date": "2027-03-31", "lines": [{"reference": key, "licence_number": "DET-1023456", "period": f"{sub.start_date}|{sub.end_date}", "net_fils": 60000, "billing_line_id": "BL-1"}]}
    r = client.post(f"/api/subscriptions/billing/{req['id']}/read-back", json={"det_record": good})
    assert r.json()["status"] == "billed" and r.json()["invoice_date"] == "2027-03-31"
    db.expire_all()
    assert db.get(Subscription, sub.id).status == "billed"
    # partial payment: partly collected with outstanding; replayed callback adds nothing
    r = client.post("/api/subscriptions/billing/payments", json={"payment_transaction_id": "PTX-1", "amount_fils": 30000, "billing_line_id": "BL-1", "reference": "PAYREF-1"})
    assert r.json()["allocation_status"] == "allocated"
    client.post("/api/subscriptions/billing/payments", json={"payment_transaction_id": "PTX-1", "amount_fils": 30000, "billing_line_id": "BL-1"})
    db.expire_all()
    br = db.get(BillingRequest, req["id"])
    assert br.collection_status == "partially_collected" and br.collected_fils == 30000 and br.outstanding_fils == 33000 and br.receipt_reference == "PAYREF-1"
    assert _audit(db, "PAYMENT_DUPLICATE_IGNORED")
    r = client.post("/api/subscriptions/billing/payments", json={"payment_transaction_id": "PTX-2", "amount_fils": 33000, "billing_line_id": "BL-1"})
    db.expire_all()
    br = db.get(BillingRequest, req["id"])
    assert br.collection_status == "collected" and db.get(Subscription, sub.id).status == "active"
    # a payment tied only to an invoice with no line information stays received_unallocated
    r = client.post("/api/subscriptions/billing/payments", json={"payment_transaction_id": "PTX-3", "amount_fils": 5000, "invoice_id": "INV-OTHER"})
    assert r.json()["allocation_status"] == "received_unallocated"
    # platform-derived split on a multi-line invoice is provisional
    r = client.post("/api/subscriptions/billing/payments", json={"payment_transaction_id": "PTX-4", "amount_fils": 556500, "invoice_id": "INV-1", "invoice_lines": [{"line_id": "L-LIC", "line_type": "licence_fee", "gross_fils": 1050000}, {"line_id": "BL-1", "line_type": "smart_services_subscription", "gross_fils": 63000}]})
    assert r.json()["allocation_status"] == "allocated"
    assert _audit(db, "PAYMENT_ALLOCATED") and any(e.details.get("basis") == "platform-derived" and e.details.get("provisional") for e in _audit(db, "PAYMENT_ALLOCATED"))


def test_licence_issuance_never_blocked_by_billing_failure(client, db):
    """Billing hook unavailable (switch off, schedule unconfirmed): the licence event is still processed and
    the subscription stays pending; the licence record is unchanged by subscription state."""
    from app.modules.licences.models import Licence, LicenceEvent

    start = TODAY + timedelta(days=46)
    _post(client, [_ev("EV-L-1", "DET-1023456", "RENEWED", ref="R-L1", effective=start, new_expiry=start + timedelta(days=364))])
    ev = db.scalar(select(LicenceEvent).where(LicenceEvent.event_id == "EV-L-1"))
    assert ev.status == "processed" and ev.acknowledged_at is not None
    lic = db.get(Licence, "lic_alnoor")
    assert lic.expiry_date == start + timedelta(days=364) and lic.status == "active"
    sub = db.scalar(select(Subscription).where(Subscription.source_event_id == "EV-L-1"))
    assert sub.status == "pending_billing"


# --- owner views, opt-out, complaints, welcome -------------------------------------------------------------


def test_owner_subscription_screen_data(client, db):
    sign_in(client, "khalid")
    r = client.get("/api/companies/co_alnoor/subscription")
    assert r.status_code == 200
    body = r.json()
    assert body["can_change"] is True and body["proposed_wording"] is True
    sub = body["licences"][0]["subscription"]
    assert sub["badge"] == "active" and sub["enrolment_basis"] == "opted_in" and sub["example_mode"] is True
    assert sub["fee"]["label"] == "example" and sub["fee"]["net_fils"] == 60000 and sub["fee"]["vat_fils"] == 3000 and sub["fee"]["gross_fils"] == 63000
    assert sub["fee"]["vat_label"] == "VAT treatment to be confirmed" and sub["fee"]["monthly_display_only"] is True
    assert sub["billing"]["payment_reference"] == "DETPAY-AN-77812" and sub["billing"]["collection_status"] == "collected"
    assert body["parameters"]["opt_out_window_days"]["confirmed"] is False and body["parameters"]["refund_window_days"]["label"].startswith("to be confirmed")
    assert body["switches"]["billing_live"] is False and body["complaint_reply_period_working_days"] == 5
    assert body["complaints"][0]["reference"] == "DEMOC2X9"
    text = r.text
    assert not any(b in text for b in BANNED)
    # remote owner: same card, read-only
    sign_in(client, "priya")
    body = client.get("/api/companies/co_bluedune/subscription").json()
    assert body["can_change"] is False and body["read_only_note"] == "only_owner_can_change"
    sub = body["licences"][0]["subscription"]
    assert sub["enrolment_basis"] == "default_on" and sub["billing"]["collection_status"] == "received_unallocated"
    assert any(p.get("status") == "received_unallocated" for p in sub["payments"])
    # Safwa: licence expired, unpaid after the provisional 30-day grace -> read-only smart services
    sign_in(client, "khalid")
    body = client.get("/api/companies/co_safwa/subscription").json()
    sub = body["licences"][0]["subscription"]
    assert sub["service_mode"] == "read_only" and sub["billing"]["collection_status"] == "failed" and body["unpaid_grace_period_days"] == 30
    # Gulf Tech: not in the pilot, interest registered
    sign_in(client, "omar")
    body = client.get("/api/companies/co_gulftech/subscription").json()
    assert body["licences"][0]["empty_state"] == "not_in_pilot" and body["licences"][0]["pilot"]["interest_status"] == "candidate"
    assert body["can_change"] is False


def test_opt_out_request_is_neutral_idempotent_owner_only_and_never_disabled(client, db):
    sign_in(client, "omar")
    r = client.post("/api/companies/co_alnoor/subscription/sub_alnoor/opt-out", json={"request_id": "q1", "reason_code": "cost", "understood": True})
    assert r.status_code == 403
    sign_in(client, "priya")
    assert client.post("/api/companies/co_bluedune/subscription/sub_bluedune/opt-out", json={"request_id": "q1", "reason_code": "cost", "understood": True}).status_code == 403
    sign_in(client, "khalid")
    r = client.post("/api/companies/co_alnoor/subscription/sub_alnoor/opt-out", json={"request_id": "q1", "reason_code": "cost", "understood": True})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["already_requested"] is False and body["case"]["state"] == "pending_DET" and body["case"]["status_text"] == "request received, DET decides"
    assert body["case"]["chip"] == "pending" and body["case"]["effective_at"] is None
    db.expire_all()
    assert db.get(Subscription, "sub_alnoor").status == "active"  # stays active and billed until DET confirms
    r2 = client.post("/api/companies/co_alnoor/subscription/sub_alnoor/opt-out", json={"request_id": "q2", "reason_code": "cost", "understood": True})
    assert r2.status_code == 200 and r2.json()["already_requested"] is True and r2.json()["case"]["id"] == body["case"]["id"]
    assert len(list(db.scalars(select(Case).where(Case.subscription_id == "sub_alnoor", Case.action == "opt_out")))) == 1
    assert service.get_opt_out_state(db, "sub_alnoor") == "window_open"
    # DET confirms (late, after needs_DET_action): applied, alert closed, audit late_confirmed
    sign_in(client, "lina")
    client.post(f"/api/det/cases/{body['case']['id']}/needs-det-action")
    sign_in(client, "sara")
    r = client.post(f"/api/det/cases/{body['case']['id']}/decision", json={"decision": "confirm"})
    assert r.status_code == 200 and r.json()["state"] == "applied"
    db.expire_all()
    assert db.get(Subscription, "sub_alnoor").status == "opted_out" and service.get_opt_out_state(db, "sub_alnoor") == "opted_out"
    assert _audit(db, "CASE_LATE_CONFIRMED") and _audit(db, "CASE_ALERT_CLOSED")
    # a later decision on a closed case is ignored and logged duplicate_ignored
    client.post(f"/api/det/cases/{body['case']['id']}/decision", json={"decision": "reject"})
    assert _audit(db, "CASE_DUPLICATE_IGNORED")
    # opt-out can never be switched off
    cfg = get_config(db, "opt_out.config")
    cfg["opt_out_allowed"]["value"] = False
    set_config(db, "opt_out.config", cfg, changed_by="test")
    db.commit()
    sign_in(client, "khalid")
    r = client.post("/api/companies/co_safwa/subscription/sub_safwa/opt-out", json={"request_id": "q3", "reason_code": "cost", "understood": True})
    assert r.status_code == 403 and r.json()["error"] == "OPT_OUT_ALWAYS_ALLOWED"


def test_refund_request_neutral_and_opt_out_before_billing_cancels(client, db):
    sign_in(client, "khalid")
    r = client.post("/api/companies/co_safwa/subscription/sub_safwa/refund-request", json={"request_id": "r1", "reason_code": "charged_in_error"})
    assert r.status_code == 200 and r.json()["already_requested"] is True  # demo refund case already pending with DET
    assert r.json()["message"] == "Request received. DET decides." and "amount" not in r.json()["case"]
    sub = _pending_sub(client, db)
    r = client.post(f"/api/companies/co_alnoor/subscription/{sub.id}/opt-out", json={"request_id": "o1", "reason_code": "not_needed", "understood": True})
    case_id = r.json()["case"]["id"]
    sign_in(client, "sara")
    client.post(f"/api/det/cases/{case_id}/decision", json={"decision": "confirm"})
    db.expire_all()
    assert db.get(Subscription, sub.id).status == "cancelled_by_opt_out"


def test_complaint_sla_and_handler_queue(client, db):
    sign_in(client, "khalid")
    r = client.post("/api/companies/co_alnoor/complaints", json={"licence_number": "DET-1023456", "category": "charge", "description": "The line appeared twice.", "preferred_language": "en"})
    assert r.status_code == 200, r.text
    c = r.json()["complaint"]
    assert c["status"] == "received" and c["sla_working_days"] == 5
    assert date.fromisoformat(c["reply_by"]) == service.add_working_days(date.today(), 5)
    assert date.fromisoformat(c["reply_by"]).weekday() < 5
    assert client.post("/api/companies/co_alnoor/complaints", json={"category": "bogus", "description": "x"}).status_code == 422
    assert client.get("/api/det/complaints").status_code == 403
    sign_in(client, "ahmed")
    q = client.get("/api/det/complaints").json()
    assert q["sla_working_days"] == 5 and any(x["reference"] == c["reference"] for x in q["complaints"])
    assert "net_fils" not in str(q)
    r = client.post(f"/api/det/complaints/{c['id']}/status", json={"status": "in_review", "reason_code": "triaged"})
    assert r.json()["status"] == "in_review"
    assert client.post(f"/api/det/complaints/{c['id']}/status", json={"status": "replied", "reason_code": ""}).status_code == 422
    assert _audit(db, "COMPLAINT_RECEIVED") and _audit(db, "COMPLAINT_STATUS_CHANGED")
    assert get_config_entry(db, "complaint.reply_period_working_days").value == 5


def test_welcome_first_run_records_versions_and_choices(client, db):
    sign_in(client, "khalid")
    r = client.get("/api/companies/co_alnoor/welcome")
    assert r.status_code == 200
    w = r.json()["welcome"]
    assert w["status"] == "pending" and w["terms_version_shown"] == "terms-v1" and w["notice_version_shown"] == "notice-v1"
    assert r.json()["subscription"]["included"] and r.json()["subscription"]["not_included"]
    assert client.post("/api/companies/co_alnoor/welcome", json={"action": "later"}).json()["status"] == "later"
    r = client.post("/api/companies/co_alnoor/welcome", json={"action": "done", "language_choice": "ar", "reminder_channel": "portal"})
    assert r.json() == {"status": "done", "language_choice": "ar", "reminder_channel": "portal"}
    assert _audit(db, "WELCOME_SHOWN") and _audit(db, "WELCOME_COMPLETED")
    terms = client.get("/api/companies/co_alnoor/subscription/terms").json()
    assert terms["version"] == "terms-v1" and terms["label"] == "Proposed wording - pending confirmation"
    assert {s["key"] for s in terms["sections"]} == set(TERMS_SECTIONS)


def test_det_aggregates_suppressed_and_without_company_data(client, db):
    sign_in(client, "sara")
    r = client.get("/api/det/subscriptions/aggregates")
    assert r.status_code == 200
    body = r.json()
    assert body["suppression_n"] == 10 and body["total_subscriptions"]["suppressed"] is True
    assert body["money_confirmed_fils"]["billed_net"] == 180000 and body["provisional_fils"]["platform_derived_collected"] == 0
    assert body["counts"]["received_unallocated"] == 1 and body["counts"]["failed"] == 1
    assert body["k4"]["rule_version"] == "k4-v1" and body["k4"]["observation_window_days"] == 90
    assert "co_alnoor" not in r.text and "sub_alnoor" not in r.text
    assert _audit(db, "DET_AGGREGATE_QUERIED")
    status = service.det_status_for_licence(db, "DET-1023456")
    assert status["subscription_status"] == "active" and not any(k.endswith("_fils") for k in status)
    sign_in(client, "khalid")
    assert client.get("/api/det/subscriptions/aggregates").status_code == 403


def test_bilingual_strings_present_and_free_of_banned_terms():
    for key, texts in {**STRINGS, **TERMS_SECTIONS}.items():
        assert texts["en"].strip() and texts["ar"].strip(), key
        for b in BANNED:
            assert b not in texts["en"], (key, b)
    assert STRINGS["badge_held_for_review"]["ar"] == "قيد المراجعة" and STRINGS["badge_ended"]["ar"] == "منتهٍ"
    assert STRINGS["proposed_wording"]["ar"] == "صياغة مقترحة - بانتظار الاعتماد"


def test_switch_defaults_and_fee_config(db):
    assert get_config(db, "subscription.billing_live.enabled") is False
    assert get_config(db, "subscription.default_on_billing.enabled") is False
    assert get_config(db, "subscription.consent_required_before_billing.enabled") is True
    assert get_config(db, "enrolment.default_on") == "opt_in"
    sched = get_config(db, "fee_schedule.schedules")[0]
    assert sched["base_annual_fils"] == 60000 and sched["status"] == "example" and sched["vat_rate_bp"] == 500
    assert get_config_entry(db, "fee_schedule.monthly_display_fils").label.startswith("display only")
    assert get_config(db, "refund.window_days") == 14 and get_config(db, "unpaid.grace_period_days") == 30
    assert get_config_entry(db, "billing.vat_split_switch").label.startswith("VAT treatment to be confirmed")
    assert get_config_entry(db, "unpaid.grace_period_days").owner == "DET pilot manager"
