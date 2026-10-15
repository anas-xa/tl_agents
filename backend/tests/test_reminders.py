"""E3-S4 / E3-S5 reminders: template registry and forbidden content, channel gating, scheduling rules, K30."""

from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest
from conftest import sign_in

from app.core.errors import NotFound, ValidationFailed
from app.core.time import dubai_today, utcnow
from app.demo import CO_ALNOOR, CO_BLUEDUNE, CO_GULFTECH, CO_SAFWA, PERSONA_UUIDS
from app.modules.config.service import set_config
from app.modules.reminders import service as rs
from app.modules.reminders.models import K30Event, Reminder, ReminderOutbox, ReminderTemplate
from app.modules.reminders.strings import TEMPLATES


@pytest.mark.parametrize(
    ("text", "code"),
    [
        ("Your VAT is AED 1,250.00", "amount"),
        ("Pay 4500.00 now", "amount"),
        ("TRN 100234567890003 is due", "trn"),
        ("Emirates ID 784-1980-1234567-1", "emirates_id"),
        ("A penalty of AED 500 will be charged", "penalty_amount"),
        ("Late filing: penalty applies", "penalty_claim"),
        ("You owe the FTA", "debt_claim"),
        ("You must file today", "instruction"),
        ("Your company is exempt", "status_judgement"),
        ("Your return was filed", "approval_or_filing_implied"),
        ("Upgrade now for a discount", "promotional"),
        ("Avoid penalties by acting now", "penalty_claim"),
    ],
)
def test_forbidden_content_validator(text, code):
    assert code in rs.validate_content(text, channel_class="portal", generic=False)


def test_tax_type_and_links_forbidden_outbound_and_for_remote_owners():
    assert "tax_type_named" in rs.validate_content("A VAT return deadline is on 28 October 2026", channel_class="outbound", generic=True)
    assert "tax_type_named" in rs.validate_content("موعد إقرار ضريبة القيمة المضافة", channel_class="portal", generic=True)
    assert rs.validate_content("A VAT return deadline is on 28 October 2026", channel_class="portal", generic=False) == []
    assert "link_not_sign_in_only" in rs.validate_content("Sign in: https://evil.example/x", channel_class="outbound", generic=True)
    assert "link_not_sign_in_only" in rs.validate_content(rs.portal_link() + "?token=abc", channel_class="outbound", generic=True)
    assert "company_name_in_sms" in rs.validate_content("Al Noor Trading LLC: deadline", channel_class="sms", generic=True, trade_name="Al Noor Trading LLC")


def test_registry_templates_bilingual_and_clean(db):
    for tid in TEMPLATES:
        for loc in ("en", "ar"):
            assert rs.template(db, tid, loc) is not None, (tid, loc)
    with pytest.raises(ValidationFailed) as e:
        rs.register_template(db, "bad.portal", kind="standard", channel_class="portal", locale="en", text="{trade_name}: you owe AED 500", version="v1", approver="x")
    assert e.value.reason_code == "TEMPLATE_FORBIDDEN_CONTENT"
    with pytest.raises(ValidationFailed) as e:
        rs.register_template(db, "bad2.portal", kind="standard", channel_class="portal", locale="en", text="{trade_name}: {ai_summary}", version="v1", approver="x")
    assert e.value.reason_code == "TEMPLATE_PARAM_NOT_ALLOWED"


def test_render_refuses_free_text_and_missing_locale(db):
    with pytest.raises(ValidationFailed):
        rs.render(db, "standard.portal", "en", {"trade_name": "X", "note": "AI wrote this"})
    with pytest.raises(NotFound):
        rs.render(db, "overdue.portal", "ar", {"trade_name": "X"})  # Arabic overdue template pending translation
    text = rs.render(db, "standard.outbound", "en", {"trade_name": "Al Noor Trading LLC", "category": "tax_return", "due_date": date(2026, 10, 28), "status": "due_soon", "source_tag": "computed_not_confirmed", "action_line": "track"})
    assert "28 October 2026" in text and "calculated from the standard rule, not confirmed with the FTA" in text and rs.portal_link() in text
    assert rs.validate_content(text, channel_class="outbound", generic=True) == []


def test_portal_mandatory_whatsapp_disabled_sms_stored_inactive(client, db):
    sign_in(client, "khalid")
    base = f"/api/companies/{CO_ALNOOR}/reminders/preferences"
    assert client.put(base, json={"channels": {"portal": False}}).json()["error"] == "MANDATORY_REMINDER"
    r = client.put(base, json={"channels": {"whatsapp": True}})
    assert r.status_code == 403 and r.json()["error"] == "WHATSAPP_DISABLED"
    r = client.put(base, json={"channels": {"sms": True}})
    assert r.status_code == 200 and r.json()["channels"]["sms"] is True and r.json()["sms_opt_in_at"]
    states = r.json()["channel_states"]
    assert states["sms"]["enabled"] is False and states["whatsapp"]["reason"] == "disabled_by_configuration" and states["portal"]["mandatory"]
    client.get(f"/api/companies/{CO_ALNOOR}/reminders")
    db.expire_all()
    assert db.query(ReminderOutbox).filter_by(channel="sms").count() == 0
    assert db.query(Reminder).filter_by(channel="sms").count() == 0


def test_email_goes_to_outbox_only_within_window(db):
    rs.schedule_for_company(db, CO_ALNOOR)
    email = db.query(Reminder).filter_by(company_id=CO_ALNOOR, channel="email", status="planned").order_by(Reminder.planned_send_at).first()
    assert email is not None
    # 06:00 Dubai is outside the 08:00-18:00 window: deferred, not sent
    early = datetime.combine(email.planned_date, datetime.min.time()) + timedelta(hours=2)  # 06:00 Dubai
    email.planned_send_at = early - timedelta(hours=1)
    db.flush()
    rs.run_due(db, early, company_id=CO_ALNOOR)
    assert email.status == "retry_wait"
    noon = datetime.combine(email.planned_date, datetime.min.time()) + timedelta(hours=8)  # 12:00 Dubai
    rs.run_due(db, noon, company_id=CO_ALNOOR)
    assert email.status == "sent" and email.provider_accepted_at == noon
    out = db.query(ReminderOutbox).filter_by(reminder_id=email.reminder_id).one()
    assert out.status == "accepted" and "VAT" not in out.body and "corporate tax" not in out.body.lower()
    assert rs.validate_content(out.body, channel_class="outbound", generic=True) == []


def test_never_on_weekend_never_after_due(db):
    rs.schedule_for_company(db, CO_ALNOOR)
    for r in db.query(Reminder).filter_by(company_id=CO_ALNOOR).all():
        assert r.planned_date.weekday() not in (5, 6)
        if r.kind != "overdue" and r.due_date_stated:
            assert r.planned_date <= r.due_date_stated
    # merge rule: never more than one reminder per deadline, recipient, channel and day
    keys = [(r.deadline_id, r.recipient_uuid, r.channel, r.planned_date) for r in db.query(Reminder).filter(Reminder.status != "cancelled").all() if r.kind in ("standard", "catch_up", "overdue")]
    assert len(keys) == len(set(keys))


def test_slots_catch_up_and_overdue_notice(db):
    today = dubai_today()
    ob = {"obligation_type": "vat_return", "date_used": (today + timedelta(days=2)).isoformat(), "recommended_submit_by": None, "provisional_date": None, "last_confirmed_date": None}
    slots = rs._slots(db, ob, today, already_sent=False)
    assert slots and all(s["date"] >= today for s in slots)
    late = {"obligation_type": "licence_renewal", "date_used": (today + timedelta(days=0)).isoformat(), "recommended_submit_by": None, "provisional_date": None, "last_confirmed_date": None}
    s2 = rs._slots(db, late, today, already_sent=False)
    assert any(s["kind"] in ("catch_up", "standard") for s in s2)
    od = {"obligation_type": "licence_renewal", "date_used": (today - timedelta(days=10)).isoformat(), "recommended_submit_by": None, "provisional_date": None, "last_confirmed_date": None}
    s3 = rs._slots(db, od, today, already_sent=True)
    assert [s["kind"] for s in s3] == ["overdue"] and s3[0]["date"] >= today


def test_k30_cancellation_when_task_completed(client, db):
    sign_in(client, "khalid")
    items = client.get(f"/api/companies/{CO_ALNOOR}/obligations").json()["items"]
    vat = next(i for i in items if i["obligation_type"] == "vat_return" and i["period_end"] == "2026-09-30")
    client.get(f"/api/companies/{CO_ALNOOR}/reminders")
    db.expire_all()
    planned = db.query(Reminder).filter_by(deadline_id=vat["obligation_id"], status="planned").count()
    assert planned > 0
    r = client.post(f"/api/companies/{CO_ALNOOR}/obligations/{vat['obligation_id']}/filed-evidence", json={"source": "receipt", "filing_reference": "ACK-9", "filed_date": "2026-10-12"})
    assert r.status_code == 200
    db.expire_all()
    assert db.query(Reminder).filter_by(deadline_id=vat["obligation_id"], status="planned").count() == 0
    cancelled = db.query(Reminder).filter_by(deadline_id=vat["obligation_id"], status="cancelled").all()
    assert cancelled and all(c.cancel_event == "filed_evidence_recorded" for c in cancelled)
    ev = db.query(K30Event).filter_by(reminder_id=cancelled[0].reminder_id).one()
    assert ev.excluded and ev.cancel_event == "filed_evidence_recorded"
    assert rs.k30_summary(db)["excluded_cancellations"] >= len(cancelled)


def test_remote_owner_generic_category_bilingual(db):
    rs.schedule_for_company(db, CO_BLUEDUNE)
    rows = db.query(Reminder).filter_by(company_id=CO_BLUEDUNE, recipient_uuid=PERSONA_UUIDS["priya"]).all()
    assert rows and all(r.language == "ar+en" for r in rows)
    assert all(r.deadline_category not in ("vat_return", "corporate_tax_return") for r in rows)
    rs.run_due(db, utcnow() + timedelta(days=400), company_id=CO_BLUEDUNE)
    priya_ids = {r.reminder_id for r in rows}
    sent = [o for o in db.query(ReminderOutbox).filter_by(company_id=CO_BLUEDUNE).all() if o.reminder_id in priya_ids]
    assert sent
    for o in sent:
        assert rs.validate_content(o.body, channel_class="outbound" if o.channel != "portal" else "portal", generic=True) == [], o.body


def test_missing_translation_holds_and_tells_owner(db):
    rs.schedule_for_company(db, CO_BLUEDUNE)
    overdue = db.query(Reminder).filter_by(company_id=CO_BLUEDUNE, kind="overdue", recipient_uuid=PERSONA_UUIDS["priya"]).first()
    if overdue is None:
        pytest.skip("no overdue Blue Dune obligation on this date")
    rs.run_due(db, utcnow() + timedelta(days=1), company_id=CO_BLUEDUNE)
    assert overdue.status == "held" and overdue.hold_reason == "missing_translation"
    box = rs.inbox(db, CO_BLUEDUNE, PERSONA_UUIDS["priya"])
    assert box["held_notices"] and "is delayed. We are preparing it in your language." in box["held_notices"][0]["text"]["en"]


def test_retries_then_portal_fallback(db):
    set_config(db, "reminders.email.adapter.simulate_failure", True, changed_by="test")
    rs.schedule_for_company(db, CO_ALNOOR)
    email = db.query(Reminder).filter_by(company_id=CO_ALNOOR, channel="email", status="planned").order_by(Reminder.planned_send_at).first()
    t0 = email.planned_send_at + timedelta(minutes=5)
    rs.run_due(db, t0, company_id=CO_ALNOOR)
    assert email.status == "retry_wait" and email.attempt == 1 and email.next_attempt_at == t0 + timedelta(minutes=15)
    rs.run_due(db, t0 + timedelta(minutes=16), company_id=CO_ALNOOR)
    assert email.attempt == 2 and email.next_attempt_at == t0 + timedelta(minutes=16) + timedelta(minutes=60)
    rs.run_due(db, t0 + timedelta(minutes=16 + 61), company_id=CO_ALNOOR)
    assert email.status == "failed_fallback" and email.attempt == 3
    idem = email.idempotency_key.rsplit("|", 1)[0] + "|portal"
    portal = db.query(Reminder).filter_by(idempotency_key=idem).one()
    assert portal.status == "sent"
    assert db.query(ReminderOutbox).filter_by(idempotency_key=email.idempotency_key).count() == 0  # nothing accepted


def test_access_lost_cancels_delegate_reminders_and_keeps_owner(db):
    rs.schedule_for_company(db, CO_ALNOOR)
    omar = PERSONA_UUIDS["omar"]
    assert db.query(Reminder).filter_by(company_id=CO_ALNOOR, recipient_uuid=omar, status="planned").count() > 0
    from app.modules.companies.models import CompanyRole

    role = db.query(CompanyRole).filter_by(company_id=CO_ALNOOR, identity_uuid=omar).one()
    role.status = "revoked"
    db.flush()
    out = rs.on_access_lost(db, CO_ALNOOR, omar)
    assert out["cancelled"] > 0
    assert all(r.cancel_event == "access_lost" for r in db.query(Reminder).filter_by(company_id=CO_ALNOOR, recipient_uuid=omar, status="cancelled").all())
    owner_rows = db.query(Reminder).filter_by(company_id=CO_ALNOOR, recipient_uuid=PERSONA_UUIDS["khalid"]).filter(Reminder.status != "cancelled").all()
    keys = [(r.deadline_id, r.channel, r.planned_date) for r in owner_rows if r.kind == "standard"]
    assert keys and len(keys) == len(set(keys))  # no duplicates for the owner


def test_no_owner_level_user_routing(db):
    recs, flags = rs.recipients(db, CO_GULFTECH, "vat_return")
    assert "no_owner_level_user" in flags
    assert recs == []  # the only delegate has no deadlines function -> held, nobody contacted
    recs2, flags2 = rs.recipients(db, CO_GULFTECH, "other")
    assert flags2 == ["no_owner_level_user"]


def test_whatsapp_and_sms_off_by_default_in_config(db):
    assert rs.channel_enabled(db, "portal") and rs.channel_enabled(db, "email")
    assert not rs.channel_enabled(db, "sms") and not rs.channel_enabled(db, "whatsapp") and not rs.channel_enabled(db, "push")
    set_config(db, "reminders.channel.sms.enabled", True, changed_by="test")
    assert not rs.channel_enabled(db, "sms")  # provider without callbacks -> channel not enabled


def test_safwa_overdue_notice_in_outbox_and_inbox(client, db):
    sign_in(client, "khalid")
    box = client.get(f"/api/companies/{CO_SAFWA}/reminders").json()
    overdue = [i for i in box["items"] if i["kind"] == "overdue"]
    if dubai_today().weekday() in (5, 6):
        pytest.skip("overdue notices go out on the next working day")
    assert overdue and "Penalties may apply" in overdue[0]["body"]["en"]
    assert all("AED" not in (i["body"]["en"] or "") for i in box["items"])
    assert db.query(ReminderTemplate).filter_by(template_id="overdue.portal", locale="ar").one().status == "pending_translation"


def test_inbox_permissions(client):
    sign_in(client, "omar")
    assert client.get(f"/api/companies/{CO_ALNOOR}/reminders").status_code == 200
    assert client.get(f"/api/companies/{CO_ALNOOR}/reminders/schedule").status_code == 403
    assert client.get(f"/api/companies/{CO_SAFWA}/reminders").status_code == 403
