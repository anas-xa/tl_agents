"""Consent store, enforcement gate, lifecycle and withdrawal (E4-S1, E4-S2).

Pure functions over a SQLAlchemy session. The gate ``check_consent`` is the single decision point other modules
use before reading data under consent; it fails closed (deny on any doubt, ``GATE_UNAVAILABLE`` when the registry
cannot be read). Withdrawal runs the ordered enforcement steps of Q377 and writes the K13 timestamps.
"""

from __future__ import annotations

import hashlib
import secrets
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import Conflict, Forbidden, NotFound, PlatformError, SwitchedOff, ValidationFailed
from app.core.ids import new_id
from app.core.time import dubai_date, to_dubai, utcnow
from app.modules.access.service import Principal, delegate_right_enabled, permissions_for, require_step_up
from app.modules.audit.service import AuditWriteError, record_event
from app.modules.companies.models import Company, CompanyRole
from app.modules.config.service import get_config
from app.modules.consent.models import (
    CONSENT_TYPES,
    PAUSE_REASONS,
    SOURCES,
    TYPE_SOURCE,
    Consent,
    ConsentReceipt,
    ConsentRequest,
    ConsentWithdrawal,
    GateToken,
    Notification,
)
from app.modules.consent.strings import s
from app.modules.licences.models import Licence, LicencePerson

OWNER_LEVEL_ROLES = ("owner", "remote_owner")
AUTHORITY_HOLDER_ROLES = ("owner", "remote_owner")


class GateUnavailable(PlatformError):
    """Registry unreachable: deny, log, retryable."""

    status_code = 503
    reason_code = "GATE_UNAVAILABLE"


@dataclass
class GateDecision:
    allowed: bool
    reason_code: str
    consent_id: str | None = None
    version: int | None = None
    token: str | None = None
    token_expires_at: datetime | None = None
    details: dict = field(default_factory=dict)


# --- configuration helpers -------------------------------------------------------------------


def controlled_lists(db: Session) -> dict:
    lists = get_config(db, "consent.controlled_lists", None) or {}
    return {
        "version": int(lists.get("version", 1)),
        "purposes": list(lists.get("purposes", [])),
        "data_types": dict(lists.get("data_types", {})),
    }


def wording_version(db: Session) -> str:
    return str(get_config(db, "consent.wording_version", "draft"))


def route_limit_months(db: Session, consent_type: str) -> int | None:
    if consent_type == "bank_data_open_finance":
        return get_config(db, "datalinks.bank.consent_max_duration_months", None)
    return get_config(db, "consent.max_duration_months", None)


def _scope_key(company_id: str, source: str, account_ids: list, purpose: str, recipient: str | None) -> str:
    raw = "|".join([company_id, source, ",".join(sorted(str(a) for a in account_ids)), purpose, recipient or ""])
    return hashlib.sha256(raw.encode()).hexdigest()


def mask_account(value: str | None) -> str:
    if not value:
        return ""
    tail = "".join(ch for ch in str(value) if ch.isalnum())[-4:]
    return f"•••• {tail}"


# --- rights ---------------------------------------------------------------------------------------


def grant_rights(db: Session, principal: Principal, company_id: str) -> dict:
    """What the signed-in person may do on this company's consents, with the reason when something is off."""
    roles = principal.roles_for(company_id)
    role_names = [r.role for r in roles]
    perms = permissions_for(db, principal, company_id)
    out = {
        "role": role_names[0] if role_names else None,
        "is_delegate": "delegate" in role_names,
        "is_remote_owner": "remote_owner" in role_names and "owner" not in role_names,
        "can_view": "consent.view" in perms,
        "can_grant": "consent.grant" in perms,
        "can_withdraw": "consent.withdraw" in perms,
        "can_upload": "uploads.manage" in perms,
        "can_request": False,
        "refusal_code": None,
        "step_up_required": str(get_config(db, "identity.approval_min_assurance_level", "SOP3")),
        "assurance_level": principal.assurance_level,
        "tax_consent_online": True,
        "det_support_path": get_config(db, "consent.det_support_help_line", None),
    }
    if out["is_delegate"] and not out["can_grant"]:
        delegate = next(r for r in roles if r.role == "delegate")
        has_right = "grant_consent" in (delegate.rights or [])
        out["refusal_code"] = "RIGHT_SWITCHED_OFF" if (not delegate_right_enabled(db, "grant_consent") or not has_right) else "NO_PERMISSION"
        out["can_request"] = True
    if out["is_remote_owner"]:
        out["tax_consent_online"] = bool(get_config(db, "consent.remote_owner_tax_consent_allowed", False))
        out["can_request"] = True
        if not out["can_grant"]:
            out["refusal_code"] = "REMOTE_OWNER_CONSENT_REQUIRES_UAE_PASS_STEP_UP"
    return out


def require_consent_act(db: Session, principal: Principal, company_id: str, permission: str, consent_type: str | None = None) -> dict:
    """Fail-closed check for grant/withdraw/resume: role, Phase-B delegate switch, remote-owner tax rule, step-up."""
    roles = principal.roles_for(company_id)
    role_names = [r.role for r in roles]
    if consent_type == "tax_data" and "remote_owner" in role_names and "owner" not in role_names and not get_config(db, "consent.remote_owner_tax_consent_allowed", False):
        record_event(db, event_type="CONSENT_GRANT_REFUSED", category="consent", outcome="refused", reason_code="REMOTE_OWNER_TAX_CONSENT_NOT_AVAILABLE", actor_key=principal.actor_key, actor_role="remote_owner", company_id=company_id, details={"consent_type": consent_type, "authority": "unclear authority, action blocked", "path": "det_support_help_line"})
        db.commit()
        raise Forbidden(s("refusal.remote_owner_tax_consent", principal.language), reason_code="REMOTE_OWNER_TAX_CONSENT_NOT_AVAILABLE", details={"path": "det_support_help_line", "authority": "unclear authority, action blocked"})
    perms = permissions_for(db, principal, company_id)
    if permission not in perms:
        for r in roles:
            if r.role == "delegate":
                has_right = "grant_consent" in (r.rights or [])
                switched_off = not delegate_right_enabled(db, "grant_consent")
                code = "RIGHT_SWITCHED_OFF" if (switched_off or not has_right) else "NO_PERMISSION"
                record_event(db, event_type="CONSENT_GRANT_REFUSED", category="consent", outcome="refused", reason_code=code, actor_key=principal.actor_key, actor_role="delegate", company_id=company_id, details={"permission": permission, "right": "grant_consent", "phase_b_switch": not switched_off, "right_held": has_right})
                db.commit()
                raise SwitchedOff(s("refusal.delegate_right_off", principal.language), reason_code=code, details={"right": "grant_consent", "request_action": "ask_the_owner"})
        record_event(db, event_type="CONSENT_GRANT_REFUSED", category="consent", outcome="refused", reason_code="NO_PERMISSION", actor_key=principal.actor_key, actor_role=principal.primary_role(), company_id=company_id, details={"permission": permission})
        db.commit()
        raise Forbidden("you do not have access to this action", reason_code="NO_PERMISSION", details={"permission": permission})
    require_step_up(db, principal, permission)
    delegate = next((r for r in roles if r.role == "delegate"), None)
    owner = next((r for r in roles if r.role in OWNER_LEVEL_ROLES), None)
    return {
        "grantor_role": "delegate" if delegate and not owner else "owner",
        "grantor_capacity": "attorney" if owner and owner.capacity == "attorney" else "authorised_signatory",
        "capacity_document_ref": (owner.authority_evidence_ref if owner else None),
        "delegation_id": delegate.id if delegate and not owner else None,
        "granting_owner_uuid": delegate.granted_by_uuid if delegate and not owner else None,
    }


# --- grant --------------------------------------------------------------------------------------------


def _validate_grant(db: Session, payload: dict) -> dict:
    lists = controlled_lists(db)
    consent_type = payload.get("consent_type")
    if consent_type not in CONSENT_TYPES:
        raise ValidationFailed("consent type is not one of the consent types held in the store", reason_code="CONSENT_TYPE_INVALID")
    source = payload.get("source") or TYPE_SOURCE.get(consent_type)
    if source not in SOURCES:
        raise ValidationFailed("source must be one of the controlled sources", reason_code="SOURCE_INVALID")
    purpose = payload.get("purpose")
    if not purpose or purpose not in lists["purposes"]:
        raise ValidationFailed("purpose is mandatory and must come from the controlled purpose list", reason_code="PURPOSE_INVALID")
    data_types = list(payload.get("data_types") or [])
    allowed = lists["data_types"].get(source, [])
    if not data_types or any(d not in allowed for d in data_types):
        raise ValidationFailed("data types are mandatory and must come from the controlled list for the source", reason_code="DATA_TYPES_INVALID")
    account_ids = [str(a).strip() for a in (payload.get("account_ids") or []) if str(a).strip()]
    if source == "bank" and not account_ids:
        raise ValidationFailed("accounts are mandatory for a bank consent", reason_code="ACCOUNTS_REQUIRED")
    expires_at = payload.get("expires_at")
    if not expires_at:
        raise ValidationFailed("expiry is mandatory", reason_code="EXPIRY_REQUIRED")
    if isinstance(expires_at, str):
        try:
            expires_at = datetime.fromisoformat(expires_at.replace("Z", ""))
        except ValueError as exc:
            raise ValidationFailed("expiry must be a date-time", reason_code="EXPIRY_INVALID") from exc
    if expires_at <= utcnow():
        raise ValidationFailed("expiry must be in the future", reason_code="EXPIRY_INVALID")
    recipient = payload.get("recipient")
    if consent_type == "auditor_specialist_evidence_access" and not recipient:
        raise ValidationFailed("evidence access must name the assigned engagement or case", reason_code="RECIPIENT_REQUIRED")
    return {"consent_type": consent_type, "source": source, "purpose": purpose, "data_types": data_types, "account_ids": account_ids, "expires_at": expires_at, "recipient": recipient, "list_version": lists["version"], "provider_name": payload.get("provider_name"), "external_consent_id": payload.get("external_consent_id")}


def grant_consent(db: Session, principal: Principal, company_id: str, payload: dict, *, grantor: dict) -> tuple[Consent, bool]:
    """Store a consent. Returns (consent, created). An identical grant for the same key is a duplicate and returns
    the existing consent; a different scope or expiry stores a new version and supersedes the previous one."""
    data = _validate_grant(db, payload)
    company = db.get(Company, company_id)
    if company is None:
        raise NotFound("company not found")
    idem = payload.get("idempotency_key")
    if idem:
        existing = db.scalar(select(Consent).where(Consent.company_id == company_id, Consent.idempotency_key == idem))
        if existing is not None:
            record_event(db, event_type="CONSENT_DUPLICATE_REJECTED", category="consent", outcome="refused", reason_code="DUPLICATE_IDEMPOTENCY_KEY", actor_key=principal.actor_key, company_id=company_id, subject_type="consent", subject_id=existing.consent_id)
            return existing, False
    scope_key = _scope_key(company_id, data["source"], data["account_ids"], data["purpose"], data["recipient"])
    current = db.scalar(select(Consent).where(Consent.scope_key == scope_key, Consent.status.in_(("active", "pending", "paused"))).order_by(Consent.version.desc()))
    # platform expiry = earlier of owner's date and the route's limit
    expires_at = data["expires_at"]
    route_limit_applied = False
    limit_months = route_limit_months(db, data["consent_type"])
    if limit_months:
        route_max = utcnow() + timedelta(days=int(limit_months) * 30)
        if expires_at > route_max:
            expires_at, route_limit_applied = route_max, True
    if current is not None:
        same = sorted(current.data_types) == sorted(data["data_types"]) and current.expires_at.replace(microsecond=0) == expires_at.replace(microsecond=0)
        if same:
            record_event(db, event_type="CONSENT_DUPLICATE_REJECTED", category="consent", outcome="refused", reason_code="DUPLICATE_GRANT", actor_key=principal.actor_key, company_id=company_id, subject_type="consent", subject_id=current.consent_id)
            return current, False
    # bank consent: the legal consent screen is the provider's; without a live licensed route the record stays Pending
    status = "active"
    if data["consent_type"] == "bank_data_open_finance":
        route_live = bool(get_config(db, "datalinks.openfinance.enabled", False)) and get_config(db, "datalinks.route_holder", "none") != "none"
        status = "active" if (route_live and data.get("external_consent_id")) else "pending"
    version = (current.version + 1) if current is not None else 1
    grantor_name = principal.display_name
    granting_owner_name = None
    if grantor.get("granting_owner_uuid"):
        from app.modules.identity.models import Identity

        owner_ident = db.get(Identity, grantor["granting_owner_uuid"])
        granting_owner_name = owner_ident.display_name if owner_ident else None
    consent = Consent(
        version=version,
        company_id=company_id,
        consent_type=data["consent_type"],
        source=data["source"],
        provider_name=data["provider_name"],
        data_types=data["data_types"],
        account_ids=data["account_ids"],
        purpose=data["purpose"],
        recipient=data["recipient"],
        valid_from=utcnow(),
        expires_at=expires_at,
        route_limit_applied=route_limit_applied,
        list_version=data["list_version"],
        status=status,
        status_reason="awaiting_provider_confirmation" if status == "pending" else None,
        grantor_identity_uuid=principal.identity_uuid,
        grantor_display_name=grantor_name,
        grantor_role=grantor["grantor_role"],
        grantor_capacity=grantor["grantor_capacity"],
        capacity_document_ref=grantor.get("capacity_document_ref"),
        identity_assurance_level=principal.assurance_level,
        granting_owner_uuid=grantor.get("granting_owner_uuid"),
        granting_owner_name=granting_owner_name,
        delegation_id=grantor.get("delegation_id"),
        external_consent_id=data.get("external_consent_id"),
        external_status="pending" if status == "pending" else None,
        idempotency_key=idem,
        scope_key=scope_key,
        wording_version=wording_version(db),
    )
    db.add(consent)
    db.flush()
    if current is not None:
        current.status = "superseded"
        current.status_reason = "new_version"
        current.superseded_by = consent.consent_id
        current.superseded_at = utcnow()
        invalidate_gate(current.consent_id)
        record_event(db, event_type="CONSENT_VERSION_SUPERSEDED", category="consent", actor_key=principal.actor_key, company_id=company_id, subject_type="consent", subject_id=current.consent_id, details={"superseded_by": consent.consent_id, "version": current.version, "new_version": version}, log_class="consent")
    try:
        ev = record_event(db, event_type="CONSENT_GRANTED", category="consent", actor_key=principal.actor_key, actor_role=grantor["grantor_role"], company_id=company_id, subject_type="consent", subject_id=consent.consent_id, details={"consent_type": consent.consent_type, "source": consent.source, "purpose": consent.purpose, "version": version, "status": status, "list_version": consent.list_version, "wording_version": consent.wording_version, "assurance_level": principal.assurance_level, "delegation_id": consent.delegation_id, "route_limit_applied": route_limit_applied}, log_class="consent", fail_closed=True)
    except AuditWriteError as exc:
        raise Conflict("consent not saved. Nothing was shared. Try again.", reason_code="AUDIT_UNAVAILABLE") from exc
    consent.audit_entry_ref = ev.event_id if ev else None
    receipt = build_grant_receipt(db, consent)
    consent.receipt_ref = receipt.receipt_id
    if consent.grantor_role == "delegate" and consent.granting_owner_uuid:
        notify(db, company_id=company_id, recipients=[(consent.granting_owner_uuid, "owner")], kind="delegate_granted_consent", template_key="notice.removed_delegate_grant", subject_type="consent", subject_id=consent.consent_id, params={})
    db.flush()
    return consent, True


def build_grant_receipt(db: Session, consent: Consent) -> ConsentReceipt:
    company = db.get(Company, consent.company_id)
    licence = db.scalar(select(Licence).where(Licence.company_id == consent.company_id).order_by(Licence.created_at.desc()))
    lists = controlled_lists(db)
    all_types = lists["data_types"].get(consent.source, [])
    not_read = [d for d in all_types if d not in consent.data_types]

    def content(lang: str) -> dict:
        rows = [
            (s("receipt.row.company", lang), f"{company.trade_name_en} / {company.trade_name_ar} ({licence.licence_number if licence else '-'})"),
            (s("receipt.row.purpose", lang), consent.purpose),
            (s("receipt.row.data_source", lang), consent.provider_name or consent.source),
            (s("receipt.row.accounts", lang), ", ".join(mask_account(a) for a in consent.account_ids) or "-"),
            (s("receipt.row.data_we_read", lang), ", ".join(consent.data_types)),
            (s("receipt.row.data_we_do_not_read", lang), ", ".join(not_read) or "-"),
            (s("receipt.row.valid_from", lang), _fmt_dubai(consent.valid_from, lang)),
            (s("receipt.row.valid_until", lang), _fmt_dubai(consent.expires_at, lang)),
            (s("receipt.row.granted_by", lang), f"{consent.grantor_display_name} ({consent.grantor_role})"),
            (s("receipt.row.acting_as", lang), consent.grantor_capacity + (f" ({consent.capacity_document_ref})" if consent.capacity_document_ref else "")),
        ]
        if consent.delegation_id:
            rows.append((s("receipt.row.delegation_id", lang), consent.delegation_id))
            rows.append((s("receipt.row.delegated_by", lang), consent.granting_owner_name or "-"))
        rows += [
            (s("receipt.row.date_granted", lang), _fmt_dubai(consent.granted_at, lang)),
            (s("receipt.row.status", lang), consent.status),
            (s("receipt.row.how_to_withdraw", lang), s("receipt.how_to_withdraw", lang)),
        ]
        return {
            "title": s("receipt.title", lang),
            "rows": [{"label": a, "value": b} for a, b in rows],
            "identity_assurance_level": consent.identity_assurance_level,
            "wording_version": consent.wording_version,
            "granted_at_utc": consent.granted_at.isoformat() + "Z",
            "granted_at_gulf": to_dubai(consent.granted_at).isoformat(),
            "audit_entry_ref": consent.audit_entry_ref,
            "footer": s("receipt.footer", lang),
        }

    receipt = ConsentReceipt(receipt_number=f"CR-{utcnow():%Y%m%d}-{secrets.token_hex(3).upper()}", kind="grant", consent_id=consent.consent_id, version=consent.version, template_version=str(get_config(db, "consent.receipt_template_version", "v1")), wording_version=consent.wording_version, content_en=content("en"), content_ar=content("ar"), audit_entry_ref=consent.audit_entry_ref)
    db.add(receipt)
    db.flush()
    return receipt


def _fmt_dubai(dt: datetime | None, lang: str) -> str:
    if not dt:
        return "-"
    d = to_dubai(dt)
    months_en = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"]
    months_ar = ["يناير", "فبراير", "مارس", "أبريل", "مايو", "يونيو", "يوليو", "أغسطس", "سبتمبر", "أكتوبر", "نوفمبر", "ديسمبر"]
    month = (months_ar if lang == "ar" else months_en)[d.month - 1]
    suffix = "بتوقيت دبي" if lang == "ar" else "Dubai time"
    return f"{d.day} {month} {d.year}, {d:%H:%M} {suffix}"


# --- gate -----------------------------------------------------------------------------------------------

_GATE_CACHE: dict[tuple, tuple[float, GateDecision]] = {}


def invalidate_gate(consent_id: str | None = None) -> None:
    """Push invalidation on withdrawal/supersede: nothing may be allowed from a cache entry for this consent."""
    if consent_id is None:
        _GATE_CACHE.clear()
        return
    for key in [k for k, (_, d) in _GATE_CACHE.items() if d.consent_id == consent_id]:
        _GATE_CACHE.pop(key, None)


def check_consent(db: Session, company_id: str, consent_type: str, scope: dict | None = None, recipient: str | None = None, *, actor_key: str | None = None) -> GateDecision:
    """Consent enforcement gate. ``scope`` = {source, data_type, account_id, purpose}. Deny by default.

    Allow only when an Active, unexpired consent of the type exists whose scope contains every requested field.
    Returns a per-request token (lifetime <= 60 s). Raises ``GateUnavailable`` when the registry cannot be read.
    """
    scope = dict(scope or {})
    cache_max = int(get_config(db, "consent.gate.cache_max_seconds", 30) or 0)
    key = (company_id, consent_type, recipient, tuple(sorted(scope.items())))
    now = time.monotonic()
    cached = _GATE_CACHE.get(key)
    if cached and now - cached[0] <= min(cache_max, 30) and not cached[1].allowed:
        return cached[1]  # a cached deny is safe to reuse; allows are re-evaluated so withdrawal wins at once
    if get_config(db, "consent.gate.simulate_unavailable", False):
        record_event(db, event_type="CONSENT_GATE_UNAVAILABLE", category="consent", outcome="error", reason_code="GATE_UNAVAILABLE", actor_key=actor_key, company_id=company_id, details={"consent_type": consent_type, "scope": scope})
        raise GateUnavailable("consent registry unreachable; pull denied, retry later", reason_code="GATE_UNAVAILABLE", details={"retryable": True})
    try:
        stmt = select(Consent).where(Consent.company_id == company_id, Consent.consent_type == consent_type, Consent.status == "active").order_by(Consent.version.desc())
        candidates = list(db.scalars(stmt))
    except Exception as exc:  # registry unreachable -> deny, log, retryable
        record_event(db, event_type="CONSENT_GATE_UNAVAILABLE", category="consent", outcome="error", reason_code="GATE_UNAVAILABLE", actor_key=actor_key, company_id=company_id, details={"consent_type": consent_type})
        raise GateUnavailable("consent registry unreachable; pull denied, retry later", reason_code="GATE_UNAVAILABLE", details={"retryable": True}) from exc
    lists = controlled_lists(db)
    reason = "NO_ACTIVE_CONSENT"
    chosen: Consent | None = None
    now_utc = utcnow()
    for c in candidates:
        if c.expires_at <= now_utc:
            reason = "CONSENT_EXPIRED"
            continue
        if recipient and c.recipient != recipient:
            reason = "RECIPIENT_OUT_OF_SCOPE"
            continue
        if scope.get("source") and scope["source"] != c.source:
            reason = "SOURCE_OUT_OF_SCOPE"
            continue
        if scope.get("purpose") and scope["purpose"] != c.purpose:
            reason = "PURPOSE_OUT_OF_SCOPE"
            continue
        if scope.get("purpose") and scope["purpose"] not in lists["purposes"]:
            reason = "PURPOSE_REMOVED_FROM_LIST"
            continue
        if scope.get("data_type") and scope["data_type"] not in c.data_types:
            reason = "DATA_TYPE_OUT_OF_SCOPE"
            continue
        if scope.get("data_type") and scope["data_type"] not in lists["data_types"].get(c.source, []):
            reason = "DATA_TYPE_REMOVED_FROM_LIST"
            continue
        if scope.get("account_id") and c.account_ids and scope["account_id"] not in c.account_ids:
            reason = "ACCOUNT_OUT_OF_SCOPE"
            continue
        chosen = c
        break
    if chosen is None:
        decision = GateDecision(False, reason, details={"consent_type": consent_type, "scope": scope})
        _GATE_CACHE[key] = (now, decision)
        record_event(db, event_type="CONSENT_GATE_DENY", category="consent", outcome="refused", reason_code=reason, actor_key=actor_key, company_id=company_id, details={"consent_type": consent_type, "scope": scope})
        return decision
    lifetime = min(int(get_config(db, "consent.gate.request_token_lifetime_max_seconds", 60) or 60), 60)
    token = GateToken(token=secrets.token_urlsafe(32), consent_id=chosen.consent_id, version=chosen.version, company_id=company_id, scope=scope, expires_at=now_utc + timedelta(seconds=lifetime))
    db.add(token)
    db.flush()
    decision = GateDecision(True, "ALLOWED", chosen.consent_id, chosen.version, token.token, token.expires_at, {"lifetime_seconds": lifetime})
    _GATE_CACHE[key] = (now, decision)
    record_event(db, event_type="CONSENT_GATE_ALLOW", category="consent", actor_key=actor_key, company_id=company_id, subject_type="consent", subject_id=chosen.consent_id, details={"consent_type": consent_type, "scope": scope, "version": chosen.version, "token_lifetime_seconds": lifetime})
    return decision


def gate_allows(db: Session, company_id: str, consent_type: str, scope: dict | None = None, recipient: str | None = None) -> bool:
    """Boolean convenience for callers that treat GATE_UNAVAILABLE as a deny (fail closed)."""
    try:
        return check_consent(db, company_id, consent_type, scope, recipient).allowed
    except GateUnavailable:
        return False


# --- withdrawal (ordered enforcement steps, Q377) -----------------------------------------------------------


def withdraw_consent(db: Session, principal: Principal, consent: Consent, *, reason: str | None = None) -> ConsentWithdrawal:
    if consent.status in ("withdrawn_on_platform", "revocation_confirmed_by_provider", "superseded", "expired"):
        raise Conflict("this consent is no longer active", reason_code="CONSENT_NOT_ACTIVE", details={"status": consent.status})
    now = utcnow()
    withdrawal = ConsentWithdrawal(consent_id=consent.consent_id, version=consent.version, company_id=consent.company_id, withdrawn_at=now, withdrawer_identity_uuid=principal.identity_uuid, withdrawer_display_name=principal.display_name, withdrawer_role=principal.primary_role(), scope="whole")
    # steps 1+2 (one registry transaction): status + withdrawn_at, gate invalidation
    consent.status = "withdrawn_on_platform"
    consent.status_reason = reason or "withdrawn_by_holder"
    consent.withdrawn_at = now
    invalidate_gate(consent.consent_id)
    for tok in db.scalars(select(GateToken).where(GateToken.consent_id == consent.consent_id, GateToken.revoked.is_(False))):
        tok.revoked = True
    db.add(withdrawal)
    try:
        ev = record_event(db, event_type="CONSENT_WITHDRAWN", category="consent", actor_key=principal.actor_key, actor_role=principal.primary_role(), company_id=consent.company_id, subject_type="consent", subject_id=consent.consent_id, details={"version": consent.version, "scope": "whole", "consent_type": consent.consent_type, "source": consent.source, "reason": consent.status_reason}, log_class="consent", fail_closed=True)
    except AuditWriteError as exc:
        db.rollback()
        raise Conflict("We could not withdraw your consent. It is still active. Try again, or contact support.", reason_code="AUDIT_UNAVAILABLE") from exc
    withdrawal.audit_entry_ref = ev.event_id if ev else None
    db.flush()
    # step 3: cancel queued and running jobs (ingestion orchestrator; idempotent)
    cancelled, had_jobs, cancel_ok = _cancel_pulls(db, consent.consent_id)
    withdrawal.jobs_cancelled = cancelled
    # step 4: data-use flag stopped + pulls_stopped_at (only when all pulls cancelled and flag set in one transaction)
    restricted, on_hold = _restrict_lineage(db, consent.consent_id)
    withdrawal.records_restricted = restricted
    withdrawal.records_on_legal_hold = on_hold
    if cancel_ok:
        withdrawal.pulls_stopped_at = utcnow()
        withdrawal.k13_class = "normal" if had_jobs else "no_scheduled_pulls"
    else:
        withdrawal.k13_class = "unenforced_open"
    # step 5: source revocation, asynchronous (pilot: provider route off; nothing to revoke for uploads)
    if consent.consent_type == "bank_data_open_finance" and consent.external_consent_id:
        withdrawal.provider_revocation_status = "pending"
        withdrawal.next_retry_at = utcnow()
        retry_source_revocation(db, withdrawal, actor_key=principal.actor_key)
    else:
        withdrawal.provider_revocation_status = "confirmed"  # no provider holds a token for this consent
        withdrawal.revocation_confirmed_at = utcnow()
    # step 6: deletion scheduled (outside the K13 clock); never promised to the user as a date
    grace = int(get_config(db, "consent.retention.deletion_grace_days", 30) or 30)
    withdrawal.deletion_scheduled_at = utcnow()
    withdrawal.deletion_due_at = utcnow() + timedelta(days=grace)
    # step 7: affected drafts stale + owner notified (hook into the bookkeeping/tax modules when present)
    withdrawal.drafts_marked_stale = _mark_drafts_stale(db, consent)
    _end_dependent_evidence_access(db, principal, consent)
    receipt = build_withdrawal_receipt(db, consent, withdrawal)
    withdrawal.receipt_ref = receipt.receipt_id
    _notify_withdrawal(db, principal, consent, withdrawal)
    record_event(db, event_type="CONSENT_ENFORCEMENT_STEPS", category="consent", actor_key=principal.actor_key, company_id=consent.company_id, subject_type="consent_withdrawal", subject_id=withdrawal.withdrawal_id, details={"jobs_cancelled": cancelled, "pulls_stopped": withdrawal.pulls_stopped_at is not None, "k13_class": withdrawal.k13_class, "records_restricted": restricted, "records_on_legal_hold": on_hold, "provider_revocation_status": withdrawal.provider_revocation_status, "drafts_marked_stale": withdrawal.drafts_marked_stale})
    db.flush()
    return withdrawal


def _cancel_pulls(db: Session, consent_id: str) -> tuple[int, bool, bool]:
    try:
        from app.modules.datalinks.service import cancel_pulls_for_consent
    except ImportError:  # pragma: no cover
        return 0, False, True
    return cancel_pulls_for_consent(db, consent_id)


def _restrict_lineage(db: Session, consent_id: str) -> tuple[int, int]:
    try:
        from app.modules.datalinks.service import restrict_lineage_for_consent
    except ImportError:  # pragma: no cover
        return 0, 0
    return restrict_lineage_for_consent(db, consent_id)


def _mark_drafts_stale(db: Session, consent: Consent) -> int:
    for mod in ("app.modules.bookkeeping.service", "app.modules.tax.service"):
        try:
            import importlib

            fn = getattr(importlib.import_module(mod), "mark_drafts_stale_for_consent", None)
            if fn:
                return int(fn(db, consent.company_id, consent.consent_id) or 0)
        except Exception:  # other modules may be absent or still being built; the withdrawal never depends on them
            continue
    return 0


def _end_dependent_evidence_access(db: Session, principal: Principal, consent: Consent) -> None:
    if consent.consent_type == "auditor_specialist_evidence_access":
        return
    deps = db.scalars(select(Consent).where(Consent.company_id == consent.company_id, Consent.consent_type == "auditor_specialist_evidence_access", Consent.source == consent.source, Consent.status == "active"))
    for d in deps:
        d.status = "withdrawn_on_platform"
        d.status_reason = "underlying_consent_withdrawn"
        d.withdrawn_at = utcnow()
        invalidate_gate(d.consent_id)
        record_event(db, event_type="EVIDENCE_ACCESS_REVOKED", category="consent", actor_key=principal.actor_key, company_id=consent.company_id, subject_type="consent", subject_id=d.consent_id, details={"cause": "underlying_consent_withdrawn", "recipient": d.recipient}, log_class="consent")


def retry_source_revocation(db: Session, withdrawal: ConsentWithdrawal, *, actor_key: str | None = None) -> ConsentWithdrawal:
    """Provider-side revocation with the configured retry schedule; the gate block stays regardless of the result."""
    if withdrawal.provider_revocation_status in ("confirmed", "not_applicable"):
        return withdrawal
    schedule = get_config(db, "consent.withdrawal.source_revocation_retry_schedule", {}) or {}
    minutes = list(schedule.get("minutes", [1, 2, 4, 8, 16]))
    hourly_hours = int(schedule.get("then_hourly_for_hours", 24))
    withdrawal.revocation_attempt_count += 1
    outcome = _provider_revoke_stub(db, withdrawal)
    if outcome == "confirmed":
        withdrawal.provider_revocation_status = "confirmed"
        withdrawal.revocation_confirmed_at = utcnow()
        withdrawal.next_retry_at = None
        consent = db.get(Consent, withdrawal.consent_id)
        if consent is not None and consent.status == "withdrawn_on_platform":
            consent.status = "revocation_confirmed_by_provider"
            consent.external_status = "revoked"
        record_event(db, event_type="SOURCE_REVOCATION_CONFIRMED", category="consent", actor_key=actor_key, company_id=withdrawal.company_id, subject_type="consent_withdrawal", subject_id=withdrawal.withdrawal_id, details={"attempts": withdrawal.revocation_attempt_count})
        return withdrawal
    n = withdrawal.revocation_attempt_count
    if n <= len(minutes):
        withdrawal.provider_revocation_status = "retrying"
        withdrawal.next_retry_at = utcnow() + timedelta(minutes=int(minutes[n - 1]))
    elif n <= len(minutes) + hourly_hours:
        withdrawal.provider_revocation_status = "retrying"
        withdrawal.next_retry_at = utcnow() + timedelta(hours=1)
    else:
        withdrawal.provider_revocation_status = "failed"
        withdrawal.next_retry_at = None
        withdrawal.manual_ticket_ref = withdrawal.manual_ticket_ref or new_id("tkt")
        record_event(db, event_type="SOURCE_REVOCATION_TICKET", category="escalation", outcome="error", reason_code="SOURCE_REVOCATION_FAILED", actor_key=actor_key, company_id=withdrawal.company_id, subject_type="consent_withdrawal", subject_id=withdrawal.withdrawal_id, details={"ticket": withdrawal.manual_ticket_ref, "attempts": n})
    record_event(db, event_type="SOURCE_REVOCATION_ATTEMPT", category="consent", outcome="error" if outcome != "confirmed" else "success", reason_code=outcome.upper(), actor_key=actor_key, company_id=withdrawal.company_id, subject_type="consent_withdrawal", subject_id=withdrawal.withdrawal_id, details={"attempt": n, "status": withdrawal.provider_revocation_status})
    return withdrawal


def _provider_revoke_stub(db: Session, withdrawal: ConsentWithdrawal) -> str:
    """Open Finance revocation adapter stub: off in the pilot (no licensed route live), so it never confirms."""
    if not get_config(db, "datalinks.openfinance.enabled", False):
        return "route_not_live"
    simulated = get_config(db, "consent.provider_revocation.simulated_result", "confirmed")
    return "confirmed" if simulated == "confirmed" else "provider_error"


def timeline(db: Session, consent: Consent) -> dict | None:
    w = db.scalar(select(ConsentWithdrawal).where(ConsentWithdrawal.consent_id == consent.consent_id).order_by(ConsentWithdrawal.created_at.desc()))
    if w is None:
        return None
    rev_state = {"confirmed": "done", "not_applicable": "done", "pending": "in_progress", "retrying": "in_progress", "failed": "failed"}[w.provider_revocation_status]
    pulls_state = "done" if w.pulls_stopped_at else ("failed" if w.k13_class == "unenforced_open" else "in_progress")
    k13_minutes = None
    if w.pulls_stopped_at:
        k13_minutes = round((w.pulls_stopped_at - w.withdrawn_at).total_seconds() / 60, 2)
    return {
        "withdrawal_id": w.withdrawal_id,
        "withdrawn_at": w.withdrawn_at.isoformat(),
        "withdrawn_by": w.withdrawer_display_name,
        "withdrawer_role": w.withdrawer_role,
        "platform_status": w.platform_status,
        "provider_revocation_status": w.provider_revocation_status,
        "revocation_attempt_count": w.revocation_attempt_count,
        "next_retry_at": w.next_retry_at.isoformat() if w.next_retry_at else None,
        "manual_ticket_ref": w.manual_ticket_ref,
        "pulls_stopped_at": w.pulls_stopped_at.isoformat() if w.pulls_stopped_at else None,
        "deletion_scheduled_at": w.deletion_scheduled_at.isoformat() if w.deletion_scheduled_at else None,
        "k13_class": w.k13_class,
        "k13_minutes": k13_minutes,
        "jobs_cancelled": w.jobs_cancelled,
        "records_restricted": w.records_restricted,
        "records_on_legal_hold": w.records_on_legal_hold,
        "drafts_marked_stale": w.drafts_marked_stale,
        "receipt_ref": w.receipt_ref,
        "steps": [
            {"key": "withdrawn", "state": "done", "at": w.withdrawn_at.isoformat()},
            {"key": "pulls_stopped", "state": pulls_state, "at": w.pulls_stopped_at.isoformat() if w.pulls_stopped_at else None},
            {"key": "revoked_at_source", "state": rev_state, "source": consent.provider_name or consent.source, "at": w.revocation_confirmed_at.isoformat() if w.revocation_confirmed_at else None},
        ],
    }


def build_withdrawal_receipt(db: Session, consent: Consent, withdrawal: ConsentWithdrawal) -> ConsentReceipt:
    company = db.get(Company, consent.company_id)
    licence = db.scalar(select(Licence).where(Licence.company_id == consent.company_id))

    def content(lang: str) -> dict:
        return {
            "title": s("withdrawal_receipt.title", lang),
            "reference": None,  # filled below with the receipt number
            "company": f"{company.trade_name_en} / {company.trade_name_ar}" if company else "-",
            "licence_number": licence.licence_number if licence else None,
            "consent_type": consent.consent_type,
            "scope": {"source": consent.provider_name or consent.source, "data_types": consent.data_types, "accounts": [mask_account(a) for a in consent.account_ids], "purpose": consent.purpose},
            "withdrawn_line": s("withdrawal_receipt.withdrawn_on", lang, date=_fmt_dubai(withdrawal.withdrawn_at, lang), name=withdrawal.withdrawer_display_name or "-"),
            "effects": [s("withdrawal_receipt.pulls_stopped", lang), s("withdrawal_receipt.effect_drafts", lang), s("withdrawal_receipt.data_held", lang)],
            "microcopy": s("withdrawal_receipt.microcopy", lang),
            "retention": [s("retention.class_a", lang), s("retention.class_b", lang), s("retention.class_c", lang)],
            "how_to_reconsent": s("withdrawal_receipt.how_to_reconsent", lang),
            "support": s("withdrawal_receipt.support", lang),
            "not_legal": s("withdrawal_receipt.not_legal", lang),
        }

    number = f"WR-{utcnow():%Y%m%d}-{secrets.token_hex(3).upper()}"
    en, ar = content("en"), content("ar")
    en["reference"] = ar["reference"] = number
    receipt = ConsentReceipt(receipt_number=number, kind="withdrawal", consent_id=consent.consent_id, version=consent.version, template_version=str(get_config(db, "consent.withdrawal_receipt_template_version", "v1")), wording_version=consent.wording_version, content_en=en, content_ar=ar, audit_entry_ref=withdrawal.audit_entry_ref)
    db.add(receipt)
    db.flush()
    return receipt


def _notify_withdrawal(db: Session, principal: Principal, consent: Consent, withdrawal: ConsentWithdrawal) -> None:
    company = db.get(Company, consent.company_id)
    date = _fmt_dubai(withdrawal.withdrawn_at, "en")
    holders = authority_holders(db, consent.company_id)
    # withdrawer: in-portal receipt + email pointer; other holders: portal + minimal email; delegates: portal only
    notify(db, company_id=consent.company_id, recipients=[(principal.identity_uuid, principal.primary_role())], kind="consent_withdrawn_receipt", template_key="notice.consent_withdrawn", subject_type="consent_withdrawal", subject_id=withdrawal.withdrawal_id, params={"company": company.trade_name_en if company else "", "date": date}, channels=("portal", "email"))
    others = [(uuid, role) for uuid, role in holders if uuid != principal.identity_uuid]
    notify(db, company_id=consent.company_id, recipients=others, kind="consent_withdrawn", template_key="notice.consent_withdrawn", subject_type="consent_withdrawal", subject_id=withdrawal.withdrawal_id, params={"company": company.trade_name_en if company else "", "date": date}, channels=("portal", "email"))
    delegates = [(r.identity_uuid, "delegate") for r in db.scalars(select(CompanyRole).where(CompanyRole.company_id == consent.company_id, CompanyRole.role == "delegate", CompanyRole.status == "active")) if r.identity_uuid and r.identity_uuid != principal.identity_uuid]
    notify(db, company_id=consent.company_id, recipients=delegates, kind="consent_withdrawn_delegate", template_key="notice.consent_withdrawn_delegate", subject_type="consent_withdrawal", subject_id=withdrawal.withdrawal_id, params={"date": date}, channels=("portal",))


# --- pending cancel, resume, lifecycle ------------------------------------------------------------------


def cancel_pending(db: Session, principal: Principal, consent: Consent) -> Consent:
    if consent.status != "pending":
        raise Conflict("only a pending request can be cancelled", reason_code="CONSENT_NOT_PENDING")
    consent.status = "withdrawn_on_platform"
    consent.status_reason = "cancelled_before_confirmation"
    consent.withdrawn_at = utcnow()
    invalidate_gate(consent.consent_id)
    record_event(db, event_type="CONSENT_REQUEST_CANCELLED", category="consent", actor_key=principal.actor_key, company_id=consent.company_id, subject_type="consent", subject_id=consent.consent_id, log_class="consent")
    return consent


def authority_rule(db: Session, company_id: str) -> str:
    """Authority-evidence model (Q47): any_one | joint | unclear, from the DET licence persons."""
    licence = db.scalar(select(Licence).where(Licence.company_id == company_id))
    if licence is None:
        return "unclear"
    rules = {p.signing_rule for p in db.scalars(select(LicencePerson).where(LicencePerson.licence_id == licence.id)) if p.signing_rule}
    if not rules or "unclear" in rules:
        return "unclear"
    if "joint" in rules:
        return "joint"
    return "any_one"


def authority_holders(db: Session, company_id: str) -> list[tuple[str, str]]:
    rows = db.scalars(select(CompanyRole).where(CompanyRole.company_id == company_id, CompanyRole.role.in_(AUTHORITY_HOLDER_ROLES), CompanyRole.status == "active"))
    return [(r.identity_uuid, r.role) for r in rows if r.identity_uuid]


def licence_state(db: Session, company_id: str) -> dict:
    lic = db.scalar(select(Licence).where(Licence.company_id == company_id).order_by(Licence.created_at.desc()))
    return {"status": lic.status if lic else None, "expiry_date": lic.expiry_date if lic else None, "licence_number": lic.licence_number if lic else None}


def subscription_state(db: Session, company_id: str) -> str | None:
    """Lazy hook into the subscriptions module (E3); absent -> unknown, which never pauses on its own."""
    try:
        import importlib

        mod = importlib.import_module("app.modules.subscriptions.service")
        fn = getattr(mod, "effective_subscription_status", None)
        return str(fn(db, company_id)) if fn else None
    except Exception:
        return None


def resume_consent(db: Session, principal: Principal, consent: Consent) -> Consent:
    """Resume after pause (Q47): (a) licence renewed / subscription active, (b) own time limit not run out,
    (c) scope unchanged (always true for the stored record), (d) recorded time-stamped act by a holder."""
    if consent.status != "paused":
        raise Conflict("only a paused consent can be resumed", reason_code="CONSENT_NOT_PAUSED")
    rule = authority_rule(db, consent.company_id)
    if rule == "unclear":
        record_event(db, event_type="CONSENT_RESUME_REFUSED", category="consent", outcome="refused", reason_code="AUTHORITY_UNCLEAR", actor_key=principal.actor_key, company_id=consent.company_id, subject_type="consent", subject_id=consent.consent_id)
        db.commit()
        raise Forbidden(s("refusal.authority_unclear", principal.language), reason_code="AUTHORITY_UNCLEAR", details={"contact": "DET support"})
    if rule == "joint":
        record_event(db, event_type="CONSENT_RESUME_REFUSED", category="consent", outcome="refused", reason_code="JOINT_AUTHORITY_REQUIRED", actor_key=principal.actor_key, company_id=consent.company_id, subject_type="consent", subject_id=consent.consent_id)
        db.commit()
        raise Forbidden("joint signing authority is needed to resume; a second holder must confirm", reason_code="JOINT_AUTHORITY_REQUIRED")
    pause_limit = int(get_config(db, "consent.pause_limit_days", 90) or 90)
    if consent.paused_at and utcnow() - consent.paused_at > timedelta(days=pause_limit):
        raise Conflict("the pause limit has passed; a fresh consent is needed", reason_code="PAUSE_LIMIT_EXCEEDED")
    if consent.expires_at <= utcnow():
        raise Conflict("the consent period has ended; a fresh consent is needed", reason_code="CONSENT_EXPIRED")
    if consent.wording_version != wording_version(db):
        raise Conflict("the notice text changed; a fresh consent is needed", reason_code="WORDING_VERSION_CHANGED")
    lic = licence_state(db, consent.company_id)
    if consent.status_reason == "licence_expired" and lic["status"] != "active":
        raise Conflict("the licence is not active; resume is not possible", reason_code="LICENCE_NOT_ACTIVE")
    if consent.status_reason == "subscription_ended" and (subscription_state(db, consent.company_id) or "active") != "active":
        raise Conflict("the subscription is not active; resume is not possible", reason_code="SUBSCRIPTION_NOT_ACTIVE")
    consent.status = "active"
    consent.status_reason = None
    consent.resumed_at = utcnow()
    record_event(db, event_type="CONSENT_RESUMED", category="consent", actor_key=principal.actor_key, actor_role=principal.primary_role(), company_id=consent.company_id, subject_type="consent", subject_id=consent.consent_id, details={"authority_rule": rule, "assurance_level": principal.assurance_level}, log_class="consent")
    return consent


def run_lifecycle(db: Session, company_id: str | None = None, *, now: datetime | None = None) -> dict:
    """Expiry (Asia/Dubai), pause on licence expiry / subscription end, 90-day pause lapse, notices, K13 alerts."""
    now = now or utcnow()
    stmt = select(Consent).where(Consent.status.in_(("active", "pending", "paused")))
    if company_id:
        stmt = stmt.where(Consent.company_id == company_id)
    consents = list(db.scalars(stmt))
    pause_limit = int(get_config(db, "consent.pause_limit_days", 90) or 90)
    notice_offsets = [int(x) for x in (get_config(db, "consent.notice_offsets_days", [30, 7]) or [])]
    reminder_offsets = [int(x) for x in (get_config(db, "consent.expiry_reminder_offsets_days", [30, 7, 1]) or [])]
    out = {"expired": 0, "paused": 0, "lapsed": 0, "notices": 0}
    licence_cache: dict[str, dict] = {}
    sub_cache: dict[str, str | None] = {}
    for c in consents:
        company = db.get(Company, c.company_id)
        cname = company.trade_name_en if company else ""
        holders = authority_holders(db, c.company_id)
        if c.company_id not in licence_cache:
            licence_cache[c.company_id] = licence_state(db, c.company_id)
            sub_cache[c.company_id] = subscription_state(db, c.company_id)
        lic = licence_cache[c.company_id]
        if c.status in ("active", "pending") and c.expires_at <= now:
            c.status, c.status_reason, c.expired_at = "expired", "period_ended", now
            invalidate_gate(c.consent_id)
            record_event(db, event_type="CONSENT_EXPIRED", category="consent", company_id=c.company_id, subject_type="consent", subject_id=c.consent_id, details={"version": c.version}, log_class="consent")
            out["expired"] += 1
            continue
        if c.status == "paused" and c.paused_at and now - c.paused_at > timedelta(days=pause_limit):
            c.status, c.status_reason, c.expired_at = "expired", "pause_limit_exceeded", now
            invalidate_gate(c.consent_id)
            record_event(db, event_type="CONSENT_PAUSE_LIMIT_EXPIRED", category="consent", company_id=c.company_id, subject_type="consent", subject_id=c.consent_id, details={"pause_limit_days": pause_limit}, log_class="consent")
            out["lapsed"] += 1
            out["notices"] += notify(db, company_id=c.company_id, recipients=holders, kind="pause_limit_expired", template_key="notice.pause_limit_expired", subject_type="consent", subject_id=c.consent_id, params={"company": cname, "date": _fmt_dubai(now, "en")}, dedupe_key=f"pause_limit:{c.consent_id}")
            continue
        if c.status in ("active", "pending"):
            pause_reason = None
            if lic["status"] in ("expired", "cancelled", "suspended"):
                pause_reason = "licence_expired"
            elif (sub_cache[c.company_id] or "") in ("ended", "lapsed", "cancelled"):
                pause_reason = "subscription_ended"
            if pause_reason in PAUSE_REASONS:
                c.status, c.status_reason, c.paused_at = "paused", pause_reason, now
                invalidate_gate(c.consent_id)
                _cancel_pulls(db, c.consent_id)
                record_event(db, event_type="CONSENT_PAUSED", category="consent", reason_code=pause_reason.upper(), company_id=c.company_id, subject_type="consent", subject_id=c.consent_id, log_class="consent")
                out["paused"] += 1
                out["notices"] += notify(db, company_id=c.company_id, recipients=holders, kind="consent_paused", template_key="notice.paused", subject_type="consent", subject_id=c.consent_id, params={"company": cname, "date": _fmt_dubai(now, "en"), "reason": s(f"pause.reason.{pause_reason}", "en")}, dedupe_key=f"paused:{c.consent_id}:{pause_reason}")
                continue
            days_left = (c.expires_at - now).days
            for off in sorted(set(notice_offsets + reminder_offsets)):
                if days_left == off:
                    out["notices"] += notify(db, company_id=c.company_id, recipients=holders + delegates_with_consent_right(db, c.company_id), kind=f"consent_expiry_{off}d", template_key="notice.consent_expiry", subject_type="consent", subject_id=c.consent_id, params={"company": cname, "date": _fmt_dubai(c.expires_at, "en")}, dedupe_key=f"expiry:{c.consent_id}:{off}")
            if lic["expiry_date"]:
                lic_days = (lic["expiry_date"] - dubai_date(now)).days
                for off in notice_offsets:
                    if lic_days == off:
                        out["notices"] += notify(db, company_id=c.company_id, recipients=holders, kind=f"licence_expiry_{off}d", template_key="notice.licence_expiry", subject_type="licence", subject_id=lic["licence_number"], params={"company": cname, "date": str(lic["expiry_date"])}, dedupe_key=f"licence_expiry:{c.company_id}:{lic['expiry_date']}:{off}")
    out["ops_alerts"] = _k13_alerts(db, now)
    out["revocation_retries"] = _due_revocation_retries(db, now)
    out["requests_expired"] = _expire_requests(db, now)
    db.flush()
    return out


def delegates_with_consent_right(db: Session, company_id: str) -> list[tuple[str, str]]:
    if not delegate_right_enabled(db, "grant_consent"):
        return []
    rows = db.scalars(select(CompanyRole).where(CompanyRole.company_id == company_id, CompanyRole.role == "delegate", CompanyRole.status == "active"))
    return [(r.identity_uuid, "delegate") for r in rows if r.identity_uuid and "grant_consent" in (r.rights or [])]


def _k13_alerts(db: Session, now: datetime) -> int:
    pulls_after = int(get_config(db, "consent.withdrawal.alert_pulls_stopped_empty_after_minutes", 5) or 5)
    rev_after = int(get_config(db, "consent.withdrawal.alert_source_revocation_pending_after_minutes", 15) or 15)
    n = 0
    for w in db.scalars(select(ConsentWithdrawal).where(ConsentWithdrawal.ops_alert_raised.is_(False))):
        age_min = (now - w.withdrawn_at).total_seconds() / 60
        reasons = []
        if w.pulls_stopped_at is None and age_min >= pulls_after:
            reasons.append("PULLS_STOPPED_EMPTY")
            w.k13_class = "unenforced_open"
        if w.provider_revocation_status in ("pending", "retrying") and age_min >= rev_after:
            reasons.append("SOURCE_REVOCATION_PENDING")
        if reasons:
            w.ops_alert_raised = True
            n += 1
            record_event(db, event_type="WITHDRAWAL_OPS_ALERT", category="escalation", outcome="error", reason_code=",".join(reasons), company_id=w.company_id, subject_type="consent_withdrawal", subject_id=w.withdrawal_id, details={"age_minutes": round(age_min, 1), "k13_class": w.k13_class})
    return n


def _due_revocation_retries(db: Session, now: datetime) -> int:
    n = 0
    for w in db.scalars(select(ConsentWithdrawal).where(ConsentWithdrawal.provider_revocation_status.in_(("pending", "retrying")))):
        if w.next_retry_at and w.next_retry_at <= now:
            retry_source_revocation(db, w)
            n += 1
    return n


def _expire_requests(db: Session, now: datetime) -> int:
    n = 0
    for r in db.scalars(select(ConsentRequest).where(ConsentRequest.status == "open", ConsentRequest.expires_at <= now)):
        r.status = "expired"
        n += 1
    return n


def external_revocation_signal(db: Session, *, external_consent_id: str | None = None, consent_id: str | None = None, external_status: str = "revoked", actor_key: str | None = None) -> Consent:
    """Provider webhook / 15-minute poll result: the external side wins (stricter)."""
    stmt = select(Consent).where(Consent.status.in_(("active", "pending", "paused")))
    stmt = stmt.where(Consent.consent_id == consent_id) if consent_id else stmt.where(Consent.external_consent_id == external_consent_id)
    consent = db.scalar(stmt)
    if consent is None:
        raise NotFound("no live consent for this provider identifier", reason_code="CONSENT_NOT_FOUND")
    consent.external_status = external_status
    consent.status = "withdrawn_on_platform"
    consent.status_reason = "withdrawn_at_source"
    consent.withdrawn_at = utcnow()
    invalidate_gate(consent.consent_id)
    cancelled, had_jobs, ok = _cancel_pulls(db, consent.consent_id)
    restricted, on_hold = _restrict_lineage(db, consent.consent_id)
    w = ConsentWithdrawal(consent_id=consent.consent_id, version=consent.version, company_id=consent.company_id, withdrawn_at=consent.withdrawn_at, withdrawer_role="provider", withdrawer_display_name=consent.provider_name, provider_revocation_status="confirmed", revocation_confirmed_at=utcnow(), jobs_cancelled=cancelled, pulls_stopped_at=utcnow() if ok else None, k13_class=("normal" if had_jobs else "no_scheduled_pulls") if ok else "unenforced_open", records_restricted=restricted, records_on_legal_hold=on_hold)
    db.add(w)
    consent.status = "revocation_confirmed_by_provider"
    record_event(db, event_type="CONSENT_WITHDRAWN_AT_SOURCE", category="consent", actor_key=actor_key, company_id=consent.company_id, subject_type="consent", subject_id=consent.consent_id, details={"external_status": external_status, "jobs_cancelled": cancelled}, log_class="consent")
    db.flush()
    return consent


# --- request-right action and notifications -------------------------------------------------------------


def request_right(db: Session, principal: Principal, company_id: str, consent_type: str, scope: dict | None = None) -> ConsentRequest:
    """View-only delegate (or remote owner for tax data) asks the owner; logged; grants nothing; rate-limited."""
    if consent_type not in CONSENT_TYPES:
        raise ValidationFailed("unknown consent type", reason_code="CONSENT_TYPE_INVALID")
    max_per_day = int(get_config(db, "consent.request_right.max_per_day", 3) or 3)
    since = utcnow() - timedelta(days=1)
    recent = len(list(db.scalars(select(ConsentRequest).where(ConsentRequest.company_id == company_id, ConsentRequest.requester_identity_uuid == principal.identity_uuid, ConsentRequest.requested_at >= since))))
    if recent >= max_per_day:
        record_event(db, event_type="CONSENT_RIGHT_REQUEST_REFUSED", category="consent", outcome="refused", reason_code="RATE_LIMITED", actor_key=principal.actor_key, company_id=company_id)
        db.commit()
        raise Conflict("you have already asked today; the owner has been told", reason_code="RATE_LIMITED", details={"max_per_day": max_per_day})
    expiry_days = int(get_config(db, "consent.request_right.expiry_days", 14) or 14)
    req = ConsentRequest(company_id=company_id, requester_identity_uuid=principal.identity_uuid, requester_display_name=principal.display_name, requester_role=principal.primary_role(), consent_type=consent_type, scope=scope or {}, expires_at=utcnow() + timedelta(days=expiry_days))
    db.add(req)
    db.flush()
    company = db.get(Company, company_id)
    holders = [(u, r) for u, r in authority_holders(db, company_id) if u != principal.identity_uuid]
    req.notified_count = notify(db, company_id=company_id, recipients=holders, kind="consent_request", template_key="notice.consent_request", subject_type="consent_request", subject_id=req.request_id, params={"requester": principal.display_name, "company": company.trade_name_en if company else "", "date": _fmt_dubai(req.requested_at, "en")}, channels=("portal", "email"))
    record_event(db, event_type="CONSENT_RIGHT_REQUESTED", category="consent", actor_key=principal.actor_key, actor_role=principal.primary_role(), company_id=company_id, subject_type="consent_request", subject_id=req.request_id, details={"consent_type": consent_type, "scope_keys": sorted((scope or {}).keys()), "expires_at": req.expires_at.isoformat(), "grants": "nothing"}, log_class="consent")
    return req


def notify(db: Session, *, company_id: str | None, recipients: list[tuple[str, str]], kind: str, template_key: str, subject_type: str | None, subject_id: str | None, params: dict, channels: tuple[str, ...] = ("portal", "email"), dedupe_key: str | None = None) -> int:
    """In-portal notice records plus a minimal email stub. Content never carries figures or identity numbers."""
    channel_cfg = get_config(db, "notifications.channels", {"portal": True, "email": True}) or {}
    n = 0
    for uuid, role in recipients:
        for ch in channels:
            if not channel_cfg.get(ch, ch == "portal"):
                continue
            dk = f"{dedupe_key}:{uuid}:{ch}" if dedupe_key else None
            if dk and db.scalar(select(Notification).where(Notification.dedupe_key == dk)) is not None:
                continue
            note = Notification(company_id=company_id, recipient_identity_uuid=uuid, recipient_role=role, channel=ch, kind=kind, template_key=template_key, subject_type=subject_type, subject_id=subject_id, dedupe_key=dk, body_en=s(template_key, "en", **params), body_ar=s(template_key, "ar", **params), delivery_status="delivered" if ch == "portal" else "stub_queued")
            db.add(note)
            n += 1
            record_event(db, event_type="NOTICE_SENT", category="reminder", company_id=company_id, subject_type=subject_type, subject_id=subject_id, details={"kind": kind, "channel": ch, "delivery_status": note.delivery_status, "recipient_role": role})
    db.flush()
    return n


# --- reads -----------------------------------------------------------------------------------------------


def get_consent(db: Session, company_id: str, consent_id: str) -> Consent:
    c = db.get(Consent, consent_id)
    if c is None or c.company_id != company_id:
        raise NotFound("consent not found", reason_code="CONSENT_NOT_FOUND")
    return c


def list_consents(db: Session, company_id: str) -> list[Consent]:
    return list(db.scalars(select(Consent).where(Consent.company_id == company_id).order_by(Consent.granted_at.desc())))


def serialize_consent(db: Session, c: Consent, *, include_timeline: bool = True) -> dict:
    lists = controlled_lists(db)
    all_types = lists["data_types"].get(c.source, [])
    display_status = c.status
    if c.status == "paused":
        display_status = f"paused_{c.status_reason}" if c.status_reason in PAUSE_REASONS else "paused"
    out: dict[str, Any] = {
        "consent_id": c.consent_id,
        "version": c.version,
        "company_id": c.company_id,
        "consent_type": c.consent_type,
        "source": c.source,
        "provider_name": c.provider_name,
        "data_types": c.data_types,
        "data_types_not_read": [d for d in all_types if d not in c.data_types],
        "accounts_masked": [mask_account(a) for a in c.account_ids],
        "purpose": c.purpose,
        "recipient": c.recipient,
        "valid_from": c.valid_from.isoformat(),
        "expires_at": c.expires_at.isoformat(),
        "expires_at_dubai": to_dubai(c.expires_at).isoformat(),
        "route_limit_applied": c.route_limit_applied,
        "list_version": c.list_version,
        "status": c.status,
        "display_status": display_status,
        "status_reason": c.status_reason,
        "grantor_display_name": c.grantor_display_name,
        "grantor_role": c.grantor_role,
        "grantor_capacity": c.grantor_capacity,
        "identity_assurance_level": c.identity_assurance_level,
        "granted_at": c.granted_at.isoformat(),
        "granting_owner_name": c.granting_owner_name,
        "delegation_id": c.delegation_id,
        "granted_by_removed_delegate": c.granted_by_removed_delegate,
        "external_consent_id": c.external_consent_id,
        "external_status": c.external_status,
        "wording_version": c.wording_version,
        "receipt_ref": c.receipt_ref,
        "audit_entry_ref": c.audit_entry_ref,
        "superseded_by": c.superseded_by,
        "paused_at": c.paused_at.isoformat() if c.paused_at else None,
        "withdrawn_at": c.withdrawn_at.isoformat() if c.withdrawn_at else None,
        "expired_at": c.expired_at.isoformat() if c.expired_at else None,
        "is_demo": c.is_demo,
        "days_left": (c.expires_at - utcnow()).days if c.status in ("active", "pending", "paused") else None,
    }
    if include_timeline:
        out["timeline"] = timeline(db, c)
    return out


def receipt_for(db: Session, consent: Consent, kind: str = "grant") -> ConsentReceipt | None:
    return db.scalar(select(ConsentReceipt).where(ConsentReceipt.consent_id == consent.consent_id, ConsentReceipt.kind == kind).order_by(ConsentReceipt.created_at.desc()))


def version_history(db: Session, consent: Consent) -> list[dict]:
    rows = list(db.scalars(select(Consent).where(Consent.scope_key == consent.scope_key).order_by(Consent.version)))
    out = []
    prev: Consent | None = None
    for r in rows:
        item = serialize_consent(db, r, include_timeline=False)
        if prev is not None:
            item["compare"] = {"added": sorted(set(r.data_types) - set(prev.data_types)), "removed": sorted(set(prev.data_types) - set(r.data_types)), "accounts_added": [mask_account(a) for a in set(r.account_ids) - set(prev.account_ids)], "accounts_removed": [mask_account(a) for a in set(prev.account_ids) - set(r.account_ids)], "expiry_changed": r.expires_at != prev.expires_at}
        out.append(item)
        prev = r
    return out


def k13_stats(db: Session) -> dict:
    rows = list(db.scalars(select(ConsentWithdrawal)))
    measured = [(w.pulls_stopped_at - w.withdrawn_at).total_seconds() / 60 for w in rows if w.pulls_stopped_at and w.k13_class in ("normal", "no_scheduled_pulls")]
    measured.sort()
    median = measured[len(measured) // 2] if measured else None
    return {
        "count": len(rows),
        "no_scheduled_pulls_count": sum(1 for w in rows if w.k13_class == "no_scheduled_pulls"),
        "unenforced_open_count": sum(1 for w in rows if w.k13_class == "unenforced_open"),
        "mean_minutes": round(sum(measured) / len(measured), 2) if measured else None,
        "median_minutes": round(median, 2) if median is not None else None,
        "max_minutes": round(max(measured), 2) if measured else None,
        "target_minutes": get_config(db, "consent.k13_target_minutes", 5),
    }


def mark_removed_delegate_grants(db: Session, company_id: str, delegate_identity_uuid: str) -> int:
    """When a delegate's access is removed, consents they granted stay active until the owner decides (Keep/Withdraw)."""
    n = 0
    for c in db.scalars(select(Consent).where(Consent.company_id == company_id, Consent.grantor_identity_uuid == delegate_identity_uuid, Consent.status.in_(("active", "pending", "paused")))):
        c.granted_by_removed_delegate = True
        n += 1
    if n:
        notify(db, company_id=company_id, recipients=authority_holders(db, company_id), kind="removed_delegate_grant", template_key="notice.removed_delegate_grant", subject_type="company", subject_id=company_id, params={}, dedupe_key=f"removed_delegate:{company_id}:{delegate_identity_uuid}")
    return n
