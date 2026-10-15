"""Egress allow-list guard (E1-S4).

Every outbound call from any module goes through ``guard(url)``. A host that is neither in the deployment
allow-list (``settings.outbound_allowlist``) nor in the two-person-approved configuration allow-list
(``hosting.egress.allow_list``) raises ``EgressBlocked``, writes an EGRESS_BLOCKED audit event and raises
an operational alert in the same call. Telemetry, analytics, fonts, CDNs and external model calls are
therefore blocked by construction: nothing is ever allow-listed by default.
"""

from __future__ import annotations

import hashlib
import json
from datetime import timedelta
from urllib.parse import urlparse

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import Conflict, Forbidden, ValidationFailed
from app.core.settings import get_settings
from app.core.time import utcnow
from app.modules.audit.service import record_event
from app.modules.config.service import get_config, set_config
from app.modules.hosting.models import EgressAllowListChange, EgressBlockAlert

ALLOW_LIST_KEY = "hosting.egress.allow_list"
POLICY_ENABLED_KEY = "hosting.egress.policy_enabled"


class EgressBlocked(Forbidden):
    """Outbound call refused: host not on the residency allow-list."""

    reason_code = "EGRESS_BLOCKED"


def host_of(url: str) -> str:
    parsed = urlparse(url if "://" in url else f"//{url}")
    return (parsed.hostname or "").lower()


def allowed_hosts(db: Session | None) -> set[str]:
    hosts = {h.lower() for h in get_settings().outbound_allowlist}
    if db is not None:
        hosts |= {str(h).lower() for h in (get_config(db, ALLOW_LIST_KEY, []) or [])}
    return hosts


def policy_enabled(db: Session | None) -> bool:
    """Production can never disable the policy; non-production disable lapses after 24 h."""
    if db is None or get_settings().environment == "production":
        return True
    value = get_config(db, POLICY_ENABLED_KEY, True)
    if value is True or value is None:
        return True
    if isinstance(value, dict) and value.get("enabled") is False:
        lapse = value.get("lapses_at")
        if lapse and utcnow().isoformat() < str(lapse):
            return False
    return True


def guard(url: str, db: Session | None = None, *, component_ref: str | None = None, handles_company_data: bool = True) -> str:
    """Return the host when permitted; otherwise log, alert and raise ``EgressBlocked``."""
    host = host_of(url)
    owns_session = False
    if db is None:
        from app.core.db import SessionLocal

        db = SessionLocal()
        owns_session = True
    try:
        if not policy_enabled(db):
            return host
        if host and host in allowed_hosts(db):
            return host
        alert = raise_block_alert(db, host or "(no host)", component_ref=component_ref, handles_company_data=handles_company_data)
        db.commit()
        raise EgressBlocked(
            "outbound call refused: destination is not on the residency allow-list",
            details={"host": host, "alert_id": alert.alert_id},
        )
    finally:
        if owns_session:
            db.close()


def raise_block_alert(db: Session, host: str, *, component_ref: str | None, handles_company_data: bool) -> EgressBlockAlert:
    ack_hours = int(get_config(db, "hosting.egress.alert_ack_hours_company_data", 1) or 1)
    ack_due = utcnow() + timedelta(hours=ack_hours) if handles_company_data else _next_working_day(utcnow())
    event = record_event(
        db,
        event_type="EGRESS_BLOCKED",
        category="system",
        outcome="refused",
        reason_code="EGRESS_BLOCKED",
        actor_role="platform",
        subject_type="egress_host",
        subject_id=host[:120],
        details={"host": host, "component_ref": component_ref, "policy": "default_deny"},
        log_class="security",
    )
    alert = EgressBlockAlert(host=host, component_ref=component_ref, handles_company_data=handles_company_data, ack_due_at=ack_due, audit_event_id=event.event_id if event else None)
    db.add(alert)
    db.flush()
    return alert


def _next_working_day(now):
    d = now + timedelta(days=1)
    while d.weekday() >= 5:  # Saturday / Sunday
        d += timedelta(days=1)
    return d.replace(hour=9, minute=0, second=0, microsecond=0)


def acknowledge_alert(db: Session, alert_id: str, actor_key: str) -> EgressBlockAlert:
    alert = db.get(EgressBlockAlert, alert_id)
    if alert is None:
        from app.core.errors import NotFound

        raise NotFound("alert not found")
    alert.acknowledged_at = utcnow()
    alert.acknowledged_by_key = actor_key
    alert.status = "acknowledged"
    record_event(db, event_type="EGRESS_ALERT_ACKNOWLEDGED", category="system", actor_key=actor_key, subject_type="egress_alert", subject_id=alert_id, log_class="security")
    return alert


def escalate_overdue_alerts(db: Session, now=None) -> int:
    """Unacknowledged alerts past their ack deadline escalate to the security owner."""
    now = now or utcnow()
    n = 0
    for alert in db.scalars(select(EgressBlockAlert).where(EgressBlockAlert.status == "open", EgressBlockAlert.ack_due_at < now)):
        alert.status = "escalated"
        alert.escalated_at = now
        record_event(db, event_type="EGRESS_ALERT_ESCALATED", category="escalation", actor_role="platform", subject_type="egress_alert", subject_id=alert.alert_id, details={"to": "qeonix_security_owner"}, log_class="security")
        n += 1
    return n


def alert_counts(db: Session) -> dict:
    rows = list(db.scalars(select(EgressBlockAlert)))
    return {"total": len(rows), "open": sum(r.status == "open" for r in rows), "acknowledged": sum(r.status == "acknowledged" for r in rows), "escalated": sum(r.status == "escalated" for r in rows)}


# --- two-person allow-list change ---------------------------------------------------------------


def change_hash(hosts: list[str]) -> str:
    return hashlib.sha256(json.dumps(sorted({h.lower() for h in hosts})).encode()).hexdigest()


def _working_days_from(start, days: int):
    d = start
    added = 0
    while added < days:
        d += timedelta(days=1)
        if d.weekday() < 5:
            added += 1
    return d


def propose_allow_list_change(db: Session, *, requester_key: str, hosts: list[str], reason: str, supersedes: str | None = None) -> EgressAllowListChange:
    hosts = sorted({h.strip().lower() for h in hosts if h and h.strip()})
    expiry_days = int(get_config(db, "hosting.egress.pending_change_expiry_working_days", 5) or 5)
    if supersedes:
        old = db.get(EgressAllowListChange, supersedes)
        if old and old.status == "pending":
            old.status = "superseded"  # an edit clears all approvals
            record_event(db, event_type="EGRESS_CHANGE_SUPERSEDED", category="config", actor_key=requester_key, subject_type="egress_change", subject_id=old.change_id, log_class="security")
    change = EgressAllowListChange(proposed_list=hosts, change_hash=change_hash(hosts), reason=reason, requester_key=requester_key, expires_at=_working_days_from(utcnow(), expiry_days), supersedes_change_id=supersedes)
    db.add(change)
    db.flush()
    record_event(db, event_type="EGRESS_CHANGE_PROPOSED", category="config", actor_key=requester_key, subject_type="egress_change", subject_id=change.change_id, details={"change_hash": change.change_hash, "hosts": hosts}, log_class="security")
    return change


def approve_allow_list_change(db: Session, change_id: str, *, approver_key: str, approver_role: str, change_hash_seen: str, fresh_auth: bool = True) -> EgressAllowListChange:
    """approver_role: 'qeonix_security_owner' (first) or 'det_security_approver' (second)."""
    change = db.get(EgressAllowListChange, change_id)
    if change is None:
        from app.core.errors import NotFound

        raise NotFound("change not found")
    if change.status != "pending":
        raise Conflict("this change is no longer pending", reason_code="CHANGE_NOT_PENDING")
    if change.expires_at < utcnow():
        expire_pending_changes(db)
        raise Conflict("this change has expired", reason_code="CHANGE_EXPIRED")
    if change_hash_seen != change.change_hash:
        raise ValidationFailed("the approval is bound to a different version of the change", reason_code="CHANGE_HASH_MISMATCH")
    if not fresh_auth:
        raise Forbidden("fresh UAE PASS re-authentication is required to approve", reason_code="REAUTH_REQUIRED")
    if approver_key == change.requester_key:
        raise Forbidden("the requester cannot approve their own change", reason_code="REQUESTER_IS_APPROVER")
    if approver_key in (change.approver_1_key, change.approver_2_key):
        raise Forbidden("the same person cannot give both approvals", reason_code="SAME_PERSON_BOTH_APPROVALS")
    if approver_role == "qeonix_security_owner" and change.approver_1_key is None:
        change.approver_1_key, change.approver_1_at = approver_key, utcnow()
    elif approver_role == "det_security_approver" and change.approver_2_key is None:
        change.approver_2_key, change.approver_2_at = approver_key, utcnow()
    else:
        raise Forbidden("this approval slot is not open for your role", reason_code="APPROVAL_SLOT_UNAVAILABLE")
    record_event(db, event_type="EGRESS_CHANGE_APPROVED", category="config", actor_key=approver_key, actor_role=approver_role, subject_type="egress_change", subject_id=change.change_id, details={"change_hash": change.change_hash}, log_class="security")
    if change.approver_1_key and change.approver_2_key:
        change.status = "applied"
        change.applied_at = utcnow()
        set_config(db, ALLOW_LIST_KEY, change.proposed_list, changed_by=change.requester_key, approved_by=f"{change.approver_1_key},{change.approver_2_key}", change_reason=change.reason, status="confirmed", label="Two-person approved (Qeonix security owner + DET security approver)")
        record_event(db, event_type="EGRESS_ALLOW_LIST_CHANGED", category="config", actor_key=change.requester_key, subject_type="config", subject_id=ALLOW_LIST_KEY, details={"change_id": change.change_id, "hosts": change.proposed_list}, log_class="security")
    return change


def withdraw_allow_list_change(db: Session, change_id: str, *, requester_key: str) -> EgressAllowListChange:
    change = db.get(EgressAllowListChange, change_id)
    if change is None or change.requester_key != requester_key:
        raise Forbidden("only the requester can withdraw the change", reason_code="NOT_REQUESTER")
    if change.status == "pending":
        change.status = "withdrawn"
        record_event(db, event_type="EGRESS_CHANGE_WITHDRAWN", category="config", actor_key=requester_key, subject_type="egress_change", subject_id=change_id, log_class="security")
    return change


def expire_pending_changes(db: Session, now=None) -> int:
    now = now or utcnow()
    n = 0
    for change in db.scalars(select(EgressAllowListChange).where(EgressAllowListChange.status == "pending", EgressAllowListChange.expires_at < now)):
        change.status = "expired"
        record_event(db, event_type="EGRESS_CHANGE_EXPIRED", category="config", actor_role="platform", subject_type="egress_change", subject_id=change.change_id, details={"requester_notified": True}, log_class="security")
        n += 1
    return n


def set_policy_disabled_nonprod(db: Session, *, approver_1_key: str, approver_2_key: str, reason: str) -> dict:
    """Non-production only: two approvals, lapses after 24 h. Production disable is impossible."""
    if get_settings().environment == "production":
        raise Forbidden("the egress policy cannot be disabled in production", reason_code="EGRESS_DISABLE_NOT_ALLOWED")
    if approver_1_key == approver_2_key:
        raise Forbidden("two different approvers are required", reason_code="SAME_PERSON_BOTH_APPROVALS")
    hours = int(get_config(db, "hosting.egress.nonprod_disable_lapse_hours", 24) or 24)
    value = {"enabled": False, "lapses_at": (utcnow() + timedelta(hours=hours)).isoformat(), "reason": reason}
    set_config(db, POLICY_ENABLED_KEY, value, changed_by=approver_1_key, approved_by=approver_2_key, change_reason=reason, status="provisional", label="non-production only; lapses after 24 hours")
    record_event(db, event_type="EGRESS_POLICY_DISABLED_NONPROD", category="config", actor_key=approver_1_key, details={"approved_by": approver_2_key, "lapses_at": value["lapses_at"]}, log_class="security")
    return value
