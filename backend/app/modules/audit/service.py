from __future__ import annotations

import hashlib
import hmac
import json
from datetime import datetime
from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.core.errors import ValidationFailed
from app.core.ids import new_id
from app.core.settings import get_settings
from app.core.time import utcnow
from app.modules.audit.models import ActorIdentityMap, AuditEvent, AuditExport, AuditPending

EXPORT_REASON_CODES = ("regulator_request", "incident_review", "internal_audit", "legal_hold", "data_subject_request")


class AuditWriteError(RuntimeError):
    """Raised when the primary audit write fails; callers that must fail closed catch this."""


def actor_key_for(identity_uuid: str | None) -> str | None:
    """Pseudonymous actor key: keyed HMAC of the identity UUID."""
    if not identity_uuid:
        return None
    secret = get_settings().secret_key.encode()
    return hmac.new(secret, identity_uuid.encode(), hashlib.sha256).hexdigest()[:40]


def ensure_identity_mapping(db: Session, identity_uuid: str) -> str:
    key = actor_key_for(identity_uuid)
    assert key
    if db.get(ActorIdentityMap, key) is None:
        db.add(ActorIdentityMap(actor_key=key, identity_uuid=identity_uuid))
    return key


def truncate_ip(ip: str | None) -> str | None:
    if not ip:
        return None
    if ":" in ip:  # IPv6 /48
        parts = ip.split(":")
        return ":".join(parts[:3]) + "::/48"
    parts = ip.split(".")
    if len(parts) == 4:
        return ".".join(parts[:3]) + ".0/24"
    return None


def _canonical(payload: dict[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)


def _compute_hash(prev_hash: str | None, payload: dict[str, Any]) -> str:
    return hashlib.sha256(((prev_hash or "") + _canonical(payload)).encode()).hexdigest()


def record_event(
    db: Session,
    *,
    event_type: str,
    category: str,
    outcome: str = "success",
    reason_code: str | None = None,
    identity_uuid: str | None = None,
    actor_key: str | None = None,
    actor_role: str | None = None,
    company_id: str | None = None,
    licence_number: str | None = None,
    subject_type: str | None = None,
    subject_id: str | None = None,
    details: dict[str, Any] | None = None,
    language: str | None = None,
    config_version: str | None = None,
    ip: str | None = None,
    browser_family: str | None = None,
    log_class: str = "standard",
    corrects_event_id: str | None = None,
    occurred_at: datetime | None = None,
    fail_closed: bool = False,
) -> AuditEvent | None:
    """Append one event to the hash-chained audit trail.

    If the write fails the payload is stored in the pending store. When ``fail_closed`` is true the
    error is re-raised (``AuditWriteError``) so the caller refuses the action (e.g. sign-in).
    """
    if identity_uuid and not actor_key:
        actor_key = ensure_identity_mapping(db, identity_uuid)
    payload = {
        "event_id": new_id("ev"),
        "occurred_at": (occurred_at or utcnow()).isoformat(),
        "event_type": event_type,
        "category": category,
        "outcome": outcome,
        "reason_code": reason_code,
        "actor_key": actor_key,
        "actor_role": actor_role,
        "company_id": company_id,
        "licence_number": licence_number,
        "subject_type": subject_type,
        "subject_id": subject_id,
        "details": details or {},
        "language": language,
        "config_version": config_version,
        "ip_truncated": truncate_ip(ip),
        "browser_family": browser_family,
        "log_class": log_class,
        "corrects_event_id": corrects_event_id,
    }
    try:
        last = db.scalar(select(AuditEvent).order_by(desc(AuditEvent.id)).limit(1))
        prev_hash = last.hash if last else None
        event = AuditEvent(
            **{k: v for k, v in payload.items() if k != "occurred_at"},
            occurred_at=datetime.fromisoformat(payload["occurred_at"]),
            prev_hash=prev_hash,
            hash=_compute_hash(prev_hash, payload),
        )
        db.add(event)
        db.flush()
        return event
    except Exception as exc:  # pragma: no cover - exercised through the simulated failure hook
        db.rollback()
        db.add(AuditPending(payload=payload, error=str(exc)))
        db.commit()
        if fail_closed:
            raise AuditWriteError(str(exc)) from exc
        return None


def verify_chain(db: Session) -> tuple[bool, int]:
    """Re-compute the hash chain; returns (intact, events_checked)."""
    prev_hash = None
    count = 0
    for ev in db.scalars(select(AuditEvent).order_by(AuditEvent.id)):
        payload = {
            "event_id": ev.event_id,
            "occurred_at": ev.occurred_at.isoformat(),
            "event_type": ev.event_type,
            "category": ev.category,
            "outcome": ev.outcome,
            "reason_code": ev.reason_code,
            "actor_key": ev.actor_key,
            "actor_role": ev.actor_role,
            "company_id": ev.company_id,
            "licence_number": ev.licence_number,
            "subject_type": ev.subject_type,
            "subject_id": ev.subject_id,
            "details": ev.details or {},
            "language": ev.language,
            "config_version": ev.config_version,
            "ip_truncated": ev.ip_truncated,
            "browser_family": ev.browser_family,
            "log_class": ev.log_class,
            "corrects_event_id": ev.corrects_event_id,
        }
        if ev.prev_hash != prev_hash or ev.hash != _compute_hash(prev_hash, payload):
            return False, count
        prev_hash = ev.hash
        count += 1
    return True, count


def query_events(
    db: Session,
    *,
    company_id: str | None = None,
    actor_key: str | None = None,
    category: str | None = None,
    event_type: str | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    limit: int = 200,
    offset: int = 0,
) -> list[AuditEvent]:
    stmt = select(AuditEvent).order_by(desc(AuditEvent.id))
    if company_id:
        stmt = stmt.where(AuditEvent.company_id == company_id)
    if actor_key:
        stmt = stmt.where(AuditEvent.actor_key == actor_key)
    if category:
        stmt = stmt.where(AuditEvent.category == category)
    if event_type:
        stmt = stmt.where(AuditEvent.event_type == event_type)
    if since:
        stmt = stmt.where(AuditEvent.occurred_at >= since)
    if until:
        stmt = stmt.where(AuditEvent.occurred_at <= until)
    return list(db.scalars(stmt.offset(offset).limit(min(limit, 1000))))


def export_events(
    db: Session,
    *,
    requested_by_key: str,
    approved_by_key: str,
    reason_code: str,
    pseudonymised: bool = True,
    filters: dict | None = None,
) -> tuple[AuditExport, list[dict]]:
    if reason_code not in EXPORT_REASON_CODES:
        raise ValidationFailed("export needs a valid reason code", reason_code="EXPORT_REASON_REQUIRED")
    if approved_by_key == requested_by_key:
        raise ValidationFailed("export needs a second approver", reason_code="SECOND_APPROVER_REQUIRED")
    filters = filters or {}
    rows = query_events(db, limit=filters.get("limit", 1000), **{k: v for k, v in filters.items() if k != "limit"})
    out = []
    for ev in rows:
        row = {
            "event_id": ev.event_id,
            "occurred_at": ev.occurred_at.isoformat(),
            "event_type": ev.event_type,
            "category": ev.category,
            "outcome": ev.outcome,
            "reason_code": ev.reason_code,
            "actor_key": ev.actor_key,
            "actor_role": ev.actor_role,
            "company_id": ev.company_id,
            "subject_type": ev.subject_type,
            "subject_id": ev.subject_id,
            "details": ev.details,
        }
        if not pseudonymised:
            m = db.get(ActorIdentityMap, ev.actor_key) if ev.actor_key else None
            row["identity_uuid"] = m.identity_uuid if m else None
        out.append(row)
    export = AuditExport(
        export_id=new_id("exp"),
        requested_by_key=requested_by_key,
        approved_by_key=approved_by_key,
        reason_code=reason_code,
        pseudonymised=pseudonymised,
        filters=filters,
        row_count=len(out),
    )
    db.add(export)
    record_event(
        db,
        event_type="AUDIT_EXPORT",
        category="system",
        actor_key=requested_by_key,
        details={"export_id": export.export_id, "reason_code": reason_code, "rows": len(out), "pseudonymised": pseudonymised, "approved_by_key": approved_by_key},
    )
    db.flush()
    return export, out
