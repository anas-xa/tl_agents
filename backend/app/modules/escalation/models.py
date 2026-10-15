"""Human escalation (E8): cases, workflow log, pauses, entitlements, case access grants, corpus, calendar.

Everything the K21/K22 dashboard computes comes from ``CaseEvent`` (the workflow log) joined on the
escalation id (= case id). No financial figures, identity numbers or free company text are stored on
events; cases hold only coded reasons, keys and references.
"""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import JSON, Boolean, Date, DateTime, Float, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.core.ids import new_id
from app.core.time import utcnow

MODULES = ("tax", "audit", "compliance", "legal", "other")
TRIGGER_SOURCES = ("agent_output", "user_question", "audit_exception", "compliance_item", "user_raised", "quarantine", "rule_set_failure")
# Owner-facing six statuses (SC10) plus the internal ones from E8-S2/E8-S3.
OWNER_STATUSES = ("open", "awaiting_consent", "with_specialist", "rejected", "resolved", "closed")
STATUSES = OWNER_STATUSES + ("awaiting_specialist_assignment", "closed_no_consent")
CLOSED_STATUSES = ("rejected", "resolved", "closed", "closed_no_consent")
PRIORITIES = ("standard", "deadline_near")
QUEUES = ("tax_specialist", "licensed_auditor", "det_compliance", "legal_queue", "escalation_ops")
SPECIALIST_TYPES = ("tax", "auditor", "lawyer", "compliance")
# E8-S4 reason code list (assumed log schema) extended with the rule-set reasons this module emits.
REASON_CODES = ("complex_tax", "audit_signoff_required", "legal_matter", "low_confidence", "user_requested", "data_conflict", "deadline_risk", "quarantine_review", "rule_set_unavailable", "unclassified")
MANDATORY_REASONS = ("audit_signoff_required", "legal_matter")
DISCRETIONARY_REASONS = ("low_confidence", "user_requested")
REJECT_CODES = ("R1", "R2", "R3", "R4", "R5")
RESOLUTION_OUTCOMES = ("a", "b", "c", "d")  # (a) answer delivered (b) reviewed/signed (c) handed back with limitation (d) closed - no consent
PAUSE_REASONS = ("awaiting_owner_consent", "awaiting_owner_information", "awaiting_owner_approval")
ENTITLEMENT_STATUSES = ("active", "expired", "suspended", "unclear")
FLAG_MANUAL_REVIEW = "manual_review_key_incomplete"


class WorkItem(Base):
    """Workflow-log case record (E8-S4 §2): one escalation-eligible matter per company, module and period.

    Other modules register their deliverables here (VAT return draft per period, audit file per period,
    compliance task); user-raised matters create one implicitly. K21's denominator.
    """

    __tablename__ = "escalation_work_items"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("wi"))
    company_id: Mapped[str] = mapped_column(String(40), index=True)
    module: Mapped[str] = mapped_column(String(20))
    case_type: Mapped[str | None] = mapped_column(String(40))
    period_ref: Mapped[str | None] = mapped_column(String(60))
    opened_by: Mapped[str] = mapped_column(String(20), default="agent")  # user | delegate | agent
    case_opened_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    case_closed_at: Mapped[datetime | None] = mapped_column(DateTime)
    calendar_version: Mapped[str | None] = mapped_column(String(40))
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)


class EscalationCase(Base):
    __tablename__ = "escalation_cases"
    __table_args__ = (UniqueConstraint("idempotency_key", name="uq_escalation_idempotency"),)

    case_id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("case"))
    company_id: Mapped[str] = mapped_column(String(40), index=True)
    work_item_id: Mapped[str | None] = mapped_column(String(40), index=True)
    module: Mapped[str] = mapped_column(String(20))
    case_type: Mapped[str] = mapped_column(String(20))
    matter_key: Mapped[str] = mapped_column(String(255), index=True)
    matter_key_rule_version: Mapped[str] = mapped_column(String(20), default="v1")
    trigger_rule_id: Mapped[str] = mapped_column(String(40))
    trigger_rule_version: Mapped[str] = mapped_column(String(20))
    trigger_event_id: Mapped[str] = mapped_column(String(80))
    idempotency_key: Mapped[str] = mapped_column(String(400))
    trigger_source: Mapped[str] = mapped_column(String(30))
    escalation_reason: Mapped[str] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(40), default="open", index=True)
    flags: Mapped[list | None] = mapped_column(JSON, default=list)
    priority: Mapped[str] = mapped_column(String(20), default="standard")
    severity: Mapped[str] = mapped_column(String(20), default="normal")
    required_action: Mapped[str | None] = mapped_column(String(40))
    queue: Mapped[str] = mapped_column(String(40))  # case_owner_role
    specialist_type: Mapped[str] = mapped_column(String(20))
    assigned_to: Mapped[str | None] = mapped_column(String(64), index=True)
    assigned_role_label: Mapped[str | None] = mapped_column(String(60))  # coded label, never a name
    linked_case_id: Mapped[str | None] = mapped_column(String(40))
    opened_by: Mapped[str] = mapped_column(String(20), default="agent")  # user | delegate | agent
    opened_by_key: Mapped[str | None] = mapped_column(String(64))
    title: Mapped[str | None] = mapped_column(String(255))  # owner's own title (voluntary); never for legal cases
    linked_item_id: Mapped[str | None] = mapped_column(String(80))
    topic_code: Mapped[str | None] = mapped_column(String(40))
    due_date: Mapped[date | None] = mapped_column(Date)
    opened_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    escalated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime)
    first_response_at: Mapped[datetime | None] = mapped_column(DateTime)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime)
    resolution_outcome: Mapped[str | None] = mapped_column(String(2))
    resolution_limitation: Mapped[bool] = mapped_column(Boolean, default=False)
    reject_reason_code: Mapped[str | None] = mapped_column(String(4))
    reject_note: Mapped[str | None] = mapped_column(String(300))
    rejected_by_key: Mapped[str | None] = mapped_column(String(64))
    rejected_at: Mapped[datetime | None] = mapped_column(DateTime)
    consent_requested_at: Mapped[datetime | None] = mapped_column(DateTime)
    consent_decision: Mapped[str | None] = mapped_column(String(20))  # granted | refused | None
    reopen_until: Mapped[date | None] = mapped_column(Date)
    legal_route_status: Mapped[str | None] = mapped_column(String(30))  # not_routed | routed | reviewed_by_named_lawyer
    calendar_version: Mapped[str | None] = mapped_column(String(40))
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)
    kpi_only: Mapped[bool] = mapped_column(Boolean, default=False)  # synthetic workflow-log rows for the K21/K22 demo; hidden from queues
    details: Mapped[dict | None] = mapped_column(JSON)  # codes and references only


class CaseEvent(Base):
    """Workflow log (join key: escalation_id = case_id). The only input to K21/K22."""

    __tablename__ = "escalation_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    escalation_id: Mapped[str] = mapped_column(String(40), index=True)
    event_type: Mapped[str] = mapped_column(String(40), index=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    actor_key: Mapped[str | None] = mapped_column(String(64))
    actor_role: Mapped[str | None] = mapped_column(String(40))
    reason_code: Mapped[str | None] = mapped_column(String(40))
    rule_version: Mapped[str | None] = mapped_column(String(20))
    details: Mapped[dict | None] = mapped_column(JSON)


class CasePause(Base):
    """K22 clock pause: awaiting owner consent / information / approval (internal waits never pause)."""

    __tablename__ = "escalation_pauses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    case_id: Mapped[str] = mapped_column(String(40), index=True)
    reason_code: Mapped[str] = mapped_column(String(40))
    started_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime)


class SpecialistEntitlement(Base):
    """Route-holder and entitlement register (versioned, human-verified; never a live lookup)."""

    __tablename__ = "specialist_entitlements"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("ent"))
    identity_uuid: Mapped[str] = mapped_column(String(64), index=True)
    specialist_type: Mapped[str] = mapped_column(String(20))  # tax | auditor | lawyer
    register_used: Mapped[str] = mapped_column(String(160))
    reference_number: Mapped[str] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(String(20), default="unclear")
    valid_to: Mapped[date | None] = mapped_column(Date)
    checked_by: Mapped[str | None] = mapped_column(String(120))
    checked_on: Mapped[date | None] = mapped_column(Date)
    jurisdiction: Mapped[str | None] = mapped_column(String(40))  # onshore Dubai | DIFC | ADGM
    firm_agreement_signed: Mapped[bool] = mapped_column(Boolean, default=False)
    review_only: Mapped[bool] = mapped_column(Boolean, default=True)  # tax: Phase 1 safe default, never submits to FTA
    version: Mapped[int] = mapped_column(Integer, default=1)
    is_current: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class CaseAccessGrant(Base):
    """Minimal per-case access grant (Phase 1 case-consent record; the consent module may supersede it)."""

    __tablename__ = "escalation_access_grants"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("grant"))
    case_id: Mapped[str] = mapped_column(String(40), index=True)
    company_id: Mapped[str] = mapped_column(String(40), index=True)
    recipient_uuid: Mapped[str] = mapped_column(String(64))
    purpose: Mapped[str] = mapped_column(String(255))
    scope: Mapped[list] = mapped_column(JSON)  # typed data items: {module, data_class, period_from, period_to}
    granted_by_key: Mapped[str] = mapped_column(String(64))
    granted_by_role: Mapped[str] = mapped_column(String(40))
    granted_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    status: Mapped[str] = mapped_column(String(20), default="active")  # active | revoked | expired
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime)
    text_version: Mapped[str] = mapped_column(String(20), default="case-consent-v1")


class CaseAccessLog(Base):
    __tablename__ = "escalation_access_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    case_id: Mapped[str] = mapped_column(String(40), index=True)
    actor_key: Mapped[str] = mapped_column(String(64))
    actor_role: Mapped[str] = mapped_column(String(40))
    item: Mapped[str] = mapped_column(String(80))
    result: Mapped[str] = mapped_column(String(10))  # allowed | denied
    reason: Mapped[str | None] = mapped_column(String(60))
    occurred_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class OpsAlert(Base):
    __tablename__ = "escalation_ops_alerts"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("alert"))
    alert_type: Mapped[str] = mapped_column(String(40))
    case_id: Mapped[str | None] = mapped_column(String(40), index=True)
    recipients: Mapped[list] = mapped_column(JSON, default=list)
    details: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    escalated_to_pilot_manager_at: Mapped[datetime | None] = mapped_column(DateTime)
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime)


class CorpusPassage(Base):
    """Versioned legal/tax corpus passage. Arabic is authoritative; English is an unofficial translation."""

    __tablename__ = "corpus_passages"

    passage_id: Mapped[str] = mapped_column(String(60), primary_key=True)
    domain: Mapped[str] = mapped_column(String(30))  # corporate_tax | vat | tax_procedures | einvoicing | licence | audit_profession | data_protection | legal_practice
    instrument: Mapped[str] = mapped_column(String(160))
    instrument_ar: Mapped[str] = mapped_column(String(160))
    article: Mapped[str] = mapped_column(String(60))
    subject: Mapped[str] = mapped_column(String(80))
    rule_type: Mapped[str] = mapped_column(String(20))  # rate | threshold | deadline | condition | definition | procedure
    value: Mapped[str | None] = mapped_column(String(80))
    unit: Mapped[str | None] = mapped_column(String(20))
    value_status: Mapped[str] = mapped_column(String(60), default="confirm instrument before quoting")
    condition: Mapped[str | None] = mapped_column(String(160))
    taxpayer_category: Mapped[str] = mapped_column(String(40), default="all")
    text_ar: Mapped[str] = mapped_column(Text)
    text_en: Mapped[str] = mapped_column(Text)
    keywords: Mapped[list] = mapped_column(JSON, default=list)
    owner_role: Mapped[str] = mapped_column(String(80))
    rank: Mapped[int] = mapped_column(Integer, default=1)
    corpus_version: Mapped[str] = mapped_column(String(20), default="2026-10")
    effective_from: Mapped[date | None] = mapped_column(Date)
    effective_to: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(20), default="in_force")  # in_force | superseded
    supersedes: Mapped[str | None] = mapped_column(String(60))
    source_ref: Mapped[str | None] = mapped_column(String(255))
    confirmed_by: Mapped[str | None] = mapped_column(String(120))
    answer_source: Mapped[bool] = mapped_column(Boolean, default=True)  # False: used only for refusal logic
    rules_ref: Mapped[str | None] = mapped_column(String(80))  # E3-S2 rule id + parameter to cross-check


class AnswerRecord(Base):
    __tablename__ = "corpus_answers"

    question_id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("q"))
    company_id: Mapped[str] = mapped_column(String(40), index=True)
    asker_key: Mapped[str | None] = mapped_column(String(64))
    question_text: Mapped[str | None] = mapped_column(Text)  # None for legal-type questions (never stored)
    language: Mapped[str] = mapped_column(String(10))
    corpus_version: Mapped[str] = mapped_column(String(20))
    threshold_version: Mapped[str] = mapped_column(String(20))
    decision: Mapped[str] = mapped_column(String(40))
    cause_code: Mapped[str | None] = mapped_column(String(40))  # internal; never shown in Phase 1
    review_band: Mapped[bool] = mapped_column(Boolean, default=False)
    retrieved_passage_ids: Mapped[list] = mapped_column(JSON, default=list)
    claims: Mapped[list] = mapped_column(JSON, default=list)
    citations: Mapped[list] = mapped_column(JSON, default=list)
    case_id: Mapped[str | None] = mapped_column(String(40))
    escalation_status: Mapped[str | None] = mapped_column(String(30))  # pending_escalation | created | not_needed
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime)
    urgent: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class WorkingCalendarVersion(Base):
    __tablename__ = "uae_working_calendar_versions"
    __table_args__ = (UniqueConstraint("calendar_id", "effective_year", "version", name="uq_calendar_version"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    calendar_id: Mapped[str] = mapped_column(String(40), default="uae_working_calendar")
    effective_year: Mapped[int] = mapped_column(Integer)
    version: Mapped[str] = mapped_column(String(20))
    source_ref: Mapped[str] = mapped_column(String(255))
    version_date: Mapped[date] = mapped_column(Date)
    updated_by: Mapped[str] = mapped_column(String(120))
    is_current: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class WorkingCalendarHoliday(Base):
    __tablename__ = "uae_working_calendar"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    calendar_id: Mapped[str] = mapped_column(String(40), default="uae_working_calendar")
    effective_year: Mapped[int] = mapped_column(Integer, index=True)
    version: Mapped[str] = mapped_column(String(20))
    holiday_date: Mapped[date] = mapped_column(Date, index=True)
    name_en: Mapped[str] = mapped_column(String(80))
    name_ar: Mapped[str] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(String(20), default="provisional")  # confirmed | provisional
    source_ref: Mapped[str | None] = mapped_column(String(255))
    weight: Mapped[float] = mapped_column(Float, default=1.0)
