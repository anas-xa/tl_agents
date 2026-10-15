"""DET licence and renewal event intake (E2-S1).

Channel-neutral read contract: one DET event (API, file adapter or manual staff entry) goes through
``intake_event``. Everything DET-specific is versioned configuration: the status mapping, the event-type
mapping, the in-scope authority list, the K6 category mapping and the freshness window. Unmapped and
unclassified values are *held for review*, never dropped, never billed and never reminded.

This handler never calls subscription or billing code. It writes an outbox row after the event is committed;
``outbox.dispatch`` runs downstream consumers separately.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import ValidationFailed
from app.core.time import dubai_date, to_dubai, utcnow
from app.modules.audit.service import record_event
from app.modules.config.service import get_config, rule_params
from app.modules.licences.models import (
    EVENT_PRECEDENCE,
    Licence,
    LicenceEvent,
    LicenceEventOutbox,
    LicenceHistory,
)

SUBSCRIPTION_TRIGGER_TYPES = ("issued", "renewed")
TRACKED_FIELDS = ("trade_name_en", "trade_name_ar", "legal_form", "category", "activities", "issue_date", "expiry_date", "term_start_date", "status", "raw_status", "issuing_authority", "licence_type")

# --- configuration readers ----------------------------------------------------------------------------


def status_mapping(db: Session) -> dict:
    cfg = get_config(db, "det_intake.status_mapping", {}) or {}
    return {"version": cfg.get("version", "v1"), "map": {k.upper(): v for k, v in (cfg.get("map") or {}).items()}}


def event_type_mapping(db: Session) -> dict:
    cfg = get_config(db, "det_intake.event_type_mapping", {}) or {}
    return {"version": cfg.get("version", "v1"), "map": {k.upper(): v for k, v in (cfg.get("map") or {}).items()}}


def freshness_window_hours(db: Session) -> int:
    return int(get_config(db, "intake.freshness_window_hours", 24) or 24)


def is_stale(db: Session, licence: Licence, now: datetime | None = None) -> bool:
    if licence.last_det_refresh_at is None:
        return True
    return (now or utcnow()) - licence.last_det_refresh_at > timedelta(hours=freshness_window_hours(db))


def classify_scope(db: Session, authority: str | None, licence_type: str | None, licence_number: str | None) -> tuple[str, str | None]:
    """In-scope test: issuing authority is DET AND licence type is mainland AND the number is a DET number.

    Category, premises and number format are never used to *infer* scope; a missing or unrecognised authority
    is unclassified and held for review (never silently dropped or accepted).
    """
    in_scope_auth = {a.upper() for a in (get_config(db, "det_intake.in_scope_authorities", ["DET"]) or [])}
    free_zone = {a.upper() for a in (get_config(db, "det_intake.free_zone_authorities", []) or [])}
    pattern = get_config(db, "det_intake.licence_number_pattern", r"^DET-\d+$")
    auth = (authority or "").strip().upper()
    if not auth:
        return "unclassified_held_for_review", "missing_authority"
    if auth in free_zone:
        return "out_of_scope", f"free_zone_authority:{auth}"
    if auth not in in_scope_auth:
        return "unclassified_held_for_review", f"unrecognised_authority:{auth}"
    ltype = (licence_type or "").strip().lower()
    if ltype and ltype != "mainland":
        # DET permission / dual licence is [OPEN] and must not count as mainland.
        return "out_of_scope", f"not_mainland:{ltype}"
    if not ltype:
        return "unclassified_held_for_review", "missing_licence_type"
    if licence_number and pattern and not re.match(pattern, licence_number):
        return "unclassified_held_for_review", "licence_number_not_det_format"
    return "in_scope", None


# --- helpers -------------------------------------------------------------------------------------------


def _d(value: Any) -> date | None:
    if value in (None, ""):
        return None
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


def _dt(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value
    s = str(value).replace("Z", "+00:00")
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is not None:
        from datetime import UTC

        dt = dt.astimezone(UTC).replace(tzinfo=None)
    return dt


def _content_hash(payload: dict) -> str:
    body = {k: v for k, v in payload.items() if k not in ("event_id", "received_at", "arrival_order")}
    return hashlib.sha256(json.dumps(body, sort_keys=True, default=str).encode()).hexdigest()


def _log(db: Session, event_type: str, ev: LicenceEvent | None, *, licence_number: str, det_reference: str | None, raw_type: str | None, effective_date: date | None, reason: str | None = None, outcome: str = "success", actor_key: str | None = None, actor_role: str | None = None, source: str | None = None) -> None:
    """Intake log entry (one of the six intake.* types) written to the audit trail: references and codes only."""
    record_event(
        db,
        event_type=event_type,
        category="system",
        outcome=outcome,
        reason_code=reason,
        actor_key=actor_key,
        actor_role=actor_role,
        licence_number=licence_number,
        subject_type="licence_event",
        subject_id=ev.event_id if ev else None,
        details={"licence_number": licence_number, "event_type": raw_type, "det_reference": det_reference, "effective_date": effective_date.isoformat() if effective_date else None, "source": source, "intake_log": event_type.lower()},
    )


def _history(db: Session, licence: Licence, field: str, old: Any, new: Any, event_id: str | None) -> None:
    def norm(v: Any) -> str | None:
        if v is None:
            return None
        if isinstance(v, (list, dict)):
            return json.dumps(v, ensure_ascii=False)
        return str(v)

    if norm(old) != norm(new):
        db.add(LicenceHistory(licence_id=licence.id, field=field, previous_value=norm(old), current_value=norm(new), event_id=event_id))


def k6_classify(db: Session, *, renewal_completed_at: datetime | None, previous_expiry: date | None, raw_status: str | None) -> tuple[str, str]:
    """K6 rule (provisional): completion day in Asia/Dubai compared with the prior expiry date (date only)."""
    params = rule_params(db, "k6-v1", {"version": "k6-v1"})
    version = str(params.get("version", "k6-v1"))
    k6_map = get_config(db, "det_intake.k6_status_mapping", {}) or {}
    raw = (raw_status or "").upper()
    for cat in ("cancelled_before_expiry", "suspended"):
        if raw in {str(x).upper() for x in (k6_map.get(cat) or [])}:
            return "excluded", version
    if renewal_completed_at is None or previous_expiry is None:
        return "not_applicable", version
    completed_day = to_dubai(renewal_completed_at).date()
    if completed_day <= previous_expiry:
        return "on_time", version
    grace = get_config(db, "det.grace_period_days", None)
    if grace is not None and completed_day <= previous_expiry + timedelta(days=int(grace)):
        return "late_within_grace", version
    return "late", version


# --- the handler ----------------------------------------------------------------------------------------


def intake_event(db: Session, payload: dict, *, source: str = "det_feed", actor_key: str | None = None, actor_role: str | None = None) -> LicenceEvent:
    """Process one DET licence event. Idempotent; atomic per licence; writes the intake log entries."""
    event_id = str(payload.get("event_id") or "").strip()
    licence_number = str(payload.get("licence_number") or "").strip()
    if not event_id or not licence_number:
        raise ValidationFailed("event_id and licence_number are required", reason_code="INTAKE_EVENT_INVALID")
    raw_type = str(payload.get("event_type") or "").strip()
    det_reference = (payload.get("det_reference") or None) and str(payload["det_reference"]).strip()
    effective_date = _d(payload.get("effective_date")) or _d(payload.get("det_event_date"))
    new_term_start = _d(payload.get("new_term_start_date"))
    content = _content_hash(payload)
    log = dict(licence_number=licence_number, det_reference=det_reference, raw_type=raw_type, effective_date=effective_date, actor_key=actor_key, actor_role=actor_role, source=source)

    _log(db, "INTAKE_EVENT_RECEIVED", None, **log)

    # 1. Idempotency on the DET event id.
    existing = db.scalar(select(LicenceEvent).where(LicenceEvent.event_id == event_id))
    if existing is not None:
        if existing.content_hash == content:
            _log(db, "INTAKE_EVENT_DUPLICATE_IGNORED", existing, reason="duplicate_event_id", **log)
            return existing
        return _quarantine(db, payload, f"{event_id}~{content[:8]}", "reference_conflict", content, log)

    # 2. Dedupe key: licence + type + DET reference; without a reference, licence + type + new term start.
    mapping = event_type_mapping(db)
    internal_type = mapping["map"].get(raw_type.upper())
    if det_reference:
        dedupe_key = f"{licence_number}|{internal_type or raw_type.upper()}|{det_reference}"
    elif new_term_start:
        dedupe_key = f"{licence_number}|{internal_type or raw_type.upper()}|{new_term_start.isoformat()}"
    else:
        return _quarantine(db, payload, event_id, "missing_reference", content, log)
    same_key = db.scalar(select(LicenceEvent).where(LicenceEvent.dedupe_key == dedupe_key, LicenceEvent.status != "quarantined"))
    if same_key is not None:
        if same_key.content_hash == content:
            _log(db, "INTAKE_EVENT_DUPLICATE_IGNORED", same_key, reason="duplicate_reference", **log)
            return same_key
        return _quarantine(db, payload, event_id, "reference_conflict", content, log)

    arrival = (db.scalar(select(LicenceEvent.id).order_by(LicenceEvent.id.desc()).limit(1)) or 0) + 1
    ev = LicenceEvent(
        event_id=event_id,
        licence_number=licence_number,
        event_type=internal_type,
        raw_event_type=raw_type,
        effective_date=effective_date,
        det_event_date=_d(payload.get("det_event_date")),
        det_reference=det_reference,
        det_sequence=payload.get("det_sequence"),
        det_timestamp=_dt(payload.get("det_timestamp")),
        arrival_order=arrival,
        payment_received_at=_dt(payload.get("payment_received_at")),
        renewal_completed_at=_dt(payload.get("renewal_completed_at")),
        new_expiry_date=_d(payload.get("new_expiry_date")),
        new_term_start_date=new_term_start,
        dedupe_key=dedupe_key,
        content_hash=content,
        payload=payload,
        source=source,
        status="received",
    )
    db.add(ev)
    db.flush()

    lic_payload = payload.get("licence") or {}
    licence = db.scalar(select(Licence).where(Licence.licence_number == licence_number))
    raw_status = lic_payload.get("status") or payload.get("status")
    smap = status_mapping(db)
    mapped_status = smap["map"].get(str(raw_status).upper()) if raw_status else None
    ev.raw_status = raw_status
    ev.mapped_status = mapped_status or ("unknown" if raw_status else None)

    # 3. Licence record (created on first sight; company link pending until the identity match links it).
    authority = lic_payload.get("issuing_authority", licence.issuing_authority if licence else None)
    ltype = lic_payload.get("licence_type", licence.licence_type if licence else None)
    scope, scope_reason = classify_scope(db, authority, ltype, licence_number)
    if licence is None:
        licence = Licence(
            company_id=None,
            licence_number=licence_number,
            issuing_authority=(authority or "").strip() or "",
            licence_type=(ltype or "").strip() or "",
            trade_name_en=lic_payload.get("trade_name_en") or "",
            trade_name_ar=lic_payload.get("trade_name_ar") or "",
            legal_form=lic_payload.get("legal_form"),
            category=lic_payload.get("category"),
            activities=lic_payload.get("activities"),
            issue_date=_d(lic_payload.get("issue_date")),
            expiry_date=_d(lic_payload.get("expiry_date")),
            status=mapped_status or "unknown",
            raw_status=raw_status,
            scope=scope,
            in_scope=scope == "in_scope",
            out_of_scope_reason=scope_reason,
            status_mapping_version=smap["version"],
            source_snapshot=lic_payload,
        )
        db.add(licence)
        db.flush()
    ev.licence_id = licence.id
    hold: str | None = None
    if scope == "unclassified_held_for_review":
        hold = "unclassified_authority"
    elif internal_type is None:
        hold = "unmapped_event_type"
    elif raw_status and mapped_status is None:
        hold = "unmapped_status"

    # 4. Scope changes are applied to the licence record even when the event is held (history kept).
    if licence.scope != scope:
        _history(db, licence, "scope", licence.scope, scope, event_id)
        licence.scope = scope
        licence.in_scope = scope == "in_scope"
        licence.out_of_scope_reason = scope_reason
    if scope == "out_of_scope":
        record_event(db, event_type="INTAKE_LICENCE_OUT_OF_SCOPE", category="system", reason_code=scope_reason, licence_number=licence_number, subject_type="licence", subject_id=licence.id, details={"reason": scope_reason, "det_reference": det_reference})

    # 5. Effective-date ordering: a late event replays the licence state; a conflict with an already applied
    #    subscription trigger is held, never auto-reversed.
    if hold is None and effective_date is not None:
        later = [e for e in db.scalars(select(LicenceEvent).where(LicenceEvent.licence_id == licence.id, LicenceEvent.status == "processed", LicenceEvent.id != ev.id)) if e.effective_date and (e.effective_date > effective_date or (e.effective_date == effective_date and _tie_after(e, ev)))]
        if later:
            _log(db, "INTAKE_EVENT_OUT_OF_ORDER_REPLAYED", ev, reason="effective_date_earlier_than_processed", **log)
            if internal_type in SUBSCRIPTION_TRIGGER_TYPES and any(e.event_type in SUBSCRIPTION_TRIGGER_TYPES for e in later):
                hold = "out_of_order_replay"
                _log(db, "INTAKE_REPLAY_CONFLICT_RAISED", ev, reason="subscription_trigger_already_applied", **log)

    # 6. Renewal is recorded only when DET shows it completed; a correction (expiry earlier) goes to review.
    if hold is None and internal_type == "renewed":
        completed_statuses = {s.upper() for s in (get_config(db, "det_intake.renewal_completed_statuses", ["ISSUED", "ACTIVE"]) or [])}
        if not raw_status or str(raw_status).upper() not in completed_statuses or ev.new_expiry_date is None:
            hold = "renewal_not_completed"
        elif licence.expiry_date and ev.new_expiry_date < licence.expiry_date:
            hold = "correction_expiry_earlier"

    if hold is not None:
        ev.status = "held_for_review"
        ev.held_for_review = True
        ev.held_reason = hold
        if hold in ("unclassified_authority", "unmapped_status"):
            licence.held_for_review = True
            licence.held_reason = hold
            if hold == "unmapped_status":
                _history(db, licence, "status", licence.status, "unknown", event_id)
                licence.status = "unknown"
                licence.raw_status = raw_status
        licence.last_det_refresh_at = utcnow()
        _log(db, "INTAKE_EVENT_HELD_FOR_REVIEW", ev, reason=hold, **log)
        ev.acknowledged_at = utcnow()
        db.flush()
        return ev

    # 7. Apply the event to the licence record, keeping previous values as history.
    _apply_event(db, licence, ev, lic_payload, mapped_status, raw_status, smap["version"])
    ev.status = "processed"
    ev.processed_at = utcnow()
    ev.acknowledged_at = ev.processed_at
    db.add(LicenceEventOutbox(event_id=event_id, licence_number=licence_number))
    _log(db, "INTAKE_EVENT_PROCESSED", ev, **log)
    db.flush()
    return ev


def _tie_after(existing: LicenceEvent, new: LicenceEvent) -> bool:
    """Same effective date: order by DET sequence/timestamp, then event-type precedence, then arrival."""
    if existing.det_sequence is not None and new.det_sequence is not None and existing.det_sequence != new.det_sequence:
        return existing.det_sequence > new.det_sequence
    if existing.det_timestamp and new.det_timestamp and existing.det_timestamp != new.det_timestamp:
        return existing.det_timestamp > new.det_timestamp
    pe, pn = EVENT_PRECEDENCE.get(existing.event_type or "", 99), EVENT_PRECEDENCE.get(new.event_type or "", 99)
    if pe != pn:
        return pe > pn
    return False


def _quarantine(db: Session, payload: dict, event_id: str, reason: str, content: str, log: dict) -> LicenceEvent:
    ev = LicenceEvent(event_id=event_id, licence_number=log["licence_number"], raw_event_type=log["raw_type"], effective_date=log["effective_date"], det_reference=log["det_reference"], content_hash=content, payload=payload, status="quarantined", quarantine_reason=reason, source=log["source"], acknowledged_at=utcnow())
    db.add(ev)
    db.flush()
    _log(db, "INTAKE_EVENT_QUARANTINED", ev, reason=reason, outcome="held", **log)
    return ev


def _apply_event(db: Session, licence: Licence, ev: LicenceEvent, lic_payload: dict, mapped_status: str | None, raw_status: str | None, mapping_version: str) -> None:
    eid = ev.event_id
    for field in ("trade_name_en", "trade_name_ar", "legal_form", "category", "activities", "issuing_authority", "licence_type"):
        if field in lic_payload and lic_payload[field] not in (None, ""):
            _history(db, licence, field, getattr(licence, field), lic_payload[field], eid)
            setattr(licence, field, lic_payload[field])
    if lic_payload.get("issue_date"):
        _history(db, licence, "issue_date", licence.issue_date, _d(lic_payload["issue_date"]), eid)
        licence.issue_date = _d(lic_payload["issue_date"])
    if ev.event_type in ("issued", "renewed"):
        previous_expiry = licence.expiry_date
        new_expiry = ev.new_expiry_date or _d(lic_payload.get("expiry_date"))
        if ev.event_type == "renewed":
            ev.previous_expiry_date = previous_expiry
            licence.previous_expiry_date = previous_expiry
            ev.k6_class, ev.k6_rule_version = k6_classify(db, renewal_completed_at=ev.renewal_completed_at, previous_expiry=previous_expiry, raw_status=raw_status)
            licence.renewal_state = "renewed"
        else:
            licence.renewal_state = "issued"
        if new_expiry:
            _history(db, licence, "expiry_date", licence.expiry_date, new_expiry, eid)
            licence.expiry_date = new_expiry
        term_start = ev.new_term_start_date or ev.effective_date
        if term_start:
            _history(db, licence, "term_start_date", licence.term_start_date, term_start, eid)
            licence.term_start_date = term_start
    elif ev.event_type == "expired":
        licence.renewal_state = "expired_in_grace"  # expired-in-grace is not cancelled
    elif ev.event_type == "cancelled":
        licence.renewal_state = "cancelled"
    elif ev.event_type == "suspended":
        licence.renewal_state = "suspended"
    elif ev.event_type == "reinstated":
        licence.renewal_state = "active"
    elif ev.event_type == "amended" and lic_payload.get("expiry_date"):
        _history(db, licence, "expiry_date", licence.expiry_date, _d(lic_payload["expiry_date"]), eid)
        licence.expiry_date = _d(lic_payload["expiry_date"])
    if mapped_status:
        _history(db, licence, "status", licence.status, mapped_status, eid)
        licence.status = mapped_status
        licence.raw_status = raw_status
    elif ev.event_type in ("expired", "cancelled", "suspended"):
        _history(db, licence, "status", licence.status, ev.event_type, eid)
        licence.status = ev.event_type
    ej = lic_payload.get("ejari") or {}
    if ej:
        licence.ejari_number = ej.get("number", licence.ejari_number)
        licence.ejari_expiry = _d(ej.get("expiry_date")) or licence.ejari_expiry
        licence.ejari_status = ej.get("status", licence.ejari_status)
    licence.status_mapping_version = mapping_version
    licence.held_for_review = False
    licence.held_reason = None
    licence.last_det_refresh_at = utcnow()
    licence.source_snapshot = lic_payload or licence.source_snapshot


# --- reads ----------------------------------------------------------------------------------------------


def licence_dict(db: Session, lic: Licence) -> dict:
    now = utcnow()
    return {
        "id": lic.id,
        "company_id": lic.company_id,
        "licence_number": lic.licence_number,
        "issuing_authority": lic.issuing_authority,
        "licence_type": lic.licence_type,
        "trade_name_en": lic.trade_name_en,
        "trade_name_ar": lic.trade_name_ar,
        "legal_form": lic.legal_form,
        "category": lic.category,
        "activities": lic.activities or [],
        "issue_date": lic.issue_date.isoformat() if lic.issue_date else None,
        "expiry_date": lic.expiry_date.isoformat() if lic.expiry_date else None,
        "previous_expiry_date": lic.previous_expiry_date.isoformat() if lic.previous_expiry_date else None,
        "term_start_date": lic.term_start_date.isoformat() if lic.term_start_date else None,
        "status": lic.status,
        "raw_status": lic.raw_status,
        "renewal_state": lic.renewal_state,
        "scope": lic.scope,
        "held_for_review": lic.held_for_review,
        "held_reason": lic.held_reason,
        "ejari": {"number": lic.ejari_number, "expiry_date": lic.ejari_expiry.isoformat() if lic.ejari_expiry else None, "status": lic.ejari_status or "unknown"},
        "last_read_at": lic.last_det_refresh_at.isoformat() if lic.last_det_refresh_at else None,
        "stale": is_stale(db, lic, now),
        "freshness_window_hours": freshness_window_hours(db),
        "days_to_expiry": (lic.expiry_date - dubai_date(now)).days if lic.expiry_date else None,
        "status_mapping_version": lic.status_mapping_version,
    }


def event_dict(ev: LicenceEvent) -> dict:
    return {
        "event_id": ev.event_id,
        "licence_number": ev.licence_number,
        "event_type": ev.event_type,
        "raw_event_type": ev.raw_event_type,
        "effective_date": ev.effective_date.isoformat() if ev.effective_date else None,
        "det_reference": ev.det_reference,
        "det_sequence": ev.det_sequence,
        "status": ev.status,
        "held_reason": ev.held_reason,
        "quarantine_reason": ev.quarantine_reason,
        "previous_expiry_date": ev.previous_expiry_date.isoformat() if ev.previous_expiry_date else None,
        "new_expiry_date": ev.new_expiry_date.isoformat() if ev.new_expiry_date else None,
        "new_term_start_date": ev.new_term_start_date.isoformat() if ev.new_term_start_date else None,
        "renewal_completed_at": ev.renewal_completed_at.isoformat() if ev.renewal_completed_at else None,
        "payment_received_at": ev.payment_received_at.isoformat() if ev.payment_received_at else None,
        "k6_class": ev.k6_class,
        "k6_rule_version": ev.k6_rule_version,
        "received_at": ev.received_at.isoformat() if ev.received_at else None,
        "processed_at": ev.processed_at.isoformat() if ev.processed_at else None,
        "source": ev.source,
    }


def licences_for_company(db: Session, company_id: str) -> list[dict]:
    """Owner view: in-scope licences only (out-of-scope records are hidden; cancelled/suspended stay visible)."""
    out = []
    history_months = int(get_config(db, "sc3.history_window_months", 24) or 24)
    cutoff = utcnow() - timedelta(days=30 * history_months)
    for lic in db.scalars(select(Licence).where(Licence.company_id == company_id).order_by(Licence.licence_number)):
        if lic.scope == "out_of_scope":
            continue
        d = licence_dict(db, lic)
        events = list(db.scalars(select(LicenceEvent).where(LicenceEvent.licence_id == lic.id, LicenceEvent.status == "processed").order_by(LicenceEvent.effective_date.desc(), LicenceEvent.id.desc()).limit(20)))
        d["events"] = [event_dict(e) for e in events]
        hist = list(db.scalars(select(LicenceHistory).where(LicenceHistory.licence_id == lic.id, LicenceHistory.changed_at >= cutoff).order_by(LicenceHistory.changed_at.desc()).limit(100)))
        d["history"] = [{"field": h.field, "previous_value": h.previous_value, "current_value": h.current_value, "changed_at": h.changed_at.isoformat(), "source": h.source} for h in hist]
        out.append(d)
    return out


def intake_status(db: Session) -> dict:
    """Aggregated intake status for the DET dashboard: counts only, no company data."""
    licences = list(db.scalars(select(Licence)))
    events = list(db.scalars(select(LicenceEvent)))
    by_scope: dict[str, int] = {}
    oos_reasons: dict[str, int] = {}
    for lic in licences:
        by_scope[lic.scope] = by_scope.get(lic.scope, 0) + 1
        if lic.scope == "out_of_scope" and lic.out_of_scope_reason:
            key = lic.out_of_scope_reason.split(":")[0]
            oos_reasons[key] = oos_reasons.get(key, 0) + 1
    by_status: dict[str, int] = {}
    held_reasons: dict[str, int] = {}
    for ev in events:
        by_status[ev.status] = by_status.get(ev.status, 0) + 1
        if ev.held_reason:
            held_reasons[ev.held_reason] = held_reasons.get(ev.held_reason, 0) + 1
        if ev.quarantine_reason:
            held_reasons[ev.quarantine_reason] = held_reasons.get(ev.quarantine_reason, 0) + 1
    now = utcnow()
    return {
        "licences_by_scope": by_scope,
        "out_of_scope_reasons": oos_reasons,
        "events_by_status": by_status,
        "held_reasons": held_reasons,
        "stale_licences": sum(1 for lic in licences if is_stale(db, lic, now)),
        "unknown_status_licences": sum(1 for lic in licences if lic.status == "unknown"),
        "freshness_window_hours": freshness_window_hours(db),
        "status_mapping_version": status_mapping(db)["version"],
        "event_type_mapping_version": event_type_mapping(db)["version"],
        "interface_type": get_config(db, "det.interface_type", "file"),
        "pending_outbox": db.scalar(select(LicenceEventOutbox).where(LicenceEventOutbox.consumed_at.is_(None), LicenceEventOutbox.dead_letter.is_(False))) is not None,
    }


def held_events(db: Session) -> list[dict]:
    rows = db.scalars(select(LicenceEvent).where(LicenceEvent.status.in_(("held_for_review", "quarantined"))).order_by(LicenceEvent.id.desc()).limit(200))
    return [event_dict(e) for e in rows]
