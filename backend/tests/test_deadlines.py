"""E3-S2 deadline engine and SC4 Obligation contract."""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from conftest import sign_in

from app.core.time import dubai_today
from app.demo import CO_ALNOOR, CO_BLUEDUNE, CO_GULFTECH, CO_SAFWA, demo_ct_year, demo_vat_quarters
from app.modules.deadlines import service as dl
from app.modules.deadlines.models import CalendarEntry, CalendarVersion, Obligation, RecalcCheckpoint

# Demo periods (today-relative): Al Noor enters the open quarter in its tax profile; CT runs on the demo year.
QUARTERS, CT = demo_vat_quarters(), demo_ct_year()
OPEN, CURRENT = QUARTERS.open, QUARTERS.current

CONTRACT_FIELDS = {"obligation_id", "company_id", "licence_number", "obligation_type", "period_start", "period_end", "due_date", "due_date_source", "date_status", "is_stated", "rule_version", "calendar_version", "readiness", "missing_items", "updated_at"}


@pytest.mark.parametrize(
    ("period_end", "due"),
    [
        (date(2026, 12, 31), date(2027, 9, 30)),
        (date(2027, 6, 30), date(2028, 3, 31)),
        (date(2026, 5, 31), date(2027, 2, 28)),  # non-leap target
        (date(2027, 5, 31), date(2028, 2, 29)),  # leap target
        (date(2027, 2, 28), date(2027, 11, 30)),  # 28 Feb non-leap is a month end
        (date(2028, 2, 29), date(2028, 11, 30)),
        (date(2028, 2, 28), date(2028, 11, 28)),  # 28 Feb leap is not a month end
        (date(2027, 3, 15), date(2027, 12, 15)),
        (date(2027, 4, 30), date(2028, 1, 31)),
    ],
)
def test_ct_last_day_vectors(period_end, due):
    assert dl.ct_due_date(period_end) == due


def test_ct_same_day_reading_changes_only_the_rule_value():
    assert dl.ct_due_date(date(2027, 6, 30), month_end_rule="same-day") == date(2028, 3, 30)


@pytest.mark.parametrize(
    ("period_end", "due"),
    [(date(2027, 3, 31), date(2027, 4, 28)), (date(2027, 1, 31), date(2027, 2, 28)), (date(2027, 2, 28), date(2027, 3, 28)), (date(2028, 2, 1), date(2028, 2, 29))],
)
def test_vat_plus_28_days(period_end, due):
    assert dl.vat_due_date(period_end) == due


def test_rules_read_from_reference_not_code(db):
    assert dl.rule_value(db, "vat.deadline_offset_days", date(2026, 9, 30))[0] == 28
    assert dl.rule_value(db, "ct.deadline_offset_months", date(2026, 12, 31))[0] == 9
    assert dl.rule_value(db, "sbr.period_end_cutoff", date(2026, 12, 31))[0] == "2029-12-31"
    roll = dl.rule_row(db, "nonworking_day_treatment.FTA.vat_return")
    assert roll.value == "no_roll" and roll.confirmation_status == "unconfirmed, source: none"


def test_rule_row_missing_mandatory_field_rejected(db):
    from app.core.errors import ValidationFailed

    with pytest.raises(ValidationFailed) as e:
        dl.create_rule(db, {"key": "x.test", "value": 1, "legal_instrument": "test", "effective_from": "2027-01-01", "version": "t1", "entered_by": "a", "entered_date": "2026-10-01"})
    assert e.value.reason_code == "RULE_ROW_INCOMPLETE" and "applicability_basis" in e.value.details["missing"] and "effective_to" in e.value.details["missing"]
    row = dl.create_rule(db, {"key": "x.test", "value": 1, "legal_instrument": "test", "effective_from": "2027-01-01", "effective_to": "open", "version": "t1", "applicability_basis": "period_end_date", "entered_by": "a", "entered_date": "2026-10-01"})
    with pytest.raises(ValidationFailed):
        dl.activate_rule(db, row.id, approved_by="a")  # second person required
    dl.activate_rule(db, row.id, approved_by="b")
    from app.core.errors import Conflict

    with pytest.raises(Conflict):
        dl.amend_rule(db, row.id, applicability_basis="event_date")  # immutable after activation


def test_owner_sees_contract_rows_with_versions(client):
    sign_in(client, "khalid")
    r = client.get(f"/api/companies/{CO_ALNOOR}/obligations")
    assert r.status_code == 200, r.text
    body = r.json()
    assert r.headers.get("etag") and "max-age=60" in r.headers.get("cache-control", "")
    items = body["items"]
    assert items and all(CONTRACT_FIELDS <= set(i) for i in items)
    vat = next(i for i in items if i["obligation_type"] == "vat_return" and i["period_end"] == OPEN.end.isoformat())
    assert vat["due_date"] == OPEN.due.isoformat() and vat["due_date_source"] == "rule_derived" and vat["is_stated"] is False
    assert vat["rule_version"] == "2026.10" and vat["calendar_version"].startswith("UAE-FEDERAL")
    assert vat["readiness"] == "draft_ready" and vat["missing_items"] == []  # from the real draft pack, ready for owner review
    pack = client.get(f"/api/companies/{CO_ALNOOR}/drafts/{vat['draft_pack_id']}").json()
    assert pack["period_id"] == OPEN.period_id and pack["review_status"] == "under_review"
    assert vat["days_left"] == (OPEN.due - dubai_today()).days
    lic = next(i for i in items if i["obligation_type"] == "licence_renewal")
    assert lic["due_date_source"] == "det_record" and lic["is_stated"] and lic["days_left"] == 45
    ejari = next(i for i in items if i["obligation_type"] == "ejari_renewal")
    assert ejari["days_left"] == 30 and ejari["due_date_source"] == "ejari_record"
    # ETag: a second call with If-None-Match is a 304
    r2 = client.get(f"/api/companies/{CO_ALNOOR}/obligations", headers={"If-None-Match": r.headers["etag"]})
    assert r2.status_code == 304


def test_overdue_pinned_top_and_safwa_states(client):
    sign_in(client, "khalid")
    items = client.get(f"/api/companies/{CO_SAFWA}/obligations").json()["items"]
    assert items[0]["days_left"] < 0
    lic = next(i for i in items if i["obligation_type"] == "licence_renewal")
    assert lic["status_chip"] == "overdue" and lic["days_left"] == -10
    ct = next(i for i in items if i["obligation_type"] == "ct_return" and i["period_end"] == CT.end.isoformat())
    assert ct["filed_state"] == "owner_declared_unverified" and ct["done"] and ct["readiness"] != "receipt_recorded"


def test_date_not_confirmed_has_no_days_left(client):
    sign_in(client, "omar")
    # Omar holds only 'bookkeeping' on Gulf Tech: every obligation is withheld
    body = client.get(f"/api/companies/{CO_GULFTECH}/obligations").json()
    assert body["items"] == [] and body["withheld_count"] > 0 and body["withheld_note"]["en"] == "Some obligations are not shared with you."


def test_gulftech_ct_date_not_confirmed(db):
    rows = dl.obligations_for(db, CO_GULFTECH)
    ct = next(r for r in rows if r["obligation_type"] == "ct_return")
    assert ct["date_status"] == "not_confirmed" and ct["due_date"] is None and ct["days_left"] is None
    assert ct["status_chip"] == "date_not_confirmed" and {m["code"] for m in ct["missing_items"]} >= {"ct_status", "tax_period"}
    ext = next(r for r in rows if r["obligation_type"] == "vat_return" and r["due_date_source"] == "fta_extension")
    assert ext["is_stated"] and ext["deadline_source"] == "FTA_NOTICE"


def test_blue_dune_ct_data_missing(db):
    rows = dl.obligations_for(db, CO_BLUEDUNE)
    ct = next(r for r in rows if r["obligation_type"] == "ct_return" and r["period_end"] == CT.end.isoformat())
    assert ct["due_date"] == CT.due.isoformat() and ct["readiness"] == "data_missing" and ct["missing_items"]
    if ct["days_left"] < 0:
        assert ct["status_chip"] == "overdue_status_unconfirmed"  # never counted late


def test_precedence_authority_over_rule_over_owner(client, db):
    sign_in(client, "khalid")
    items = client.get(f"/api/companies/{CO_ALNOOR}/obligations").json()["items"]
    vat = next(i for i in items if i["obligation_type"] == "vat_return" and i["period_end"] == CURRENT.end.isoformat())
    stated = (CURRENT.due + timedelta(days=1)).isoformat()
    # authority date without evidence is refused
    r = client.post(f"/api/companies/{CO_ALNOOR}/obligations/{vat['obligation_id']}/authority-date", json={"kind": "FTA_NOTICE", "stated_date": stated})
    assert r.status_code == 422 and r.json()["error"] == "EVIDENCE_REQUIRED"
    r = client.post(f"/api/companies/{CO_ALNOOR}/obligations/{vat['obligation_id']}/authority-date", json={"kind": "FTA_NOTICE", "stated_date": stated, "evidence_ref": "doc_123"})
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["due_date"] == stated and out["statutory_date"] == CURRENT.due.isoformat() and out["due_date_source"] == "fta_stated" and out["is_stated"]
    assert out["date_updated"]["old_date"] == CURRENT.due.isoformat() and out["date_updated"]["source_tag"] == "authority date entered by you"


def test_no_roll_weekend_keeps_statutory_and_recommends_earlier(db):
    # 28 Feb 2027 is a Sunday: VAT for January 2027 ends 31 Jan -> statutory 28 Feb 2027 stays; submit-by Friday 26 Feb
    c = {"key": "vat_return:t", "type": "vat_return", "authority": "FTA", "period_end": date(2027, 1, 31), "rule_key": "vat.deadline_offset_days", "deadline_source": "RULE_DERIVED", "is_stated": False}
    r = dl.resolve(db, CO_ALNOOR, c, date(2027, 1, 1))
    assert r["date_used"] == date(2027, 2, 28) and r["statutory_date"] == date(2027, 2, 28)
    assert r["nonworking_flag"] == "weekend" and r["recommended_submit_by"] == date(2027, 2, 26)


def test_provisional_holiday_no_roll_no_nonworking_label(db):
    d = date(2027, 3, 10)  # provisional Eid al-Fitr in the seeded federal calendar (a Wednesday)
    assert dl.day_flag(db, d, "UAE-FEDERAL") == "provisional_holiday"
    assert dl.is_working_day(db, d, "UAE-FEDERAL")  # not presented as a confirmed non-working day
    assert dl.recommended_submit_by(db, d, "UAE-FEDERAL") < d  # reminders run against the earlier date


def test_confirmed_holiday_two_person_approval_and_recalc(db):
    from app.core.errors import ValidationFailed

    e = dl.add_calendar_entry(db, {"jurisdiction": "UAE-FEDERAL", "name_en": "Test holiday", "name_ar": "عطلة", "start_date": "2027-04-14", "status": "confirmed", "source_reference": "Cabinet announcement test"}, entered_by="Faisal")
    assert dl.day_flag(db, date(2027, 4, 14), "UAE-FEDERAL") == "none"  # not active until approved
    with pytest.raises(ValidationFailed):
        dl.approve_calendar_entry(db, e.id, approved_by="Faisal")
    out = dl.approve_calendar_entry(db, e.id, approved_by="Adel")
    assert out["version"] == "2027.2" and out["batch"]["status"] in ("finished", "finished_with_failures")
    assert dl.day_flag(db, date(2027, 4, 14), "UAE-FEDERAL") == "public_holiday"


def test_missing_calendar_uses_working_week_only(db):
    assert dl.calendar_state(db, "UAE-FEDERAL", 2031)["state"] == "missing"
    assert dl.day_flag(db, date(2031, 12, 2), "UAE-FEDERAL") == "none"  # no holiday claims without a calendar
    v = db.query(CalendarVersion).filter_by(jurisdiction="UAE-FEDERAL", year=2026).one()
    v.checked_at = dubai_today() - timedelta(days=45)
    db.flush()
    assert dl.calendar_state(db, "UAE-FEDERAL", 2026)["state"] == "stale"
    assert db.query(CalendarEntry).filter_by(jurisdiction="DUBAI-GOV").count() > 0


def test_batch_priority_checkpoint_resume_and_failure(db):
    dl.obligations_for(db, CO_ALNOOR)
    dl.obligations_for(db, CO_SAFWA)
    first = dl.run_recalculation_batch(db, reason="test", company_ids=[CO_GULFTECH, CO_ALNOOR, CO_SAFWA, CO_BLUEDUNE], stop_after=1)
    assert first["status"] == "running" and len(first["done"]) == 1 and len(first["pending"]) == 3
    # unprocessed companies show 'Recalculation pending' with the old date
    pending_co = first["pending"][0]
    rows = dl.obligations_for(db, pending_co)
    assert any(r["recalc_state"] == "recalculation_pending" and r["status_chip"] == "date_being_updated" for r in rows if not r["done"])
    resumed = dl.resume_batch(db, first["batch_id"], fail_companies={CO_BLUEDUNE})
    assert resumed["status"] == "finished_with_failures" and CO_BLUEDUNE in resumed["failed"] and resumed["attempts"][CO_BLUEDUNE] == 3
    assert resumed["done"][0] == first["done"][0]  # finished companies never re-applied
    cp = db.query(RecalcCheckpoint).filter_by(batch_id=first["batch_id"], company_id=first["done"][0]).one()
    assert cp.attempts == 1
    failed_rows = dl.obligations_for(db, CO_BLUEDUNE)
    failed_only = [r for r in failed_rows if r["recalc_state"] == "recalculation_failed"]
    assert failed_only and all(r["date_status"] == "not_confirmed" and r["days_left"] is None for r in failed_only)
    assert any(r["last_confirmed_date"] for r in failed_only)  # last confirmed date kept, never shown as current
    from app.core.time import utcnow

    assert dl.escalate_failed_recalculations(db, now=utcnow() + timedelta(hours=25)) == 1
    retry = dl.retry_company(db, CO_BLUEDUNE)
    assert retry["done"] == [CO_BLUEDUNE]


def test_filed_receipt_marks_done_and_owner_only_declaration(client):
    sign_in(client, "omar")
    items = client.get(f"/api/companies/{CO_ALNOOR}/obligations").json()["items"]
    vat = next(i for i in items if i["obligation_type"] == "vat_return" and i["period_end"] == OPEN.end.isoformat())
    r = client.post(f"/api/companies/{CO_ALNOOR}/obligations/{vat['obligation_id']}/filed-evidence", json={"source": "owner_declaration"})
    assert r.status_code == 403
    r = client.post(f"/api/companies/{CO_ALNOOR}/obligations/{vat['obligation_id']}/filed-evidence", json={"source": "receipt", "filing_reference": "ACK-1"})
    assert r.status_code == 422
    r = client.post(f"/api/companies/{CO_ALNOOR}/obligations/{vat['obligation_id']}/filed-evidence", json={"source": "receipt", "filing_reference": "ACK-1", "filed_date": QUARTERS.today.isoformat()})
    assert r.status_code == 200 and r.json()["readiness"] == "receipt_recorded" and r.json()["done"]


def test_delegate_sees_only_assigned_functions_and_portfolio(client):
    sign_in(client, "omar")
    body = client.get(f"/api/companies/{CO_ALNOOR}/obligations").json()
    assert {i["obligation_type"] for i in body["items"]} <= {"vat_return", "ct_return"} and body["withheld_count"] >= 2
    me = client.get("/api/me/obligations").json()
    assert {i["company_id"] for i in me["items"]} <= {CO_ALNOOR, CO_BLUEDUNE, CO_GULFTECH}
    assert all(i["company_name"] for i in me["items"])
    flags = [i["days_left"] is not None and i["days_left"] < 0 for i in me["items"]]
    assert flags == sorted(flags, reverse=True)  # overdue pinned top
    # notify owner is rate-limited once per 24 h per item
    assert client.post(f"/api/companies/{CO_GULFTECH}/obligations/notify-owner", json={"item_code": "tax_period"}).status_code == 200
    assert client.post(f"/api/companies/{CO_GULFTECH}/obligations/notify-owner", json={"item_code": "tax_period"}).json()["error"] == "NOTIFY_RATE_LIMITED"


def test_company_isolation_and_det_admin(client):
    sign_in(client, "priya")
    assert client.get(f"/api/companies/{CO_ALNOOR}/obligations").status_code == 403
    assert client.get(f"/api/companies/{CO_BLUEDUNE}/obligations").status_code == 200
    client.cookies.clear()
    sign_in(client, "sara")
    assert client.get(f"/api/companies/{CO_ALNOOR}/obligations").status_code == 403
    agg = client.get("/api/deadlines/aggregates")
    assert agg.status_code == 200 and "company_id" not in str(agg.json())


def test_tax_hook_and_superseded_rows(db):
    out = dl.due_date_for(db, CO_ALNOOR, "vat", OPEN.end)
    assert out["date"] == OPEN.due
    assert db.query(Obligation).filter_by(company_id=CO_ALNOOR, superseded=True).count() == 0
