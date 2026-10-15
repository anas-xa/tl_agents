"""Sign-in flow (E1-S1), sessions and staff-role administration."""

from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass, field
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import Forbidden, NotFound, Unauthenticated, ValidationFailed
from app.core.ids import reference_code
from app.core.settings import get_settings
from app.core.time import utcnow
from app.modules.audit.service import AuditWriteError, actor_key_for, record_event
from app.modules.companies.models import CompanyRole
from app.modules.config.service import get_config, get_config_entry
from app.modules.identity.models import (
    EXCLUSIVE_STAFF_PAIRS,
    STAFF_ROLES,
    Identity,
    OperationalAlert,
    PendingSignIn,
    SignInFailureCounter,
    StaffRole,
    UserSession,
)
from app.modules.identity.oidc import (
    AssertionInvalid,
    ProviderUnavailable,
    authorize_url,
    exchange_and_validate,
    make_pkce,
)

LEVEL_ORDER = {"SOP1": 1, "SOP2": 2, "SOP3": 3}
OWNER_LEVEL_ROLES = {"owner", "remote_owner"}


def _hash_state(state: str) -> str:
    return hashlib.sha256(state.encode()).hexdigest()


def hash_emirates_id(idn: str) -> str:
    """Salted hash used to match a UAE PASS assertion to a DET person record without storing the number."""
    return hashlib.sha256((get_settings().secret_key + "|" + idn.replace("-", "")).encode()).hexdigest()


@dataclass
class SignInResult:
    ok: bool
    reason_code: str | None = None
    reference: str | None = None
    session_id: str | None = None
    language: str = "en"
    return_to: str | None = None
    no_company_role: bool = False
    message_key: str | None = None
    details: dict = field(default_factory=dict)


def start_signin(db: Session, *, language: str = "en", return_to: str | None = None, invitation_token: str | None = None, language_explicit: bool = False) -> tuple[str, str]:
    settings = get_settings()
    state = secrets.token_urlsafe(32)
    nonce = secrets.token_urlsafe(24)
    verifier, challenge = make_pkce()
    minutes = int(get_config(db, "identity.pending_signin_expiry_minutes", settings.pending_signin_expiry_minutes))
    db.add(
        PendingSignIn(
            state_hash=_hash_state(state),
            nonce=nonce,
            code_verifier=verifier,
            language=language,
            language_explicit=language_explicit,
            expires_at=utcnow() + timedelta(minutes=minutes),
            return_to=(return_to or "") + (f"|invite={invitation_token}" if invitation_token else "") or None,
        )
    )
    db.flush()
    return authorize_url(settings, state=state, nonce=nonce, code_challenge=challenge, language=language), state


def cancel_signin(db: Session, state: str, *, ip: str | None = None) -> None:
    pending = db.get(PendingSignIn, _hash_state(state))
    if pending and not pending.used:
        pending.cancelled = True
        pending.used = True
    record_event(db, event_type="SIGN_IN", category="sign_in", outcome="info", reason_code="CANCELLED", details={"stage": "interstitial"}, ip=ip, log_class="sign_in")


def _refuse(db: Session, reason: str, *, language: str, identity_uuid: str | None = None, level: str | None = None, profile_type: int | None = None, config_version: str | None = None, ip: str | None = None, browser: str | None = None, state_hash: str | None = None, detail: str | None = None) -> SignInResult:
    ref = reference_code()
    record_event(
        db,
        event_type="SIGN_IN",
        category="sign_in",
        outcome="refused",
        reason_code=reason,
        identity_uuid=identity_uuid,
        details={"assurance_level": level, "profile_type": profile_type, "state_ref": state_hash, "reference": ref, "detail": detail},
        language=language,
        config_version=config_version,
        ip=ip,
        browser_family=browser,
        log_class="sign_in",
    )
    _count_failure(db, identity_uuid, reason, ip)
    return SignInResult(ok=False, reason_code=reason, reference=ref, language=language)


def _count_failure(db: Session, identity_uuid: str | None, reason: str, ip: str | None) -> None:
    settings = get_settings()
    db.add(SignInFailureCounter(identity_uuid=identity_uuid, source=ip, reason_code=reason))
    db.flush()
    now = utcnow()
    if identity_uuid:
        n = db.scalar(
            select(func.count(SignInFailureCounter.id)).where(
                SignInFailureCounter.identity_uuid == identity_uuid, SignInFailureCounter.occurred_at >= now - timedelta(minutes=10)
            )
        )
        if n and n >= settings.signin_failure_alert_per_identity:
            _raise_alert(db, "SIGNIN_FAILURES_IDENTITY", {"identity_key": actor_key_for(identity_uuid), "count": n})
    total = db.scalar(select(func.count(SignInFailureCounter.id)).where(SignInFailureCounter.occurred_at >= now - timedelta(minutes=5)))
    if total and total >= settings.signin_failure_alert_platform:
        _raise_alert(db, "SIGNIN_FAILURES_PLATFORM", {"count": total})


def _raise_alert(db: Session, alert_type: str, details: dict) -> None:
    recent = db.scalar(
        select(OperationalAlert).where(OperationalAlert.alert_type == alert_type, OperationalAlert.created_at >= utcnow() - timedelta(minutes=10))
    )
    if recent is None:
        db.add(OperationalAlert(alert_type=alert_type, recipients=["platform-ops-oncall", "security-lead"], details=details))
        db.flush()


def det_match(db: Session, idn: str | None) -> str:
    """Match the Emirates ID on the assertion against DET persons (hashed). Never stores the number."""
    if not idn:
        return "no_emirates_id"
    from app.modules.licences.models import LicencePerson

    h = hash_emirates_id(idn)
    found = db.scalar(select(LicencePerson).where(LicencePerson.emirates_id_hash == h))
    return "matched" if found else "unmatched"


def complete_signin(db: Session, *, state: str, code: str | None, error: str | None, ip: str | None = None, browser: str | None = None) -> SignInResult:
    settings = get_settings()
    pending = db.get(PendingSignIn, _hash_state(state)) if state else None
    language = pending.language if pending else "en"
    if pending is None or pending.used or pending.cancelled:
        return _refuse(db, "STATE_INVALID", language=language, ip=ip, browser=browser, state_hash=_hash_state(state)[:16] if state else None)
    if pending.expires_at < utcnow():
        pending.used = True
        return _refuse(db, "STATE_EXPIRED", language=language, ip=ip, browser=browser, state_hash=pending.state_hash[:16])
    pending.used = True
    return_to = pending.return_to
    invitation_token = None
    if return_to and "|invite=" in return_to:
        return_to, invitation_token = return_to.split("|invite=", 1)
    if error == "access_denied":
        record_event(db, event_type="SIGN_IN", category="sign_in", outcome="info", reason_code="CANCELLED", language=language, ip=ip, browser_family=browser, log_class="sign_in")
        return SignInResult(ok=False, reason_code="CANCELLED", reference=reference_code(), language=language)
    if error or not code:
        return _refuse(db, "PROVIDER_UNAVAILABLE", language=language, ip=ip, browser=browser, detail=error)
    try:
        assertion = exchange_and_validate(code, pending.code_verifier, pending.nonce, settings)
    except AssertionInvalid as exc:
        return _refuse(db, "ASSERTION_INVALID", language=language, ip=ip, browser=browser, detail=str(exc))
    except ProviderUnavailable as exc:
        return _refuse(db, "PROVIDER_UNAVAILABLE", language=language, ip=ip, browser=browser, detail=str(exc))

    cfg = get_config_entry(db, "identity.min_assurance_level")
    config_version = f"identity.min_assurance_level@v{cfg.version}"
    min_level = str(cfg.value)
    if LEVEL_ORDER[assertion.assurance_level] < LEVEL_ORDER[min_level]:
        return _refuse(db, "LEVEL_TOO_LOW", language=language, identity_uuid=assertion.sub, level=assertion.assurance_level, profile_type=assertion.profile_type, config_version=config_version, ip=ip, browser=browser)

    identity = db.get(Identity, assertion.sub)
    now = utcnow()
    match = det_match(db, assertion.idn)
    if identity is None:
        identity = Identity(uuid=assertion.sub, display_name=assertion.name, assurance_level=assertion.assurance_level, profile_type=assertion.profile_type, det_match_result=match, language=language, first_sign_in_at=now)
        db.add(identity)
    else:
        identity.display_name = assertion.name
        if pending.language_explicit:  # explicit choice this visit > profile (E1-S5 precedence); saved to profile
            identity.language = language
        identity.assurance_level = assertion.assurance_level
        identity.profile_type = assertion.profile_type
        identity.det_match_result = match
    identity.last_sign_in_at = now
    db.flush()

    if invitation_token:
        bind_staff_invitation(db, invitation_token, identity.uuid)
    from app.modules.delegates.service import bind_pending_delegate_invitations

    bind_pending_delegate_invitations(db, identity.uuid, hash_emirates_id(assertion.idn) if assertion.idn else None)

    roles = resolve_roles(db, identity.uuid, det_match_result=match)
    owner_roles_blocked = roles["owner_blocked"]
    if owner_roles_blocked:
        record_event(db, event_type="SIGN_IN", category="sign_in", outcome="refused", reason_code="DET_MATCH_FAIL", identity_uuid=identity.uuid, details={"assurance_level": assertion.assurance_level, "profile_type": assertion.profile_type, "blocked_owner_roles": owner_roles_blocked}, language=language, config_version=config_version, ip=ip, browser_family=browser, log_class="sign_in")
    no_role = not roles["company_roles"] and not roles["staff_roles"]

    session = UserSession(
        session_id=secrets.token_urlsafe(32),
        identity_uuid=identity.uuid,
        absolute_expires_at=now + timedelta(hours=int(get_config(db, "identity.session_max_length_hours", settings.session_max_length_hours))),
        language=language,
        assurance_level=assertion.assurance_level,
        config_version=config_version,
        client_meta={"browser_family": browser},
    )
    db.add(session)
    try:
        record_event(
            db,
            event_type="SIGN_IN",
            category="sign_in",
            outcome="success" if not no_role else "refused",
            reason_code="NO_COMPANY_ROLE" if no_role else None,
            identity_uuid=identity.uuid,
            details={"assurance_level": assertion.assurance_level, "profile_type": assertion.profile_type, "det_match": match, "state_ref": pending.state_hash[:16], "session_ref": hashlib.sha256(session.session_id.encode()).hexdigest()[:16], "companies": len(roles["company_roles"]), "staff_roles": roles["staff_roles"]},
            language=language,
            config_version=config_version,
            ip=ip,
            browser_family=browser,
            log_class="sign_in",
            fail_closed=True,
        )
    except AuditWriteError:
        db.rollback()
        ref = reference_code()
        return SignInResult(ok=False, reason_code="AUDIT_UNAVAILABLE", reference=ref, language=language)
    db.flush()
    return SignInResult(ok=True, session_id=session.session_id, language=language, return_to=return_to or None, no_company_role=no_role, details={"det_match": match})


def resolve_roles(db: Session, identity_uuid: str, *, det_match_result: str | None = None) -> dict:
    """Roles come only from platform records; each company role is scoped to its company."""
    if det_match_result is None:
        ident = db.get(Identity, identity_uuid)
        det_match_result = ident.det_match_result if ident else "unmatched"
    rows = list(db.scalars(select(CompanyRole).where(CompanyRole.identity_uuid == identity_uuid, CompanyRole.status == "active")))
    company_roles = []
    owner_blocked = []
    for r in rows:
        if r.role in OWNER_LEVEL_ROLES and det_match_result != "matched":
            owner_blocked.append(r.company_id)
            continue
        if r.valid_to and r.valid_to < utcnow().date():
            continue
        company_roles.append(r)
    staff = list(db.scalars(select(StaffRole).where(StaffRole.identity_uuid == identity_uuid, StaffRole.status == "active")))
    return {"company_roles": company_roles, "staff_roles": [s.role for s in staff], "owner_blocked": owner_blocked, "staff_records": staff}


# --- sessions --------------------------------------------------------------------------------------


def get_active_session(db: Session, session_id: str | None) -> UserSession:
    if not session_id:
        raise Unauthenticated("no session")
    session = db.get(UserSession, session_id)
    if session is None or session.ended_at is not None:
        raise Unauthenticated("session ended", reason_code="SESSION_ENDED")
    now = utcnow()
    idle = int(get_config(db, "identity.session_idle_timeout_minutes", get_settings().session_idle_timeout_minutes))
    if session.last_seen_at + timedelta(minutes=idle) < now:
        session.ended_at = now
        session.end_reason = "idle_timeout"
        record_event(db, event_type="SESSION_ENDED", category="sign_in", outcome="info", reason_code="IDLE_TIMEOUT", identity_uuid=session.identity_uuid, log_class="sign_in")
        raise Unauthenticated("session ended", reason_code="SESSION_ENDED")
    if session.absolute_expires_at < now:
        session.ended_at = now
        session.end_reason = "max_length"
        record_event(db, event_type="SESSION_ENDED", category="sign_in", outcome="info", reason_code="MAX_LENGTH", identity_uuid=session.identity_uuid, log_class="sign_in")
        raise Unauthenticated("session ended", reason_code="SESSION_ENDED")
    session.last_seen_at = now
    return session


def end_session(db: Session, session_id: str, reason: str = "sign_out") -> None:
    session = db.get(UserSession, session_id)
    if session and session.ended_at is None:
        session.ended_at = utcnow()
        session.end_reason = reason
        record_event(db, event_type="SIGN_OUT", category="sign_in", outcome="info", reason_code=reason.upper(), identity_uuid=session.identity_uuid, log_class="sign_in")


def session_timing(db: Session, session: UserSession) -> dict:
    settings = get_settings()
    idle = int(get_config(db, "identity.session_idle_timeout_minutes", settings.session_idle_timeout_minutes))
    warn = int(get_config(db, "identity.session_warning_minutes", settings.session_warning_minutes))
    return {
        "idle_timeout_minutes": idle,
        "warning_minutes": warn,
        "idle_expires_at": (session.last_seen_at + timedelta(minutes=idle)).isoformat(),
        "absolute_expires_at": session.absolute_expires_at.isoformat(),
    }


# --- staff roles (two-person administration, Q4) ------------------------------------------------


def create_staff_invitation(db: Session, *, role: str, work_email: str, requester: str, approver: str, reason: str | None, scope: str | None = None, entitlement_ref: str | None = None) -> StaffRole:
    if role not in STAFF_ROLES:
        raise ValidationFailed(f"unknown staff role {role}")
    if requester == approver:
        raise ValidationFailed("requester and approver must be different people", reason_code="SECOND_APPROVER_REQUIRED")
    own = db.scalar(select(StaffRole).where(StaffRole.identity_uuid == requester, StaffRole.work_email == work_email.lower()))
    if own is not None or work_email.lower() in (requester.lower(), approver.lower()):
        raise Forbidden("nobody can assign a staff role to themselves", reason_code="SELF_ASSIGNMENT")
    days = int(get_config(db, "identity.staff_invitation_days", 7))
    row = StaffRole(
        role=role,
        scope=scope,
        work_email=work_email.lower(),
        invitation_token=secrets.token_urlsafe(24),
        invitation_expires_at=utcnow() + timedelta(days=days),
        requester=requester,
        approver=approver,
        reason=reason,
        entitlement_ref=entitlement_ref,
    )
    db.add(row)
    db.flush()
    record_event(db, event_type="STAFF_ROLE_INVITED", category="access", details={"role": role, "scope": scope, "requester": requester, "approver": approver, "reason": reason, "staff_role_id": row.id})
    return row


def bind_staff_invitation(db: Session, token: str, identity_uuid: str) -> StaffRole | None:
    row = db.scalar(select(StaffRole).where(StaffRole.invitation_token == token))
    if row is None or row.status != "invited":
        record_event(db, event_type="STAFF_ROLE_BIND", category="access", outcome="refused", reason_code="INVITATION_INVALID", identity_uuid=identity_uuid)
        return None
    if row.invitation_expires_at and row.invitation_expires_at < utcnow():
        row.status = "expired"
        record_event(db, event_type="STAFF_ROLE_BIND", category="access", outcome="refused", reason_code="INVITATION_EXPIRED", identity_uuid=identity_uuid)
        return None
    existing = {s.role for s in db.scalars(select(StaffRole).where(StaffRole.identity_uuid == identity_uuid, StaffRole.status == "active"))}
    for pair in EXCLUSIVE_STAFF_PAIRS:
        if row.role in pair and (existing & (pair - {row.role})):
            record_event(db, event_type="STAFF_ROLE_BIND", category="access", outcome="refused", reason_code="ROLE_COMBINATION_REFUSED", identity_uuid=identity_uuid, details={"role": row.role})
            return None
    row.identity_uuid = identity_uuid
    row.status = "active"
    row.bound_at = utcnow()
    row.invitation_token = None
    record_event(db, event_type="STAFF_ROLE_BOUND", category="access", identity_uuid=identity_uuid, details={"role": row.role, "staff_role_id": row.id})
    return row


def remove_staff_role(db: Session, staff_role_id: int, *, requester: str, approver: str, reason: str | None) -> StaffRole:
    if requester == approver:
        raise ValidationFailed("requester and approver must be different people", reason_code="SECOND_APPROVER_REQUIRED")
    row = db.get(StaffRole, staff_role_id)
    if row is None:
        raise NotFound("staff role not found")
    row.status = "removed"
    row.removed_at = utcnow()
    record_event(db, event_type="STAFF_ROLE_REMOVED", category="access", identity_uuid=row.identity_uuid, details={"role": row.role, "requester": requester, "approver": approver, "reason": reason, "staff_role_id": row.id})
    return row
