"""Delegate management (E1-S6) and the remaining E1-S2 controls: per-case grants, revocation with quarantine,
signatory-change hold, auditor firewall, DET authority reconciliation, SC15 activity rows, SC14 counters.

Pure functions ``fn(db, ...)``; no HTTP objects. Other modules are reached lazily and optionally.
In-app delegation is never described as a power of attorney.
"""

from __future__ import annotations

import importlib
import re
import secrets
import unicodedata
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import Conflict, Forbidden, NotFound, SwitchedOff, ValidationFailed
from app.core.time import to_dubai, utcnow
from app.modules.access.service import (
    DELEGATE_RIGHT_PERMS,
    Principal,
    check_role_combination,
    delegate_right_enabled,
)
from app.modules.audit.models import ActorIdentityMap, AuditEvent
from app.modules.audit.service import actor_key_for, record_event
from app.modules.companies.models import Company, CompanyRole
from app.modules.config.service import get_config
from app.modules.delegates.models import (
    PHASE_B_TOGGLES,
    RIGHT_TO_TOGGLE,
    TOGGLE_TO_RIGHT,
    AccessGrant,
    CompanyHold,
    DelegateChange,
    DelegateInvitation,
    FirewallRecord,
    QuarantinedDraft,
    SupportQueueCase,
)
from app.modules.delegates.strings import PURPOSES, SPECIALIST_LABELS, WORDS, s
from app.modules.identity.models import Identity, OperationalAlert, StaffRole, UserSession
from app.modules.licences.models import Licence, LicencePerson

OWNER_LEVEL = ("owner", "remote_owner")
# Functions held during a signatory-change hold / no-owner state (settled Q12). Reads stay available.
HELD_PERMS = {"consent.grant", "consent.withdraw", "returns.approve", "delegates.manage", "subscription.change", "grants.create"}
# In the DET-caused no-owner state every delegate right is suspended (prepare-type writes included).
NO_OWNER_DELEGATE_PERMS = HELD_PERMS | {"tax.prepare", "tax.correct", "returns.send_for_approval", "uploads.manage", "links.manage", "taxprofile.edit"}
# High-impact acts blocked when DET data is stale (> stale threshold): consent, delegation, approval, subscription.
STALE_BLOCKED_PERMS = {"consent.grant", "consent.withdraw", "returns.approve", "delegates.manage", "subscription.change", "grants.create"}

# Other modules may register providers returning the drafts a delegate touched on a company:
# fn(db, identity_uuid, company_id) -> list[dict(draft_type, draft_ref, touched_action, data_version)]
TOUCHED_DRAFT_PROVIDERS: list[Callable[[Session, str, str], list[dict]]] = []


# --- helpers -------------------------------------------------------------------------------------


def _optional(module: str, attr: str):
    try:
        mod = importlib.import_module(module)
    except ModuleNotFoundError:
        return None
    return getattr(mod, attr, None)


def _refuse(db: Session, exc: Exception) -> None:
    """Denials are fail-safe (E1-S2): the refusal event is committed, then the action is refused."""
    db.commit()
    raise exc


def _int(db: Session, key: str, default: int) -> int:
    return int(get_config(db, key, default))


def _company(db: Session, company_id: str) -> Company:
    company = db.get(Company, company_id)
    if company is None:
        raise Forbidden("company not available to you", reason_code="NOT_YOUR_COMPANY")
    return company


def _identity_name(db: Session, identity_uuid: str | None) -> str | None:
    if not identity_uuid:
        return None
    ident = db.get(Identity, identity_uuid)
    return ident.display_name if ident else None


def _change(db: Session, *, company_id: str, change_type: str, principal: Principal | None, delegate_identity_uuid: str | None = None, delegate_label: str | None = None, subject_ref: str | None = None, before: dict | None = None, after: dict | None = None, reason: str | None = None) -> DelegateChange:
    row = DelegateChange(company_id=company_id, change_type=change_type, delegate_identity_uuid=delegate_identity_uuid, delegate_label=delegate_label, subject_ref=subject_ref, before=before, after=after, reason=reason, changed_by_uuid=principal.identity_uuid if principal else None, changed_by_role=_role_on(principal, company_id) if principal else "system")
    db.add(row)
    db.flush()
    return row


def _role_on(principal: Principal | None, company_id: str) -> str:
    if principal is None:
        return "system"
    roles = principal.roles_for(company_id)
    return roles[0].role if roles else principal.primary_role()


ARABIC_INDIC = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")


def normalise_emirates_id(raw: str) -> str:
    """Digits only (Arabic-Indic digits normalised). Must be the 15-digit Emirates ID format starting 784."""
    digits = re.sub(r"\D", "", (raw or "").translate(ARABIC_INDIC))
    if len(digits) != 15 or not digits.startswith("784"):
        raise ValidationFailed("Emirates ID must be 15 digits starting with 784", reason_code="EMIRATES_ID_INVALID")
    return digits


_AR_DIACRITICS = re.compile(r"[ؐ-ًؚ-ٰٟۖ-ۭـ]")


def normalise_name(name: str | None) -> set[str]:
    """Soft-check normalisation: Arabic diacritics/tatweel removed, alef/yaa/taa-marbuta unified, digits normalised,
    case-folded, spaces collapsed, tokens compared in any order."""
    if not name:
        return set()
    text = unicodedata.normalize("NFKC", name).translate(ARABIC_INDIC)
    text = _AR_DIACRITICS.sub("", text)
    text = re.sub("[أإآٱ]", "ا", text).replace("ى", "ي").replace("ئ", "ي").replace("ؤ", "و").replace("ة", "ه")
    text = text.casefold()
    text = re.sub(r"[^\w\s]", " ", text)
    return {t for t in text.split() if t and t not in {"al", "ال", "bin", "bint", "dr", "mr", "mrs", "ms"}}


def name_differs(entered: str | None, asserted: str | None) -> bool:
    a, b = normalise_name(entered), normalise_name(asserted)
    if not a or not b:
        return False
    return not (a & b)


# --- DET authority reconciliation and hold state ------------------------------------------------


def get_hold(db: Session, company_id: str) -> CompanyHold:
    row = db.get(CompanyHold, company_id)
    if row is None:
        row = CompanyHold(company_id=company_id, hold_state="none")
        db.add(row)
        db.flush()
    return row


def authority_state(db: Session, company_id: str) -> dict:
    """DET record freshness (cache <= 24 h, stale > 48 h fail-closed for high-impact acts) and hold state."""
    licence = db.scalar(select(Licence).where(Licence.company_id == company_id).order_by(Licence.created_at.desc()))
    refreshed = licence.last_det_refresh_at if licence else None
    cache_h = _int(db, "delegates.det_authority_cache_hours", 24)
    stale_h = _int(db, "delegates.det_authority_stale_hours", 48)
    now = utcnow()
    age_h = (now - refreshed).total_seconds() / 3600 if refreshed else None
    hold = get_hold(db, company_id)
    persons = list(db.scalars(select(LicencePerson).where(LicencePerson.licence_id == licence.id))) if licence else []
    has_matchable_owner = any(p.emirates_id_hash for p in persons)
    reconfirm = db.scalar(select(func.min(CompanyRole.reconfirm_by)).where(CompanyRole.company_id == company_id, CompanyRole.status == "active", CompanyRole.reconfirm_by.isnot(None)))
    return {
        "det_refreshed_at": refreshed.isoformat() if refreshed else None,
        "det_cache_hours": cache_h,
        "det_stale_hours": stale_h,
        "refresh_due": age_h is None or age_h > cache_h,
        "stale": age_h is None or age_h > stale_h,
        "no_det_record": licence is None,
        "has_matchable_owner": has_matchable_owner,
        "hold_state": hold.hold_state,
        "hold_started_at": hold.hold_started_at.isoformat() if hold.hold_started_at else None,
        "hold_reason": hold.reason,
        "max_hold_days": _int(db, "delegates.signatory_change_max_hold_days", 30),
        "det_operations_alerted_at": hold.alerted_det_operations_at.isoformat() if hold.alerted_det_operations_at else None,
        "reconfirm_by": reconfirm.isoformat() if reconfirm else None,
    }


def require_not_on_hold(db: Session, company_id: str, permission: str, *, principal: Principal | None = None) -> None:
    """Fail closed for held functions while the company is on hold or its DET data is stale. Reads pass."""
    hold = get_hold(db, company_id)
    is_delegate = bool(principal and any(r.role == "delegate" for r in principal.roles_for(company_id)))
    held = NO_OWNER_DELEGATE_PERMS if (hold.hold_state == "no_owner" and is_delegate) else HELD_PERMS
    if hold.hold_state != "none" and permission in held:
        record_event(db, event_type="ACCESS_REFUSED", category="access", outcome="refused", reason_code="COMPANY_ON_HOLD", actor_key=principal.actor_key if principal else None, actor_role=_role_on(principal, company_id) if principal else None, company_id=company_id, details={"permission": permission, "hold_state": hold.hold_state})
        _refuse(db, Forbidden("this company is on hold until the signatory change is confirmed", reason_code="COMPANY_ON_HOLD", details={"hold_state": hold.hold_state, "permission": permission}))
    if permission in STALE_BLOCKED_PERMS:
        state = authority_state(db, company_id)
        if state["stale"]:
            record_event(db, event_type="ACCESS_REFUSED", category="access", outcome="refused", reason_code="DET_DATA_STALE", actor_key=principal.actor_key if principal else None, company_id=company_id, details={"permission": permission, "det_refreshed_at": state["det_refreshed_at"]})
            _refuse(db, Forbidden("licence data is older than the allowed threshold; viewing and preparing continue", reason_code="DET_DATA_STALE", details={"permission": permission, "stale_hours": state["det_stale_hours"]}))
    if permission in STALE_BLOCKED_PERMS and principal is not None:
        for r in principal.roles_for(company_id):
            if r.reconfirm_by and r.role in OWNER_LEVEL:
                record_event(db, event_type="ACCESS_REFUSED", category="access", outcome="refused", reason_code="RECONFIRMATION_PENDING", actor_key=principal.actor_key, company_id=company_id, details={"permission": permission})
                _refuse(db, Forbidden("your authority on this company is view-only until it is reconfirmed", reason_code="RECONFIRMATION_PENDING", details={"reconfirm_by": r.reconfirm_by.isoformat()}))


def _suspend_delegations(db: Session, company_id: str, *, reason: str, granted_by: str | None = None) -> int:
    stmt = select(CompanyRole).where(CompanyRole.company_id == company_id, CompanyRole.role == "delegate", CompanyRole.status == "active")
    if granted_by:
        stmt = stmt.where(CompanyRole.granted_by_uuid == granted_by)
    n = 0
    window = _int(db, "delegate.reconfirmation_window_days", 30)
    for r in db.scalars(stmt):
        r.status = "suspended"
        r.suspended_reason = reason
        r.reconfirm_by = utcnow().date() + timedelta(days=window)
        _change(db, company_id=company_id, change_type="authority_suspended", principal=None, delegate_identity_uuid=r.identity_uuid, delegate_label=_identity_name(db, r.identity_uuid), subject_ref=r.id, reason=reason)
        record_event(db, event_type="DELEGATION_CHANGE", category="access", outcome="info", reason_code="SUSPENDED_AUTHORITY_CHANGED", company_id=company_id, subject_type="company_role", subject_id=r.id, details={"reason": reason})
        _enforce_revocation(db, identity_uuid=r.identity_uuid, company_id=company_id, principal=None, reason=reason, quarantine=False)
        n += 1
    return n


def start_signatory_change_hold(db: Session, company_id: str, *, reason: str = "signatory_changed", principal: Principal | None = None) -> CompanyHold:
    """Apply the owner-change hold: held functions blocked, consents suspended, pending approvals cancelled,
    delegations by the previous owner suspended. Reads, dashboard and reminders stay. Every step audited."""
    _company(db, company_id)
    hold = get_hold(db, company_id)
    if hold.hold_state == "signatory_change_hold":
        return hold
    hold.hold_state = "signatory_change_hold"
    hold.hold_started_at = utcnow()
    hold.reason = reason
    hold.lifted_at = None
    hold.alerted_det_operations_at = None
    actor = principal.actor_key if principal else None
    record_event(db, event_type="COMPANY_HOLD_STARTED", category="access", actor_key=actor, company_id=company_id, subject_type="company_hold", subject_id=company_id, details={"hold_state": "signatory_change_hold", "reason": reason})
    for prev in db.scalars(select(CompanyRole).where(CompanyRole.company_id == company_id, CompanyRole.role.in_(OWNER_LEVEL), CompanyRole.status == "active")):
        prev.reconfirm_by = utcnow().date() + timedelta(days=_int(db, "delegate.reconfirmation_window_days", 30))
        _suspend_delegations(db, company_id, reason="authority_changed", granted_by=prev.identity_uuid)
    fn = _optional("app.modules.consent.service", "suspend_consents_for_hold")
    paused = fn(db, company_id) if fn else 0
    record_event(db, event_type="CONSENT_PAUSED", category="consent", outcome="info", reason_code="SIGNATORY_CHANGED", company_id=company_id, details={"count": paused, "hold": True})
    fn = _optional("app.modules.approvals.service", "cancel_pending_for_hold")
    cancelled = fn(db, company_id, "signatory changed") if fn else 0
    record_event(db, event_type="APPROVAL_VOIDED", category="approval", outcome="info", reason_code="SIGNATORY_CHANGED", company_id=company_id, details={"count": cancelled, "reason": "signatory changed"})
    db.flush()
    return hold


def set_no_owner_state(db: Session, company_id: str, *, reason: str = "no_matchable_owner_on_det_record") -> CompanyHold:
    hold = get_hold(db, company_id)
    if hold.hold_state == "no_owner":
        return hold
    hold.hold_state = "no_owner"
    hold.hold_started_at = utcnow()
    hold.reason = reason
    hold.lifted_at = None
    record_event(db, event_type="COMPANY_HOLD_STARTED", category="access", company_id=company_id, subject_type="company_hold", subject_id=company_id, details={"hold_state": "no_owner", "reason": reason})
    db.flush()
    return hold


def lift_hold(db: Session, company_id: str, *, lifted_by: str, principal: Principal | None = None) -> CompanyHold:
    hold = get_hold(db, company_id)
    if hold.hold_state == "none":
        return hold
    before = hold.hold_state
    hold.hold_state = "none"
    hold.lifted_at = utcnow()
    hold.lifted_by = lifted_by
    for r in db.scalars(select(CompanyRole).where(CompanyRole.company_id == company_id, CompanyRole.role.in_(OWNER_LEVEL), CompanyRole.status == "active")):
        r.reconfirm_by = None  # the DET record was confirmed (by match or by DET support)
    for case in db.scalars(select(SupportQueueCase).where(SupportQueueCase.company_id == company_id, SupportQueueCase.status == "open")):
        case.status = "resolved"
        case.resolved_at = utcnow()
        case.resolved_by = lifted_by
    record_event(db, event_type="COMPANY_HOLD_LIFTED", category="access", actor_key=principal.actor_key if principal else None, company_id=company_id, subject_type="company_hold", subject_id=company_id, details={"from": before, "lifted_by": "uaepass_match" if lifted_by == "uaepass_match" else "det_support"})
    db.flush()
    return hold


def check_hold_alerts(db: Session) -> int:
    """Holds older than the configured maximum alert DET operations; they are never released by timeout."""
    max_days = _int(db, "delegates.signatory_change_max_hold_days", 30)
    n = 0
    for hold in db.scalars(select(CompanyHold).where(CompanyHold.hold_state != "none", CompanyHold.alerted_det_operations_at.is_(None))):
        if hold.hold_started_at and hold.hold_started_at + timedelta(days=max_days) <= utcnow():
            hold.alerted_det_operations_at = utcnow()
            db.add(OperationalAlert(alert_type="COMPANY_HOLD_EXCEEDED", severity="high", recipients=["det-operations"], details={"company_id": hold.company_id, "hold_state": hold.hold_state, "max_days": max_days}))
            record_event(db, event_type="COMPANY_HOLD_ALERT", category="system", company_id=hold.company_id, details={"max_days": max_days, "recipients": ["det-operations"]})
            n += 1
    db.flush()
    return n


def _licence_person_hashes(db: Session, company_id: str) -> set[str]:
    rows = db.execute(select(LicencePerson.emirates_id_hash).join(Licence, Licence.id == LicencePerson.licence_id).where(Licence.company_id == company_id, LicencePerson.emirates_id_hash.isnot(None))).all()
    return {r[0] for r in rows}


def try_lift_hold_on_signin(db: Session, identity_uuid: str, idn_hash: str | None) -> list[str]:
    """New signatory signs in with UAE PASS: an exact Emirates ID match on the held company's DET record lifts
    the hold automatically; an owner-level person on a held company without a match goes to the DET onboarding
    support queue. The platform never edits DET data."""
    lifted: list[str] = []
    for hold in db.scalars(select(CompanyHold).where(CompanyHold.hold_state != "none")):
        matched = bool(idn_hash) and idn_hash in _licence_person_hashes(db, hold.company_id)
        if matched:
            role = db.scalar(select(CompanyRole).where(CompanyRole.identity_uuid == identity_uuid, CompanyRole.company_id == hold.company_id, CompanyRole.role.in_(OWNER_LEVEL)))
            if role is None:
                ident = db.get(Identity, identity_uuid)
                db.add(CompanyRole(identity_uuid=identity_uuid, company_id=hold.company_id, role="remote_owner" if ident and ident.profile_type == 2 else "owner", capacity="authorised_signatory", functions=["all"], granted_by_uuid="det_record_match"))
            else:
                role.status = "active"
                role.reconfirm_by = None
            lift_hold(db, hold.company_id, lifted_by="uaepass_match")
            record_event(db, event_type="ROLE_CHANGE", category="access", identity_uuid=identity_uuid, company_id=hold.company_id, details={"role": "owner", "source": "det_record_match", "hold_lifted": True})
            lifted.append(hold.company_id)
        else:
            holds_owner = db.scalar(select(CompanyRole).where(CompanyRole.identity_uuid == identity_uuid, CompanyRole.company_id == hold.company_id, CompanyRole.role.in_(OWNER_LEVEL)))
            if holds_owner is not None and db.scalar(select(SupportQueueCase).where(SupportQueueCase.company_id == hold.company_id, SupportQueueCase.status == "open")) is None:
                db.add(SupportQueueCase(company_id=hold.company_id, identity_uuid=identity_uuid, case_type="signatory_no_match"))
                record_event(db, event_type="DET_SUPPORT_CASE_OPENED", category="access", identity_uuid=identity_uuid, company_id=hold.company_id, details={"case_type": "signatory_no_match"})
    db.flush()
    return lifted


def reconcile_company_authority(db: Session, company_id: str) -> dict:
    """Daily/at-request reconciliation against the DET record: no matchable owner-level person -> no-owner state."""
    state = authority_state(db, company_id)
    hold = get_hold(db, company_id)
    if not state["no_det_record"] and not state["has_matchable_owner"] and hold.hold_state == "none":
        set_no_owner_state(db, company_id)
        _suspend_delegations(db, company_id, reason="no_owner")
    expire_invitations(db, company_id)
    expire_unconfirmed_authority(db, company_id)
    return authority_state(db, company_id)


def expire_unconfirmed_authority(db: Session, company_id: str | None = None) -> int:
    """Authority not reconfirmed within the window ends (audit keeps history). Last owner-level person is never
    removed by the platform."""
    today = utcnow().date()
    stmt = select(CompanyRole).where(CompanyRole.reconfirm_by.isnot(None), CompanyRole.reconfirm_by < today, CompanyRole.status.in_(("active", "suspended")))
    if company_id:
        stmt = stmt.where(CompanyRole.company_id == company_id)
    n = 0
    for r in db.scalars(stmt):
        if r.role in OWNER_LEVEL:
            others = db.scalar(select(func.count(CompanyRole.id)).where(CompanyRole.company_id == r.company_id, CompanyRole.role.in_(OWNER_LEVEL), CompanyRole.status == "active", CompanyRole.id != r.id))
            if not others:
                continue  # last-owner rule
        r.status = "expired"
        r.revoked_at = utcnow()
        record_event(db, event_type="ROLE_CHANGE", category="access", outcome="info", reason_code="RECONFIRMATION_EXPIRED", company_id=r.company_id, subject_type="company_role", subject_id=r.id, details={"role": r.role})
        n += 1
    return n


# --- invitations ---------------------------------------------------------------------------------


def _validate_toggles(db: Session, toggles: list[str]) -> list[str]:
    rights: list[str] = []
    for t in toggles:
        if t not in TOGGLE_TO_RIGHT:
            raise ValidationFailed(f"unknown function toggle {t}", reason_code="UNKNOWN_FUNCTION")
        if t in PHASE_B_TOGGLES:
            right = TOGGLE_TO_RIGHT[t]
            if not (get_config(db, "delegates.phase_b_switch", False) and delegate_right_enabled(db, right)):
                raise SwitchedOff("Not available yet: only the owner can do this.", reason_code="RIGHT_SWITCHED_OFF", details={"right": right, "toggle": t})
        rights.append(TOGGLE_TO_RIGHT[t])
    return sorted(set(rights))


def _toggles(rights: list | None) -> list[str]:
    return sorted(RIGHT_TO_TOGGLE[r] for r in (rights or []) if r in RIGHT_TO_TOGGLE)


def _count_company_delegates(db: Session, company_id: str) -> int:
    active = db.scalar(select(func.count(CompanyRole.id)).where(CompanyRole.company_id == company_id, CompanyRole.role == "delegate", CompanyRole.status.in_(("active", "suspended")))) or 0
    pending = db.scalar(select(func.count(DelegateInvitation.id)).where(DelegateInvitation.company_id == company_id, DelegateInvitation.status == "pending")) or 0
    return active + pending


def _count_delegate_companies(db: Session, idn_hash: str, identity_uuid: str | None) -> int:
    pending = db.scalar(select(func.count(DelegateInvitation.id)).where(DelegateInvitation.emirates_id_hash == idn_hash, DelegateInvitation.status == "pending")) or 0
    active = 0
    if identity_uuid:
        active = db.scalar(select(func.count(CompanyRole.id)).where(CompanyRole.identity_uuid == identity_uuid, CompanyRole.role == "delegate", CompanyRole.status.in_(("active", "suspended")))) or 0
    return pending + active


def _known_identity_for_hash(db: Session, idn_hash: str) -> str | None:
    """The Emirates ID number is never stored; an identity is known for a hash only through an earlier activation."""
    return db.scalar(select(DelegateInvitation.identity_uuid).where(DelegateInvitation.emirates_id_hash == idn_hash, DelegateInvitation.identity_uuid.isnot(None)).order_by(DelegateInvitation.accepted_at.desc()))


def invite_delegate(db: Session, principal: Principal, company_id: str, *, emirates_id: str, entered_name: str | None, email: str | None, mobile: str | None, toggles: list[str], functions: list[str] | None = None) -> DelegateInvitation:
    from app.modules.identity.service import hash_emirates_id

    _company(db, company_id)
    if not any(r.role in OWNER_LEVEL for r in principal.roles_for(company_id)):
        record_event(db, event_type="ACCESS_REFUSED", category="access", outcome="refused", reason_code="OWNER_ONLY", actor_key=principal.actor_key, actor_role=_role_on(principal, company_id), company_id=company_id, details={"action": "invite_delegate"})
        _refuse(db, Forbidden("Only the company owner can do this. Ask the owner for this right.", reason_code="OWNER_ONLY"))
    digits = normalise_emirates_id(emirates_id)
    idn_hash = hash_emirates_id(digits)
    rights = _validate_toggles(db, toggles)
    if _count_company_delegates(db, company_id) >= _int(db, "delegates.max_delegates_per_company", 10):
        raise ValidationFailed("delegate limit reached for this company", reason_code="DELEGATE_LIMIT_COMPANY", details={"limit": _int(db, "delegates.max_delegates_per_company", 10)})
    known = _known_identity_for_hash(db, idn_hash)
    if _count_delegate_companies(db, idn_hash, known) >= _int(db, "delegates.max_companies_per_delegate", 50):
        raise ValidationFailed("this person already has the maximum number of companies", reason_code="DELEGATE_LIMIT_PERSON", details={"limit": _int(db, "delegates.max_companies_per_delegate", 50)})
    if db.scalar(select(DelegateInvitation).where(DelegateInvitation.company_id == company_id, DelegateInvitation.emirates_id_hash == idn_hash, DelegateInvitation.status == "pending")):
        raise Conflict("an invitation for this person is already pending", reason_code="INVITATION_PENDING")
    if known:
        if db.scalar(select(CompanyRole).where(CompanyRole.identity_uuid == known, CompanyRole.company_id == company_id, CompanyRole.role == "delegate", CompanyRole.status.in_(("active", "suspended")))):
            raise Conflict("this person is already a delegate on this company", reason_code="ALREADY_DELEGATE")
        staff = [r.role for r in db.scalars(select(StaffRole).where(StaffRole.identity_uuid == known, StaffRole.status == "active"))]
        check_role_combination(db, known, company_id, "delegate", staff_roles=staff)
        if "compliance_reviewer" in staff:
            raise Forbidden("a compliance reviewer cannot hold a company role in the same account", reason_code="ROLE_COMBINATION_REFUSED", details={"pair": ["compliance_reviewer", "delegate"]})
    if idn_hash in _licence_person_hashes(db, company_id):
        raise Conflict("this person is already an owner-level person on the licence record", reason_code="ALREADY_OWNER")
    days = _int(db, "delegates.invitation_validity_days", 7)
    inv = DelegateInvitation(company_id=company_id, emirates_id_hash=idn_hash, entered_name=(entered_name or "").strip() or None, email=(email or "").strip().lower() or None, mobile=(mobile or "").strip() or None, functions=functions or ["bookkeeping", "tax_preparation", "uploads"], rights=rights, token=secrets.token_urlsafe(24), invited_by_uuid=principal.identity_uuid, expires_at=utcnow() + timedelta(days=days))
    db.add(inv)
    db.flush()
    _change(db, company_id=company_id, change_type="invited", principal=principal, delegate_label=inv.entered_name, subject_ref=inv.id, after={"toggles": _toggles(rights)})
    record_event(db, event_type="DELEGATE_INVITED", category="access", actor_key=principal.actor_key, actor_role=_role_on(principal, company_id), company_id=company_id, subject_type="delegate_invitation", subject_id=inv.id, details={"toggles": _toggles(rights), "validity_days": days, "channels": [c for c, v in (("email", inv.email), ("mobile", inv.mobile)) if v]})
    return inv


def resend_invitation(db: Session, principal: Principal, company_id: str, invitation_id: str) -> DelegateInvitation:
    inv = db.get(DelegateInvitation, invitation_id)
    if inv is None or inv.company_id != company_id or inv.status not in ("pending", "expired"):
        raise NotFound("invitation not available", reason_code="NOT_FOUND")
    inv.status = "pending"
    inv.resent_at = utcnow()
    inv.expires_at = utcnow() + timedelta(days=_int(db, "delegates.invitation_validity_days", 7))  # resend resets the clock
    inv.token = secrets.token_urlsafe(24)
    _change(db, company_id=company_id, change_type="resent", principal=principal, delegate_label=inv.entered_name, subject_ref=inv.id)
    record_event(db, event_type="DELEGATE_INVITATION_RESENT", category="access", actor_key=principal.actor_key, company_id=company_id, subject_type="delegate_invitation", subject_id=inv.id)
    return inv


def withdraw_invitation(db: Session, principal: Principal, company_id: str, invitation_id: str) -> DelegateInvitation:
    inv = db.get(DelegateInvitation, invitation_id)
    if inv is None or inv.company_id != company_id or inv.status != "pending":
        raise NotFound("invitation not available", reason_code="NOT_FOUND")
    inv.status = "withdrawn"
    inv.withdrawn_at = utcnow()
    _change(db, company_id=company_id, change_type="withdrawn", principal=principal, delegate_label=inv.entered_name, subject_ref=inv.id)
    record_event(db, event_type="DELEGATE_INVITATION_WITHDRAWN", category="access", actor_key=principal.actor_key, company_id=company_id, subject_type="delegate_invitation", subject_id=inv.id)
    return inv


def expire_invitations(db: Session, company_id: str | None = None) -> int:
    stmt = select(DelegateInvitation).where(DelegateInvitation.status == "pending", DelegateInvitation.expires_at < utcnow())
    if company_id:
        stmt = stmt.where(DelegateInvitation.company_id == company_id)
    n = 0
    for inv in db.scalars(stmt):
        inv.status = "expired"
        _change(db, company_id=inv.company_id, change_type="expired", principal=None, delegate_label=inv.entered_name, subject_ref=inv.id)
        record_event(db, event_type="DELEGATE_INVITATION_EXPIRED", category="access", outcome="info", company_id=inv.company_id, subject_type="delegate_invitation", subject_id=inv.id)
        n += 1
    return n


def bind_pending_delegate_invitations(db: Session, identity_uuid: str, idn_hash: str | None) -> list[CompanyRole]:
    """Sign-in hook (called lazily from ``identity.service.complete_signin``): activate every pending invitation
    whose Emirates ID hash equals the assertion's. Exact match only; names are a soft check; mismatch is one
    generic refusal with a log entry. Also runs the signatory-change hold match for the signing-in identity."""
    created: list[CompanyRole] = []
    ident = db.get(Identity, identity_uuid)
    try:
        try_lift_hold_on_signin(db, identity_uuid, idn_hash)
    except Exception:  # never block sign-in on hold reconciliation
        db.rollback()
    if not idn_hash:
        return created
    expire_invitations(db)
    staff = [r.role for r in db.scalars(select(StaffRole).where(StaffRole.identity_uuid == identity_uuid, StaffRole.status == "active"))]
    for inv in db.scalars(select(DelegateInvitation).where(DelegateInvitation.emirates_id_hash == idn_hash, DelegateInvitation.status == "pending")):
        if ident and ident.profile_type == 2 and ident.assurance_level == "SOP1":
            record_event(db, event_type="DELEGATE_ACTIVATION", category="access", outcome="refused", reason_code="VISITOR_LEVEL_REFUSED", identity_uuid=identity_uuid, company_id=inv.company_id, subject_type="delegate_invitation", subject_id=inv.id)
            continue
        try:
            check_role_combination(db, identity_uuid, inv.company_id, "delegate", staff_roles=staff)
            if "compliance_reviewer" in staff:
                raise Forbidden("exclusive role", reason_code="ROLE_COMBINATION_REFUSED")
        except Forbidden as exc:
            inv.status = "withdrawn"
            inv.withdrawn_at = utcnow()
            record_event(db, event_type="DELEGATE_ACTIVATION", category="access", outcome="refused", reason_code=exc.reason_code, identity_uuid=identity_uuid, company_id=inv.company_id, subject_type="delegate_invitation", subject_id=inv.id, details=exc.details)
            continue
        active_companies = db.scalar(select(func.count(CompanyRole.id)).where(CompanyRole.identity_uuid == identity_uuid, CompanyRole.role == "delegate", CompanyRole.status.in_(("active", "suspended")))) or 0
        if active_companies >= _int(db, "delegates.max_companies_per_delegate", 50):
            record_event(db, event_type="DELEGATE_ACTIVATION", category="access", outcome="refused", reason_code="DELEGATE_LIMIT_PERSON", identity_uuid=identity_uuid, company_id=inv.company_id, subject_type="delegate_invitation", subject_id=inv.id)
            continue
        existing = db.scalar(select(CompanyRole).where(CompanyRole.identity_uuid == identity_uuid, CompanyRole.company_id == inv.company_id, CompanyRole.role == "delegate"))
        if existing is None:
            existing = CompanyRole(identity_uuid=identity_uuid, company_id=inv.company_id, role="delegate", capacity="delegate", granted_by_uuid=inv.invited_by_uuid)
            db.add(existing)
        existing.status = "active"
        existing.functions = inv.functions
        existing.rights = inv.rights
        existing.granted_at = utcnow()
        existing.revoked_at = None
        existing.suspended_reason = None
        db.flush()
        inv.status = "accepted"
        inv.accepted_at = utcnow()
        inv.identity_uuid = identity_uuid
        inv.company_role_id = existing.id
        inv.name_differs = name_differs(inv.entered_name, ident.display_name if ident else None)
        _change(db, company_id=inv.company_id, change_type="accepted", principal=None, delegate_identity_uuid=identity_uuid, delegate_label=ident.display_name if ident else inv.entered_name, subject_ref=existing.id, after={"toggles": _toggles(inv.rights), "name_differs": inv.name_differs})
        record_event(db, event_type="DELEGATE_ACTIVATED", category="access", identity_uuid=identity_uuid, actor_role="delegate", company_id=inv.company_id, subject_type="company_role", subject_id=existing.id, details={"invitation_id": inv.id, "toggles": _toggles(inv.rights), "name_differs": inv.name_differs})
        if inv.name_differs:
            record_event(db, event_type="DELEGATE_NAME_DIFFERS", category="access", outcome="info", identity_uuid=identity_uuid, company_id=inv.company_id, subject_type="delegate_invitation", subject_id=inv.id)
        created.append(existing)
    db.flush()
    return created


# --- people list ---------------------------------------------------------------------------------


def list_people(db: Session, company_id: str, *, own_identity: str | None = None) -> list[dict]:
    """People with access to the company: owner-level persons, delegates (any status) and open invitations.
    With ``own_identity`` only that person's rows are returned (delegate's own view)."""
    expire_invitations(db, company_id)
    flag_days = _int(db, "delegates.delegate_dormancy_flag_days", 180)
    hold = get_hold(db, company_id)
    out: list[dict] = []
    for r in db.scalars(select(CompanyRole).where(CompanyRole.company_id == company_id, CompanyRole.role.in_(("owner", "remote_owner", "delegate"))).order_by(CompanyRole.granted_at)):
        if own_identity and r.identity_uuid != own_identity:
            continue
        ident = db.get(Identity, r.identity_uuid) if r.identity_uuid else None
        inv = db.scalar(select(DelegateInvitation).where(DelegateInvitation.company_role_id == r.id)) if r.role == "delegate" else None
        dormant = bool(ident and ident.last_sign_in_at and ident.last_sign_in_at + timedelta(days=flag_days) < utcnow())
        if r.role == "delegate":
            chip = {"active": "active", "suspended": "suspended", "revoked": "removed", "expired": "removed", "invited": "pending"}.get(r.status, r.status)
            if r.status == "active" and hold.hold_state == "no_owner":
                chip = "suspended"
        else:
            chip = "active" if r.status == "active" else r.status
        out.append({
            "kind": "role", "id": r.id, "identity_uuid": r.identity_uuid, "display_name": ident.display_name if ident else None, "role": r.role,
            "status": r.status, "chip": chip, "toggles": _toggles(r.rights) if r.role == "delegate" else [], "functions": r.functions or [], "granted_at": r.granted_at.isoformat(),
            "valid_to": r.valid_to.isoformat() if r.valid_to else None, "suspended_reason": r.suspended_reason, "reconfirm_by": r.reconfirm_by.isoformat() if r.reconfirm_by else None,
            "name_differs": bool(inv and inv.name_differs), "dormant_flag": dormant, "removed_at": r.revoked_at.isoformat() if r.revoked_at else None,
            "authority_label": "suspended_authority_changed" if (r.suspended_reason in ("authority_changed", "no_owner") or (r.role == "delegate" and hold.hold_state == "no_owner")) else None,
        })
    if not own_identity:
        for inv in db.scalars(select(DelegateInvitation).where(DelegateInvitation.company_id == company_id, DelegateInvitation.status.in_(("pending", "expired", "withdrawn"))).order_by(DelegateInvitation.invited_at.desc())):
            out.append({"kind": "invitation", "id": inv.id, "identity_uuid": None, "display_name": inv.entered_name, "role": "delegate", "status": inv.status, "chip": "pending" if inv.status == "pending" else "removed", "toggles": _toggles(inv.rights), "functions": inv.functions or [], "granted_at": inv.invited_at.isoformat(), "expires_at": inv.expires_at.isoformat(), "resent_at": inv.resent_at.isoformat() if inv.resent_at else None, "name_differs": False, "dormant_flag": False, "authority_label": None})
    return out


def _delegate_role(db: Session, company_id: str, role_id: str) -> CompanyRole:
    r = db.get(CompanyRole, role_id)
    if r is None or r.company_id != company_id or r.role != "delegate":
        raise NotFound("not available", reason_code="NOT_FOUND")
    return r


# --- revocation enforcement and quarantine ---------------------------------------------------------


def quarantine_touched_drafts(db: Session, *, identity_uuid: str, company_id: str, principal: Principal | None) -> tuple[list[QuarantinedDraft], int]:
    """Every draft the delegate created/edited/submitted is quarantined (viewing never quarantines).

    Returns the rows held in this module's register and the count held by owning modules in their own screens."""
    providers = list(TOUCHED_DRAFT_PROVIDERS)
    fn = _optional("app.modules.bookkeeping.service", "quarantine_drafts_for")
    if fn:
        providers.append(fn)
    rows: list[QuarantinedDraft] = []
    held_elsewhere = 0
    for provider in providers:
        try:
            touched = provider(db, identity_uuid, company_id) or []
        except Exception:  # a provider failure must not stop revocation
            touched = []
        if isinstance(touched, int):  # the provider held its own drafts (decided in its own screen); count only
            held_elsewhere += touched
            continue
        for item in touched:
            d = item if isinstance(item, dict) else {"draft_type": item[0], "draft_ref": item[1], "touched_action": item[2] if len(item) > 2 else "edited"}
            if d.get("touched_action", "edited") not in ("created", "edited", "submitted"):
                continue
            if db.scalar(select(QuarantinedDraft).where(QuarantinedDraft.company_id == company_id, QuarantinedDraft.draft_ref == d["draft_ref"], QuarantinedDraft.status == "quarantined")):
                continue
            qd = QuarantinedDraft(company_id=company_id, draft_type=d.get("draft_type", "draft"), draft_ref=d["draft_ref"], delegate_identity_uuid=identity_uuid, touched_action=d.get("touched_action", "edited"), data_version=d.get("data_version"))
            db.add(qd)
            db.flush()
            record_event(db, event_type="DRAFT_QUARANTINED", category="access", outcome="info", reason_code="ACCESS_REVOKED", actor_key=principal.actor_key if principal else None, company_id=company_id, subject_type=qd.draft_type, subject_id=qd.draft_ref, details={"quarantine_id": qd.id, "touched": qd.touched_action, "delegate_key": actor_key_for(identity_uuid)})
            rows.append(qd)
    if held_elsewhere:
        record_event(db, event_type="DRAFT_QUARANTINED", category="access", outcome="info", reason_code="ACCESS_REVOKED", actor_key=principal.actor_key if principal else None, company_id=company_id, details={"held_in_owning_module": held_elsewhere, "delegate_key": actor_key_for(identity_uuid)})
    return rows, held_elsewhere


def _enforce_revocation(db: Session, *, identity_uuid: str | None, company_id: str, principal: Principal | None, reason: str, quarantine: bool = True) -> dict:
    """Only the affected delegate is signed out; in-flight exports cancelled (partial files discarded); jobs abort
    at the next tool call with the marker 'stopped by access change'; touched drafts quarantined."""
    actor = principal.actor_key if principal else None
    summary = {"sessions_ended": 0, "exports_cancelled": 0, "jobs_aborted": 0, "drafts_quarantined": 0}
    if not identity_uuid:
        return summary
    record_event(db, event_type="ACCESS_REVOKED", category="access", outcome="info", reason_code=reason.upper(), actor_key=actor, company_id=company_id, subject_type="identity", subject_id=actor_key_for(identity_uuid), details={"scope": company_id})
    for sess in db.scalars(select(UserSession).where(UserSession.identity_uuid == identity_uuid, UserSession.ended_at.is_(None))):
        sess.ended_at = utcnow()
        sess.end_reason = "revoked"
        summary["sessions_ended"] += 1
        record_event(db, event_type="SESSION_ENDED", category="access", outcome="info", reason_code="ACCESS_REVOKED", identity_uuid=identity_uuid, company_id=company_id, details={"scope": company_id})
    fn = _optional("app.modules.documents.service", "cancel_exports_for")
    summary["exports_cancelled"] = int(fn(db, identity_uuid, company_id) or 0) if fn else 0
    record_event(db, event_type="EXPORT_CANCELLED", category="access", outcome="info", reason_code="ACCESS_REVOKED", actor_key=actor, company_id=company_id, details={"count": summary["exports_cancelled"], "partial_files": "discarded"})
    fn = _optional("app.modules.bookkeeping.service", "abort_jobs_for")
    summary["jobs_aborted"] = int(fn(db, identity_uuid, company_id) or 0) if fn else 0
    record_event(db, event_type="JOB_ABORTED", category="access", outcome="info", reason_code="ACCESS_REVOKED", actor_key=actor, company_id=company_id, details={"count": summary["jobs_aborted"], "marker": "stopped by access change"})
    if quarantine:
        rows, held_elsewhere = quarantine_touched_drafts(db, identity_uuid=identity_uuid, company_id=company_id, principal=principal)
        summary["drafts_quarantined"] = len(rows) + held_elsewhere
    fn = _optional("app.modules.reminders.service", "on_access_lost")
    if fn:
        try:
            fn(db, company_id, identity_uuid)  # their reminders are cancelled; the deadlines stay with the owner
        except Exception:  # never let a reminder failure block revocation
            record_event(db, event_type="REMINDER_REROUTE_FAILED", category="reminder", outcome="failed", company_id=company_id)
    db.flush()
    return summary


def change_rights(db: Session, principal: Principal, company_id: str, role_id: str, *, toggles: list[str], functions: list[str] | None = None) -> dict:
    """Edit a delegate's rights: effective on the delegate's next request; a reduction signs out only that
    delegate and quarantines every draft they touched; an extension is just recorded."""
    r = _delegate_role(db, company_id, role_id)
    new_rights = _validate_toggles(db, toggles)
    before = {"toggles": _toggles(r.rights), "functions": r.functions or []}
    reduced = bool(set(r.rights or []) - set(new_rights)) or (functions is not None and bool(set(r.functions or []) - set(functions)))
    r.rights = new_rights
    if functions is not None:
        r.functions = functions
    after = {"toggles": _toggles(new_rights), "functions": r.functions or []}
    name = _identity_name(db, r.identity_uuid)
    change = _change(db, company_id=company_id, change_type="rights_changed", principal=principal, delegate_identity_uuid=r.identity_uuid, delegate_label=name, subject_ref=r.id, before=before, after=after)
    record_event(db, event_type="DELEGATION_CHANGE", category="access", actor_key=principal.actor_key, actor_role=_role_on(principal, company_id), company_id=company_id, subject_type="company_role", subject_id=r.id, details={"before": before["toggles"], "after": after["toggles"], "reduced": reduced, "change_id": change.id})
    summary = _enforce_revocation(db, identity_uuid=r.identity_uuid, company_id=company_id, principal=principal, reason="rights_reduced") if reduced else {"sessions_ended": 0, "exports_cancelled": 0, "jobs_aborted": 0, "drafts_quarantined": 0}
    db.flush()
    return {"role_id": r.id, "display_name": name, "toggles": after["toggles"], "reduced": reduced, **summary}


def remove_delegate(db: Session, principal: Principal | None, company_id: str, role_id: str, *, reason: str = "owner_removed") -> dict:
    r = _delegate_role(db, company_id, role_id)
    if r.status == "revoked":
        raise Conflict("already removed", reason_code="ALREADY_REMOVED")
    before = {"toggles": _toggles(r.rights), "status": r.status}
    r.status = "revoked"
    r.revoked_at = utcnow()
    r.suspended_reason = reason
    name = _identity_name(db, r.identity_uuid)
    _change(db, company_id=company_id, change_type="removed", principal=principal, delegate_identity_uuid=r.identity_uuid, delegate_label=name, subject_ref=r.id, before=before, after={"status": "removed"}, reason=reason)
    record_event(db, event_type="DELEGATION_CHANGE", category="access", reason_code="REMOVED", actor_key=principal.actor_key if principal else None, actor_role=_role_on(principal, company_id), company_id=company_id, subject_type="company_role", subject_id=r.id, details={"removal_reason": reason})
    summary = _enforce_revocation(db, identity_uuid=r.identity_uuid, company_id=company_id, principal=principal, reason=reason)
    return {"role_id": r.id, "display_name": name, "status": "removed", **summary}


def suspend_delegate(db: Session, principal: Principal, company_id: str, role_id: str) -> CompanyRole:
    r = _delegate_role(db, company_id, role_id)
    if r.status != "active":
        raise Conflict("delegate is not active", reason_code="NOT_ACTIVE")
    r.status = "suspended"
    r.suspended_reason = "owner_suspended"
    _change(db, company_id=company_id, change_type="suspended", principal=principal, delegate_identity_uuid=r.identity_uuid, delegate_label=_identity_name(db, r.identity_uuid), subject_ref=r.id)
    record_event(db, event_type="DELEGATION_CHANGE", category="access", reason_code="SUSPENDED", actor_key=principal.actor_key, actor_role=_role_on(principal, company_id), company_id=company_id, subject_type="company_role", subject_id=r.id)
    _enforce_revocation(db, identity_uuid=r.identity_uuid, company_id=company_id, principal=principal, reason="suspended", quarantine=False)
    return r


def reinstate_delegate(db: Session, principal: Principal, company_id: str, role_id: str) -> CompanyRole:
    r = _delegate_role(db, company_id, role_id)
    if r.status != "suspended":
        raise Conflict("delegate is not suspended", reason_code="NOT_SUSPENDED")
    r.status = "active"
    r.suspended_reason = None
    r.reconfirm_by = None
    _change(db, company_id=company_id, change_type="reinstated", principal=principal, delegate_identity_uuid=r.identity_uuid, delegate_label=_identity_name(db, r.identity_uuid), subject_ref=r.id)
    record_event(db, event_type="DELEGATION_CHANGE", category="access", reason_code="REINSTATED", actor_key=principal.actor_key, actor_role=_role_on(principal, company_id), company_id=company_id, subject_type="company_role", subject_id=r.id)
    return r


def list_quarantine(db: Session, company_id: str, *, status: str | None = "quarantined") -> list[dict]:
    stmt = select(QuarantinedDraft).where(QuarantinedDraft.company_id == company_id).order_by(QuarantinedDraft.quarantined_at.desc())
    if status:
        stmt = stmt.where(QuarantinedDraft.status == status)
    return [
        {"id": q.id, "draft_type": q.draft_type, "draft_ref": q.draft_ref, "delegate_identity_uuid": q.delegate_identity_uuid, "delegate_name": _identity_name(db, q.delegate_identity_uuid), "touched_action": q.touched_action, "marker": q.marker, "status": q.status, "quarantined_at": q.quarantined_at.isoformat(), "decided_at": q.decided_at.isoformat() if q.decided_at else None, "new_draft_ref": q.new_draft_ref, "is_demo": q.is_demo}
        for q in db.scalars(stmt)
    ]


DECISIONS = {"keep": "released", "release": "released", "discard": "rejected", "reject": "rejected", "reassign": "reassigned"}


def decide_quarantine(db: Session, principal: Principal, company_id: str, quarantine_id: str, *, decision: str, reassign_to: str | None = None) -> QuarantinedDraft:
    """Owner decision Keep / Reassign / Discard (= release / reassign / reject). Nothing is released automatically."""
    q = db.get(QuarantinedDraft, quarantine_id)
    if q is None or q.company_id != company_id:
        raise NotFound("not available", reason_code="NOT_FOUND")
    if q.status != "quarantined":
        raise Conflict("this draft has already been decided", reason_code="ALREADY_DECIDED")
    new_status = DECISIONS.get(decision)
    if new_status is None:
        raise ValidationFailed("decision must be keep, reassign or discard", reason_code="DECISION_INVALID")
    if new_status == "reassigned":
        target = reassign_to or principal.identity_uuid
        if target != principal.identity_uuid and not db.scalar(select(CompanyRole).where(CompanyRole.identity_uuid == target, CompanyRole.company_id == company_id, CompanyRole.status == "active")):
            raise ValidationFailed("reassignment target must have access to this company", reason_code="REASSIGN_TARGET_INVALID")
        q.reassigned_to_uuid = target
        q.new_draft_ref = f"{q.draft_ref}:v2"  # reassign creates a new draft version for another delegate or the owner
    q.status = new_status
    q.decided_by_uuid = principal.identity_uuid
    q.decided_at = utcnow()
    q.decision_identity_level = principal.assurance_level
    fn = _optional("app.modules.bookkeeping.service", "apply_quarantine_decision")
    if fn:
        try:
            fn(db, q.draft_type, q.draft_ref, new_status, q.new_draft_ref, q.reassigned_to_uuid)
        except Exception:
            pass
    _change(db, company_id=company_id, change_type="quarantine_decision", principal=principal, delegate_identity_uuid=q.delegate_identity_uuid, delegate_label=_identity_name(db, q.delegate_identity_uuid), subject_ref=q.id, after={"decision": new_status, "draft_ref": q.draft_ref, "new_draft_ref": q.new_draft_ref})
    record_event(db, event_type="QUARANTINE_DECIDED", category="approval", actor_key=principal.actor_key, actor_role=_role_on(principal, company_id), company_id=company_id, subject_type=q.draft_type, subject_id=q.draft_ref, details={"quarantine_id": q.id, "decision": new_status, "data_version": q.data_version, "identity_level": principal.assurance_level, "new_draft_ref": q.new_draft_ref})
    return q


def is_quarantined(db: Session, company_id: str, draft_ref: str) -> bool:
    """Approval/release modules call this: a quarantined draft cannot be approved, submitted or released."""
    return db.scalar(select(QuarantinedDraft).where(QuarantinedDraft.company_id == company_id, QuarantinedDraft.draft_ref == draft_ref, QuarantinedDraft.status == "quarantined")) is not None


def recent_changes(db: Session, company_id: str, *, limit: int = 20, identity_uuid: str | None = None) -> list[dict]:
    stmt = select(DelegateChange).where(DelegateChange.company_id == company_id).order_by(DelegateChange.changed_at.desc()).limit(limit)
    if identity_uuid:
        stmt = stmt.where(DelegateChange.delegate_identity_uuid == identity_uuid)
    return [_change_row(db, c) for c in db.scalars(stmt)]


def _change_row(db: Session, c: DelegateChange) -> dict:
    company = db.get(Company, c.company_id)
    return {"id": c.id, "company_id": c.company_id, "company_name_en": company.trade_name_en if company else None, "company_name_ar": company.trade_name_ar if company else None, "change_type": c.change_type, "delegate_label": c.delegate_label, "before": c.before, "after": c.after, "reason": c.reason, "changed_by_name": _identity_name(db, c.changed_by_uuid), "changed_by_role": c.changed_by_role, "changed_at": c.changed_at.isoformat(), "acknowledged": c.acknowledged_at is not None}


def my_access_changes(db: Session, identity_uuid: str) -> list[dict]:
    """Rights edits and removals affecting the signed-in delegate that they have not yet acknowledged (30-second
    client check). Other delegates are never told."""
    stmt = select(DelegateChange).where(DelegateChange.delegate_identity_uuid == identity_uuid, DelegateChange.change_type.in_(("rights_changed", "removed", "suspended", "reinstated", "authority_suspended")), DelegateChange.acknowledged_at.is_(None)).order_by(DelegateChange.changed_at.desc())
    return [_change_row(db, c) for c in db.scalars(stmt)]


def acknowledge_change(db: Session, identity_uuid: str, change_id: str) -> None:
    c = db.get(DelegateChange, change_id)
    if c is None or c.delegate_identity_uuid != identity_uuid:
        raise NotFound("not available", reason_code="NOT_FOUND")
    c.acknowledged_at = utcnow()


# --- dormancy --------------------------------------------------------------------------------------


def run_dormancy_check(db: Session) -> dict:
    """Delegates dormant 180 days are flagged to the owner (stay active); staff dormant 90 days are suspended."""
    flag_days = _int(db, "delegates.delegate_dormancy_flag_days", 180)
    staff_days = _int(db, "delegates.staff_dormancy_suspend_days", 90)
    now = utcnow()
    flagged = suspended = 0
    for r in db.scalars(select(CompanyRole).where(CompanyRole.role == "delegate", CompanyRole.status == "active")):
        ident = db.get(Identity, r.identity_uuid) if r.identity_uuid else None
        last = (ident.last_sign_in_at if ident and ident.last_sign_in_at else r.granted_at)
        if last + timedelta(days=flag_days) < now:
            already = db.scalar(select(DelegateChange).where(DelegateChange.subject_ref == r.id, DelegateChange.change_type == "dormancy_flagged", DelegateChange.changed_at >= now - timedelta(days=flag_days)))
            if already is None:
                _change(db, company_id=r.company_id, change_type="dormancy_flagged", principal=None, delegate_identity_uuid=r.identity_uuid, delegate_label=ident.display_name if ident else None, subject_ref=r.id)
                record_event(db, event_type="DELEGATE_DORMANT_FLAGGED", category="access", outcome="info", company_id=r.company_id, subject_type="company_role", subject_id=r.id, details={"days": flag_days})
                flagged += 1
    for srow in db.scalars(select(StaffRole).where(StaffRole.status == "active", StaffRole.identity_uuid.isnot(None))):
        ident = db.get(Identity, srow.identity_uuid)
        last = ident.last_sign_in_at if ident and ident.last_sign_in_at else (srow.bound_at or srow.created_at)
        if last + timedelta(days=staff_days) < now:
            srow.status = "suspended"
            record_event(db, event_type="STAFF_ROLE_SUSPENDED", category="access", outcome="info", reason_code="DORMANT", identity_uuid=srow.identity_uuid, details={"role": srow.role, "days": staff_days, "re_approval_required": True})
            suspended += 1
    db.flush()
    return {"delegates_flagged": flagged, "staff_suspended": suspended}


# --- per-case access grants -----------------------------------------------------------------------


def create_grant(db: Session, principal: Principal, company_id: str, *, recipient_identity_uuid: str, recipient_role: str, case_ref: str, purpose: str, data_scope: list[str], days: int | None = None) -> AccessGrant:
    """Granted only by the owner / authorised signatory (never a delegate); time-limited; revocable; logged."""
    _company(db, company_id)
    if not any(r.role in OWNER_LEVEL for r in principal.roles_for(company_id)):
        record_event(db, event_type="ACCESS_REFUSED", category="access", outcome="refused", reason_code="OWNER_ONLY", actor_key=principal.actor_key, company_id=company_id, details={"action": "create_grant"})
        _refuse(db, Forbidden("Only the company owner can do this. Ask the owner for this right.", reason_code="OWNER_ONLY"))
    if recipient_role not in ("specialist", "licensed_auditor"):
        raise ValidationFailed("recipient role must be specialist or licensed_auditor", reason_code="ROLE_INVALID")
    if not case_ref or not purpose:
        raise ValidationFailed("case reference and purpose are required", reason_code="VALIDATION_FAILED")
    staff = [r.role for r in db.scalars(select(StaffRole).where(StaffRole.identity_uuid == recipient_identity_uuid, StaffRole.status == "active"))]
    if "det_admin" in staff or "compliance_reviewer" in staff:
        raise Forbidden("this person's role cannot hold a company case grant", reason_code="ROLE_COMBINATION_REFUSED", details={"pair": [staff[0], recipient_role]})
    check_role_combination(db, recipient_identity_uuid, company_id, recipient_role, staff_roles=staff)
    max_days = _int(db, "delegates.case_grant_expiry_days", 90)
    days = min(days or max_days, max_days)
    grant = AccessGrant(company_id=company_id, case_ref=case_ref, recipient_identity_uuid=recipient_identity_uuid, recipient_role=recipient_role, purpose=purpose, data_scope=sorted(set(data_scope or [])), granted_by_uuid=principal.identity_uuid, granted_by_capacity=principal.roles_for(company_id)[0].capacity, expires_at=utcnow() + timedelta(days=days))
    db.add(grant)
    db.flush()
    record_event(db, event_type="CASE_GRANT_CREATED", category="access", actor_key=principal.actor_key, actor_role=_role_on(principal, company_id), company_id=company_id, subject_type="access_grant", subject_id=grant.id, details={"case_ref": case_ref, "recipient_key": actor_key_for(recipient_identity_uuid), "recipient_role": recipient_role, "purpose": purpose, "data_scope": grant.data_scope, "days": days})
    return grant


def revoke_grant(db: Session, principal: Principal, company_id: str, grant_id: str) -> AccessGrant:
    g = db.get(AccessGrant, grant_id)
    if g is None or g.company_id != company_id:
        raise NotFound("not available", reason_code="NOT_FOUND")
    if g.revoked_at is None:
        g.revoked_at = utcnow()
        g.revoked_by_uuid = principal.identity_uuid
        record_event(db, event_type="CASE_GRANT_REVOKED", category="access", actor_key=principal.actor_key, actor_role=_role_on(principal, company_id), company_id=company_id, subject_type="access_grant", subject_id=g.id, details={"case_ref": g.case_ref})
        _enforce_revocation(db, identity_uuid=g.recipient_identity_uuid, company_id=company_id, principal=principal, reason="grant_revoked", quarantine=False)
    return g


def list_grants(db: Session, company_id: str) -> list[dict]:
    now = utcnow()
    return [
        {"id": g.id, "case_ref": g.case_ref, "recipient_identity_uuid": g.recipient_identity_uuid, "recipient_name": _identity_name(db, g.recipient_identity_uuid), "recipient_role": g.recipient_role, "purpose": g.purpose, "data_scope": g.data_scope or [], "granted_at": g.granted_at.isoformat(), "expires_at": g.expires_at.isoformat(), "revoked_at": g.revoked_at.isoformat() if g.revoked_at else None, "status": "revoked" if g.revoked_at else ("expired" if g.expires_at < now else "active"), "is_demo": g.is_demo}
        for g in db.scalars(select(AccessGrant).where(AccessGrant.company_id == company_id).order_by(AccessGrant.granted_at.desc()))
    ]


def has_valid_grant(db: Session, identity_uuid: str, company_id: str, case_ref: str) -> bool:
    """Record exists, unexpired, unrevoked and names this recipient and case."""
    now = utcnow()
    return db.scalar(select(AccessGrant).where(AccessGrant.recipient_identity_uuid == identity_uuid, AccessGrant.company_id == company_id, AccessGrant.case_ref == case_ref, AccessGrant.revoked_at.is_(None), AccessGrant.expires_at > now)) is not None


def require_grant(db: Session, principal: Principal, company_id: str, case_ref: str) -> AccessGrant:
    """Fail closed: specialists and auditors read company data only under a valid per-case grant; refusals logged."""
    now = utcnow()
    g = db.scalar(select(AccessGrant).where(AccessGrant.recipient_identity_uuid == principal.identity_uuid, AccessGrant.company_id == company_id, AccessGrant.case_ref == case_ref, AccessGrant.revoked_at.is_(None), AccessGrant.expires_at > now))
    if g is None:
        record_event(db, event_type="ACCESS_REFUSED", category="access", outcome="refused", reason_code="NO_CASE_GRANT", actor_key=principal.actor_key, actor_role=principal.primary_role(), company_id=company_id, details={"case_ref": case_ref})
        _refuse(db, Forbidden("you do not have access to this action", reason_code="NO_PERMISSION", details={"case_ref": case_ref}))
    record_event(db, event_type="DATA_ACCESS", category="data_access", actor_key=principal.actor_key, actor_role=g.recipient_role, company_id=company_id, subject_type="case", subject_id=case_ref, details={"grant_id": g.id, "purpose": g.purpose})
    return g


# --- auditor firewall --------------------------------------------------------------------------------


def related_entities(db: Session, company_id: str) -> list[dict]:
    """Related-entity links from DET licence records: same related_entity_group and shared licence persons (hashes)."""
    company = _company(db, company_id)
    links: dict[str, dict] = {}
    if company.related_entity_group:
        for c in db.scalars(select(Company).where(Company.related_entity_group == company.related_entity_group, Company.id != company_id)):
            links[c.id] = {"company_id": c.id, "link": "related_entity_group", "group": company.related_entity_group}
    own_hashes = _licence_person_hashes(db, company_id)
    if own_hashes:
        rows = db.execute(select(Licence.company_id).join(LicencePerson, LicencePerson.licence_id == Licence.id).where(LicencePerson.emirates_id_hash.in_(own_hashes), Licence.company_id != company_id).distinct()).all()
        for (cid,) in rows:
            links.setdefault(cid, {"company_id": cid, "link": "shared_licence_person"})
    return list(links.values())


def evaluate_firewall(db: Session, auditor_identity_uuid: str, company_id: str, engagement_id: str, *, firm: str | None = None) -> FirewallRecord:
    """Conservative first screen from DET records: refuse on hit, never clear on miss. Result wording is
    'conflict_found' or 'no_conflict_found_in_det_records' (never 'independent'). Re-evaluated on each call;
    a new hit suspends an active engagement record."""
    _company(db, company_id)
    links = related_entities(db, company_id)
    scope_ids = [company_id] + [link["company_id"] for link in links]
    hits: list[dict] = []
    # The auditor (or an account they hold) as owner / signatory / delegate / specialist of the engaged or a linked company.
    for r in db.scalars(select(CompanyRole).where(CompanyRole.identity_uuid == auditor_identity_uuid, CompanyRole.company_id.in_(scope_ids), CompanyRole.role != "licensed_auditor")):
        hits.append({"company_id": r.company_id, "role": r.role, "status": r.status, "via": "same_company" if r.company_id == company_id else "related_entity"})
    rule_version = str(get_config(db, "delegates.firewall_rule_version", "firewall-v1"))
    rec = db.scalar(select(FirewallRecord).where(FirewallRecord.engagement_id == engagement_id, FirewallRecord.auditor_identity_uuid == auditor_identity_uuid))
    flags = list(rec.manual_conflict_flags or []) if rec else []
    result = "conflict_found" if hits or flags else "no_conflict_found_in_det_records"
    if rec is None:
        rec = FirewallRecord(engagement_id=engagement_id, company_id=company_id, auditor_identity_uuid=auditor_identity_uuid, firm=firm, related_entity_links_used=links, rule_version=rule_version, result=result, manual_conflict_flags=flags)
        db.add(rec)
    else:
        if rec.result == "no_conflict_found_in_det_records" and result == "conflict_found":
            rec.status = "suspended"
        rec.related_entity_links_used = links
        rec.rule_version = rule_version
        rec.result = result
        rec.firm = firm or rec.firm
        rec.evaluated_at = utcnow()
        rec.evaluation_count = (rec.evaluation_count or 1) + 1
    db.flush()
    record_event(db, event_type="FIREWALL_EVALUATED", category="access", outcome="refused" if result == "conflict_found" else "success", reason_code="FIREWALL_CONFLICT" if result == "conflict_found" else None, identity_uuid=auditor_identity_uuid, actor_role="licensed_auditor", company_id=company_id, subject_type="engagement", subject_id=engagement_id, details={"rule_version": rule_version, "links_used": len(links), "hits": [{"company_id": h["company_id"], "role": h["role"], "via": h["via"]} for h in hits], "manual_flags": len(flags), "control": "product control, not a legal finding"})
    return rec


def declare_independence(db: Session, principal: Principal, engagement_id: str) -> FirewallRecord:
    rec = db.scalar(select(FirewallRecord).where(FirewallRecord.engagement_id == engagement_id, FirewallRecord.auditor_identity_uuid == principal.identity_uuid))
    if rec is None:
        raise NotFound("not available", reason_code="NOT_FOUND")
    rec.independence_declared_at = utcnow()
    record_event(db, event_type="INDEPENDENCE_DECLARED", category="sign_off", actor_key=principal.actor_key, actor_role="licensed_auditor", company_id=rec.company_id, subject_type="engagement", subject_id=engagement_id, details={"rule_version": rec.rule_version})
    return rec


def add_manual_conflict_flag(db: Session, principal: Principal, engagement_id: str, *, code: str) -> FirewallRecord:
    """Manual conflict flag by a reviewer or the owner: blocking until cleared outside the portal."""
    rec = db.scalar(select(FirewallRecord).where(FirewallRecord.engagement_id == engagement_id))
    if rec is None:
        raise NotFound("not available", reason_code="NOT_FOUND")
    flags = list(rec.manual_conflict_flags or [])
    flags.append({"code": code, "by_role": principal.primary_role(), "at": utcnow().isoformat()})
    rec.manual_conflict_flags = flags
    rec.result = "conflict_found"
    rec.status = "suspended"
    record_event(db, event_type="FIREWALL_MANUAL_FLAG", category="access", outcome="refused", reason_code="FIREWALL_CONFLICT", actor_key=principal.actor_key, actor_role=principal.primary_role(), company_id=rec.company_id, subject_type="engagement", subject_id=engagement_id, details={"code": code})
    return rec


def firewall_clear(db: Session, engagement_id: str, auditor_identity_uuid: str) -> bool:
    rec = db.scalar(select(FirewallRecord).where(FirewallRecord.engagement_id == engagement_id, FirewallRecord.auditor_identity_uuid == auditor_identity_uuid))
    return bool(rec and rec.result == "no_conflict_found_in_det_records" and rec.independence_declared_at and not rec.manual_conflict_flags and rec.status == "active")


def firewall_row(rec: FirewallRecord) -> dict:
    return {"id": rec.id, "engagement_id": rec.engagement_id, "company_id": rec.company_id, "firm": rec.firm, "result": rec.result, "rule_version": rec.rule_version, "links_used": len(rec.related_entity_links_used or []), "independence_declared_at": rec.independence_declared_at.isoformat() if rec.independence_declared_at else None, "manual_conflict_flags": len(rec.manual_conflict_flags or []), "status": rec.status, "evaluated_at": rec.evaluated_at.isoformat()}


# --- SC15 owner/delegate activity list -------------------------------------------------------------

# Event types shown, mapped to one of the 14 plain-language wordings. Anything else never appears (AML and
# security detail included), leaving no gap.
EVENT_MAP: dict[str, int] = {
    "SIGN_IN": 1, "DATA_ACCESS": 2, "COMPANY_DATA_VIEWED": 2, "DOCUMENT_UPLOADED": 3, "AGENT_ACTION": 4, "DRAFT_PREPARED": 4, "DRAFT_READY_FOR_REVIEW": 4,
    "APPROVAL_RECORDED": 5, "APPROVAL_DECIDED": 5, "APPROVAL_VOIDED": 6, "CONSENT_GRANTED": 7, "CONSENT_PAUSED": 7, "CONSENT_RESUMED": 7, "CONSENT_WITHDRAWN": 7,
    "DELEGATE_INVITED": 8, "DELEGATE_ACTIVATED": 8, "DELEGATION_CHANGE": 8, "DRAFT_QUARANTINED": 8, "QUARANTINE_DECIDED": 8,
    "ESCALATION_OPENED": 9, "ESCALATION_UPDATED": 9, "ESCALATION_CLOSED": 9, "AUDIT_DRAFT_REVIEWED": 10, "AUDIT_DRAFT_RETURNED": 10, "SIGN_OFF": 11, "AUDIT_REPORT_SIGNED": 11,
    "DOCUMENT_ISSUED": 12, "DOCUMENT_SUPERSEDED": 12, "SUBSCRIPTION_STARTED": 13, "SUBSCRIPTION_RENEWED": 13, "SUBSCRIPTION_CANCELLED": 13, "SUBSCRIPTION_PAUSED": 13,
    "EXPORT_DOWNLOADED": 14, "RECORDS_EXPORTED": 14, "ACTIVITY_EXPORTED": 14,
}
# Refused attempts shown with outcome 'refused' (consent / approval / delegation attempts).
REFUSED_PERMISSION_MAP = {"consent.grant": 7, "consent.withdraw": 7, "returns.approve": 5, "delegates.manage": 8, "subscription.change": 13}
EXCLUDED_PREFIXES = ("AML", "SECURITY", "KEY_", "PROBE")


def _word(code: str, lang: str) -> str:
    return WORDS.get(code, {}).get(lang) or code


def _purpose(code: str | None, lang: str) -> str:
    return PURPOSES.get(code or "review", PURPOSES["review"])[lang]


def _fill(key: str, lang: str, **params: str) -> str:
    return s(key, lang, **params)


def _wording(idx: int, ev: AuditEvent, lang: str, name: str | None) -> str:
    d = ev.details or {}
    if idx == 1:
        return _fill("ev_1", lang)
    if idx == 2:
        return _fill("ev_2", lang, purpose=_purpose(d.get("purpose"), lang), **{"الغرض": _purpose(d.get("purpose"), lang)})
    if idx == 3:
        fname = str(d.get("file_name") or d.get("document_name") or PURPOSES["documents"][lang])  # never an opaque id
        return _fill("ev_3", lang, **{"file name": fname, "اسم الملف": fname})
    if idx == 4:
        item = _purpose(d.get("item") or ev.subject_type, lang)
        return _fill("ev_4", lang, item=item, **{"البند": item})
    if idx == 5:
        tax = _purpose(d.get("tax_type"), lang) if d.get("tax_type") else ""
        period = str(d.get("period") or "")
        return _fill("ev_5", lang, **{"tax type": tax, "period": period, "نوع الضريبة": tax, "الفترة": period})
    if idx == 6:
        return _fill("ev_6", lang)
    if idx == 7:
        action = {"CONSENT_GRANTED": "given", "CONSENT_PAUSED": "paused", "CONSENT_RESUMED": "resumed", "CONSENT_WITHDRAWN": "withdrawn"}.get(ev.event_type, "given")
        purpose = _purpose(d.get("purpose") or "bank_data", lang)
        return _fill("ev_7", lang, purpose=purpose, **{"given / paused / resumed / withdrawn": _word(action, lang), "منح / إيقاف / استئناف / سحب": _word(action, lang), "الغرض": purpose})
    if idx == 8:
        action = "added" if ev.event_type in ("DELEGATE_INVITED", "DELEGATE_ACTIVATED") else ("removed" if (ev.reason_code or "") == "REMOVED" else "changed")
        who = name or ""
        return _fill("ev_8", lang, name=who, **{"added / changed / removed": _word(action, lang), "إضافة / تعديل / إزالة": _word(action, lang), "الاسم": who})
    if idx == 9:
        action = {"ESCALATION_OPENED": "opened", "ESCALATION_UPDATED": "updated", "ESCALATION_CLOSED": "closed"}[ev.event_type]
        return _fill("ev_9", lang, **{"opened / updated / closed": _word(action, lang), "فتح / تحديث / إغلاق": _word(action, lang)})
    if idx == 10:
        action = "returned" if ev.event_type.endswith("RETURNED") else "reviewed"
        return _fill("ev_10", lang, **{"reviewed / returned": _word(action, lang)})
    if idx == 11:
        return _fill("ev_11", lang)
    if idx == 12:
        dname = str(d.get("document_name") or d.get("file_name") or PURPOSES["documents"][lang])
        text = _fill("ev_12", lang, name=dname, **{"الاسم": dname})
        return text
    if idx == 13:
        action = ev.event_type.split("_", 1)[1].lower()
        return _fill("ev_13", lang, **{"started / renewed / cancelled / paused": _word(action, lang), "بدء / تجديد / إلغاء / إيقاف": _word(action, lang)})
    return _fill("ev_14", lang)


def _actor_line(db: Session, ev: AuditEvent, lang: str, company_id: str, cache: dict) -> tuple[str, str | None]:
    """Returns (actor line, actor_key). Owners never see personal names of DET staff or specialists."""
    if ev.category == "agent" or ev.actor_role == "agent" or (ev.actor_key is None and (ev.details or {}).get("agent")):
        return _fill("actor_ai", lang), None
    if not ev.actor_key:
        return _fill("actor_det", lang) if (ev.details or {}).get("by") == "det" else _fill("actor_ai", lang), None
    if ev.actor_key in cache:
        return cache[ev.actor_key]
    mapping = db.get(ActorIdentityMap, ev.actor_key)
    ident = db.get(Identity, mapping.identity_uuid) if mapping else None
    name = ident.display_name if ident else "—"
    roles = [r.role for r in db.scalars(select(CompanyRole).where(CompanyRole.identity_uuid == mapping.identity_uuid, CompanyRole.company_id == company_id))] if mapping else []
    staff = [r for r in db.scalars(select(StaffRole).where(StaffRole.identity_uuid == mapping.identity_uuid, StaffRole.status == "active"))] if mapping else []
    if any(r in OWNER_LEVEL for r in roles):
        line = _fill("actor_owner", lang, Name=name, **{"الاسم": name})
    elif "delegate" in roles:
        line = _fill("actor_delegate", lang, Name=name, **{"الاسم": name})
    elif any(sr.role == "licensed_auditor" for sr in staff) or "licensed_auditor" in roles:
        firm = next((sr.scope for sr in staff if sr.role == "licensed_auditor" and sr.scope), None) or (ev.details or {}).get("firm") or "—"
        line = _fill("actor_auditor", lang, firm=str(firm), **{"الشركة": str(firm)})
    elif any(sr.role in SPECIALIST_LABELS for sr in staff) or "specialist" in roles:
        code = next((sr.role for sr in staff if sr.role in SPECIALIST_LABELS), "tax_specialist")
        label = SPECIALIST_LABELS[code][lang]
        if ev.subject_type == "case" and ev.subject_id:
            label = f"{label} · {ev.subject_id}"
        line = _fill("actor_specialist", lang, **{"coded role label": label, "التسمية": label})
    elif any(sr.role.startswith("det_") for sr in staff):
        line = _fill("actor_det", lang)
    else:
        line = _fill("actor_owner", lang, Name=name, **{"الاسم": name}) if roles else _fill("actor_det", lang)
    cache[ev.actor_key] = (line, ev.actor_key)
    return line, ev.actor_key


def _member_keys(db: Session, company_id: str) -> set[str]:
    keys = set()
    for (uuid,) in db.execute(select(CompanyRole.identity_uuid).where(CompanyRole.company_id == company_id, CompanyRole.identity_uuid.isnot(None))).all():
        k = actor_key_for(uuid)
        if k:
            keys.add(k)
    return keys


def _subject_name(db: Session, ev: AuditEvent) -> str | None:
    if ev.subject_type == "company_role" and ev.subject_id:
        r = db.get(CompanyRole, ev.subject_id)
        return _identity_name(db, r.identity_uuid) if r else None
    if ev.subject_type == "delegate_invitation" and ev.subject_id:
        inv = db.get(DelegateInvitation, ev.subject_id)
        return inv.entered_name if inv else None
    if ev.event_type in ("DRAFT_QUARANTINED", "QUARANTINE_DECIDED"):
        qid = (ev.details or {}).get("quarantine_id")
        q = db.get(QuarantinedDraft, qid) if qid else None
        return _identity_name(db, q.delegate_identity_uuid) if q else None
    return None


def activity_rows(db: Session, principal: Principal, company_id: str, *, lang: str = "en", page: int = 1, event_kind: int | None = None, since: datetime | None = None, until: datetime | None = None, actor_key: str | None = None, outcome: str | None = None) -> dict:
    """Plain-language rows; newest first; 50 per page (config). Owner sees every actor on the company; a
    delegate sees only their own actions (including refused and quarantined)."""
    company = _company(db, company_id)
    page_size = _int(db, "delegates.sc15_page_size", 50)
    is_owner = any(r.role in OWNER_LEVEL for r in principal.roles_for(company_id))
    own_only = not is_owner
    member_keys = _member_keys(db, company_id)
    types = list(EVENT_MAP) + ["ACCESS_REFUSED"]
    stmt = select(AuditEvent).where(AuditEvent.event_type.in_(types)).order_by(AuditEvent.id.desc())
    stmt = stmt.where(((AuditEvent.company_id == company_id)) | ((AuditEvent.event_type == "SIGN_IN") & (AuditEvent.company_id.is_(None)) & (AuditEvent.actor_key.in_(member_keys or {"-"}))))
    if own_only:
        stmt = stmt.where(AuditEvent.actor_key == principal.actor_key)
    elif actor_key:
        stmt = stmt.where(AuditEvent.actor_key == actor_key)
    if since:
        stmt = stmt.where(AuditEvent.occurred_at >= since)
    if until:
        stmt = stmt.where(AuditEvent.occurred_at <= until)
    rows: list[dict] = []
    cache: dict = {}
    for ev in db.scalars(stmt.limit(2000)):
        if ev.event_type.startswith(EXCLUDED_PREFIXES):
            continue
        if ev.event_type == "SIGN_IN" and ev.outcome != "success":
            continue
        if ev.event_type == "ACCESS_REFUSED":
            idx = REFUSED_PERMISSION_MAP.get((ev.details or {}).get("permission") or "")
            if idx is None:
                continue
            row_outcome = "refused"
        else:
            idx = EVENT_MAP[ev.event_type]
            row_outcome = "quarantined" if ev.event_type in ("DRAFT_QUARANTINED",) else ("refused" if ev.outcome == "refused" else "done")
        if event_kind and idx != event_kind:
            continue
        if outcome and row_outcome != outcome:
            continue
        actor_line, akey = _actor_line(db, ev, lang, company_id, cache)
        name = _subject_name(db, ev) if idx == 8 else None
        rows.append({
            "event_id": ev.event_id,
            "time": to_dubai(ev.occurred_at).isoformat(),
            "time_label": _dubai_label(ev.occurred_at, lang),
            "kind": idx,
            "action": _wording(idx, ev, lang, name),
            "actor": actor_line,
            "actor_key": akey,
            "company": company.trade_name_ar if lang == "ar" else company.trade_name_en,
            "object_ref": ev.subject_id if ev.subject_type not in ("identity",) else None,
            "outcome": row_outcome,
            "outcome_label": _fill(f"outcome_{row_outcome}", lang),
            "reason_code": ev.reason_code if row_outcome != "done" else None,
        })
    total = len(rows)
    start = (page - 1) * page_size
    record_event(db, event_type="ACTIVITY_LIST_VIEWED", category="data_access", actor_key=principal.actor_key, actor_role=_role_on(principal, company_id), company_id=company_id, details={"page": page, "own_only": own_only, "rows": total}, log_class="standard")
    return {"rows": rows[start : start + page_size], "page": page, "page_size": page_size, "total": total, "own_only": own_only, "retention_months": _int(db, "delegates.sc15_retention_months", 24)}


MONTHS_EN = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
MONTHS_AR = ["يناير", "فبراير", "مارس", "أبريل", "مايو", "يونيو", "يوليو", "أغسطس", "سبتمبر", "أكتوبر", "نوفمبر", "ديسمبر"]


def _dubai_label(dt: datetime, lang: str) -> str:
    d = to_dubai(dt)
    month = (MONTHS_AR if lang == "ar" else MONTHS_EN)[d.month - 1]
    return f"{d.day} {month} {d.year}, {d.strftime('%H:%M')} {'بتوقيت دبي' if lang == 'ar' else 'Dubai time'}"


def export_activity(db: Session, principal: Principal, company_id: str, *, lang: str = "en") -> dict:
    """PDF export stub: HTML-ready bilingual content, chosen language first, the other language as a second page
    version, no hash columns, no figures. The export itself is recorded."""
    pages = []
    for page_lang in ([lang, "ar" if lang == "en" else "en"]):
        data = activity_rows(db, principal, company_id, lang=page_lang, page=1)
        rows_html = "".join(f"<tr><td>{r['time_label']}</td><td>{_esc(r['actor'])}</td><td>{_esc(r['action'])}</td><td>{_esc(r['company'])}</td><td>{_esc(r['object_ref'] or '')}</td><td>{r['outcome_label']}</td></tr>" for r in data["rows"])
        html = f"<section lang=\"{page_lang}\" dir=\"{'rtl' if page_lang == 'ar' else 'ltr'}\"><h1>{_fill('export_title', page_lang)}</h1><table><tbody>{rows_html}</tbody></table></section>"
        pages.append({"lang": page_lang, "html": html, "rows": len(data["rows"])})
    record_event(db, event_type="ACTIVITY_EXPORTED", category="document", actor_key=principal.actor_key, actor_role=_role_on(principal, company_id), company_id=company_id, details={"format": "pdf_stub_html", "languages": [p["lang"] for p in pages]})
    return {"format": "html", "pages": pages, "generated_at": _dubai_label(utcnow(), lang)}


def _esc(text: str) -> str:
    return (text or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


# --- SC14 delegation overview ----------------------------------------------------------------------


def _cell(value: int, minimum: int) -> dict:
    """A suppressed cell never carries its value in the payload."""
    if value < minimum:
        return {"suppressed": True, "display": f"<{minimum}"}
    return {"suppressed": False, "value": value}


def _complement(cells: dict[str, dict], values: dict[str, int], minimum: int) -> None:
    """Exactly one suppressed cell in a breakdown -> the next smallest is suppressed too."""
    suppressed = [k for k, c in cells.items() if c["suppressed"]]
    if len(suppressed) == 1 and len(cells) > 1:
        rest = sorted((v, k) for k, v in values.items() if k not in suppressed)
        if rest:
            cells[rest[0][1]] = {"suppressed": True, "display": f"<{minimum}", "complement": True}


def delegation_overview(db: Session, principal: Principal | None = None, *, period_days: int = 30) -> dict:
    """SC14 'Delegation overview': operational counters only, suppression below the minimum group size,
    no names, identities, company names or rights contents. Every DET view is logged."""
    from app.modules.kpis.suppression import min_group_size

    minimum = min_group_size(db)
    now = utcnow()
    since = now - timedelta(days=period_days)
    fn = _optional("app.modules.subscriptions.service", "count_subscribed_companies")
    denominator = int(fn(db) or 0) if fn else (db.scalar(select(func.count(Company.id))) or 0)
    with_delegate = db.scalar(select(func.count(func.distinct(CompanyRole.company_id))).where(CompanyRole.role == "delegate", CompanyRole.status == "active")) or 0
    pending = db.scalar(select(func.count(DelegateInvitation.id)).where(DelegateInvitation.status == "pending")) or 0
    expired = db.scalar(select(func.count(DelegateInvitation.id)).where(DelegateInvitation.status == "expired", DelegateInvitation.expires_at >= since)) or 0
    removals_values = {}
    for reason in ("owner_removed", "identity_failed", "no_owner"):
        removals_values[reason] = db.scalar(select(func.count(DelegateChange.id)).where(DelegateChange.change_type == "removed", DelegateChange.reason == reason, DelegateChange.changed_at >= since)) or 0
    removals = {k: _cell(v, minimum) for k, v in removals_values.items()}
    _complement(removals, removals_values, minimum)
    quarantine_events = db.scalar(select(func.count(AuditEvent.id)).where(AuditEvent.event_type == "DRAFT_QUARANTINED", AuditEvent.occurred_at >= since)) or 0
    no_owner = db.scalar(select(func.count(CompanyHold.company_id)).where(CompanyHold.hold_state == "no_owner")) or 0
    rights: dict[str, Any] = {}
    for toggle in PHASE_B_TOGGLES:
        right = TOGGLE_TO_RIGHT[toggle]
        if get_config(db, "delegates.phase_b_switch", False) and delegate_right_enabled(db, right):
            n = db.scalar(select(func.count(func.distinct(CompanyRole.company_id))).where(CompanyRole.role == "delegate", CompanyRole.status == "active", CompanyRole.rights.contains(right))) or 0
            rights[toggle] = _cell(n, minimum)
        else:
            rights[toggle] = {"suppressed": False, "display": "not enabled", "not_enabled": True}
    share = _cell(with_delegate, minimum)
    if not share["suppressed"] and denominator >= minimum:
        share["percent"] = round(with_delegate * 100.0 / denominator, 1)
    level = "month"
    if any(c["suppressed"] for c in removals.values()) or share["suppressed"]:
        level = "quarter"  # merge split to the next level when a monthly cell is suppressed
    check_hold_alerts(db)
    if principal is not None:
        record_event(db, event_type="DET_AGGREGATE_VIEWED", category="data_access", actor_key=principal.actor_key, actor_role=principal.primary_role(), details={"screen": "SC14", "block": "delegation_overview", "min_group_size": minimum})
    return {
        "as_of": _dubai_label(now, "en"),
        "as_of_iso": now.isoformat(),
        "period_days": period_days,
        "period_level": level,
        "min_group_size": minimum,
        "refresh": str(get_config(db, "delegates.sc14_refresh", "daily 02:00 Asia/Dubai")),
        "companies_with_active_delegate": share,
        "pending_invitations": _cell(pending, minimum),
        "expired_invitations": _cell(expired, minimum),
        "removals_by_reason": removals,
        "quarantine_events": _cell(quarantine_events, minimum),
        "no_owner_companies": _cell(no_owner, minimum),
        "delegated_rights": rights,
        "phase_note": "Delegation aggregates appear from Phase 1C",
    }


def delegate_rights_for(db: Session, principal: Principal, company_id: str) -> dict:
    """The delegate's own view: assigned scope and toggles, plus which Phase B toggles are locked."""
    roles = [r for r in principal.roles_for(company_id) if r.role == "delegate"]
    hold = get_hold(db, company_id)
    r = roles[0] if roles else None
    return {
        "company_id": company_id,
        "toggles": _toggles(r.rights) if r else [],
        "functions": (r.functions if r else []) or [],
        "status": r.status if r else None,
        "valid_to": r.valid_to.isoformat() if r and r.valid_to else None,
        "hold_state": hold.hold_state,
        "locked_toggles": {t: {"locked": not (get_config(db, "delegates.phase_b_switch", False) and delegate_right_enabled(db, TOGGLE_TO_RIGHT[t])), "permissions": sorted(DELEGATE_RIGHT_PERMS[TOGGLE_TO_RIGHT[t]])} for t in PHASE_B_TOGGLES},
    }
