"""E2-S1 licence and renewal event intake."""

from __future__ import annotations

from datetime import date, datetime, timedelta

from sqlalchemy import select

from app.modules.audit.models import AuditEvent
from app.modules.config.service import get_config_entry, get_rule, set_config
from app.modules.licences.models import Licence, LicenceEvent, LicenceEventOutbox, LicenceHistory
from tests.conftest import sign_in

SECRET = {"X-DET-Intake-Secret": "det-intake-dev-secret"}
TODAY = date.today()


def _ev(event_id: str, licence: str, raw_type: str = "RENEWED", *, ref: str | None = None, effective: date | None = None, new_expiry: date | None = None, completed: datetime | None = None, status: str = "ISSUED", authority: str = "DET", ltype: str = "mainland", term_start: date | None = None, **extra) -> dict:
    effective = effective or TODAY
    p = {
        "event_id": event_id,
        "licence_number": licence,
        "event_type": raw_type,
        "det_reference": ref,
        "effective_date": effective.isoformat(),
        "new_expiry_date": (new_expiry or effective + timedelta(days=364)).isoformat(),
        "new_term_start_date": (term_start or effective).isoformat(),
        "renewal_completed_at": (completed or datetime.combine(effective, datetime.min.time())).isoformat() + "Z",
        "licence": {"issuing_authority": authority, "licence_type": ltype, "trade_name_en": "Test Co", "trade_name_ar": "شركة اختبار", "legal_form": "LLC", "category": "Commercial", "activities": ["General trading"], "status": status},
    }
    p.update(extra)
    return p


def _post(client, events, headers=SECRET):
    return client.post("/api/det/intake/events", json={"events": events}, headers=headers)


def _audit(db, event_type, reason=None):
    stmt = select(AuditEvent).where(AuditEvent.event_type == event_type)
    if reason:
        stmt = stmt.where(AuditEvent.reason_code == reason)
    return list(db.scalars(stmt))


def test_intake_creates_licence_and_event_and_owner_sees_them(client, db):
    r = _post(client, [_ev("EV-NEW-1", "DET-9000001", "ISSUED", ref="R-1", status="ISSUED")])
    assert r.status_code == 200, r.text
    assert r.json()["results"][0]["status"] == "processed"
    lic = db.scalar(select(Licence).where(Licence.licence_number == "DET-9000001"))
    assert lic.scope == "in_scope" and lic.status == "active" and lic.trade_name_ar == "شركة اختبار" and lic.company_id is None
    assert lic.expiry_date == TODAY + timedelta(days=364) and lic.term_start_date == TODAY
    assert _audit(db, "INTAKE_EVENT_RECEIVED") and _audit(db, "INTAKE_EVENT_PROCESSED")
    # Owner view of the demo licence with its intake events, freshness stamp and history.
    sign_in(client, "khalid")
    r = client.get("/api/companies/co_alnoor/licences")
    assert r.status_code == 200
    lic = r.json()["licences"][0]
    assert lic["licence_number"] == "DET-1023456" and lic["stale"] is False and lic["freshness_window_hours"] == 24
    assert lic["events"][0]["event_type"] == "renewed" and lic["events"][0]["k6_class"] == "on_time"
    assert any(h["field"] == "expiry_date" and h["source"] == "Read from DET" for h in lic["history"])


def test_duplicate_event_is_ignored_once(client, db):
    ev = _ev("EV-DUP-1", "DET-9000002", "ISSUED", ref="R-2")
    _post(client, [ev])
    _post(client, [ev])
    rows = list(db.scalars(select(LicenceEvent).where(LicenceEvent.licence_number == "DET-9000002")))
    assert len(rows) == 1
    assert _audit(db, "INTAKE_EVENT_DUPLICATE_IGNORED")
    assert len(list(db.scalars(select(LicenceEventOutbox).where(LicenceEventOutbox.licence_number == "DET-9000002")))) == 1


def test_free_zone_is_out_of_scope_with_reason_and_hidden(client, db):
    _post(client, [_ev("EV-FZ-2", "JAFZA-1", "ISSUED", ref="R-3", authority="JAFZA", ltype="free_zone")])
    lic = db.scalar(select(Licence).where(Licence.licence_number == "JAFZA-1"))
    assert lic.scope == "out_of_scope" and lic.out_of_scope_reason == "free_zone_authority:JAFZA"
    assert _audit(db, "INTAKE_LICENCE_OUT_OF_SCOPE")
    sign_in(client, "sara")
    status = client.get("/api/det/intake/status").json()
    assert status["out_of_scope_reasons"]["free_zone_authority"] >= 2 and "company" not in str(status)


def test_missing_authority_is_unclassified_and_never_billed(client, db):
    r = _post(client, [_ev("EV-UNC-1", "DET-9000003", "ISSUED", ref="R-4", authority="")])
    assert r.json()["results"][0]["held_reason"] == "unclassified_authority"
    lic = db.scalar(select(Licence).where(Licence.licence_number == "DET-9000003"))
    assert lic.scope == "unclassified_held_for_review" and lic.held_for_review
    assert db.scalar(select(LicenceEventOutbox).where(LicenceEventOutbox.licence_number == "DET-9000003")) is None  # no subscription work queued
    assert _audit(db, "INTAKE_EVENT_HELD_FOR_REVIEW", "unclassified_authority")


def test_unmapped_status_and_event_type_are_held(client, db):
    r = _post(client, [_ev("EV-UNM-1", "DET-9000004", "ISSUED", ref="R-5", status="PENDING_INSPECTION"), _ev("EV-UNM-2", "DET-9000005", "REVOKED_BY_COURT", ref="R-6")])
    out = r.json()["results"]
    assert out[0]["held_reason"] == "unmapped_status" and out[1]["held_reason"] == "unmapped_event_type"
    lic = db.scalar(select(Licence).where(Licence.licence_number == "DET-9000004"))
    assert lic.status == "unknown" and lic.raw_status == "PENDING_INSPECTION"
    entry = get_config_entry(db, "det_intake.status_mapping")
    assert "not the DET list" in entry.label and entry.status == "to_be_confirmed"


def test_quarantine_missing_reference_and_reference_conflict(client, db):
    no_ref = _ev("EV-Q-1", "DET-9000006", "ISSUED")
    no_ref["det_reference"], no_ref["new_term_start_date"] = None, None
    r = _post(client, [no_ref])
    assert r.json()["results"][0]["quarantine_reason"] == "missing_reference"
    first = _ev("EV-Q-2", "DET-9000007", "ISSUED", ref="R-7")
    _post(client, [first])
    same_ref_other_content = _ev("EV-Q-3", "DET-9000007", "ISSUED", ref="R-7", new_expiry=TODAY + timedelta(days=100))
    r = _post(client, [same_ref_other_content])
    assert r.json()["results"][0]["quarantine_reason"] == "reference_conflict"
    identical_other_id = dict(first, event_id="EV-Q-4")
    r = _post(client, [identical_other_id])
    assert r.json()["results"][0]["status"] == "processed" and r.json()["results"][0]["event_id"] == "EV-Q-2"  # duplicate ignored
    assert _audit(db, "INTAKE_EVENT_QUARANTINED", "missing_reference") and _audit(db, "INTAKE_EVENT_QUARANTINED", "reference_conflict")


def test_out_of_order_renewal_is_replayed_and_conflict_held(client, db):
    _post(client, [_ev("EV-O-1", "DET-9000008", "ISSUED", ref="R-8", effective=TODAY - timedelta(days=400))])
    _post(client, [_ev("EV-O-2", "DET-9000008", "RENEWED", ref="R-9", effective=TODAY - timedelta(days=30), new_expiry=TODAY + timedelta(days=335))])
    # a late renewal with an earlier effective date than the processed one: replayed, conflict held, nothing reversed
    r = _post(client, [_ev("EV-O-3", "DET-9000008", "RENEWED", ref="R-10", effective=TODAY - timedelta(days=200), new_expiry=TODAY + timedelta(days=100))])
    assert r.json()["results"][0]["held_reason"] == "out_of_order_replay"
    assert _audit(db, "INTAKE_EVENT_OUT_OF_ORDER_REPLAYED") and _audit(db, "INTAKE_REPLAY_CONFLICT_RAISED")
    lic = db.scalar(select(Licence).where(Licence.licence_number == "DET-9000008"))
    assert lic.expiry_date == TODAY + timedelta(days=335)


def test_correction_and_incomplete_renewal_are_held_and_payment_is_never_the_signal(client, db):
    _post(client, [_ev("EV-C-1", "DET-9000009", "ISSUED", ref="R-11", effective=TODAY - timedelta(days=10))])
    r = _post(client, [_ev("EV-C-2", "DET-9000009", "RENEWED", ref="R-12", effective=TODAY, new_expiry=TODAY + timedelta(days=30))])
    assert r.json()["results"][0]["held_reason"] == "correction_expiry_earlier"
    r = _post(client, [_ev("EV-C-3", "DET-9000009", "RENEWED", ref="R-13", effective=TODAY + timedelta(days=1), status="UNDER_RENEWAL", payment_received_at=datetime.utcnow().isoformat() + "Z")])
    assert r.json()["results"][0]["held_reason"] == "renewal_not_completed"


def test_k6_classification_fixtures(client, db):
    old_expiry = TODAY - timedelta(days=5)
    _post(client, [_ev("EV-K-1", "DET-9000010", "ISSUED", ref="R-14", effective=old_expiry - timedelta(days=364), new_expiry=old_expiry)])
    r = _post(client, [_ev("EV-K-2", "DET-9000010", "RENEWED", ref="R-15", effective=old_expiry + timedelta(days=1), new_expiry=old_expiry + timedelta(days=365), completed=datetime.combine(old_expiry + timedelta(days=3), datetime.min.time()))])
    ev = db.scalar(select(LicenceEvent).where(LicenceEvent.event_id == "EV-K-2"))
    assert ev.k6_class == "late" and ev.k6_rule_version == "k6-v1" and ev.previous_expiry_date == old_expiry
    # grace period configured -> late within grace; cancelled status -> excluded from the denominator
    set_config(db, "det.grace_period_days", 30, changed_by="test")
    db.commit()
    _post(client, [_ev("EV-K-3", "DET-9000011", "ISSUED", ref="R-16", effective=old_expiry - timedelta(days=364), new_expiry=old_expiry)])
    _post(client, [_ev("EV-K-4", "DET-9000011", "RENEWED", ref="R-17", effective=old_expiry + timedelta(days=1), new_expiry=old_expiry + timedelta(days=365), completed=datetime.combine(old_expiry + timedelta(days=3), datetime.min.time()))])
    assert db.scalar(select(LicenceEvent).where(LicenceEvent.event_id == "EV-K-4")).k6_class == "late_within_grace"
    assert get_rule(db, "k6-v1").status == "provisional"
    # Dubai calendar day: completion at 21:00 UTC on expiry day is the next day in Asia/Dubai -> late
    _post(client, [_ev("EV-K-5", "DET-9000012", "ISSUED", ref="R-18", effective=old_expiry - timedelta(days=364), new_expiry=old_expiry)])
    _post(client, [_ev("EV-K-6", "DET-9000012", "RENEWED", ref="R-19", effective=old_expiry + timedelta(days=1), new_expiry=old_expiry + timedelta(days=365), completed=datetime.combine(old_expiry, datetime.min.time()).replace(hour=21))])
    assert db.scalar(select(LicenceEvent).where(LicenceEvent.event_id == "EV-K-6")).k6_class != "on_time"  # grace still set: late within grace


def test_stale_flag_after_freshness_window(client, db):
    lic = db.get(Licence, "lic_safwa")
    lic.last_det_refresh_at = datetime.utcnow() - timedelta(hours=30)
    db.commit()
    sign_in(client, "khalid")
    rows = client.get("/api/companies/co_safwa/licences").json()["licences"]
    assert rows[0]["stale"] is True and rows[0]["status"] == "expired" and rows[0]["renewal_state"] == "expired_in_grace"


def test_history_kept_when_record_changes(client, db):
    _post(client, [_ev("EV-H-1", "DET-9000013", "ISSUED", ref="R-20", effective=TODAY - timedelta(days=5))])
    _post(client, [_ev("EV-H-2", "DET-9000013", "AMENDED", ref="R-21", effective=TODAY, licence={"issuing_authority": "DET", "licence_type": "mainland", "legal_form": "Sole establishment", "status": "ACTIVE"})])
    lic = db.scalar(select(Licence).where(Licence.licence_number == "DET-9000013"))
    hist = list(db.scalars(select(LicenceHistory).where(LicenceHistory.licence_id == lic.id, LicenceHistory.field == "legal_form")))
    assert hist and hist[-1].previous_value == "LLC" and hist[-1].current_value == "Sole establishment"


def test_intake_auth_and_company_isolation(client):
    assert _post(client, [_ev("EV-A-1", "DET-9000014", "ISSUED", ref="R-22")], headers={}).status_code == 401
    assert _post(client, [_ev("EV-A-1", "DET-9000014", "ISSUED", ref="R-22")], headers={"X-DET-Intake-Secret": "wrong"}).status_code == 401
    sign_in(client, "lina")  # integrations.manage: manual adapter
    assert _post(client, [_ev("EV-A-2", "DET-9000015", "ISSUED", ref="R-23")], headers={}).status_code == 200
    sign_in(client, "omar")
    assert client.get("/api/companies/co_alnoor/licences").status_code == 200
    assert client.get("/api/companies/co_safwa/licences").status_code == 403
    sign_in(client, "sara")
    assert client.get("/api/companies/co_alnoor/licences").status_code == 403
    held = client.get("/api/det/intake/held").json()["events"]
    assert any(e["held_reason"] == "unclassified_authority" for e in held)


def test_demo_fixtures_and_config_keys(db):
    for key in ("intake.freshness_window_hours", "intake.retry_schedule_minutes", "intake.alert_after_failed_cycles", "det.interface_type", "det.grace_period_days", "det_intake.event_type_mapping", "det_intake.k6_status_mapping", "sc3.check_again_cooldown_seconds"):
        get_config_entry(db, key)
    assert get_config_entry(db, "det.grace_period_days").value is None
    held = list(db.scalars(select(LicenceEvent).where(LicenceEvent.status == "held_for_review")))
    assert {e.held_reason for e in held} >= {"unclassified_authority", "unmapped_status"}
    assert db.get(Licence, "lic_alnoor").scope == "in_scope"
