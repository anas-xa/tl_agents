"""Escalation service (E8-S1..S3): triggers, cases, specialist handling with consent, corpus Q&A refusal.

Pure functions over a Session; no HTTP objects. Every decision is rule-based: no confidence score exists.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import Conflict, Forbidden, NotFound, SwitchedOff, ValidationFailed
from app.core.ids import new_id
from app.core.time import dubai_today, utcnow
from app.modules.audit.service import AuditWriteError, record_event
from app.modules.config.service import get_config, get_rule
from app.modules.escalation import corpus as corpus_mod
from app.modules.escalation.calendar import calendar_version_label, working_days_between
from app.modules.escalation.models import (
    CLOSED_STATUSES,
    FLAG_MANUAL_REVIEW,
    MODULES,
    PAUSE_REASONS,
    REASON_CODES,
    REJECT_CODES,
    RESOLUTION_OUTCOMES,
    AnswerRecord,
    CaseAccessGrant,
    CaseAccessLog,
    CaseEvent,
    CasePause,
    CorpusPassage,
    EscalationCase,
    OpsAlert,
    SpecialistEntitlement,
    WorkItem,
)
from app.modules.escalation.strings import bilingual

RULE_SET_ID = "trigger_rule_set"
MATTER_KEY_RULES_ID = "matter_key_rules_v1"
QUEUE_FOR_MODULE = {"tax": "tax_specialist", "audit": "licensed_auditor", "compliance": "det_compliance", "legal": "legal_queue", "other": "escalation_ops"}
SPECIALIST_TYPE_FOR_MODULE = {"tax": "tax", "audit": "auditor", "compliance": "compliance", "legal": "lawyer", "other": "compliance"}
ROLE_LABEL_FOR_TYPE = {"tax": "Tax specialist lead", "auditor": "Licensed auditor firm", "lawyer": "Licensed lawyer route", "compliance": "DET compliance"}
STAFF_ROLE_FOR_TYPE = {"tax": "tax_specialist", "auditor": "licensed_auditor", "lawyer": "legal_specialist", "compliance": "det_compliance_lead"}
RULE_REASON = {"user_raised": "user_requested", "audit_required": "audit_signoff_required", "sign_off_needed": "audit_signoff_required", "filing_blocked": "data_conflict", "deadline_risk": "deadline_risk", "legal_type_request": "legal_matter", "quarantine": "quarantine_review"}


class RuleSetUnavailable(RuntimeError):
    """The versioned trigger rule set could not be loaded: every output fails closed (held, 'not checked')."""


class CaseSetupPending(RuntimeError):
    """Read-back after write failed after the configured retries; the owner sees the neutral setup state."""


# --- helpers ------------------------------------------------------------------------------------


def _log(db: Session, case: EscalationCase | None, event_type: str, *, actor_key: str | None = None, actor_role: str | None = None, reason_code: str | None = None, rule_version: str | None = None, details: dict | None = None, occurred_at: datetime | None = None, category: str = "escalation", outcome: str = "success", fail_closed: bool = False) -> None:
    occurred_at = occurred_at or utcnow()
    if case is not None:
        db.add(CaseEvent(escalation_id=case.case_id, event_type=event_type, occurred_at=occurred_at, actor_key=actor_key, actor_role=actor_role, reason_code=reason_code, rule_version=rule_version or (case.trigger_rule_version if case else None), details=details or {}))
    record_event(db, event_type=event_type.upper(), category=category, outcome=outcome, reason_code=reason_code, actor_key=actor_key, actor_role=actor_role, company_id=case.company_id if case else None, subject_type="escalation_case" if case else None, subject_id=case.case_id if case else None, details={**(details or {}), **({"rule_version": rule_version or case.trigger_rule_version} if case else {})}, occurred_at=occurred_at, fail_closed=fail_closed)


def raise_ops_alert(db: Session, alert_type: str, *, case_id: str | None = None, details: dict | None = None) -> OpsAlert:
    alert = OpsAlert(alert_type=alert_type, case_id=case_id, recipients=["escalation_ops"], details=details or {})
    db.add(alert)
    record_event(db, event_type="OPS_ALERT_RAISED", category="escalation", reason_code=alert_type, subject_type="ops_alert", subject_id=alert.id, details={"case_id": case_id, **(details or {})})
    db.flush()
    return alert


def escalate_stale_alerts(db: Session, now: datetime | None = None) -> int:
    """After the ops alert window (config, to be confirmed) an unacknowledged alert goes to the DET pilot manager queue."""
    now = now or utcnow()
    hours = int(get_config(db, "ops_alert.escalation_window_hours", 24))
    n = 0
    for a in db.scalars(select(OpsAlert).where(OpsAlert.acknowledged_at.is_(None), OpsAlert.escalated_to_pilot_manager_at.is_(None))):
        if a.created_at + timedelta(hours=hours) <= now:
            a.escalated_to_pilot_manager_at = now
            a.recipients = sorted(set(a.recipients or []) | {"det_pilot_manager"})
            record_event(db, event_type="OPS_ALERT_ESCALATED", category="escalation", reason_code=a.alert_type, subject_type="ops_alert", subject_id=a.id, details={"to": "det_pilot_manager", "window_hours": hours})
            n += 1
    db.flush()
    return n


def get_case(db: Session, case_id: str) -> EscalationCase:
    case = db.get(EscalationCase, case_id)
    if case is None:
        raise NotFound("case not found", reason_code="CASE_NOT_FOUND")
    return case


def _add_flag(case: EscalationCase, flag: str) -> None:
    flags = list(case.flags or [])
    if flag not in flags:
        flags.append(flag)
    case.flags = flags


# --- rule set and matter keys (E8-S1) ----------------------------------------------------------


def load_rule_set(db: Session) -> dict:
    """Load the versioned trigger rule set from the rule register; raise RuleSetUnavailable on failure."""
    try:
        row = get_rule(db, RULE_SET_ID)
    except NotFound as exc:
        raise RuleSetUnavailable("trigger rule set not found") from exc
    params = dict(row.parameters or {})
    if not params.get("rules"):
        raise RuleSetUnavailable("trigger rule set has no rules")
    return {"version": row.version, "rules": params["rules"], "status": row.status}


def build_matter_key(db: Session, source: str, facts: dict) -> tuple[str, bool, str]:
    """(matter_key, complete, rule_version) per matter_key_rules_v1: fixed concatenation per source.
    Free text is never hashed or matched. Missing field → 'unkeyed:' + event id (flag manual review)."""
    try:
        rules = dict(get_rule(db, MATTER_KEY_RULES_ID).parameters or {})
        version = get_rule(db, MATTER_KEY_RULES_ID).version
    except NotFound:
        rules, version = DEFAULT_MATTER_KEY_RULES, "v1"
    fields = rules.get(source) or rules.get("user_question")
    if source == "user_question":
        linked = facts.get("linked_item_id")
        topic = facts.get("topic_code")
        if linked:
            return f"item:{linked}", True, version
        if topic:
            return f"topic:{topic}", True, version
        return f"unkeyed:{facts.get('event_id')}", False, version
    parts = [facts.get(f) for f in fields]
    if any(p in (None, "") for p in parts):
        return f"unkeyed:{facts.get('event_id')}", False, version
    return "|".join(str(p) for p in parts), True, version


DEFAULT_MATTER_KEY_RULES = {
    "agent_output": ["return_type", "tax_period", "rule_id"],
    "audit_exception": ["audit_file_id", "rule_id", "period"],
    "compliance_item": ["licence_number", "requirement_code", "due_period"],
    "user_question": ["linked_item_id", "topic_code"],
}


def _deadline_near(db: Session, due: date | None, today: date | None = None) -> str:
    if due is None:
        return "standard"
    days = int(get_config(db, "priority.deadline_near.days", 14))
    today = today or dubai_today()
    return "deadline_near" if (due - today).days <= days else "standard"


def evaluate_triggers(db: Session, company_id: str, facts: dict) -> dict:
    """Evaluate the versioned rule set against deterministic facts. Returns the decision and any case opened.

    ``facts`` keys (all optional): event_id, source, user_raised (bool), module, linked_item_id, topic_code,
    audit_required_flag, revenue_fils, tax_group, qfzp, audit_flag_input_missing, signoff_required,
    audit_file_id, period, rule_id, filing_blocked, return_type, tax_period, deadline_type (vat|corporate_tax|
    licence), due_date (ISO), preparation_complete, licence_number, requirement_code, legal_type_request,
    quarantine (bool), conflict_flags (list), actor_key, actor_role, opened_by (user|delegate|agent), title, due_date.
    Fail-closed: if the rule set cannot load every output is held ('not checked') and a manual-review case opens
    for the owning specialist; licence issuance and renewal are never blocked.
    """
    event_id = facts.get("event_id") or new_id("ev")
    facts = {**facts, "event_id": event_id}
    try:
        rule_set = load_rule_set(db)
    except RuleSetUnavailable as exc:
        record_event(db, event_type="RULE_SET_LOAD_FAILED", category="escalation", outcome="failed", reason_code="RULE_SET_UNAVAILABLE", company_id=company_id, details={"event_id": event_id})
        record_event(db, event_type="OUTPUT_HELD_NOT_CHECKED", category="escalation", outcome="held", reason_code="RULE_SET_UNAVAILABLE", company_id=company_id, details={"event_id": event_id})
        raise_ops_alert(db, "rule_set_load_failure", details={"event_id": event_id, "company_id": company_id})
        module = facts.get("module") if facts.get("module") in MODULES else "tax"
        case = open_case(db, company_id=company_id, module=module, reason_code="rule_set_unavailable", matter_key=f"unkeyed:{event_id}", event_id=event_id, opened_by="agent", trigger_source="rule_set_failure", trigger_rule_id="fail_closed", trigger_rule_version="unavailable", flags=[FLAG_MANUAL_REVIEW, "not_checked"], details={"error": str(exc)[:80]})
        return {"decision": "held_not_checked", "rule_version": None, "case_id": case.case_id, "message": bilingual("held_for_review"), "licence_flows_blocked": False}
    version = rule_set["version"]
    params = {r["id"]: r for r in rule_set["rules"]}
    fired: list[tuple[str, str, str, bool]] = []  # (rule_id, module, source, complete-key?)
    conflict_flags = list(facts.get("conflict_flags") or [])
    if facts.get("user_raised") and params.get("user_raised", {}).get("enabled", True):
        fired.append(("user_raised", facts.get("module") or "tax", "user_raised"))
    p = params.get("audit_required", {})
    if p.get("enabled", True):
        threshold = int(get_config(db, "trigger.audit_required.revenue_threshold_fils", p.get("revenue_threshold_fils", 50_000_000 * 100)))
        if facts.get("audit_required_flag") or facts.get("tax_group") or facts.get("qfzp") or facts.get("audit_flag_input_missing") or (facts.get("revenue_fils") is not None and int(facts["revenue_fils"]) > threshold):
            fired.append(("audit_required", "audit", "audit_exception"))
    if facts.get("signoff_required") and params.get("sign_off_needed", {}).get("enabled", True):
        fired.append(("sign_off_needed", "audit", "audit_exception"))
    if (facts.get("filing_blocked") or conflict_flags) and params.get("filing_blocked", {}).get("enabled", True):
        fired.append(("filing_blocked", "tax", "agent_output"))
    p = params.get("deadline_risk", {})
    if p.get("enabled", True) and facts.get("deadline_type") and facts.get("due_date") and not facts.get("preparation_complete", False):
        kind = facts["deadline_type"]
        days = int(get_config(db, f"trigger.deadline_risk.days.{kind}", p.get("days", {}).get(kind, 30)))
        due = date.fromisoformat(str(facts["due_date"]))
        if (due - dubai_today()).days <= days:
            fired.append(("deadline_risk", "compliance", "compliance_item"))
    if facts.get("legal_type_request") and params.get("legal_type_request", {}).get("enabled", True):
        fired.append(("legal_type_request", "legal", "user_question"))
    if facts.get("quarantine") and params.get("quarantine", {}).get("enabled", True):
        fired.append(("quarantine", "other", "quarantine"))
    record_event(db, event_type="TRIGGER_EVALUATED", category="escalation", company_id=company_id, actor_key=facts.get("actor_key"), details={"event_id": event_id, "rule_version": version, "fired": [f[0] for f in fired]})
    cases = []
    for rule_id, module, source in fired:
        key_source = "user_question" if source in ("user_raised", "user_question") else source
        matter_key, complete, mk_version = build_matter_key(db, key_source, {**facts, "rule_id": rule_id})
        due = date.fromisoformat(str(facts["due_date"])) if facts.get("due_date") else None
        case = open_case(db, company_id=company_id, module=module, reason_code=RULE_REASON[rule_id], matter_key=matter_key, event_id=event_id, opened_by=facts.get("opened_by") or ("agent" if source not in ("user_raised",) else "user"), trigger_source=source, trigger_rule_id=rule_id, trigger_rule_version=version, matter_key_rule_version=mk_version, flags=[] if complete else [FLAG_MANUAL_REVIEW], title=None if module == "legal" else facts.get("title"), linked_item_id=facts.get("linked_item_id"), topic_code=facts.get("topic_code"), due_date=due, opened_by_key=facts.get("actor_key"), work_item_id=facts.get("work_item_id"), period_ref=facts.get("tax_period") or facts.get("period") or facts.get("due_period"))
        cases.append(case.case_id)
    return {"decision": "escalate" if fired else "no_trigger", "rule_version": version, "fired": [f[0] for f in fired], "case_ids": cases, "case_id": cases[0] if cases else None, "licence_flows_blocked": False}


# --- case creation (E8-S1) -----------------------------------------------------------------------


def _ensure_work_item(db: Session, case: EscalationCase, period_ref: str | None) -> WorkItem:
    wi = WorkItem(company_id=case.company_id, module=case.module, case_type=case.case_type, period_ref=period_ref, opened_by=case.opened_by, case_opened_at=case.opened_at, calendar_version=case.calendar_version, is_demo=case.is_demo)
    db.add(wi)
    db.flush()
    return wi


def _read_back(db: Session, case_id: str, idempotency_key: str) -> bool:
    db.flush()
    row = db.get(EscalationCase, case_id)
    return row is not None and row.idempotency_key == idempotency_key


def _queue_has_specialist(db: Session, specialist_type: str) -> bool:
    today = dubai_today()
    rows = db.scalars(select(SpecialistEntitlement).where(SpecialistEntitlement.specialist_type == specialist_type, SpecialistEntitlement.is_current.is_(True), SpecialistEntitlement.status == "active"))
    return any(r.valid_to is None or r.valid_to >= today for r in rows)


def open_case(
    db: Session,
    *,
    company_id: str,
    module: str,
    reason_code: str,
    matter_key: str,
    event_id: str,
    opened_by: str,
    priority: str | None = None,
    details: dict | None = None,
    trigger_source: str = "agent_output",
    trigger_rule_id: str = "external",
    trigger_rule_version: str | None = None,
    matter_key_rule_version: str = "v1",
    flags: list[str] | None = None,
    title: str | None = None,
    linked_item_id: str | None = None,
    topic_code: str | None = None,
    due_date: date | None = None,
    opened_by_key: str | None = None,
    work_item_id: str | None = None,
    period_ref: str | None = None,
    occurred_at: datetime | None = None,
    is_demo: bool = False,
) -> EscalationCase:
    """Open (or attach to) an escalation case. Public entry point for other modules.

    Idempotency key = company + module + matter key + event id: the same event id never creates a second
    case. Strict duplicate detection on company + module + matter key among OPEN cases attaches the new
    event. The same key on a resolved/closed case opens a NEW case linked to the earlier one (never reopened).
    Unkeyed matters ('unkeyed:'+event id) never merge and carry 'manual review: key incomplete'.
    """
    if module not in MODULES:
        raise ValidationFailed("unknown module", reason_code="MODULE_INVALID")
    if reason_code not in REASON_CODES:
        reason_code = "unclassified"
    if trigger_rule_version is None:
        try:
            trigger_rule_version = load_rule_set(db)["version"]
        except RuleSetUnavailable:
            trigger_rule_version = "unavailable"
    now = occurred_at or utcnow()
    idem = f"{company_id}|{module}|{matter_key}|{event_id}"
    existing = db.scalar(select(EscalationCase).where(EscalationCase.idempotency_key == idem))
    if existing is not None:
        record_event(db, event_type="CASE_EVENT_REPLAYED", category="escalation", outcome="ignored", company_id=company_id, subject_type="escalation_case", subject_id=existing.case_id, details={"event_id": event_id, "rule_version": trigger_rule_version})
        return existing
    unkeyed = matter_key.startswith("unkeyed:")
    flags = list(flags or [])
    if unkeyed and FLAG_MANUAL_REVIEW not in flags:
        flags.append(FLAG_MANUAL_REVIEW)
    if not unkeyed:
        open_match = db.scalar(select(EscalationCase).where(EscalationCase.company_id == company_id, EscalationCase.module == module, EscalationCase.matter_key == matter_key, EscalationCase.status.not_in(CLOSED_STATUSES)).order_by(EscalationCase.opened_at))
        if open_match is not None:
            return attach_event(db, open_match, event_id=event_id, rule_version=trigger_rule_version, details=details, severity=(details or {}).get("severity"), required_action=(details or {}).get("required_action"), occurred_at=now)
    linked = None
    if not unkeyed:
        linked = db.scalar(select(EscalationCase).where(EscalationCase.company_id == company_id, EscalationCase.module == module, EscalationCase.matter_key == matter_key, EscalationCase.status.in_(CLOSED_STATUSES)).order_by(EscalationCase.opened_at.desc()))
    specialist_type = SPECIALIST_TYPE_FOR_MODULE[module]
    case = EscalationCase(
        company_id=company_id, work_item_id=work_item_id, module=module, case_type=module, matter_key=matter_key, matter_key_rule_version=matter_key_rule_version,
        trigger_rule_id=trigger_rule_id, trigger_rule_version=trigger_rule_version, trigger_event_id=event_id, idempotency_key=idem, trigger_source=trigger_source,
        escalation_reason=reason_code, status="open", flags=flags, priority=priority or _deadline_near(db, due_date, now.date()), queue=QUEUE_FOR_MODULE[module], specialist_type=specialist_type,
        linked_case_id=linked.case_id if linked else None, opened_by=opened_by, opened_by_key=opened_by_key, title=None if module == "legal" else title, linked_item_id=linked_item_id,
        topic_code=topic_code, due_date=due_date, opened_at=now, escalated_at=now, calendar_version=calendar_version_label(db), is_demo=is_demo, details={k: v for k, v in (details or {}).items() if k not in ("free_text",)},
        legal_route_status="not_routed" if module == "legal" else None,
    )
    if module == "legal" and not get_config(db, "legal.lawyer_routing.enabled", False):
        case.queue = "legal_queue"
    db.add(case)
    db.flush()
    if work_item_id is None:
        case.work_item_id = _ensure_work_item(db, case, period_ref).id
    retries = int(get_config(db, "case.readback.retries", 3))
    ok = False
    for attempt in range(retries + 1):
        if _read_back(db, case.case_id, idem):
            ok = True
            break
        record_event(db, event_type="READBACK_RETRY", category="escalation", outcome="failed", company_id=company_id, subject_type="escalation_case", subject_id=case.case_id, details={"attempt": attempt + 1, "backoff_seconds": get_config(db, "case.readback.backoff_seconds", [5, 30, 120])})
    if not ok:
        record_event(db, event_type="READBACK_FAILED", category="escalation", outcome="failed", reason_code="CASE_SETUP_PENDING", company_id=company_id, subject_type="escalation_case", subject_id=case.case_id, details={"idempotency_key_hash": len(idem)})
        raise_ops_alert(db, "readback_failure", case_id=case.case_id)
        raise CaseSetupPending(case.case_id)
    _log(db, case, "case_created", actor_key=opened_by_key, actor_role=opened_by, reason_code=reason_code, details={"module": module, "trigger_rule_id": trigger_rule_id, "priority": case.priority, "queue": case.queue, "trigger_source": trigger_source}, occurred_at=now)
    _log(db, case, "escalated", actor_key=opened_by_key, reason_code=reason_code, details={"specialist_type": specialist_type}, occurred_at=now)
    if linked is not None:
        _log(db, case, "case_linked", details={"linked_case_id": linked.case_id}, occurred_at=now)
    if FLAG_MANUAL_REVIEW in flags:
        _log(db, case, "case_flagged_manual_review", reason_code="KEY_INCOMPLETE", occurred_at=now)
    if module != "legal":
        _log(db, case, "notification_sent", details={"to": "owner", "kind": "case_opened", "next_step_key": f"next_step.{module if module in ('tax', 'audit', 'compliance') else 'compliance'}"}, category="reminder", occurred_at=now)
    if module in ("tax", "audit", "legal") and not _queue_has_specialist(db, specialist_type):
        if module == "legal" and not get_config(db, "legal.lawyer_routing.enabled", False):
            pass  # legal queue has no route holder by design in Phase 1; no queue-empty alert
        else:
            raise_ops_alert(db, "queue_empty", case_id=case.case_id, details={"queue": case.queue})
    db.flush()
    return case


def attach_event(db: Session, case: EscalationCase, *, event_id: str, rule_version: str | None, details: dict | None = None, severity: str | None = None, required_action: str | None = None, occurred_at: datetime | None = None) -> EscalationCase:
    """A new event id with the same open key attaches to the case (logged with rule version, shown as activity).
    The owner is re-notified only when severity or required action changes."""
    now = occurred_at or utcnow()
    _log(db, case, "event_attached", rule_version=rule_version, details={"event_id": event_id, **{k: v for k, v in (details or {}).items() if k in ("source", "rule_id")}}, occurred_at=now)
    changed = False
    if severity and severity != case.severity:
        case.severity, changed = severity, True
    if required_action and required_action != case.required_action:
        case.required_action, changed = required_action, True
    if changed:
        _log(db, case, "notification_sent", details={"to": "owner", "kind": "case_changed"}, category="reminder", occurred_at=now)
    db.flush()
    return case


# --- pauses (K22 clock) --------------------------------------------------------------------------


def start_pause(db: Session, case: EscalationCase, reason: str, *, at: datetime | None = None) -> None:
    if reason not in PAUSE_REASONS:
        raise ValidationFailed("unknown pause reason", reason_code="PAUSE_REASON_INVALID")
    if db.scalar(select(CasePause).where(CasePause.case_id == case.case_id, CasePause.ended_at.is_(None))):
        return
    at = at or utcnow()
    db.add(CasePause(case_id=case.case_id, reason_code=reason, started_at=at))
    _log(db, case, "pause", reason_code=reason, occurred_at=at)


def end_pause(db: Session, case: EscalationCase, *, at: datetime | None = None, reason: str | None = None) -> None:
    at = at or utcnow()
    for p in db.scalars(select(CasePause).where(CasePause.case_id == case.case_id, CasePause.ended_at.is_(None))):
        p.ended_at = at
        _log(db, case, "resume", reason_code=reason or p.reason_code, occurred_at=at)


def paused_working_days(db: Session, case: EscalationCase, until: datetime | None = None) -> float:
    until = until or utcnow()
    total = 0.0
    for p in db.scalars(select(CasePause).where(CasePause.case_id == case.case_id)):
        total += working_days_between(db, p.started_at, p.ended_at or until)
    return round(total, 1)


def turnaround(db: Session, case: EscalationCase) -> dict:
    """K22 split: active handling time (pauses excluded) beside raw elapsed, in working days (one decimal)."""
    end = case.resolved_at or case.closed_at or utcnow()
    raw = working_days_between(db, case.escalated_at, end)
    paused = paused_working_days(db, case, end)
    return {"raw_working_days": raw, "paused_working_days": paused, "active_working_days": round(max(raw - paused, 0.0), 1), "calendar_days": round((end - case.escalated_at).total_seconds() / 86400, 1), "paused_now": db.scalar(select(CasePause).where(CasePause.case_id == case.case_id, CasePause.ended_at.is_(None))) is not None}


# --- owner side (E8-S1/E8-S2) --------------------------------------------------------------------


def owner_status(case: EscalationCase) -> str:
    if case.status == "open" and case.assigned_to:
        return "with_specialist"
    if case.status == "awaiting_specialist_assignment":
        return "open"
    if case.status == "closed_no_consent":
        return "closed"
    return case.status


def handler_type(case: EscalationCase) -> str:
    """'licensed_human' once a named, entitled human owns it; otherwise 'ai_draft' (AI prepared, not human approved)."""
    return "licensed_human" if case.assigned_to else "ai_draft"


def _is_owner_level(principal, company_id: str) -> bool:
    return any(r.role in ("owner", "remote_owner") for r in principal.roles_for(company_id))


def _actor_role(principal, company_id: str) -> str:
    roles = principal.roles_for(company_id)
    return roles[0].role if roles else principal.primary_role()


def list_company_cases(db: Session, company_id: str) -> list[EscalationCase]:
    return list(db.scalars(select(EscalationCase).where(EscalationCase.company_id == company_id, EscalationCase.kpi_only.is_(False)).order_by(EscalationCase.opened_at.desc())))


def open_user_case(db: Session, principal, company_id: str, *, module: str, title: str | None, linked_item_id: str | None, topic_code: str | None, due_date: date | None = None, kind: str = "ask_a_human") -> EscalationCase:
    """'Ask a human' (rule 1) is always available to owners and delegates; a legal-type request opens the
    neutral-state case (no routing, no stored question text)."""
    if module not in ("tax", "audit", "compliance", "legal"):
        raise ValidationFailed("module must be tax, audit, compliance or legal", reason_code="MODULE_INVALID")
    role = _actor_role(principal, company_id)
    facts = {"module": module, "user_raised": module != "legal", "legal_type_request": module == "legal", "linked_item_id": linked_item_id, "topic_code": topic_code, "title": title, "actor_key": principal.actor_key, "actor_role": role, "opened_by": "delegate" if role == "delegate" else "user", "due_date": due_date.isoformat() if due_date else None}
    result = evaluate_triggers(db, company_id, facts)
    if not result.get("case_id"):
        raise Conflict("no case was opened", reason_code="NO_TRIGGER")
    return get_case(db, result["case_id"])


def reject_case(db: Session, principal, case: EscalationCase, *, reason_code: str, note: str | None) -> EscalationCase:
    if not _is_owner_level(principal, case.company_id):
        record_event(db, event_type="CASE_REJECT_REFUSED", category="escalation", outcome="refused", reason_code="ONLY_OWNER_CAN_REJECT", actor_key=principal.actor_key, actor_role=_actor_role(principal, case.company_id), company_id=case.company_id, subject_type="escalation_case", subject_id=case.case_id)
        raise Forbidden("Only the owner can reject a case.", reason_code="ONLY_OWNER_CAN_REJECT")
    if reason_code not in REJECT_CODES:
        raise ValidationFailed("Choose a reason to continue.", reason_code="REJECT_REASON_REQUIRED", details={"field": "reason_code"})
    max_chars = int(get_config(db, "reject.note.max_chars", 300))
    if note and len(note) > max_chars:
        raise ValidationFailed("note too long", reason_code="REJECT_NOTE_TOO_LONG", details={"max_chars": max_chars})
    if reason_code == "R5" and not (note or "").strip():
        raise ValidationFailed("a note is required for 'Other'", reason_code="REJECT_NOTE_REQUIRED", details={"field": "note"})
    if case.status in CLOSED_STATUSES:
        raise Conflict("case is closed", reason_code="CASE_CLOSED")
    now = utcnow()
    end_pause(db, case, at=now)
    case.status = "rejected"
    case.reject_reason_code, case.reject_note, case.rejected_by_key, case.rejected_at = reason_code, (note or None), principal.actor_key, now
    case.closed_at = now
    for g in db.scalars(select(CaseAccessGrant).where(CaseAccessGrant.case_id == case.case_id, CaseAccessGrant.status == "active")):
        g.status, g.revoked_at = "revoked", now
    _log(db, case, "case_rejected", actor_key=principal.actor_key, actor_role=_actor_role(principal, case.company_id), reason_code=reason_code, details={"note_present": bool(note)}, occurred_at=now)
    db.flush()
    return case


def reopen_case(db: Session, principal, case: EscalationCase) -> EscalationCase:
    """A case closed for no consent reopens within the window with the same reference; a rejected/resolved case
    is never reopened - a new linked case is opened instead."""
    now = utcnow()
    if case.status == "closed_no_consent":
        window = int(get_config(db, "consent_wait.reopen_window", 30))
        if case.reopen_until and now.date() > case.reopen_until:
            raise Conflict("the reopen window has passed; open a new case", reason_code="REOPEN_WINDOW_PASSED", details={"window_days": window})
        case.status = "awaiting_consent"
        case.closed_at, case.resolution_outcome, case.consent_requested_at, case.consent_decision = None, None, now, None
        start_pause(db, case, "awaiting_owner_consent", at=now)
        _log(db, case, "case_reopened", actor_key=principal.actor_key, actor_role=_actor_role(principal, case.company_id), occurred_at=now)
        db.flush()
        return case
    if case.status in CLOSED_STATUSES:
        return open_case(db, company_id=case.company_id, module=case.module, reason_code=case.escalation_reason, matter_key=case.matter_key if not case.matter_key.startswith("unkeyed:") else f"unkeyed:{new_id('ev')}", event_id=new_id("ev"), opened_by="user", trigger_source="user_raised", trigger_rule_id="user_raised", title=case.title, linked_item_id=case.linked_item_id, topic_code=case.topic_code, due_date=case.due_date, opened_by_key=principal.actor_key)
    raise Conflict("case is not closed", reason_code="CASE_NOT_CLOSED")


def submit_owner_answer(db: Session, principal, case: EscalationCase, *, answer_ref: str | None, document_refs: list[str] | None) -> EscalationCase:
    """Owner supplies information/documents: ends the 'awaiting owner information' pause. References only."""
    if case.status in CLOSED_STATUSES:
        raise Conflict("case is closed", reason_code="CASE_CLOSED")
    now = utcnow()
    end_pause(db, case, at=now, reason="awaiting_owner_information")
    case.required_action = None
    _log(db, case, "owner_information_received", actor_key=principal.actor_key, actor_role=_actor_role(principal, case.company_id), details={"answer_ref": answer_ref, "documents": len(document_refs or [])}, occurred_at=now)
    db.flush()
    return case


# --- consent and access grants (E8-S2) -----------------------------------------------------------


def request_consent(db: Session, case: EscalationCase, *, scope: list[dict], purpose: str, actor_key: str | None = None, at: datetime | None = None) -> EscalationCase:
    at = at or utcnow()
    case.status = "awaiting_consent"
    case.consent_requested_at = at
    case.consent_decision = None
    case.details = {**(case.details or {}), "requested_scope": scope, "purpose": purpose}
    start_pause(db, case, "awaiting_owner_consent", at=at)
    _log(db, case, "consent_requested", actor_key=actor_key, actor_role="specialist", details={"scope_items": len(scope)}, category="consent", occurred_at=at)
    _log(db, case, "notification_sent", details={"to": "owner", "kind": "consent_needed"}, category="reminder", occurred_at=at)
    db.flush()
    return case


def _external_consent_ok(db: Session, company_id: str, item: str, *, module: str, purpose: str, recipient: str | None) -> bool | None:
    """Consult the consent module's gate when present (case-specific type 'evidence_access', scope
    {source, data_type, purpose}); its ``GateDecision.allowed`` wins when true. None when the module is absent;
    any error or an unavailable gate counts as 'not allowed' (fail closed) and the Phase 1 case grant applies."""
    try:
        from app.modules.consent.service import check_consent  # type: ignore[import-not-found]
    except ImportError:
        return None
    try:
        decision = check_consent(db, company_id, "evidence_access", {"source": module, "data_type": item, "purpose": purpose}, recipient=recipient)
    except Exception:
        return False
    return bool(getattr(decision, "allowed", False))


def grant_case_access(db: Session, principal, case: EscalationCase, *, scope: list[dict], purpose: str, expiry_days: int | None = None) -> CaseAccessGrant:
    """Per-case access grant: created by the owner/authorised signatory only (delegate only with the delegated
    consent right, which is switched off in the pilot). Revocable; expiry from config (default 90 days)."""
    if case.company_id != principal_company_guard(principal, case.company_id):
        raise Forbidden("company not available to you", reason_code="NOT_YOUR_COMPANY")
    if not _is_owner_level(principal, case.company_id):
        from app.modules.access.service import authorize

        authorize(db, principal, "consent.grant", company_id=case.company_id)  # delegate path: refused unless the right is on
    if case.status in CLOSED_STATUSES:
        raise Conflict("case is closed", reason_code="CASE_CLOSED")
    if not case.assigned_to:
        raise Conflict("no named specialist is assigned yet; nothing to grant", reason_code="NO_RECIPIENT")
    if not scope:
        raise ValidationFailed("scope must list at least one data item", reason_code="SCOPE_REQUIRED")
    days = int(expiry_days or get_config(db, "case_access.grant_expiry_days", 90))
    cap = int(get_config(db, "case_access.grant_expiry_days", 90))
    days = min(days, cap)
    now = utcnow()
    grant = CaseAccessGrant(case_id=case.case_id, company_id=case.company_id, recipient_uuid=case.assigned_to, purpose=purpose[:255], scope=scope, granted_by_key=principal.actor_key, granted_by_role=_actor_role(principal, case.company_id), granted_at=now, expires_at=now + timedelta(days=days))
    db.add(grant)
    case.consent_decision = "granted"
    if case.status == "awaiting_consent":
        case.status = "open"
    end_pause(db, case, at=now, reason="awaiting_owner_consent")
    _log(db, case, "consent_granted", actor_key=principal.actor_key, actor_role=grant.granted_by_role, details={"grant_id": grant.id, "scope_items": len(scope), "expires_at": grant.expires_at.isoformat(), "text_version": grant.text_version}, category="consent", occurred_at=now, fail_closed=True)
    db.flush()
    return grant


def principal_company_guard(principal, company_id: str) -> str:
    return company_id if principal.roles_for(company_id) else ""


def refuse_case_consent(db: Session, principal, case: EscalationCase) -> EscalationCase:
    """Owner refuses consent: specialists work only on supplied documents; outputs carry the limitation label."""
    if not _is_owner_level(principal, case.company_id):
        raise Forbidden("Only the owner can decide on consent.", reason_code="ONLY_OWNER_CAN_CONSENT")
    now = utcnow()
    case.consent_decision = "refused"
    case.resolution_limitation = True
    if case.status == "awaiting_consent":
        case.status = "open"
    end_pause(db, case, at=now, reason="awaiting_owner_consent")
    _log(db, case, "consent_refused", actor_key=principal.actor_key, actor_role=_actor_role(principal, case.company_id), category="consent", occurred_at=now)
    db.flush()
    return case


def revoke_case_access(db: Session, principal, case: EscalationCase) -> int:
    if not _is_owner_level(principal, case.company_id):
        from app.modules.access.service import authorize

        authorize(db, principal, "consent.withdraw", company_id=case.company_id)
    now = utcnow()
    n = 0
    for g in db.scalars(select(CaseAccessGrant).where(CaseAccessGrant.case_id == case.case_id, CaseAccessGrant.status == "active")):
        g.status, g.revoked_at = "revoked", now
        n += 1
    if n:
        case.consent_decision = "withdrawn"
        case.status = "awaiting_consent" if case.status not in CLOSED_STATUSES else case.status
        case.consent_requested_at = now
        start_pause(db, case, "awaiting_owner_consent", at=now)
        _log(db, case, "consent_withdrawn", actor_key=principal.actor_key, actor_role=_actor_role(principal, case.company_id), details={"withdrawn_at": now.isoformat(), "first_access_denied_at": None, "pulls_stopped_at": now.isoformat()}, category="consent", occurred_at=now, fail_closed=True)
    db.flush()
    return n


def active_grant(db: Session, case: EscalationCase, recipient_uuid: str, *, now: datetime | None = None) -> CaseAccessGrant | None:
    now = now or utcnow()
    for g in db.scalars(select(CaseAccessGrant).where(CaseAccessGrant.case_id == case.case_id, CaseAccessGrant.recipient_uuid == recipient_uuid, CaseAccessGrant.status == "active")):
        if g.expires_at <= now:
            g.status = "expired"
            continue
        return g
    return None


# --- entitlement register and specialist access (E8-S2) ------------------------------------------


def entitlement_for(db: Session, identity_uuid: str, specialist_type: str) -> SpecialistEntitlement | None:
    return db.scalar(select(SpecialistEntitlement).where(SpecialistEntitlement.identity_uuid == identity_uuid, SpecialistEntitlement.specialist_type == specialist_type, SpecialistEntitlement.is_current.is_(True)))


def check_entitlement(db: Session, identity_uuid: str, specialist_type: str, *, actor_key: str | None = None, case: EscalationCase | None = None) -> SpecialistEntitlement:
    """Fail closed: missing, expired, suspended or 'unclear' record blocks assignment and every access (logged)."""
    ent = entitlement_for(db, identity_uuid, specialist_type)
    today = dubai_today()
    problem = None
    if ent is None:
        problem = "ENTITLEMENT_MISSING"
    elif ent.status != "active":
        problem = f"ENTITLEMENT_{ent.status.upper()}"
    elif ent.valid_to and ent.valid_to < today:
        problem = "ENTITLEMENT_EXPIRED"
    elif specialist_type == "lawyer" and not ent.firm_agreement_signed:
        problem = "FIRM_AGREEMENT_MISSING"
    if specialist_type == "tax" and not get_config(db, "escalation.tax_specialist_path.enabled", False):
        problem = problem or "TAX_PATH_SWITCHED_OFF"
    if specialist_type == "lawyer" and not get_config(db, "escalation.lawyer_path.enabled", False):
        problem = problem or "LAWYER_PATH_SWITCHED_OFF"
    if problem:
        try:
            record_event(db, event_type="ENTITLEMENT_CHECK_FAILED", category="access", outcome="refused", reason_code=problem, actor_key=actor_key, actor_role=STAFF_ROLE_FOR_TYPE.get(specialist_type), company_id=case.company_id if case else None, subject_type="escalation_case" if case else "entitlement", subject_id=case.case_id if case else identity_uuid, details={"specialist_type": specialist_type}, fail_closed=True)
        except AuditWriteError as exc:
            raise Forbidden("audit unavailable; access refused", reason_code="AUDIT_UNAVAILABLE") from exc
        if case is not None:
            raise_ops_alert(db, "entitlement_lapsed", case_id=case.case_id, details={"reason": problem})
        if problem.endswith("SWITCHED_OFF"):
            raise SwitchedOff("this specialist path is switched off", reason_code=problem)
        raise Forbidden("entitlement record is not current; access refused", reason_code=problem)
    record_event(db, event_type="ENTITLEMENT_CHECKED", category="access", reason_code="OK", actor_key=actor_key, company_id=case.company_id if case else None, subject_type="entitlement", subject_id=ent.id, details={"specialist_type": specialist_type, "register": ent.register_used})
    return ent


def _assert_staff(db: Session, principal, *perms: str) -> set[str]:
    from app.modules.access.service import permissions_for

    have = permissions_for(db, principal, None)
    if not have & set(perms):
        record_event(db, event_type="ACCESS_REFUSED", category="access", outcome="refused", reason_code="NO_PERMISSION", actor_key=principal.actor_key, actor_role=principal.primary_role(), details={"permission": list(perms)})
        raise Forbidden("you do not have access to this action", reason_code="NO_PERMISSION", details={"permission": list(perms)})
    return have


def specialist_type_for(principal) -> str | None:
    for role, st in (("tax_specialist", "tax"), ("licensed_auditor", "auditor"), ("legal_specialist", "lawyer"), ("det_compliance_lead", "compliance")):
        if principal.has_staff(role):
            return st
    return None


def queue_for(db: Session, principal) -> dict:
    """Specialists see only their own queue; escalation operations and the pilot manager see metadata of every case."""
    have = _assert_staff(db, principal, "cases.queue.tax", "cases.queue.legal", "cases.queue.audit", "cases.assign", "cases.queue_fallback", "cases.view_assigned")
    ops = bool(have & {"cases.assign", "cases.queue_fallback"})
    st = specialist_type_for(principal)
    stmt = select(EscalationCase).where(EscalationCase.kpi_only.is_(False)).order_by(EscalationCase.priority.desc(), EscalationCase.escalated_at)
    rows = list(db.scalars(stmt))
    if ops:
        mine = [c for c in rows if c.status not in CLOSED_STATUSES or (c.closed_at and c.closed_at > utcnow() - timedelta(days=30))]
        alerts = list(db.scalars(select(OpsAlert).where(OpsAlert.acknowledged_at.is_(None)).order_by(OpsAlert.created_at.desc())))
        record_event(db, event_type="CASE_METADATA_VIEWED", category="data_access", actor_key=principal.actor_key, actor_role=principal.primary_role(), details={"count": len(mine), "scope": "queue"})
        return {"mode": "ops", "cases": [case_metadata(db, c) for c in mine], "alerts": [{"id": a.id, "type": a.alert_type, "case_id": a.case_id, "created_at": a.created_at.isoformat(), "recipients": a.recipients, "escalated_to_pilot_manager": a.escalated_to_pilot_manager_at is not None} for a in alerts]}
    if st is None:
        return {"mode": "specialist", "cases": [], "unassigned": []}
    own = [c for c in rows if c.assigned_to == principal.identity_uuid]
    unassigned = [c for c in rows if c.assigned_to is None and c.specialist_type == st and c.status not in CLOSED_STATUSES and c.module != "legal"]
    record_event(db, event_type="CASE_QUEUE_VIEWED", category="data_access", actor_key=principal.actor_key, actor_role=principal.primary_role(), details={"own": len(own), "unassigned": len(unassigned)})
    return {"mode": "specialist", "specialist_type": st, "cases": [case_metadata(db, c) for c in own], "unassigned": [case_metadata(db, c) for c in unassigned]}


def case_metadata(db: Session, case: EscalationCase) -> dict:
    """Metadata only: case id, module, priority, status, timestamps, coded reason. No content, no figures."""
    return {
        "case_id": case.case_id, "module": case.module, "priority": case.priority, "status": case.status, "escalation_reason": case.escalation_reason, "queue": case.queue,
        "specialist_type": case.specialist_type, "assigned": case.assigned_to is not None, "assigned_role_label": case.assigned_role_label, "flags": case.flags or [],
        "opened_at": case.opened_at.isoformat(), "escalated_at": case.escalated_at.isoformat(), "accepted_at": case.accepted_at.isoformat() if case.accepted_at else None,
        "first_response_at": case.first_response_at.isoformat() if case.first_response_at else None, "resolved_at": case.resolved_at.isoformat() if case.resolved_at else None,
        "closed_at": case.closed_at.isoformat() if case.closed_at else None, "consent_decision": case.consent_decision, "consent_requested_at": case.consent_requested_at.isoformat() if case.consent_requested_at else None,
        "due_date": case.due_date.isoformat() if case.due_date else None, "linked_case_id": case.linked_case_id, "legal_route_status": case.legal_route_status, "turnaround": turnaround(db, case), "is_demo": case.is_demo,
    }


def pre_consent_summary(db: Session, principal, case: EscalationCase) -> dict:
    """Fixed fields, nothing else: reference, type, coded reason, deadline, priority, company reference, owner's title."""
    record_event(db, event_type="CASE_SUMMARY_VIEWED", category="data_access", actor_key=principal.actor_key, actor_role=principal.primary_role(), company_id=case.company_id, subject_type="escalation_case", subject_id=case.case_id, details={"pre_consent": True})
    return {"case_id": case.case_id, "case_type": case.case_type, "escalation_reason": case.escalation_reason, "deadline": case.due_date.isoformat() if case.due_date else None, "priority": case.priority, "company_ref": case.company_id, "title": case.title, "ai_label": bilingual("ai_label"), "status": case.status, "consent_decision": case.consent_decision, "locked_items": [{"item": s.get("data_class", "item"), "locked": True, "cause": "absent" if case.consent_decision is None else case.consent_decision} for s in (case.details or {}).get("requested_scope", [])]}


def assign_case(db: Session, principal, case: EscalationCase, *, assignee_uuid: str) -> EscalationCase:
    """Escalation operations (or the DET pilot manager fallback) assigns/reassigns; entitlement checked first."""
    _assert_staff(db, principal, "cases.assign", "cases.queue_fallback")
    if case.status in CLOSED_STATUSES:
        raise Conflict("case is closed", reason_code="CASE_CLOSED")
    if case.module == "legal" and not get_config(db, "legal.lawyer_routing.enabled", False):
        raise SwitchedOff("lawyer routing is switched off until the legal service model is agreed", reason_code="LAWYER_ROUTING_OFF")
    ent = check_entitlement(db, assignee_uuid, case.specialist_type, actor_key=principal.actor_key, case=case)
    now = utcnow()
    previous = case.assigned_to
    if previous and previous != assignee_uuid:
        for g in db.scalars(select(CaseAccessGrant).where(CaseAccessGrant.case_id == case.case_id, CaseAccessGrant.recipient_uuid == previous, CaseAccessGrant.status == "active")):
            g.status, g.revoked_at = "revoked", now  # consent never transfers
        case.consent_decision = None
        _log(db, case, "notification_sent", details={"to": "owner", "kind": "specialist_changed"}, category="reminder", occurred_at=now)
    case.assigned_to = assignee_uuid
    case.assigned_role_label = ROLE_LABEL_FOR_TYPE[case.specialist_type]
    if case.status == "awaiting_specialist_assignment":
        case.status = "open"
    _log(db, case, "assigned" if previous is None else "reassigned", actor_key=principal.actor_key, actor_role=principal.primary_role(), details={"entitlement_id": ent.id, "role_label": case.assigned_role_label, "reassignment": previous is not None}, occurred_at=now)
    db.flush()
    return case


def _require_assigned(db: Session, principal, case: EscalationCase) -> SpecialistEntitlement:
    _assert_staff(db, principal, "cases.work")
    ent = check_entitlement(db, principal.identity_uuid, case.specialist_type, actor_key=principal.actor_key, case=case)
    if case.assigned_to != principal.identity_uuid:
        record_event(db, event_type="CASE_ACCESS_REFUSED", category="access", outcome="refused", reason_code="NOT_ASSIGNED", actor_key=principal.actor_key, actor_role=principal.primary_role(), company_id=case.company_id, subject_type="escalation_case", subject_id=case.case_id)
        raise Forbidden("You no longer have access to this case.", reason_code="NOT_ASSIGNED")
    return ent


def accept_case(db: Session, principal, case: EscalationCase, *, requested_scope: list[dict] | None = None, purpose: str | None = None) -> EscalationCase:
    """Specialist accepts; may request case-specific consent for typed data items (starts the consent-wait clock)."""
    if case.assigned_to is None and specialist_type_for(principal) == case.specialist_type and case.module != "legal":
        _assert_staff(db, principal, "cases.work")
        check_entitlement(db, principal.identity_uuid, case.specialist_type, actor_key=principal.actor_key, case=case)
        case.assigned_to, case.assigned_role_label = principal.identity_uuid, ROLE_LABEL_FOR_TYPE[case.specialist_type]
        _log(db, case, "assigned", actor_key=principal.actor_key, actor_role=principal.primary_role(), details={"self_pick": True, "role_label": case.assigned_role_label})
    _require_assigned(db, principal, case)
    if case.status in CLOSED_STATUSES:
        raise Conflict("case is closed", reason_code="CASE_CLOSED")
    now = utcnow()
    case.accepted_at = case.accepted_at or now
    _log(db, case, "accepted", actor_key=principal.actor_key, actor_role=principal.primary_role(), occurred_at=now)
    if requested_scope:
        request_consent(db, case, scope=requested_scope, purpose=purpose or "case review", actor_key=principal.actor_key, at=now)
    db.flush()
    return case


def first_response(db: Session, principal, case: EscalationCase, *, note_ref: str | None = None) -> EscalationCase:
    _require_assigned(db, principal, case)
    now = utcnow()
    if case.first_response_at is None:
        case.first_response_at = now
    _log(db, case, "first_response", actor_key=principal.actor_key, actor_role=principal.primary_role(), details={"note_ref": note_ref}, occurred_at=now)
    _log(db, case, "notification_sent", details={"to": "owner", "kind": "first_response"}, category="reminder", occurred_at=now)
    db.flush()
    return case


def request_information(db: Session, principal, case: EscalationCase, *, request_code: str) -> EscalationCase:
    """Ask the owner for a document or answer: pauses the K22 clock (owner sees 'waiting for you')."""
    _require_assigned(db, principal, case)
    now = utcnow()
    case.required_action = request_code[:40]
    start_pause(db, case, "awaiting_owner_information", at=now)
    _log(db, case, "information_requested", actor_key=principal.actor_key, actor_role=principal.primary_role(), reason_code=request_code[:40], occurred_at=now)
    _log(db, case, "notification_sent", details={"to": "owner", "kind": "information_needed"}, category="reminder", occurred_at=now)
    db.flush()
    return case


def resolve_case(db: Session, principal, case: EscalationCase, *, outcome: str, limitation: bool = False, supplied_documents_date: date | None = None) -> dict:
    """Resolution (not closure) with a coded outcome (a)-(d). Refused consent forces (c) with the fixed limitation label."""
    _require_assigned(db, principal, case)
    if outcome not in RESOLUTION_OUTCOMES or outcome == "d":
        raise ValidationFailed("outcome must be a, b or c", reason_code="OUTCOME_INVALID")
    if case.status in CLOSED_STATUSES:
        raise Conflict("case is closed", reason_code="CASE_CLOSED")
    if case.consent_decision == "refused" and outcome != "c":
        raise ValidationFailed("without consent the outcome is (c): handed back with a stated limitation", reason_code="OUTCOME_LIMITATION_REQUIRED")
    if case.consent_decision != "refused" and outcome in ("a", "b") and case.module != "compliance" and active_grant(db, case, principal.identity_uuid) is None and (case.details or {}).get("requested_scope"):
        raise Forbidden("no active case access grant; the owner has not consented", reason_code="NO_ACCESS_GRANT")
    now = utcnow()
    end_pause(db, case, at=now)
    case.status, case.resolved_at, case.resolution_outcome = "resolved", now, outcome
    case.resolution_limitation = limitation or case.consent_decision == "refused"
    label = bilingual("supplied_documents_label", date=(supplied_documents_date or now.date()).isoformat()) if case.resolution_limitation else None
    _log(db, case, "resolved", actor_key=principal.actor_key, actor_role=principal.primary_role(), reason_code=f"outcome_{outcome}", details={"limitation": case.resolution_limitation}, occurred_at=now)
    _log(db, case, "notification_sent", details={"to": "owner", "kind": "resolved"}, category="reminder", occurred_at=now)
    db.flush()
    return {"case": case, "output_label": label, "ai_label": bilingual("ai_label")}


def close_case(db: Session, principal, case: EscalationCase, *, reason_code: str) -> EscalationCase:
    """Specialist/ops closure with a coded reason (e.g. key incomplete and not completable, duplicate)."""
    _assert_staff(db, principal, "cases.work", "cases.assign", "cases.queue_fallback")
    if case.status in CLOSED_STATUSES:
        raise Conflict("case is closed", reason_code="CASE_CLOSED")
    if reason_code not in ("key_incomplete_closed", "duplicate", "not_in_scope", "withdrawn_by_ops"):
        raise ValidationFailed("unknown close reason", reason_code="CLOSE_REASON_INVALID")
    now = utcnow()
    end_pause(db, case, at=now)
    case.status, case.closed_at = "closed", now
    _log(db, case, "closed", actor_key=principal.actor_key, actor_role=principal.primary_role(), reason_code=reason_code, occurred_at=now)
    db.flush()
    return case


def complete_matter_key(db: Session, principal, case: EscalationCase, *, matter_key: str) -> EscalationCase:
    _require_assigned(db, principal, case)
    if FLAG_MANUAL_REVIEW not in (case.flags or []):
        raise Conflict("case key is complete", reason_code="KEY_COMPLETE")
    case.matter_key = matter_key
    case.flags = [f for f in (case.flags or []) if f != FLAG_MANUAL_REVIEW]
    _log(db, case, "key_completed", actor_key=principal.actor_key, actor_role=principal.primary_role())
    db.flush()
    return case


def access_case_item(db: Session, principal, case: EscalationCase, *, item: str) -> dict:
    """Every read of company data: entitlement + assignment + active grant covering the item; logged allowed/denied.
    Nothing is returned without a grant (fail closed). Returns a reference, never figures."""
    now = utcnow()
    role = principal.primary_role()

    def deny(reason: str) -> None:
        db.add(CaseAccessLog(case_id=case.case_id, actor_key=principal.actor_key, actor_role=role, item=item, result="denied", reason=reason, occurred_at=now))
        try:
            record_event(db, event_type="CASE_DATA_ACCESS_DENIED", category="data_access", outcome="refused", reason_code=reason, actor_key=principal.actor_key, actor_role=role, company_id=case.company_id, subject_type="escalation_case", subject_id=case.case_id, details={"item": item}, fail_closed=True)
        except AuditWriteError as exc:
            raise Forbidden("audit unavailable; access refused", reason_code="AUDIT_UNAVAILABLE") from exc
        db.flush()
        raise Forbidden("You do not have access to this item. Access depends on the owner's consent.", reason_code=reason)

    try:
        _require_assigned(db, principal, case)
    except (Forbidden, SwitchedOff) as exc:
        deny(exc.reason_code)
    grant = active_grant(db, case, principal.identity_uuid, now=now)
    scope = grant.scope if grant else []
    ext = _external_consent_ok(db, case.company_id, item, module=case.module, purpose=(case.details or {}).get("purpose", "case review"), recipient=case.assigned_to)
    if ext is True:
        pass  # consent module confirms an active evidence_access consent for this recipient
    elif grant is None:
        deny("DENIED_CONSENT_ENDED" if case.consent_decision in ("granted", "withdrawn") else "DENIED_NO_CONSENT")
    elif not any(s.get("data_class") == item or s.get("data_class") == "*" for s in scope):
        deny("DENIED_NOT_IN_SCOPE")
    db.add(CaseAccessLog(case_id=case.case_id, actor_key=principal.actor_key, actor_role=role, item=item, result="allowed", reason=None, occurred_at=now))
    try:
        record_event(db, event_type="CASE_DATA_ACCESSED", category="data_access", actor_key=principal.actor_key, actor_role=role, company_id=case.company_id, subject_type="escalation_case", subject_id=case.case_id, details={"item": item, "grant_id": grant.id if grant else "consent_module"}, fail_closed=True)
    except AuditWriteError as exc:
        raise Forbidden("audit unavailable; access refused", reason_code="AUDIT_UNAVAILABLE") from exc
    db.flush()
    return {"item": item, "reference": f"{case.company_id}:{item}", "grant_id": grant.id if grant else None, "accessed_at": now.isoformat(), "ai_label": bilingual("ai_label")}


def access_log(db: Session, case: EscalationCase, *, limit: int = 50, offset: int = 0) -> list[dict]:
    rows = db.scalars(select(CaseAccessLog).where(CaseAccessLog.case_id == case.case_id).order_by(CaseAccessLog.occurred_at.desc()).offset(offset).limit(limit))
    return [{"who": r.actor_key[:8], "role": r.actor_role, "what": r.item, "when": r.occurred_at.isoformat(), "result": "Allowed" if r.result == "allowed" else "Denied", "reason": r.reason} for r in rows]


# --- consent-wait timeline (E8-S2) ----------------------------------------------------------------


def run_consent_wait(db: Session, now: datetime | None = None, *, case_id: str | None = None) -> dict:
    """Reminders day 3 and 7, ops alert day 7, close day 14 as 'closed - no consent', reopen within 30 days.
    Never auto-reassigns, never auto-resolves. Deadline-near cases use the shortened timeline when configured."""
    now = now or utcnow()
    reminder_days = [int(d) for d in get_config(db, "consent_wait.reminder_days", [3, 7])]
    ops_day = int(get_config(db, "consent_wait.ops_alert_day", 7))
    close_day = int(get_config(db, "consent_wait.close_day", 14))
    reopen_window = int(get_config(db, "consent_wait.reopen_window", 30))
    shortened = get_config(db, "consent_wait.deadline_near_timeline", None)
    out = {"reminders": 0, "ops_alerts": 0, "closed": 0}
    stmt = select(EscalationCase).where(EscalationCase.status == "awaiting_consent", EscalationCase.consent_requested_at.is_not(None))
    if case_id:
        stmt = stmt.where(EscalationCase.case_id == case_id)
    for case in db.scalars(stmt):
        day = (now - case.consent_requested_at).days
        c_days, c_close, c_ops = reminder_days, close_day, ops_day
        if case.priority == "deadline_near" and isinstance(shortened, dict):
            c_days = [int(d) for d in shortened.get("reminder_days", reminder_days)]
            c_close, c_ops = int(shortened.get("close_day", close_day)), int(shortened.get("ops_alert_day", ops_day))
        sent = {e.details.get("day") for e in db.scalars(select(CaseEvent).where(CaseEvent.escalation_id == case.case_id, CaseEvent.event_type == "reminder_sent"))}
        for d in c_days:
            if day >= d and d not in sent:
                _log(db, case, "reminder_sent", details={"day": d, "to": "owner_and_signatories", "text_key": "consent_wait.reminder", "deadline_note": case.priority == "deadline_near"}, category="reminder", occurred_at=now)
                out["reminders"] += 1
        if day >= c_ops and not db.scalar(select(OpsAlert).where(OpsAlert.case_id == case.case_id, OpsAlert.alert_type == "consent_wait_day7")):
            raise_ops_alert(db, "consent_wait_day7", case_id=case.case_id, details={"day": day})
            out["ops_alerts"] += 1
        if day >= c_close:
            end_pause(db, case, at=now)
            case.status, case.closed_at, case.resolution_outcome = "closed_no_consent", now, "d"
            case.reopen_until = (now + timedelta(days=reopen_window)).date()
            _log(db, case, "closed", reason_code="no_consent", details={"outcome": "d", "reopen_until": case.reopen_until.isoformat(), "text_key": "consent_wait.closed"}, occurred_at=now)
            _log(db, case, "notification_sent", details={"to": "owner", "kind": "closed_no_consent"}, category="reminder", occurred_at=now)
            out["closed"] += 1
    db.flush()
    return out


# --- corpus Q&A with refusal (E8-S3) --------------------------------------------------------------


def _passages(db: Session) -> list[CorpusPassage]:
    return list(db.scalars(select(CorpusPassage).order_by(CorpusPassage.passage_id)))


def _rules_data_disagrees(db: Session, p: CorpusPassage) -> bool:
    """E3-S2 rules data disagreeing with a corpus passage → refuse + data-quality flag; rules never overridden."""
    if not p.rules_ref or ":" not in p.rules_ref:
        return False
    rule_id, param = p.rules_ref.split(":", 1)
    try:
        value = (get_rule(db, rule_id).parameters or {}).get(param)
    except NotFound:
        return False
    if value is None:
        return False
    a, b = _first_number(value), _first_number(p.value)
    if a is not None and b is not None:
        return a != b
    return str(value) != str(p.value)


def _first_number(v: object) -> float | None:
    import re

    m = re.search(r"-?\d+(?:\.\d+)?", str(v).replace(",", ""))
    return float(m.group()) if m else None


def _try_open_refusal_case(db: Session, rec: AnswerRecord, principal, company_id: str, *, module: str) -> None:
    retries = int(get_config(db, "escalation.create.retries", 3))
    alert_after = int(get_config(db, "escalation.ops_alert_after_failures", 3))
    window_h = int(get_config(db, "escalation.create.backoff_window_hours", 24))
    rec.attempts += 1
    try:
        case = open_case(db, company_id=company_id, module=module, reason_code="user_requested" if rec.decision == "refuse_and_route" else "complex_tax", matter_key=f"question:{rec.question_id}", event_id=rec.question_id, opened_by="user", trigger_source="user_question", trigger_rule_id="corpus_refusal", title=None, topic_code="qa_refusal", opened_by_key=principal.actor_key)
        rec.case_id, rec.escalation_status, rec.next_retry_at = case.case_id, "created", None
    except CaseSetupPending:
        rec.escalation_status = "pending_escalation"
        backoff = [5, 30, 120][min(rec.attempts - 1, 2)]
        rec.next_retry_at = utcnow() + timedelta(seconds=backoff) if rec.attempts <= retries else utcnow() + timedelta(hours=window_h)
        if rec.attempts >= alert_after and rec.attempts == alert_after:
            raise_ops_alert(db, "escalation_create_failed", details={"question_id": rec.question_id, "attempts": rec.attempts})


def retry_pending_escalations(db: Session, principal, company_id: str, *, question_id: str | None = None) -> list[str]:
    stmt = select(AnswerRecord).where(AnswerRecord.company_id == company_id, AnswerRecord.escalation_status == "pending_escalation")
    if question_id:
        stmt = stmt.where(AnswerRecord.question_id == question_id)
    done = []
    for rec in db.scalars(stmt):
        _try_open_refusal_case(db, rec, principal, company_id, module="tax")
        if rec.case_id:
            done.append(rec.question_id)
    db.flush()
    return done


def ask_question(db: Session, principal, company_id: str, *, question: str, urgent: bool = False, lang: str | None = None) -> dict:
    """Retrieve with citations; decide answer-as-information / refuse-and-route / out-of-corpus refuse on retrieval
    evidence only; legal-type questions get the neutral message with NO stored question text and no case."""
    if not (question or "").strip():
        raise ValidationFailed("question is empty", reason_code="QUESTION_REQUIRED")
    lang = lang or corpus_mod.detect_language(question)
    kind = corpus_mod.question_kind(question)
    thr_version = str(get_config(db, "coverage.threshold.version", "v1"))
    passages = _passages(db)
    corpus_version = max((p.corpus_version for p in passages), default="none")
    base = {"language": lang, "status_chip": bilingual("qa.status_chip"), "label": bilingual("qa.label"), "ai_label": bilingual("ai_label"), "corpus_version": corpus_version, "label_order": ["status_chip", "label", "body"]}
    if kind == "legal":
        rec = AnswerRecord(company_id=company_id, asker_key=principal.actor_key, question_text=None, language=lang, corpus_version=corpus_version, threshold_version=thr_version, decision="legal_neutral", cause_code=None, escalation_status="not_needed")
        db.add(rec)
        record_event(db, event_type="QUESTION_LEGAL_NEUTRAL", category="agent", company_id=company_id, actor_key=principal.actor_key, subject_type="question", subject_id=rec.question_id, details={"stored_text": False, "lawyer_routing": False})
        db.flush()
        return {**base, "question_id": rec.question_id, "decision": "legal_neutral", "summary": bilingual("qa.not_answered"), "body": bilingual("qa.legal_neutral"), "own_choice": bilingual("qa.legal_own_choice"), "label_legal": {"en": "general information, not legal advice", "ar": "معلومات عامة، وليست استشارة قانونية"}, "send_button": bilingual("qa.send_to_licensed_person"), "case_id": None, "citations": [], "legal_route_status": "not_routed"}
    on = dubai_today()
    retrieved = corpus_mod.retrieve(question, passages, on=on)
    thr_key = "coverage.threshold.tax"
    threshold = float(get_config(db, thr_key, 0.80))
    band = float(get_config(db, "coverage.review_band", 0.05))
    best = retrieved[0] if retrieved else None
    score = best.score if best else 0.0
    review_band = abs(score - threshold) <= band
    cause = None
    decision = "answer_as_information"
    if best is None:
        decision, cause = "out_of_corpus_refuse", "unsupported_claim"
    elif score < threshold:
        decision, cause = "refuse_and_route", "below_threshold"
    elif corpus_mod.detect_conflict(best.passage, passages, on=on):
        decision, cause = "refuse_and_route", "conflicting_sources"
    elif _rules_data_disagrees(db, best.passage):
        decision, cause = "refuse_and_route", "rules_data_mismatch"
        record_event(db, event_type="CORPUS_DATA_QUALITY_FLAG", category="system", outcome="flagged", reason_code="RULES_DATA_MISMATCH", subject_type="corpus_passage", subject_id=best.passage.passage_id, details={"owner_role": best.passage.owner_role, "rules_ref": best.passage.rules_ref})
    if kind == "own_position" and decision in ("answer_as_information", "refuse_and_route"):
        decision, cause = "refuse_and_route", "own_tax_position"
    citations = [corpus_mod.citation_for(best.passage, lang)] if (best and decision == "answer_as_information") else []
    claims = [{"claim": best.passage.subject, "passage_id": best.passage.passage_id}] if best and decision == "answer_as_information" else []
    rec = AnswerRecord(company_id=company_id, asker_key=principal.actor_key, question_text=question[:2000], language=lang, corpus_version=corpus_version, threshold_version=thr_version, decision=decision, cause_code=cause, review_band=review_band, retrieved_passage_ids=[r.passage.passage_id for r in retrieved], claims=claims, citations=citations, urgent=urgent, escalation_status="not_needed")
    db.add(rec)
    db.flush()
    record_event(db, event_type="QUESTION_DECIDED", category="agent", company_id=company_id, actor_key=principal.actor_key, subject_type="question", subject_id=rec.question_id, details={"decision": decision, "cause_code": cause, "review_band": review_band, "corpus_version": corpus_version, "threshold_version": thr_version, "passages": len(retrieved)})
    if decision == "answer_as_information":
        p = best.passage
        body = {"ar": p.text_ar, "en": p.text_en}
        return {**base, "question_id": rec.question_id, "decision": decision, "summary": bilingual("qa.answered"), "body": body, "answer_language_note": bilingual("qa.original_language_arabic") if lang == "en" else None, "unofficial_translation_note": bilingual("qa.unofficial_translation") if lang == "en" else None, "tax_disclaimer": bilingual("qa.tax_disclaimer"), "sources_heading": bilingual("qa.sources"), "citations": citations, "claims": claims, "review_band": review_band, "ask_human": bilingual("qa.ask_a_human"), "case_id": None, "value_status": p.value_status}
    module = "tax"
    _try_open_refusal_case(db, rec, principal, company_id, module=module)
    db.flush()
    general_rule = None
    if cause == "own_tax_position" and best is not None and score >= threshold:
        general_rule = {"note": bilingual("qa.own_position_general_rule"), "body": {"ar": best.passage.text_ar, "en": best.passage.text_en}, "citations": [corpus_mod.citation_for(best.passage, lang)], "tax_disclaimer": bilingual("qa.tax_disclaimer")}
    out = {**base, "question_id": rec.question_id, "decision": decision, "summary": bilingual("qa.not_answered"), "body": bilingual("qa.refusal_line") if rec.case_id else bilingual("qa.refusal_line_minimal"), "told_when_ready": bilingual("qa.told_when_ready"), "case_id": rec.case_id, "escalation_status": rec.escalation_status, "open_case": bilingual("qa.open_case"), "citations": [], "general_rule": general_rule, "routed_to": "tax_specialist" if rec.case_id else None}
    if rec.escalation_status == "pending_escalation":
        out["case_message"] = bilingual("qa.case_retrying") if rec.attempts < int(get_config(db, "escalation.create.retries", 3)) else bilingual("qa.case_failed")
        out["retry_now"] = bilingual("qa.retry_now")
    return out


# --- misc ---------------------------------------------------------------------------------------


def count_open_by_queue(db: Session) -> dict[str, int]:
    rows = db.execute(select(EscalationCase.queue, func.count()).where(EscalationCase.status.not_in(CLOSED_STATUSES)).group_by(EscalationCase.queue)).all()
    return {q: n for q, n in rows}


def record_work_item(db: Session, *, company_id: str, module: str, period_ref: str | None, opened_by: str = "agent", case_type: str | None = None, opened_at: datetime | None = None, is_demo: bool = False) -> WorkItem:
    """Other modules register a deliverable (K21 denominator): one per company, module and period (idempotent)."""
    existing = db.scalar(select(WorkItem).where(WorkItem.company_id == company_id, WorkItem.module == module, WorkItem.period_ref == period_ref))
    if existing is not None:
        return existing
    wi = WorkItem(company_id=company_id, module=module, case_type=case_type or module, period_ref=period_ref, opened_by=opened_by, case_opened_at=opened_at or utcnow(), calendar_version=calendar_version_label(db), is_demo=is_demo)
    db.add(wi)
    db.flush()
    return wi


def owner_view(db: Session, case: EscalationCase, lang: str) -> dict:
    st = owner_status(case)
    paused = db.scalar(select(CasePause).where(CasePause.case_id == case.case_id, CasePause.ended_at.is_(None)))
    events = list(db.scalars(select(CaseEvent).where(CaseEvent.escalation_id == case.case_id, CaseEvent.event_type.in_(("case_created", "event_attached", "case_linked", "assigned", "reassigned", "accepted", "first_response", "information_requested", "owner_information_received", "consent_requested", "consent_granted", "consent_refused", "consent_withdrawn", "resolved", "closed", "case_rejected", "case_reopened", "reminder_sent", "pause", "resume"))).order_by(CaseEvent.occurred_at)))
    next_key = f"next_step.{case.module}" if case.module in ("tax", "audit", "compliance") else "licensed_professional_can_review"
    return {
        "case_id": case.case_id, "module": case.module, "status": st, "status_label": bilingual(f"status.{st}"), "handler_type": handler_type(case), "ai_label": bilingual("ai_label"), "priority": case.priority,
        "escalation_reason": case.escalation_reason, "title": case.title, "linked_item_id": case.linked_item_id, "topic_code": case.topic_code, "due_date": case.due_date.isoformat() if case.due_date else None,
        "opened_at": case.opened_at.isoformat(), "resolved_at": case.resolved_at.isoformat() if case.resolved_at else None, "closed_at": case.closed_at.isoformat() if case.closed_at else None,
        "case_owner_role": case.queue, "assigned": case.assigned_to is not None, "assigned_role_label": case.assigned_role_label, "next_step": bilingual(next_key), "linked_case_id": case.linked_case_id,
        "consent_needed": case.status == "awaiting_consent", "consent_notice": bilingual("consent_needed") if case.status == "awaiting_consent" else None, "consent_decision": case.consent_decision,
        "requested_scope": (case.details or {}).get("requested_scope", []), "waiting_for_you": paused is not None and paused.reason_code in ("awaiting_owner_information", "awaiting_owner_approval"), "waiting_label": bilingual("status.waiting_for_you") if paused else None,
        "required_action": case.required_action, "reject": {"reason_code": case.reject_reason_code, "note": case.reject_note, "rejected_at": case.rejected_at.isoformat() if case.rejected_at else None} if case.reject_reason_code else None,
        "resolution_outcome": case.resolution_outcome, "resolution_limitation": case.resolution_limitation, "output_label": bilingual("supplied_documents_label", date=(case.resolved_at or utcnow()).date().isoformat()) if case.resolution_limitation else None,
        "closed_no_consent": case.status == "closed_no_consent", "reopen_until": case.reopen_until.isoformat() if case.reopen_until else None, "closed_no_consent_notice": bilingual("consent_wait.closed", days=int(get_config(db, "consent_wait.reopen_window", 30))) if case.status == "closed_no_consent" else None,
        "legal_route_status": case.legal_route_status, "flags": case.flags or [], "is_demo": case.is_demo, "read_only": case.status in CLOSED_STATUSES,
        "activity": [{"type": e.event_type, "at": e.occurred_at.isoformat(), "reason_code": e.reason_code, "rule_version": e.rule_version} for e in events],
        "information_label": bilingual("information_not_advice"),
    }
