"""Reminders by channel and role (E3-S4) - owner of the reminder template registry - and remote-owner reminder
delivery (E3-S5). Nothing is really sent: every delivery is recorded in ``reminder_outbox`` by a channel adapter.

* ``ReminderTemplate``   versioned bilingual templates (approved per locale before use).
* ``ReminderPreference`` per recipient and company: language, channels (portal mandatory; email 1B; SMS 1C opt-in
                         recorded; WhatsApp disabled by configuration), contact verification and bounce state.
* ``Reminder``           one planned reminder (deadline, recipient, channel, lead time, planned_send_at, window...).
* ``ReminderOutbox``     the delivery record written by the adapters (portal visible / email accepted).
* ``K30Event``           timeliness record per sent or cancelled reminder (cancellations excluded from K30).
* ``ReminderRequest``    'Remind me' requests from the compliance cards (E3-S3 -> E3-S4).
"""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import JSON, Boolean, Date, DateTime, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.core.ids import new_id
from app.core.time import utcnow

CHANNELS = ("portal", "email", "sms", "whatsapp", "push")
TEMPLATE_KINDS = ("standard", "catch_up", "date_updated", "overdue", "quarantine_decision_needed", "dates_changed", "requested")
DELIVERY_STATUSES = ("accepted", "delivered", "failed", "bounced", "unknown")
REMINDER_STATUSES = ("planned", "retry_wait", "sent", "cancelled", "held", "failed_fallback")
CANCEL_EVENTS = ("task_completed", "filed_evidence_recorded", "access_lost", "deadline_superseded", "recipient_removed")
HOLD_REASONS = ("batch_running", "missing_translation", "blocked_content", "no_owner_no_delegate")
DEADLINE_CATEGORIES = ("tax_return", "licence_renewal", "tenancy_renewal", "chamber_membership", "licence_requirement", "vat_return", "corporate_tax_return")


class ReminderTemplate(Base):
    __tablename__ = "reminder_templates"
    __table_args__ = (UniqueConstraint("template_id", "locale", "version", name="uq_reminder_template_version"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    template_id: Mapped[str] = mapped_column(String(80), index=True)  # e.g. 'standard.portal', 'standard.outbound'
    kind: Mapped[str] = mapped_column(String(40))  # TEMPLATE_KINDS
    channel_class: Mapped[str] = mapped_column(String(20))  # portal | outbound | sms
    locale: Mapped[str] = mapped_column(String(5))  # ar | en
    text: Mapped[str] = mapped_column(Text)
    version: Mapped[str] = mapped_column(String(20), default="v1")
    status: Mapped[str] = mapped_column(String(30), default="approved")  # approved | pending_translation | draft
    approver: Mapped[str | None] = mapped_column(String(120))
    reviewer_status: Mapped[str] = mapped_column(String(20), default="unreviewed")  # native-speaker review state
    is_current: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class ReminderPreference(Base):
    __tablename__ = "reminder_preferences"
    __table_args__ = (UniqueConstraint("company_id", "identity_uuid", name="uq_reminder_pref"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    company_id: Mapped[str] = mapped_column(String(40), index=True)
    identity_uuid: Mapped[str] = mapped_column(String(64), index=True)
    language: Mapped[str | None] = mapped_column(String(5))  # None -> ar + en together (remote owners)
    email_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    sms_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    sms_opt_in_at: Mapped[datetime | None] = mapped_column(DateTime)  # recorded opt-in (Phase 1C channel)
    whatsapp_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    email_masked: Mapped[str | None] = mapped_column(String(120))
    mobile_masked: Mapped[str | None] = mapped_column(String(40))
    email_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    mobile_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    email_state: Mapped[str] = mapped_column(String(20), default="ok")  # ok | unverified | undeliverable
    soft_bounces: Mapped[int] = mapped_column(Integer, default=0)
    delegate_reminder_right: Mapped[bool] = mapped_column(Boolean, default=True)  # owner can switch a delegate's right off
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Reminder(Base):
    __tablename__ = "reminders"
    __table_args__ = (UniqueConstraint("idempotency_key", name="uq_reminder_idempotency"),)

    reminder_id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("rem"))
    deadline_id: Mapped[str | None] = mapped_column(String(40), index=True)  # obligation_id
    obligation_key: Mapped[str | None] = mapped_column(String(160))
    company_id: Mapped[str] = mapped_column(String(40), index=True)
    recipient_uuid: Mapped[str] = mapped_column(String(64), index=True)
    recipient_role: Mapped[str] = mapped_column(String(30))
    language: Mapped[str] = mapped_column(String(8))  # ar | en | ar+en
    channel: Mapped[str] = mapped_column(String(20))
    kind: Mapped[str] = mapped_column(String(30), default="standard")
    template_id: Mapped[str] = mapped_column(String(80))
    template_version: Mapped[str] = mapped_column(String(20), default="v1")
    deadline_category: Mapped[str] = mapped_column(String(40))
    lead_time_days: Mapped[int | None] = mapped_column(Integer)
    planned_date: Mapped[date] = mapped_column(Date)
    planned_send_at: Mapped[datetime] = mapped_column(DateTime)  # UTC
    window_minutes: Mapped[int] = mapped_column(Integer, default=60)
    calendar_version: Mapped[str | None] = mapped_column(String(120))
    rule_version: Mapped[str | None] = mapped_column(String(40))
    due_date_stated: Mapped[date | None] = mapped_column(Date)
    source_label: Mapped[str | None] = mapped_column(String(80))
    computed_only_flag: Mapped[bool] = mapped_column(Boolean, default=False)
    flags: Mapped[list | None] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(20), default="planned")  # REMINDER_STATUSES
    hold_reason: Mapped[str | None] = mapped_column(String(40))
    reminder_visible_at: Mapped[datetime | None] = mapped_column(DateTime)
    provider_accepted_at: Mapped[datetime | None] = mapped_column(DateTime)
    delivery_status: Mapped[str | None] = mapped_column(String(20))
    provider_message_id: Mapped[str | None] = mapped_column(String(80))
    attempt: Mapped[int] = mapped_column(Integer, default=0)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime)
    idempotency_key: Mapped[str] = mapped_column(String(300))
    cancellation_key: Mapped[str] = mapped_column(String(300), index=True)
    cancel_event: Mapped[str | None] = mapped_column(String(40))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime)
    inbox_state: Mapped[str] = mapped_column(String(20), default="unread")  # unread | acknowledged
    body_en: Mapped[str | None] = mapped_column(Text)
    body_ar: Mapped[str | None] = mapped_column(Text)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class ReminderOutbox(Base):
    __tablename__ = "reminder_outbox"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("rob"))
    reminder_id: Mapped[str] = mapped_column(String(40), index=True)
    company_id: Mapped[str] = mapped_column(String(40), index=True)
    channel: Mapped[str] = mapped_column(String(20))
    recipient_ref: Mapped[str] = mapped_column(String(80))  # reference only (pseudonymous), never the address
    template_id: Mapped[str] = mapped_column(String(80))
    template_version: Mapped[str] = mapped_column(String(20))
    language: Mapped[str] = mapped_column(String(8))
    subject: Mapped[str | None] = mapped_column(String(255))
    body: Mapped[str] = mapped_column(Text)
    idempotency_key: Mapped[str] = mapped_column(String(300), index=True)
    attempt: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(20), default="accepted")  # visible | accepted | failed
    provider_message_id: Mapped[str | None] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)


class K30Event(Base):
    __tablename__ = "reminder_k30_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    reminder_id: Mapped[str] = mapped_column(String(40), index=True)
    company_id: Mapped[str] = mapped_column(String(40), index=True)
    channel: Mapped[str] = mapped_column(String(20))
    planned_send_at: Mapped[datetime] = mapped_column(DateTime)
    window_minutes: Mapped[int] = mapped_column(Integer)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime)
    on_time: Mapped[bool | None] = mapped_column(Boolean)
    catch_up: Mapped[bool] = mapped_column(Boolean, default=False)
    held_delay_minutes: Mapped[int | None] = mapped_column(Integer)
    cancel_event: Mapped[str | None] = mapped_column(String(40))  # cancellations excluded from K30
    excluded: Mapped[bool] = mapped_column(Boolean, default=False)
    peak_window: Mapped[bool] = mapped_column(Boolean, default=False)
    calendar_version: Mapped[str | None] = mapped_column(String(120))
    recorded_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class ReminderRequest(Base):
    __tablename__ = "reminder_requests"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("rrq"))
    company_id: Mapped[str] = mapped_column(String(40), index=True)
    requirement_type: Mapped[str] = mapped_column(String(40))
    requested_by_uuid: Mapped[str] = mapped_column(String(64))
    requested_by_role: Mapped[str] = mapped_column(String(30))
    reminder_date: Mapped[date] = mapped_column(Date)
    channel: Mapped[str] = mapped_column(String(20), default="portal")
    status: Mapped[str] = mapped_column(String(20), default="scheduled")  # scheduled | cancelled | sent
    reminder_id: Mapped[str | None] = mapped_column(String(40))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
