"""Reminder template registry, reminder_policy v1, channel switches and demo reminders in the outbox (E3-S4)."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.time import utcnow
from app.demo import CO_ALNOOR, CO_BLUEDUNE, CO_GULFTECH, CO_SAFWA, PERSONA_UUIDS
from app.modules.config.service import ensure_config
from app.modules.reminders.models import ReminderPreference, ReminderTemplate
from app.modules.reminders.service import POLICY_DEFAULT, register_template, run_due, schedule_for_company
from app.modules.reminders.strings import TEMPLATES

ORDER = 44


def seed(db: Session) -> None:
    for tid, t in TEMPLATES.items():
        for loc in ("en", "ar"):
            if db.scalar(select(ReminderTemplate).where(ReminderTemplate.template_id == tid, ReminderTemplate.locale == loc)) is not None:
                continue
            status = t.get("ar_status", "approved") if loc == "ar" else "approved"
            register_template(db, tid, kind=t["kind"], channel_class=t["channel_class"], locale=loc, text=t[loc], version="v1", approver="seed: UX and compliance reviewer (Arabic pending native review)" if status == "approved" else None, status=status)
    items = [
        ("reminders.policy.v1", POLICY_DEFAULT, "provisional", "reminder_policy v1 working values; tests assert against configuration", None),
        ("reminders.channel.email.enabled", True, "provisional", "Phase 1B per-channel switch (email through the outbox adapter only)", None),
        ("reminders.channel.sms.enabled", False, "provisional", "Phase 1C switch: SMS exists but is off", None),
        ("reminders.channel.whatsapp.enabled", False, "confirmed", "WhatsApp disabled by configuration (not removed)", None),
        ("reminders.channel.push.enabled", False, "confirmed", "push not in Phase 1", None),
        ("reminders.provider.callbacks", {"email": True, "sms": False}, "to_be_confirmed", "provider with accepted/delivered/failed/bounced callbacks; none -> channel not enabled, status unknown", None),
        ("reminders.email.adapter.simulate_failure", False, "provisional", "test hook for the retry path (outbox adapter)", None),
        ("reminders.sms.adapter.simulate_failure", False, "provisional", "test hook for the retry path (outbox adapter)", None),
        ("reminders.service.unavailable", False, "provisional", "test hook: E3-S4 unavailable -> request not saved, .ics fallback", None),
        ("reminders.k30.window_minutes", 60, "provisional", "illustrative", "minutes"),
        ("reminders.sc11.loading_timeout_seconds", 10, "provisional", "illustrative", "seconds"),
        ("reminders.contact_support_after_failures", 2, "provisional", "default", "count"),
        ("reminders.quarantine_prompt", {"repeat_after_working_days": 3, "max": 3}, "provisional", "illustrative", None),
        ("compliance.reminder.default_lead_days", 7, "provisional", "illustrative: 7 days before due", "days"),
        ("compliance.reminder.overdue_repeat_days", 3, "provisional", "illustrative: 'Remind me again in 3 days'", "days"),
    ]
    for key, value, status, label, unit in items:
        ensure_config(db, key, value, status=status, label=label, unit=unit, owner="Tech Lead (E3-S4)")
    db.flush()


def seed_demo(db: Session) -> None:
    if db.scalar(select(ReminderPreference).where(ReminderPreference.company_id == CO_ALNOOR).limit(1)) is not None:
        return
    prefs = [
        (CO_ALNOOR, PERSONA_UUIDS["khalid"], "en", True, "k•••@example.ae"),
        (CO_SAFWA, PERSONA_UUIDS["khalid"], "en", True, "k•••@example.ae"),
        (CO_BLUEDUNE, PERSONA_UUIDS["priya"], None, True, "p•••@example.co.uk"),
        (CO_ALNOOR, PERSONA_UUIDS["omar"], "en", False, None),
        (CO_BLUEDUNE, PERSONA_UUIDS["omar"], "en", False, None),
        (CO_GULFTECH, PERSONA_UUIDS["omar"], "en", False, None),
    ]
    for cid, uuid, lang, email, masked in prefs:
        db.add(ReminderPreference(company_id=cid, identity_uuid=uuid, language=lang, email_enabled=email, email_verified=email, email_masked=masked, mobile_masked="+971 5• ••• ••12" if uuid == PERSONA_UUIDS["khalid"] else None))
    db.flush()
    for cid in (CO_ALNOOR, CO_BLUEDUNE, CO_SAFWA, CO_GULFTECH):
        schedule_for_company(db, cid)
    run_due(db, utcnow())  # today's in-portal reminders and overdue notices land in the outbox (Demo data)
    from app.modules.reminders.models import Reminder, ReminderOutbox

    for r in db.scalars(select(Reminder)):
        r.is_demo = True
    for o in db.scalars(select(ReminderOutbox)):
        o.is_demo = True
    db.flush()
