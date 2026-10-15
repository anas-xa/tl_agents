"""Pilot cohort register service (E2-S5)."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import Conflict, Forbidden, NotFound, SwitchedOff, ValidationFailed
from app.core.time import utcnow
from app.modules.audit.service import record_event
from app.modules.cohorts.models import (
    CHANGE_ACTIONS,
    COHORT_STATUSES,
    ENROLMENT_MODES,
    Cohort,
    CohortChangeRequest,
    CohortInterest,
    CohortMembership,
)
from app.modules.config.service import get_config, rule_params
from app.modules.licences.models import Licence, LicencePerson

FORBIDDEN_MODULES = ("aml", "virtual_lawyer", "remote_services_agent")

# --- configuration ------------------------------------------------------------------------------------


def waves(db: Session) -> list[dict]:
    return list(get_config(db, "cohort.waves", []) or [])


def wave_config(db: Session, code: str) -> dict:
    for w in waves(db):
        if w.get("code") == code:
            return w
    raise ValidationFailed(f"unknown wave {code}", reason_code="COHORT_WAVE_UNKNOWN")


def suppression_n(db: Session) -> int:
    return int(get_config(db, "suppression.N", 10) or 10)


def default_on_mode_enabled(db: Session) -> bool:
    return bool(get_config(db, "cohort.default_on_mode.enabled", False))


def stale_threshold_hours(db: Session) -> int:
    return int(get_config(db, "cohort.stale_block_threshold_hours", 36) or 36)


# --- suppression (one shared function for UI, export, API) -------------------------------------------


def suppress_cell(value: int, n: int) -> dict:
    if value < n:
        return {"value": None, "suppressed": True, "label": f"fewer_than_{n}"}
    return {"value": value, "suppressed": False}


def suppress_breakdown(cells: dict[str, int], n: int) -> dict[str, dict]:
    """Primary suppression (< N) plus complementary suppression of the next-smallest cell so that a hidden
    value cannot be derived by subtraction from the total."""
    out = {k: suppress_cell(v, n) for k, v in cells.items()}
    hidden = [k for k, v in out.items() if v["suppressed"]]
    visible = [k for k, v in out.items() if not v["suppressed"]]
    if len(hidden) == 1 and visible:
        smallest = min(visible, key=lambda k: cells[k])
        out[smallest] = {"value": None, "suppressed": True, "label": f"fewer_than_{n}", "complementary": True}
    return out


# --- cohorts ---------------------------------------------------------------------------------------------


def current_cohort(db: Session, cohort_id: str) -> Cohort:
    row = db.scalar(select(Cohort).where(Cohort.cohort_id == cohort_id, Cohort.is_current.is_(True)))
    if row is None:
        raise NotFound("cohort not found", reason_code="COHORT_NOT_FOUND")
    return row


def cohort_version_at(db: Session, cohort_id: str, at: datetime) -> Cohort | None:
    rows = list(db.scalars(select(Cohort).where(Cohort.cohort_id == cohort_id, Cohort.created_at <= at).order_by(Cohort.version.desc()).limit(1)))
    if rows:
        return rows[0]
    # created after `at`: the earliest version is the one in force conceptually (subscription created before any change)
    return db.scalar(select(Cohort).where(Cohort.cohort_id == cohort_id).order_by(Cohort.version).limit(1))


def _validate_cohort_fields(db: Session, *, wave: str, size_limit: int | None, modules: list | None, enrolment_mode: str, status: str) -> int | None:
    w = wave_config(db, wave)
    cap = w.get("cap")
    if enrolment_mode not in ENROLMENT_MODES:
        raise ValidationFailed("enrolment mode invalid", reason_code="COHORT_MODE_INVALID")
    if enrolment_mode == "default_on_with_opt_out" and not default_on_mode_enabled(db):
        raise SwitchedOff("default-on enrolment is off until the signed DET-Qeonix agreement; opt_in applies", reason_code="DEFAULT_ON_MODE_OFF", details={"fallback": "opt_in"})
    if status not in COHORT_STATUSES:
        raise ValidationFailed("status invalid", reason_code="COHORT_STATUS_INVALID")
    for m in modules or []:
        if m in FORBIDDEN_MODULES:
            raise ValidationFailed(f"module {m} cannot be enabled by a cohort setting", reason_code="COHORT_MODULE_NOT_ALLOWED", details={"module": m})
    if cap is not None:
        if size_limit is None:
            size_limit = int(cap)
        elif size_limit > int(cap):
            raise ValidationFailed(f"size limit exceeds the wave cap of {cap}", reason_code="COHORT_WAVE_CAP", details={"cap": cap})
    return size_limit


def create_cohort(db: Session, *, name: str, code: str, wave: str, actor_key: str, size_limit: int | None = None, start_date: date | None = None, modules: list | None = None, criteria: dict | None = None, enrolment_mode: str = "opt_in", reason: str | None = None, status: str = "draft", is_demo: bool = False) -> Cohort:
    size_limit = _validate_cohort_fields(db, wave=wave, size_limit=size_limit, modules=modules, enrolment_mode=enrolment_mode, status=status)
    criteria = dict(criteria or {})
    criteria["mainland_only"] = True  # fixed, non-editable first rule
    row = Cohort(code=code, name=name, wave=wave, phase=wave_config(db, wave).get("phase", "phase1"), size_limit=size_limit, start_date=start_date, modules=modules or [], selection_criteria=criteria, enrolment_mode=enrolment_mode, status=status, created_by=actor_key, reason=reason or "created", is_demo=is_demo)
    db.add(row)
    db.flush()
    record_event(db, event_type="COHORT_CREATED", category="config", actor_key=actor_key, subject_type="cohort", subject_id=row.cohort_id, config_version=f"{row.cohort_id}@v1", details={"wave": wave, "enrolment_mode": enrolment_mode, "size_limit": size_limit, "status": status})
    return row


def new_version(db: Session, cohort_id: str, *, actor_key: str, reason: str, **changes: Any) -> Cohort:
    """Every edit is a new version with a recorded reason; the previous version stays readable."""
    if not reason:
        raise ValidationFailed("a reason is required for every cohort change", reason_code="REASON_REQUIRED")
    cur = current_cohort(db, cohort_id)
    data = {"name": cur.name, "code": cur.code, "wave": cur.wave, "size_limit": cur.size_limit, "start_date": cur.start_date, "modules": cur.modules, "selection_criteria": cur.selection_criteria, "enrolment_mode": cur.enrolment_mode, "status": cur.status}
    data.update({k: v for k, v in changes.items() if v is not None})
    data["size_limit"] = _validate_cohort_fields(db, wave=data["wave"], size_limit=data["size_limit"], modules=data["modules"], enrolment_mode=data["enrolment_mode"], status=data["status"])
    crit = dict(data["selection_criteria"] or {})
    crit["mainland_only"] = True
    data["selection_criteria"] = crit
    cur.is_current = False
    row = Cohort(cohort_id=cohort_id, version=cur.version + 1, phase=wave_config(db, data["wave"]).get("phase", cur.phase), created_by=actor_key, reason=reason, is_demo=cur.is_demo, **data)
    db.add(row)
    db.flush()
    record_event(db, event_type="COHORT_VERSION_ADDED", category="config", actor_key=actor_key, subject_type="cohort", subject_id=cohort_id, config_version=f"{cohort_id}@v{row.version}", details={"changed": sorted(changes.keys()), "reason_code": "edit"})
    return row


# --- eligibility (cohort_eligibility_v1; placeholders, nothing is DET fact) -----------------------------


def check_eligibility(db: Session, lic: Licence) -> dict:
    params = rule_params(db, "cohort_eligibility_v1", {})
    free_zone = {a.upper() for a in (get_config(db, "det_intake.free_zone_authorities", []) or [])}
    reasons: list[str] = []
    flags: list[str] = []
    if (lic.issuing_authority or "").upper() in free_zone:
        reasons.append("not_det_licensed")
    elif lic.scope != "in_scope":
        reasons.append("not_det_licensed" if lic.scope == "out_of_scope" else "scope_unclassified")
    status_map = params.get("status_mapping", {"active": "eligible"})
    if status_map.get(lic.status, "excluded") != "eligible":
        reasons.append(f"status_{lic.status}")
    mandatory = params.get("mandatory_fields", {})
    values = {"licence_number": lic.licence_number, "licence_status": lic.status, "licence_type_or_authority": lic.issuing_authority, "legal_form": lic.legal_form, "issue_date": lic.issue_date, "expiry_date": lic.expiry_date, "activity_code": (lic.activities or [None])[0] if lic.activities else None, "ejari_number": lic.ejari_number}
    for field, reason_code in mandatory.items():
        if field == "owner_with_emirates_id":
            if not db.scalar(select(LicencePerson).where(LicencePerson.licence_id == lic.id, LicencePerson.has_emirates_id.is_(True))):
                reasons.append(reason_code)
        elif values.get(field) in (None, "", []):
            reasons.append(reason_code)
    exclusions = get_config(db, "cohort.exclusion_categories", []) or []
    hay = " ".join([(lic.legal_form or ""), (lic.category or ""), *[str(a) for a in (lic.activities or [])]]).lower()
    for cat in exclusions:
        if any(k.lower() in hay for k in cat.get("keywords", [])):
            (reasons if cat.get("mode") == "exclude" else flags).append(cat["code"])
    return {"eligible": not reasons, "reason_codes": reasons, "flags_for_review": flags, "rule_version": params.get("version", "cohort_eligibility_v1")}


def _matches(lic: Licence, criteria: dict) -> bool:
    """AND between criteria, OR within one (multi-select). No nested groups."""
    for key, values in (criteria or {}).items():
        if key == "mainland_only" or not values:
            continue
        vals = {str(v).lower() for v in (values if isinstance(values, list) else [values])}
        if key == "legal_form" and (lic.legal_form or "").lower() not in vals:
            return False
        if key == "activity" and not ({str(a).lower() for a in (lic.activities or [])} & vals):
            return False
        if key == "category" and (lic.category or "").lower() not in vals:
            return False
        if key == "renewal_month" and (not lic.expiry_date or str(lic.expiry_date.month) not in vals):
            return False
    return True


def _rule_summary(criteria: dict) -> str:
    parts = ["Licence is a DET mainland licence"]
    labels = {"legal_form": "Legal form is", "activity": "activity is", "category": "category is", "renewal_month": "renewal month is"}
    for key, values in (criteria or {}).items():
        if key in labels and values:
            vs = values if isinstance(values, list) else [values]
            parts.append(f"{labels[key]} {' or '.join(str(v) for v in vs)}")
    return " and ".join(parts) + "."


def active_member_count(db: Session, cohort_id: str) -> int:
    return len(list(db.scalars(select(CohortMembership).where(CohortMembership.cohort_id == cohort_id, CohortMembership.status.in_(("enrolled_starts_next_event", "active", "paused"))))))


def preview(db: Session, cohort_id: str) -> dict:
    cohort = current_cohort(db, cohort_id)
    now = utcnow()
    matched, excluded, flagged = [], [], []
    oldest: datetime | None = None
    for lic in db.scalars(select(Licence).order_by(Licence.expiry_date)):
        if not _matches(lic, cohort.selection_criteria or {}):
            continue
        if lic.last_det_refresh_at and (oldest is None or lic.last_det_refresh_at < oldest):
            oldest = lic.last_det_refresh_at
        elig = check_eligibility(db, lic)
        other = db.scalar(select(CohortMembership).where(CohortMembership.licence_number == lic.licence_number, CohortMembership.cohort_id != cohort_id, CohortMembership.status.in_(("enrolled_starts_next_event", "active", "paused"))))
        if other is not None:
            elig = {**elig, "eligible": False, "reason_codes": elig["reason_codes"] + ["already_in_another_cohort"]}
        row = {"licence_number": lic.licence_number, "expiry_date": lic.expiry_date.isoformat() if lic.expiry_date else None, "legal_form": lic.legal_form, "reason_codes": elig["reason_codes"], "flags_for_review": elig["flags_for_review"]}
        if elig["eligible"]:
            (flagged if elig["flags_for_review"] else matched).append(row)
        else:
            excluded.append(row)
    age_hours = (now - oldest).total_seconds() / 3600 if oldest else None
    limit = cohort.size_limit
    return {
        "cohort_id": cohort_id,
        "matched": matched,
        "flagged_for_review": flagged,
        "excluded": excluded,
        "match_count": len(matched),
        "size_limit": limit,
        "current_members": active_member_count(db, cohort_id),
        "over_limit": max(0, len(matched) + active_member_count(db, cohort_id) - limit) if limit is not None else 0,
        "rule_summary": _rule_summary(cohort.selection_criteria or {}),
        "last_pulled_at": oldest.isoformat() if oldest else None,
        "age_hours": round(age_hours, 1) if age_hours is not None else None,
        "stale": age_hours is None or age_hours > stale_threshold_hours(db),
        "stale_threshold_hours": stale_threshold_hours(db),
        "eligibility_rule": rule_params(db, "cohort_eligibility_v1", {}).get("version", "cohort_eligibility_v1"),
    }


# --- change requests (two-person rule, idempotent) ------------------------------------------------------


def request_change(db: Session, *, cohort_id: str, licence_numbers: list[str], action: str, request_id: str, reason: str, requester_key: str, effective_at: datetime | None = None, allow_shift: bool | None = None, target_wave: str | None = None) -> list[CohortChangeRequest]:
    cohort = current_cohort(db, cohort_id)
    if action not in CHANGE_ACTIONS:
        raise ValidationFailed("action invalid", reason_code="COHORT_ACTION_INVALID")
    if not reason or not reason.strip():
        raise ValidationFailed("a reason is required (saved in the audit trail, not shown to the company)", reason_code="REASON_REQUIRED")
    if not request_id:
        raise ValidationFailed("request_id is required", reason_code="REQUEST_ID_REQUIRED")
    now = utcnow()
    effective_at = effective_at or now
    if effective_at < now - timedelta(minutes=1):
        raise ValidationFailed("the effective time may be now or in the future, never in the past", reason_code="EFFECTIVE_AT_PAST")
    if allow_shift is None:
        allow_shift = bool(get_config(db, "cohort.allow_shift_default", False))
    if action == "close":
        licence_numbers = licence_numbers or ["*"]
    if not licence_numbers:
        raise ValidationFailed("at least one licence number is required", reason_code="LICENCE_REQUIRED")
    # Batch over the size limit is refused in full, with the excess count.
    if action == "enrol" and cohort.size_limit is not None:
        new = [ln for ln in licence_numbers if db.scalar(select(CohortMembership).where(CohortMembership.cohort_id == cohort_id, CohortMembership.licence_number == ln, CohortMembership.status.in_(("enrolled_starts_next_event", "active", "paused")))) is None]
        total = active_member_count(db, cohort_id) + len(new)
        if total > cohort.size_limit:
            record_event(db, event_type="COHORT_CHANGE_REFUSED", category="config", outcome="refused", reason_code="COHORT_SIZE_LIMIT", actor_key=requester_key, subject_type="cohort", subject_id=cohort_id, details={"excess": total - cohort.size_limit, "batch": len(licence_numbers)})
            db.commit()  # the refusal is audited; nothing was enrolled
            raise ValidationFailed(f"{total} licences would exceed the size limit of {cohort.size_limit}; {total - cohort.size_limit} over the limit. Nothing was enrolled.", reason_code="COHORT_SIZE_LIMIT", details={"excess": total - cohort.size_limit, "size_limit": cohort.size_limit})
    out = []
    for ln in licence_numbers:
        if action == "enrol":
            _check_enrolable(db, cohort_id, ln)
        key = f"{cohort_id}|{ln}|{action}|{request_id}"
        existing = db.scalar(select(CohortChangeRequest).where(CohortChangeRequest.idempotency_key == key))
        if existing is not None:
            if existing.reason != reason.strip() or existing.requester_key != requester_key:
                record_event(db, event_type="COHORT_CHANGE_REPLAY_MISMATCH", category="config", outcome="ignored", reason_code="replay_mismatch", actor_key=requester_key, subject_type="cohort_change", subject_id=existing.id, details={"licence_number": ln, "action": action})
            out.append(existing)
            continue
        open_pending = db.scalar(select(CohortChangeRequest).where(CohortChangeRequest.cohort_id == cohort_id, CohortChangeRequest.licence_number == ln, CohortChangeRequest.action == action, CohortChangeRequest.state == "pending"))
        if open_pending is not None:
            out.append(open_pending)
            continue
        row = CohortChangeRequest(cohort_id=cohort_id, licence_number=ln, action=action, request_id=request_id, idempotency_key=key, reason=reason.strip(), effective_at=effective_at, allow_shift=allow_shift, target_wave=target_wave, requester_key=requester_key, cohort_version_at_change=cohort.version)
        db.add(row)
        db.flush()
        record_event(db, event_type="COHORT_CHANGE_REQUESTED", category="config", actor_key=requester_key, subject_type="cohort_change", subject_id=row.id, licence_number=None if ln == "*" else ln, details={"cohort_id": cohort_id, "action": action, "effective_at": effective_at.isoformat(), "request_id": request_id})
        out.append(row)
    return out


def _check_enrolable(db: Session, cohort_id: str, licence_number: str) -> Licence:
    lic = db.scalar(select(Licence).where(Licence.licence_number == licence_number))
    if lic is None:
        raise ValidationFailed("licence not in the DET register read", reason_code="COHORT_LICENCE_UNKNOWN", details={"licence_number": licence_number})
    elig = check_eligibility(db, lic)
    if not elig["eligible"]:
        raise ValidationFailed("licence is not eligible for the pilot", reason_code="COHORT_LICENCE_INELIGIBLE", details={"licence_number": licence_number, "reason_codes": elig["reason_codes"]})
    other = db.scalar(select(CohortMembership).where(CohortMembership.licence_number == licence_number, CohortMembership.cohort_id != cohort_id, CohortMembership.status.in_(("enrolled_starts_next_event", "active", "paused"))))
    if other is not None:
        raise Conflict("a licence belongs to one active cohort at a time", reason_code="COHORT_ALREADY_MEMBER", details={"cohort_id": other.cohort_id})
    return lic


def approve_change(db: Session, change_id: str, *, approver_key: str) -> CohortChangeRequest:
    row = db.get(CohortChangeRequest, change_id)
    if row is None:
        raise NotFound("change not found", reason_code="COHORT_CHANGE_NOT_FOUND")
    if row.state != "pending":
        return row
    if row.requester_key == approver_key:
        record_event(db, event_type="COHORT_CHANGE_REFUSED", category="approval", outcome="refused", reason_code="SELF_APPROVAL", actor_key=approver_key, subject_type="cohort_change", subject_id=row.id)
        db.commit()  # the refusal is audited even though the request is rejected
        raise Forbidden("the requester may not approve their own change", reason_code="SELF_APPROVAL")
    now = utcnow()
    if row.effective_at < now - timedelta(minutes=1):
        if row.allow_shift:
            row.effective_at = now
        else:
            row.state, row.rejection_reason, row.decided_at, row.approver_key = "rejected", "effective date passed", now, approver_key
            record_event(db, event_type="COHORT_CHANGE_REJECTED", category="approval", outcome="refused", reason_code="EFFECTIVE_DATE_PASSED", actor_key=approver_key, subject_type="cohort_change", subject_id=row.id)
            return row
    cohort = current_cohort(db, row.cohort_id)
    if row.action in ("enrol", "remove", "wave") and row.licence_number != "*":
        lic = db.scalar(select(Licence).where(Licence.licence_number == row.licence_number))
        if lic is None or lic.last_det_refresh_at is None or now - lic.last_det_refresh_at > timedelta(hours=stale_threshold_hours(db)):
            raise Conflict("Confirmation is blocked: licence data is out of date. Refresh the preview to continue.", reason_code="STALE_LICENCE_DATA", details={"threshold_hours": stale_threshold_hours(db)})
        if row.action == "enrol":
            _check_enrolable(db, row.cohort_id, row.licence_number)
            if cohort.size_limit is not None and active_member_count(db, row.cohort_id) + 1 > cohort.size_limit:
                raise ValidationFailed("the cohort is at its size limit", reason_code="COHORT_SIZE_LIMIT", details={"size_limit": cohort.size_limit})
    row.state, row.approver_key, row.decided_at = "approved", approver_key, now
    record_event(db, event_type="COHORT_CHANGE_APPROVED", category="approval", actor_key=approver_key, subject_type="cohort_change", subject_id=row.id, licence_number=None if row.licence_number == "*" else row.licence_number, details={"cohort_id": row.cohort_id, "action": row.action, "requester_key": row.requester_key})
    _apply(db, row, cohort)
    return row


def reject_change(db: Session, change_id: str, *, approver_key: str, reason: str) -> CohortChangeRequest:
    row = db.get(CohortChangeRequest, change_id)
    if row is None:
        raise NotFound("change not found", reason_code="COHORT_CHANGE_NOT_FOUND")
    if row.state != "pending":
        return row
    row.state, row.rejection_reason, row.approver_key, row.decided_at = "rejected", (reason or "rejected")[:120], approver_key, utcnow()
    record_event(db, event_type="COHORT_CHANGE_REJECTED", category="approval", outcome="refused", reason_code="REJECTED_BY_APPROVER", actor_key=approver_key, subject_type="cohort_change", subject_id=row.id)
    return row


def _notice(db: Session, m: CohortMembership, event_type: str, actor_key: str) -> None:
    """Company notice: fixed bilingual template per event type (placeholders only), recorded and audited."""
    version = str(get_config(db, "cohort.notice_version", "notice-v1"))
    m.last_notice_event, m.last_notice_at, m.notice_version = event_type, utcnow(), version
    record_event(db, event_type="COHORT_COMPANY_NOTICE", category="reminder", actor_key=actor_key, company_id=m.company_id, licence_number=m.licence_number, subject_type="cohort_membership", subject_id=m.id, config_version=version, details={"notice": event_type, "cohort_id": m.cohort_id})


def _apply(db: Session, row: CohortChangeRequest, cohort: Cohort) -> None:
    now = utcnow()
    actor = row.approver_key or row.requester_key
    if row.action == "close":
        new_version(db, cohort.cohort_id, actor_key=actor, reason=f"closed: {row.reason}", status="closed")
        for m in db.scalars(select(CohortMembership).where(CohortMembership.cohort_id == cohort.cohort_id, CohortMembership.status.in_(("enrolled_starts_next_event", "active", "paused")))):
            _notice(db, m, "closed", actor)  # existing subscriptions continue; no new enrolments
    else:
        lic = db.scalar(select(Licence).where(Licence.licence_number == row.licence_number))
        m = db.scalar(select(CohortMembership).where(CohortMembership.cohort_id == cohort.cohort_id, CohortMembership.licence_number == row.licence_number))
        if row.action == "enrol":
            interest = db.scalar(select(CohortInterest).where(CohortInterest.licence_number == row.licence_number))
            if m is None:
                m = CohortMembership(cohort_id=cohort.cohort_id, licence_number=row.licence_number, company_id=lic.company_id if lic else None)
                db.add(m)
            m.status, m.effective_at, m.enrolled_at, m.removed_at, m.paused_at = "enrolled_starts_next_event", row.effective_at, now, None, None
            m.cohort_version_at_change = cohort.version
            if interest is not None:
                m.owner_opted_in_at = m.owner_opted_in_at or interest.registered_at
                interest.status = "selected"
            db.flush()
            _notice(db, m, "enrolled", actor)
        elif m is None:
            raise NotFound("licence is not a member of this cohort", reason_code="COHORT_NOT_MEMBER")
        elif row.action == "pause":
            m.status, m.paused_at, m.effective_at, m.cohort_version_at_change = "paused", now, row.effective_at, cohort.version
            _notice(db, m, "paused", actor)
        elif row.action == "remove":
            # Leaving never cancels or refunds a paid term: the subscription runs to its term end (E2-S2/E2-S4).
            m.status, m.removed_at, m.effective_at, m.cohort_version_at_change = "removed", now, row.effective_at, cohort.version
            _notice(db, m, "removed", actor)
        elif row.action == "wave":
            new_version(db, cohort.cohort_id, actor_key=actor, reason=f"wave change: {row.reason}", wave=row.target_wave)
    row.state, row.applied_at = "applied", now
    record_event(db, event_type="COHORT_CHANGE_APPLIED", category="config", actor_key=actor, subject_type="cohort_change", subject_id=row.id, licence_number=None if row.licence_number == "*" else row.licence_number, details={"cohort_id": cohort.cohort_id, "action": row.action, "effective_at": row.effective_at.isoformat()})


# --- point-in-time lookup for E2-S2 ---------------------------------------------------------------------


def membership_at(db: Session, licence_number: str, at: datetime | date) -> dict | None:
    """Cohort state of a licence at a moment: membership effective by then and not removed/paused before it,
    plus the cohort version in force at that moment. A subscription created between a change and its
    effective time carries the earlier state."""
    moment = datetime.combine(at, datetime.min.time()) if isinstance(at, date) and not isinstance(at, datetime) else at
    for m in db.scalars(select(CohortMembership).where(CohortMembership.licence_number == licence_number)):
        if m.status in ("enrolled_starts_next_event", "active"):
            if m.effective_at > moment:
                continue  # not yet effective at that moment
        else:  # removed / paused: effective_at is the time of the removal or pause
            if m.enrolled_at > moment or m.effective_at <= moment:
                continue
        cohort = cohort_version_at(db, m.cohort_id, moment) or current_cohort(db, m.cohort_id)
        if cohort.status not in ("active",):
            continue
        w = wave_config(db, cohort.wave)
        return {
            "membership_id": m.id,
            "cohort_id": m.cohort_id,
            "cohort_code": cohort.code,
            "cohort_version": cohort.version,
            "wave": cohort.wave,
            "enrolment_mode": cohort.enrolment_mode,
            "status": m.status,
            "owner_opted_in_at": m.owner_opted_in_at,
            "billing_allowed": bool(w.get("billing", False)),
            "modules": cohort.modules or [],
        }
    return None


def mark_active(db: Session, membership_id: str) -> None:
    m = db.get(CohortMembership, membership_id)
    if m is not None and m.status == "enrolled_starts_next_event":
        m.status = "active"


# --- company side ---------------------------------------------------------------------------------------


def register_interest(db: Session, *, company_id: str, licence_number: str, actor_key: str, language: str | None) -> CohortInterest:
    lic = db.scalar(select(Licence).where(Licence.licence_number == licence_number, Licence.company_id == company_id))
    if lic is None:
        raise NotFound("licence not found for this company", reason_code="LICENCE_NOT_FOUND")
    row = db.scalar(select(CohortInterest).where(CohortInterest.company_id == company_id, CohortInterest.licence_number == licence_number))
    if row is None:
        row = CohortInterest(company_id=company_id, licence_number=licence_number, registered_by_key=actor_key, language=language)
        db.add(row)
        db.flush()
        record_event(db, event_type="COHORT_INTEREST_REGISTERED", category="consent", actor_key=actor_key, company_id=company_id, licence_number=licence_number, subject_type="cohort_interest", subject_id=row.id, language=language, details={"status": "candidate"})
    return row


def company_cohort_view(db: Session, company_id: str) -> list[dict]:
    out = []
    for lic in db.scalars(select(Licence).where(Licence.company_id == company_id, Licence.scope != "out_of_scope").order_by(Licence.licence_number)):
        m = db.scalar(select(CohortMembership).where(CohortMembership.licence_number == lic.licence_number, CohortMembership.status.in_(("enrolled_starts_next_event", "active", "paused"))).order_by(CohortMembership.enrolled_at.desc()).limit(1))
        removed = db.scalar(select(CohortMembership).where(CohortMembership.licence_number == lic.licence_number, CohortMembership.status == "removed").order_by(CohortMembership.removed_at.desc()).limit(1))
        interest = db.scalar(select(CohortInterest).where(CohortInterest.company_id == company_id, CohortInterest.licence_number == lic.licence_number))
        cohort = current_cohort(db, m.cohort_id) if m else None
        out.append({
            "licence_number": lic.licence_number,
            "pilot_status": m.status if m else ("removed" if removed else "not_in_pilot"),
            "cohort_name": cohort.name if cohort else None,
            "wave": cohort.wave if cohort else None,
            "enrolment_mode": cohort.enrolment_mode if cohort else None,
            "modules": cohort.modules if cohort else [],
            "effective_at": (m or removed).effective_at.isoformat() if (m or removed) else None,
            "last_notice_event": (m or removed).last_notice_event if (m or removed) else None,
            "interest_registered_at": interest.registered_at.isoformat() if interest else None,
            "interest_status": interest.status if interest else None,
        })
    return out


# --- DET views ------------------------------------------------------------------------------------------


def cohort_dict(c: Cohort) -> dict:
    return {"cohort_id": c.cohort_id, "code": c.code, "version": c.version, "name": c.name, "wave": c.wave, "phase": c.phase, "size_limit": c.size_limit, "start_date": c.start_date.isoformat() if c.start_date else None, "modules": c.modules or [], "selection_criteria": c.selection_criteria or {}, "enrolment_mode": c.enrolment_mode, "status": c.status, "created_by": c.created_by, "created_at": c.created_at.isoformat(), "reason": c.reason, "is_demo": c.is_demo}


def change_dict(r: CohortChangeRequest) -> dict:
    return {"id": r.id, "cohort_id": r.cohort_id, "licence_number": r.licence_number, "action": r.action, "request_id": r.request_id, "effective_at": r.effective_at.isoformat(), "allow_shift": r.allow_shift, "target_wave": r.target_wave, "requester_key": r.requester_key, "approver_key": r.approver_key, "state": r.state, "rejection_reason": r.rejection_reason, "created_at": r.created_at.isoformat(), "decided_at": r.decided_at.isoformat() if r.decided_at else None, "applied_at": r.applied_at.isoformat() if r.applied_at else None}


def list_cohorts(db: Session) -> list[dict]:
    out = []
    for c in db.scalars(select(Cohort).where(Cohort.is_current.is_(True)).order_by(Cohort.created_at)):
        d = cohort_dict(c)
        d["member_count"] = active_member_count(db, c.cohort_id)
        d["pending_changes"] = len(list(db.scalars(select(CohortChangeRequest).where(CohortChangeRequest.cohort_id == c.cohort_id, CohortChangeRequest.state == "pending"))))
        out.append(d)
    return out


def cohort_detail(db: Session, cohort_id: str, *, actor_key: str) -> dict:
    cohort = current_cohort(db, cohort_id)
    n = suppression_n(db)
    members = list(db.scalars(select(CohortMembership).where(CohortMembership.cohort_id == cohort_id).order_by(CohortMembership.enrolled_at)))
    try:  # subscription state per licence (DET-admin allowed fields only: states, never amounts)
        from app.modules.subscriptions.service import det_status_for_licence
    except ImportError:  # pragma: no cover
        det_status_for_licence = None  # type: ignore[assignment]
    rows = []
    for m in members:
        sub = det_status_for_licence(db, m.licence_number) if det_status_for_licence else {}
        rows.append({"membership_id": m.id, "licence_number": m.licence_number, "status": m.status, "effective_at": m.effective_at.isoformat(), "enrolled_at": m.enrolled_at.isoformat(), "owner_opted_in": m.owner_opted_in_at is not None, "last_notice_event": m.last_notice_event, "cohort_version_at_change": m.cohort_version_at_change, **sub})
    by_status: dict[str, int] = {}
    for m in members:
        by_status[m.status] = by_status.get(m.status, 0) + 1
    record_event(db, event_type="COHORT_AGGREGATE_QUERIED", category="data_access", actor_key=actor_key, subject_type="cohort", subject_id=cohort_id, details={"members": len(members), "suppression_n": n})
    return {
        "cohort": cohort_dict(cohort),
        "wave_config": wave_config(db, cohort.wave),
        "versions": [cohort_dict(v) for v in db.scalars(select(Cohort).where(Cohort.cohort_id == cohort_id).order_by(Cohort.version.desc()))],
        "members": rows,
        "member_count": active_member_count(db, cohort_id),
        "pending_changes": [change_dict(r) for r in db.scalars(select(CohortChangeRequest).where(CohortChangeRequest.cohort_id == cohort_id).order_by(CohortChangeRequest.created_at.desc()).limit(50))],
        "aggregates": {"members_by_status": suppress_breakdown(by_status, n), "total": suppress_cell(len(members), n), "suppression_n": n, "suppression_label": "provisional, set by DET"},
    }
