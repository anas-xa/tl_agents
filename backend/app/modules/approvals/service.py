"""Approval workflow (E6-S1), delegate approval grants (E6-S2) and the manual filing path with the
pre-submission gate (E6-S3). The platform never files: the owner or authorised signatory files in EmaraTax and
records the outcome here. Nothing is ever auto-approved; a timeout never counts as approval.
"""

from __future__ import annotations

import hashlib
import re
from datetime import date, datetime, time, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import Conflict, Forbidden, NotFound, SwitchedOff, ValidationFailed
from app.core.time import dubai_today, utcnow
from app.modules.access.service import authorize, require_step_up
from app.modules.approvals.models import (
    Approval,
    ApprovalRequest,
    ApprovalStatusEvent,
    AuthorityHolder,
    DelegateApprovalGrant,
    GateDecision,
    GrantEvent,
    ManualFilingEdit,
    ManualFilingRecord,
)
from app.modules.approvals.strings import (
    BLOCKED_CAUSE_LABELS,
    DECLARATION_WORDING,
    DECLARATION_WORDING_VERSION,
    FILING_STATE_LABELS,
    GRANT_WORDING_VERSION,
    STRINGS,
)
from app.modules.audit.service import AuditWriteError, record_event
from app.modules.companies.models import Company, CompanyRole
from app.modules.config.models import RuleRegisterEntry
from app.modules.config.service import get_config
from app.modules.drafts import service as drafts
from app.modules.drafts.models import DraftPack
from app.modules.licences.models import Licence, LicencePerson

OWNER_LEVEL = ("owner", "remote_owner")
NOT_REVIEWED = ("not_reviewed", "prepared", "stale")
UNAPPROVABLE = ("superseded", "stale", "filed_user_confirmed")
GST_OFFSET = timedelta(hours=4)
REF_RE = re.compile(r"^[A-Za-z0-9]+$")
RECEIPT_TYPES = ("application/pdf", "image/png", "image/jpeg")
# Phrases never used for the approval act or a filing the platform did not make (tests assert on outputs).
BANNED_WORDING = (
    "electronic signature", "legally binding", "legal signature", "power of attorney", "FTA-recognised authority",
    "Tax Agent", "audit certificate", "certified", "Filed (confirmed)", "confirmed by the tax authority", "amend",
    "correct your return", "file again", "do not file", "Do not file manually yet", "penalty", "late filing",
)


def S(key: str, lang: str = "en") -> str:
    v = STRINGS[key]
    return v.get(lang) or v["en"]


def check_wording(text: str) -> list[str]:
    low = text.lower()
    return [t for t in BANNED_WORDING if t.lower() in low]


def _int(db: Session, key: str, default: int) -> int:
    try:
        return int(get_config(db, key, default))
    except (TypeError, ValueError):
        return default


def _ref(value: str | None) -> str | None:
    return hashlib.sha256(value.encode()).hexdigest()[:16] if value else None


def short_hash(h: str | None) -> str:
    return (h or "")[:8]


# --- roles -----------------------------------------------------------------------------------------


def role_on(principal: Any, company_id: str) -> str:
    roles = principal.roles_for(company_id)
    return roles[0].role if roles else "none"


def owner_blocked(db: Session, principal: Any, company_id: str) -> bool:
    """Owner-level role on record but no matched Emirates ID: no owner-level role (NO_OWNER_ROLE)."""
    if getattr(principal, "det_match_result", "matched") == "matched":
        return False
    return db.scalar(select(CompanyRole).where(CompanyRole.identity_uuid == principal.identity_uuid, CompanyRole.company_id == company_id, CompanyRole.role.in_(OWNER_LEVEL), CompanyRole.status == "active").limit(1)) is not None


def _refuse(db: Session, principal: Any, company_id: str, code: str, message: str, *, exc: type = Forbidden, subject_id: str | None = None, event: str = "APPROVAL_REFUSED", details: dict | None = None) -> None:
    record_event(db, event_type=event, category="approval", outcome="refused", reason_code=code, actor_key=getattr(principal, "actor_key", None), actor_role=role_on(principal, company_id) if principal else None, company_id=company_id, subject_type="approval_request", subject_id=subject_id, details=details)
    raise exc(message, reason_code=code, details=details or {})


# --- configuration-derived values ------------------------------------------------------------------


def flow_enabled(db: Session) -> bool:
    return bool(get_config(db, "approval.flow_enabled", True))


def phase_b_on(db: Session, company_id: str) -> bool:
    """Delegate approval (Phase B) switch: global right switch AND the company listed. Default OFF."""
    if not get_config(db, "delegate_rights.approve_submissions.enabled", False):
        return False
    return company_id in (get_config(db, "approval.phase_b.enabled_companies", []) or [])


def validity_days(db: Session) -> int:
    lo, hi = _int(db, "approval.validity_days.min", 1), _int(db, "approval.validity_days.max", 30)
    return max(lo, min(hi, _int(db, "approval.validity_days", 7)))


def due_end_utc(due: date) -> datetime:
    """End of the due date in Gulf Standard Time (UTC+4), as naive UTC. No clock time is invented for display."""
    return datetime.combine(due, time(23, 59, 59)) - GST_OFFSET


def compute_valid_until(db: Session, approved_at: datetime, due: date | None) -> dict:
    """min(approved_at + window, end of the filing due date). The window is configuration (default 7, 1-30)."""
    days = validity_days(db)
    window_end = approved_at + timedelta(days=days)
    out = {"valid_until": window_end, "days": days, "capped_at_due_date": False, "due_date_passed": False, "warn_due_closer": False}
    if due is not None:
        cap = due_end_utc(due)
        if cap < approved_at:
            out["due_date_passed"] = True  # cap cannot lie in the past; window applies (neutral, information only)
        elif cap < window_end:
            out |= {"valid_until": cap, "capped_at_due_date": True, "warn_due_closer": True}
    return out


def pack_due_date(db: Session, pack: DraftPack) -> tuple[date | None, str, date | None, date | None]:
    """Due-date precedence: the authority's due date always prevails (config override); computed date is a
    cross-check only; no-roll rule (a statutory date is never moved)."""
    override = get_config(db, "filing.authority_due_dates", {}) or {}
    key = f"{pack.company_id}|{pack.tax_type}|{pack.period_id}"
    start = end = None
    calc = None
    try:
        from app.modules.tax import service as tax

        calc = db.get(tax.CalculationResult, pack.calculation_id) if pack.calculation_id else None
        if calc is not None:
            start, end = calc.period_start, calc.period_end
        else:
            start, end = tax.period_for(db, pack.company_id, pack.period_id)
    except Exception:  # period unknown for this company
        pass
    if key in override:
        return date.fromisoformat(str(override[key])), "authority", start, end
    if calc is not None and getattr(calc, "due_date", None):
        return calc.due_date, calc.due_date_source or "computed", start, end
    if end is not None:
        try:
            from app.modules.tax import service as tax

            d, src = tax.due_date_for(db, pack.company_id, pack.tax_type, end)
            return d, src, start, end
        except Exception:
            pass
    return None, "unknown", start, end


def rule_version_ids(pack: DraftPack) -> list[dict]:
    refs = ((pack.basis or {}).get("rule_refs") or {}) if isinstance(pack.basis, dict) else {}
    out = [{"rule_id": v.get("rule_id"), "version": v.get("version"), "instrument": v.get("instrument"), "effective_from": v.get("effective_from"), "status": v.get("status")} for v in refs.values() if isinstance(v, dict) and v.get("rule_id")]
    if not out and pack.rule_version:
        out = [{"rule_id": None, "version": pack.rule_version}]
    return out


def rule_version_superseded(db: Session, ids: list[dict] | None) -> bool:
    for r in ids or []:
        if not r.get("rule_id"):
            continue
        cur = db.scalar(select(RuleRegisterEntry).where(RuleRegisterEntry.rule_id == r["rule_id"], RuleRegisterEntry.is_current.is_(True)))
        if cur is None or (r.get("version") and cur.version != r["version"]):
            return True
    return False


def pack_amounts(pack: DraftPack) -> list[dict]:
    return [{"key": ln["key"], "term": ln.get("term"), "value_fils": ln.get("value_fils")} for ln in (pack.lines or []) if ln.get("value_fils") is not None]


def headline_amount(pack: DraftPack) -> int | None:
    for key in ("net_vat", "tax"):
        for ln in pack.lines or []:
            if ln.get("key") == key:
                return ln.get("value_fils")
    return None


# --- authority-evidence model (Q110) -------------------------------------------------------------

CAPACITY_MAP = {"owner": "owner", "partner": "partner", "manager": "manager", "authorised_signatory": "signatory", "signatory": "signatory", "attorney": "attorney"}
RULE_MAP = {"any_one": "any_one", "joint": "two_together", "two_together": "two_together"}


def _norm(name: str | None) -> str:
    return " ".join((name or "").lower().split())


def ensure_authority(db: Session, company_id: str) -> list[AuthorityHolder]:
    """Holders for the company; derived from the DET licence record on first use (primary source). Signing
    powers are not assumed machine-readable: silent or ambiguous text maps to 'unclear'. Determinations logged."""
    rows = list(db.scalars(select(AuthorityHolder).where(AuthorityHolder.company_id == company_id)))
    if rows:
        return rows
    licence = db.scalar(select(Licence).where(Licence.company_id == company_id).order_by(Licence.created_at.desc()))
    if licence is None:
        return []
    for p in db.scalars(select(LicencePerson).where(LicencePerson.licence_id == licence.id)):
        rule = RULE_MAP.get(p.signing_rule or "", "unclear")
        h = AuthorityHolder(company_id=company_id, display_name=p.display_name, capacity=CAPACITY_MAP.get(p.capacity, "signatory"), source_document=p.source_document or "DET licence record", source_version=licence.status_mapping_version, rule_type=rule, quorum_n=2 if rule == "two_together" else 1, valid_to=p.valid_to, determination_note="derived from the DET licence record")
        db.add(h)
        db.flush()
        rows.append(h)
        record_event(db, event_type="AUTHORITY_DETERMINED", category="approval", company_id=company_id, subject_type="authority_holder", subject_id=h.id, details={"rule_type": rule, "capacity": h.capacity, "source": "det_record"})
    return rows


def _holder_valid(h: AuthorityHolder, today: date | None = None) -> bool:
    today = today or dubai_today()
    return h.active and h.verification_status == "verified" and (h.valid_from is None or h.valid_from <= today) and (h.valid_to is None or h.valid_to >= today)


def authority_rule(db: Session, company_id: str) -> tuple[str, int]:
    """any_one | two_together (N of M) | unclear. Conflicting, silent or expired evidence -> unclear (never
    defaults to any_one)."""
    holders = [h for h in ensure_authority(db, company_id) if h.action_class == "approve_return" and h.active]
    valid = [h for h in holders if _holder_valid(h)]
    if not valid:
        return "unclear", 0
    types = {h.rule_type for h in valid}
    if "unclear" in types or len(types) > 1:
        return "unclear", 0
    if types == {"two_together"}:
        return "two_together", max(h.quorum_n for h in valid)
    return "any_one", 1


def holder_for(db: Session, company_id: str, principal: Any) -> AuthorityHolder | None:
    holders = [h for h in ensure_authority(db, company_id) if h.action_class == "approve_return" and h.active]
    for h in holders:
        if h.identity_uuid == principal.identity_uuid:
            return h
    for h in holders:
        if h.identity_uuid is None and _norm(h.display_name) == _norm(principal.display_name):
            h.identity_uuid = principal.identity_uuid
            record_event(db, event_type="AUTHORITY_HOLDER_BOUND", category="approval", actor_key=principal.actor_key, company_id=company_id, subject_type="authority_holder", subject_id=h.id)
            db.flush()
            return h
    return None


# --- entitlement (server-side at the moment of decision) ---------------------------------------


def _grant_covers(g: DelegateApprovalGrant, pack: DraftPack, due: date | None, today: date) -> bool:
    if g.status != "active" or g.start_date > today or g.end_date < today:
        return False
    if g.scope_option == "single_return" and g.used_by_approval_id:
        return False
    for item in g.scope_items or []:
        if item.get("submission_type", "return_pack") != "return_pack" or item.get("tax_type") != pack.tax_type:
            continue
        if g.scope_option == "single_return" and item.get("period_id") == pack.period_id:
            break
        if g.scope_option == "time_period" and due is not None and g.start_date <= due <= g.end_date:
            break
    else:
        return False
    if g.max_amount_fils is not None:
        amt = headline_amount(pack)
        if amt is not None and abs(amt) > g.max_amount_fils:
            return False
    return True


def grant_authority_valid(db: Session, g: DelegateApprovalGrant) -> bool:
    """Re-check the granting owner's authority (and the delegate's role) at each use."""
    owner_role = db.scalar(select(CompanyRole).where(CompanyRole.identity_uuid == g.granting_owner_uuid, CompanyRole.company_id == g.company_id, CompanyRole.role.in_(OWNER_LEVEL), CompanyRole.status == "active").limit(1))
    holder = db.get(AuthorityHolder, g.granting_authority_ref) if g.granting_authority_ref else None
    return owner_role is not None and holder is not None and _holder_valid(holder)


def delegate_active(db: Session, company_id: str, identity_uuid: str) -> bool:
    return db.scalar(select(CompanyRole).where(CompanyRole.identity_uuid == identity_uuid, CompanyRole.company_id == company_id, CompanyRole.role == "delegate", CompanyRole.status == "active").limit(1)) is not None


def entitlement(db: Session, principal: Any, req: ApprovalRequest, pack: DraftPack, *, log: bool = True) -> dict:
    """Allow or refuse with a reason code. Owner-level identity (matched Emirates ID) + valid authority evidence,
    or a delegate with a valid in-scope grant while the Phase B switch is ON. Refusals are logged."""
    cid = req.company_id
    role = role_on(principal, cid)

    def refuse(code: str, msg: str, exc: type = Forbidden) -> None:
        if log:
            _refuse(db, principal, cid, code, msg, exc=exc, subject_id=req.id)
        raise exc(msg, reason_code=code)

    if role == "none":
        if owner_blocked(db, principal, cid):
            refuse("NO_OWNER_ROLE", S("NO_OWNER_ROLE"))
        refuse("NO_PERMISSION", S("view_only"))
    if role in OWNER_LEVEL:
        try:
            require_step_up(db, principal, "returns.approve")
        except Forbidden:
            if log:
                record_event(db, event_type="STEP_UP_REQUIRED", category="approval", outcome="refused", reason_code="LEVEL_TOO_LOW_FOR_ACTION", actor_key=principal.actor_key, company_id=cid, subject_type="approval_request", subject_id=req.id)
            raise
        from app.modules.delegates.service import require_not_on_hold

        require_not_on_hold(db, cid, "returns.approve", principal=principal)
        rule, n = authority_rule(db, cid)
        if rule == "unclear":
            refuse("AUTHORITY_UNCLEAR", S("authority_unclear"))
        holder = holder_for(db, cid, principal)
        if holder is None:
            refuse("NOT_AUTHORITY_HOLDER", S("view_only"))
        if holder.verification_status != "verified":
            refuse("AUTHORITY_NEEDS_REVERIFICATION", S("authority_unclear"))
        if not _holder_valid(holder):
            refuse("AUTHORITY_EXPIRED", S("authority_unclear"))
        company = db.get(Company, cid)
        abroad = role == "remote_owner" or (company is not None and company.owner_location_self_declared == "abroad")
        return {"role": role, "capacity": "owner" if holder.capacity == "owner" else "authorised_signatory", "display_role": "Owner abroad" if abroad else "Owner", "holder": holder, "rule": rule, "quorum": n, "grant": None, "delegation_basis": None}
    if role == "delegate":
        if not phase_b_on(db, cid):
            refuse("RIGHT_SWITCHED_OFF", S("phase_b_off"), SwitchedOff)
        require_step_up(db, principal, "returns.approve")
        from app.modules.delegates.service import require_not_on_hold

        require_not_on_hold(db, cid, "returns.approve", principal=principal)
        if pack.on_hold:
            refuse("ON_HOLD", S("on_hold_owner_decides"))
        due, _, _, _ = pack_due_date(db, pack)
        today = dubai_today()
        grants = list(db.scalars(select(DelegateApprovalGrant).where(DelegateApprovalGrant.company_id == cid, DelegateApprovalGrant.delegate_uuid == principal.identity_uuid)))
        for g in grants:
            if g.status == "active" and not grant_authority_valid(db, g):
                _grant_status(db, g, "suspended", "granting_authority_lost")
        grant = next((g for g in grants if _grant_covers(g, pack, due, today)), None)
        if grant is None:
            states = {g.status for g in grants}
            code = "GRANT_SUSPENDED" if "suspended" in states else "GRANT_EXPIRED" if "expired" in states else "GRANT_REVOKED" if "revoked" in states else "NO_APPROVAL_RIGHT"
            refuse(code, S("view_only"))
        rule, _ = authority_rule(db, cid)
        if rule != "any_one":
            refuse("DELEGATE_NOT_IN_QUORUM" if rule == "two_together" else "AUTHORITY_UNCLEAR", S("view_only") if rule == "two_together" else S("authority_unclear"))
        basis = {"grant_id": grant.id, "granting_owner_uuid": grant.granting_owner_uuid, "granting_owner_name": grant.granting_owner_name, "start_date": grant.start_date.isoformat(), "end_date": grant.end_date.isoformat()}
        return {"role": role, "capacity": "delegate", "display_role": "Delegate with owner's delegated right", "holder": None, "rule": rule, "quorum": 1, "grant": grant, "delegation_basis": basis}
    refuse("NO_PERMISSION", S("view_only"))
    raise AssertionError  # pragma: no cover


def can_approve(db: Session, principal: Any, req: ApprovalRequest, pack: DraftPack | None) -> dict:
    """Read-only entitlement preview for the screen (no refusal logged)."""
    if pack is None:
        return {"allowed": False, "reason_code": "NOT_FOUND"}
    if req.status != "open":
        return {"allowed": False, "reason_code": {"superseded": "REQUEST_SUPERSEDED", "expired": "REQUEST_EXPIRED", "decided": "ALREADY_DECIDED", "blocked": req.status_reason or "AUTHORITY_UNCLEAR"}.get(req.status, "REQUEST_CLOSED")}
    try:
        entitlement(db, principal, req, pack, log=False)
    except (Forbidden, SwitchedOff) as e:
        return {"allowed": False, "reason_code": e.reason_code}
    return {"allowed": True, "reason_code": None}


# --- status events -----------------------------------------------------------------------------


def _set_approval(db: Session, a: Approval, status: str, reason: str) -> None:
    if a.status == status:
        return
    db.add(ApprovalStatusEvent(approval_id=a.id, request_id=a.request_id, from_status=a.status, to_status=status, reason_code=reason))
    a.status, a.status_reason, a.status_changed_at = status, reason, utcnow()
    ev = {"superseded": "APPROVAL_SUPERSEDED", "expired": "APPROVAL_EXPIRED", "withdrawn": "APPROVAL_WITHDRAWN", "suspended": "APPROVAL_SUSPENDED", "active": "APPROVAL_ACTIVE"}.get(status, "APPROVAL_STATUS_CHANGED")
    record_event(db, event_type=ev, category="approval", reason_code=reason.upper(), company_id=a.company_id, subject_type="approval", subject_id=a.id, details={"request_id": a.request_id, "to": status})
    if status == "expired":
        record_event(db, event_type="NOTIFICATION_SENT", category="reminder", company_id=a.company_id, subject_type="approval", subject_id=a.id, details={"to": "owner", "kind": "approval_expired"})


def _set_request(db: Session, req: ApprovalRequest, status: str, reason: str | None = None) -> None:
    if req.status == status:
        return
    db.add(ApprovalStatusEvent(request_id=req.id, from_status=req.status, to_status=status, reason_code=reason))
    req.status, req.status_reason = status, reason
    record_event(db, event_type={"superseded": "APPROVAL_REQUEST_SUPERSEDED", "expired": "APPROVAL_REQUEST_EXPIRED", "decided": "APPROVAL_REQUEST_DECIDED", "blocked": "APPROVAL_REQUEST_BLOCKED"}.get(status, "APPROVAL_REQUEST_STATUS"), category="approval", reason_code=(reason or "").upper() or None, company_id=req.company_id, subject_type="approval_request", subject_id=req.id, details={"to": status})


def _grant_status(db: Session, g: DelegateApprovalGrant, status: str, reason: str, actor_uuid: str | None = None) -> None:
    if g.status == status:
        return
    g.status, g.status_reason = status, reason
    db.add(GrantEvent(grant_id=g.id, event=f"grant_{status}", actor_uuid=actor_uuid, details={"reason": reason}))
    record_event(db, event_type=f"GRANT_{status.upper()}", category="approval", reason_code=reason.upper(), company_id=g.company_id, subject_type="delegate_grant", subject_id=g.id)
    if status in ("revoked", "suspended", "expired"):
        _return_to_owner(db, g, reason)


def _return_to_owner(db: Session, g: DelegateApprovalGrant, reason: str) -> None:
    """Recorded-but-unsubmitted delegate approvals become invalid; requests go back to the owner only."""
    for a in db.scalars(select(Approval).where(Approval.company_id == g.company_id, Approval.capacity == "delegate", Approval.status == "active")):
        if (a.delegation_basis or {}).get("grant_id") != g.id:
            continue
        if db.scalar(select(ManualFilingRecord).where(ManualFilingRecord.approval_id == a.id).limit(1)):
            continue
        _set_approval(db, a, "withdrawn" if g.status == "revoked" else "suspended", f"grant_{g.status}")
        req = db.get(ApprovalRequest, a.request_id)
        if req is not None:
            req.awaiting_owner = True
            pack = db.get(DraftPack, req.pack_id)
            if pack is not None and not pack.superseded:
                new = _new_request(db, pack, requested_by=None, role="system", reason="returned_to_owner")
                new.awaiting_owner = True
    record_event(db, event_type="REQUESTS_RETURNED_TO_OWNER", category="approval", reason_code=reason.upper(), company_id=g.company_id, subject_type="delegate_grant", subject_id=g.id)


# --- requests ----------------------------------------------------------------------------------


def _new_request(db: Session, pack: DraftPack, *, requested_by: Any | None, role: str, reason: str | None = None, is_demo: bool = False, route: bool = True) -> ApprovalRequest:
    due, src, start, end = pack_due_date(db, pack)
    rule, n = authority_rule(db, pack.company_id)
    now = utcnow()
    holders = [h for h in ensure_authority(db, pack.company_id) if h.active and _holder_valid(h)]
    entitled = [{"name": h.display_name, "capacity": h.capacity, "kind": "authority_holder"} for h in holders]
    if phase_b_on(db, pack.company_id):
        for g in db.scalars(select(DelegateApprovalGrant).where(DelegateApprovalGrant.company_id == pack.company_id, DelegateApprovalGrant.status == "active")):
            if _grant_covers(g, pack, due, dubai_today()):
                entitled.append({"name": g.delegate_name, "capacity": "delegate", "kind": "grant", "grant_id": g.id})
    req = ApprovalRequest(
        company_id=pack.company_id, pack_id=pack.id, submission_type="return_pack", return_type=pack.tax_type, period_id=pack.period_id, period_start=start, period_end=end,
        due_date=due, due_date_source=src, amounts=pack_amounts(pack), rule_version=pack.rule_version, human_review_status=pack.review_status, draft_content_hash=drafts.pack_hash(pack),
        pack_version=pack.version, authority_rule_type=rule, quorum_n=max(n, 1), entitled_approvers=entitled, status="open",
        requested_by_uuid=getattr(requested_by, "identity_uuid", None), requested_by_name=getattr(requested_by, "display_name", None), requested_by_role=role,
        created_at=now, link_expires_at=now + timedelta(days=_int(db, "approval.request_link_days", 3)), is_demo=is_demo,
    )
    db.add(req)
    db.flush()
    record_event(db, event_type="APPROVAL_REQUEST_CREATED", category="approval", actor_key=getattr(requested_by, "actor_key", None), actor_role=role, company_id=pack.company_id, subject_type="approval_request", subject_id=req.id, details={"pack_id": pack.id, "version": pack.version, "submission_type": "return_pack", "rule_type": rule, "reason": reason})
    for e in entitled:
        record_event(db, event_type="NOTIFICATION_SENT", category="reminder", company_id=pack.company_id, subject_type="approval_request", subject_id=req.id, details={"to": e["kind"], "kind": "approval_requested", "languages": ["ar", "en"]})
    if rule == "unclear":
        _set_request(db, req, "blocked", "AUTHORITY_UNCLEAR")
        req.escalation_case_id = _route_to_reviewer(db, req) if route else None
    return req


def _route_to_reviewer(db: Session, req: ApprovalRequest) -> str | None:
    """Unclear authority -> blocked, flagged and routed to a reviewer for a determination with evidence."""
    try:
        from app.modules.escalation.service import open_case

        case = open_case(db, company_id=req.company_id, module="compliance", reason_code="data_conflict", matter_key=f"approval_authority:{req.company_id}", event_id=req.id, opened_by="system", trigger_source="compliance_item", trigger_rule_id="approval_authority_unclear", title="Approval authority to be determined", linked_item_id=req.id, due_date=req.due_date)
        return case.case_id
    except Exception:  # escalation unavailable: the request stays blocked either way
        record_event(db, event_type="AUTHORITY_REVIEW_ROUTING_PENDING", category="escalation", outcome="failed", company_id=req.company_id, subject_type="approval_request", subject_id=req.id)
        return None


def request_approval(db: Session, principal: Any, company_id: str, pack_id: str, *, submission_type: str = "return_pack") -> ApprovalRequest:
    """Send a pack for approval (delegate or owner). One return, one period, one data version per request."""
    if not flow_enabled(db):
        raise SwitchedOff("The approval flow is switched off for the pilot until a root cause and fix are recorded.", reason_code="APPROVAL_FLOW_SWITCHED_OFF")
    if submission_type not in (get_config(db, "approval.submission_types_enabled", ["return_pack"]) or []):
        _refuse(db, principal, company_id, "SUBMISSION_TYPE_NOT_ENABLED", "Only tax return packs have an approval flow.", exc=ValidationFailed)
    pack = drafts.get_pack(db, pack_id)
    if pack.company_id != company_id:
        raise Forbidden("You do not have access to this company's drafts.", reason_code="NOT_YOUR_COMPANY")
    drafts.check_out_of_date(db, pack)
    if pack.superseded or pack.review_status in UNAPPROVABLE or pack.locked:
        raise Conflict(drafts.STATUS_LABELS.get("superseded", {}).get("en", "superseded") if pack.superseded else "This version cannot be sent for approval.", reason_code="PACK_NOT_APPROVABLE", details={"review_status": pack.review_status})
    if pack.on_hold:
        raise Conflict(S("on_hold_owner_decides"), reason_code="ON_HOLD")
    h = drafts.pack_hash(pack)
    for old in db.scalars(select(ApprovalRequest).where(ApprovalRequest.company_id == company_id, ApprovalRequest.return_type == pack.tax_type, ApprovalRequest.period_id == pack.period_id, ApprovalRequest.status.in_(("open", "blocked")))):
        refresh_request(db, old)
        if old.status in ("open", "blocked") and old.pack_id == pack.id and old.draft_content_hash == h:
            return old  # idempotent: the open request for this exact data version
    role = role_on(principal, company_id)
    return _new_request(db, pack, requested_by=principal, role=role)


def refresh_request(db: Session, req: ApprovalRequest) -> ApprovalRequest:
    """Void on any change (figures, period, attached/source data, rule version) and expire the link after the
    configured days. A changed pack raises a new request for the current version."""
    if req.status not in ("open", "blocked"):
        return req
    pack = db.get(DraftPack, req.pack_id)
    if pack is None:
        return req
    if not pack.locked:
        drafts.check_out_of_date(db, pack)
    changed = pack.superseded or pack.review_status in ("stale", "superseded") or drafts.pack_hash(pack) != req.draft_content_hash
    if changed:
        _set_request(db, req, "superseded", "DATA_CHANGED")
        for a in db.scalars(select(Approval).where(Approval.request_id == req.id, Approval.status.in_(("pending_joint", "active")))):
            _set_approval(db, a, "superseded", "data_changed")
        current = drafts.latest_pack(db, pack.company_id, pack.tax_type, pack.period_id)
        if current is not None and current.id != pack.id and not current.superseded and not current.locked and current.review_status not in UNAPPROVABLE and not current.on_hold:
            new = _new_request(db, current, requested_by=None, role="system", reason="new_version")
            req.superseded_by = new.id
            record_event(db, event_type="NEW_REQUEST_RAISED", category="approval", company_id=req.company_id, subject_type="approval_request", subject_id=new.id, details={"supersedes": req.id})
    elif req.status == "open" and utcnow() > req.link_expires_at:
        _set_request(db, req, "expired", "LINK_EXPIRED")
        for a in db.scalars(select(Approval).where(Approval.request_id == req.id, Approval.status == "pending_joint")):
            _set_approval(db, a, "expired", "joint_window_closed")
        record_event(db, event_type="NOTIFICATION_SENT", category="reminder", company_id=req.company_id, subject_type="approval_request", subject_id=req.id, details={"to": "owner", "kind": "request_expired"})
    db.flush()
    return req


def get_request(db: Session, company_id: str, request_id: str) -> ApprovalRequest:
    req = db.get(ApprovalRequest, request_id)
    if req is None or req.company_id != company_id:
        raise NotFound("approval request not found", reason_code="NOT_FOUND")
    return req


# --- approval validity -------------------------------------------------------------------------


def approval_state(db: Session, a: Approval, *, now: datetime | None = None) -> tuple[bool, str | None]:
    """Valid only if active, unexpired, bound to the current pack hash and rule versions, and the approver (or
    the delegate grant) is still entitled. Applies the void/expire transitions it detects."""
    now = now or utcnow()
    if a.decision != "approve" or a.status in ("pending_joint", "declined"):
        return False, "approval_missing"
    if a.status == "expired":
        return False, "approval_expired"
    if a.status == "superseded":
        return False, "data_changed_since_approval"
    if a.status in ("withdrawn", "suspended"):
        return False, "approver_no_longer_has_rights"
    pack = db.get(DraftPack, a.pack_id)
    if pack is None:
        _set_approval(db, a, "superseded", "pack_missing")
        return False, "data_changed_since_approval"
    if not pack.locked:
        drafts.check_out_of_date(db, pack)
    if pack.superseded or pack.review_status in ("stale", "superseded") or drafts.pack_hash(pack) != a.data_version_hash:
        _set_approval(db, a, "superseded", "data_changed")
        return False, "data_changed_since_approval"
    if rule_version_superseded(db, a.rule_version_ids):
        _set_approval(db, a, "superseded", "rule_version_superseded")
        return False, "data_changed_since_approval"
    if a.valid_until is not None and now > a.valid_until:
        _set_approval(db, a, "expired", "validity_window")
        return False, "approval_expired"
    if a.capacity == "delegate":
        g = db.get(DelegateApprovalGrant, (a.delegation_basis or {}).get("grant_id")) if a.delegation_basis else None
        if g is None or g.status != "active" or not grant_authority_valid(db, g) or not delegate_active(db, a.company_id, a.approver_uuid):
            _set_approval(db, a, "withdrawn" if (g is None or g.status == "revoked") else "suspended", "grant_not_valid")
            return False, "approver_no_longer_has_rights"
    else:
        holder = db.get(AuthorityHolder, a.authority_evidence_ref) if a.authority_evidence_ref else None
        if holder is None or not _holder_valid(holder):
            _set_approval(db, a, "withdrawn", "authority_lost")
            return False, "approver_no_longer_has_rights"
    return True, None


def current_approval(db: Session, req: ApprovalRequest) -> Approval | None:
    return db.scalar(select(Approval).where(Approval.request_id == req.id, Approval.decision == "approve", Approval.status.in_(("active", "expired", "superseded", "withdrawn", "suspended"))).order_by(Approval.decided_at.desc()).limit(1))


# --- recording a decision ------------------------------------------------------------------------


def _uaepass(db: Session, principal: Any, req: ApprovalRequest, confirmation: str | None) -> None:
    """Fresh UAE PASS assertion at the moment of the act (mock: confirmed | failed | cancelled). On failure or
    cancel nothing is saved; three consecutive failures add the support link."""
    max_age = get_config(db, "approval.step_up_max_age_minutes", None)
    if max_age:
        from app.modules.identity.models import UserSession

        sess = db.get(UserSession, getattr(principal, "session_id", None))
        last = (sess.step_up_at or sess.created_at) if sess is not None else None
        if last is not None and (utcnow() - last) > timedelta(minutes=int(max_age)) and confirmation != "confirmed":
            _refuse(db, principal, req.company_id, "STEP_UP_REQUIRED", S("uaepass_failed"), subject_id=req.id, event="STEP_UP_REQUIRED")
    if confirmation in (None, "confirmed"):
        fails = dict(req.uaepass_failures or {})
        if fails.pop(principal.identity_uuid, None) is not None:
            req.uaepass_failures = fails
        return
    if confirmation == "cancelled":
        record_event(db, event_type="UAEPASS_CANCELLED", category="approval", outcome="cancelled", reason_code="UAEPASS_CANCELLED", actor_key=principal.actor_key, company_id=req.company_id, subject_type="approval_request", subject_id=req.id)
        raise Forbidden(S("uaepass_cancelled"), reason_code="UAEPASS_CANCELLED")
    fails = dict(req.uaepass_failures or {})
    fails[principal.identity_uuid] = int(fails.get(principal.identity_uuid, 0)) + 1
    req.uaepass_failures = fails
    threshold = _int(db, "approval.uaepass_failure_help_threshold", 3)
    record_event(db, event_type="UAEPASS_FAILED", category="approval", outcome="failed", reason_code="REAUTH_FAILED", actor_key=principal.actor_key, company_id=req.company_id, subject_type="approval_request", subject_id=req.id, details={"consecutive": fails[principal.identity_uuid]})
    raise Forbidden(S("uaepass_failed"), reason_code="REAUTH_FAILED", details={"consecutive_failures": fails[principal.identity_uuid], "show_support": fails[principal.identity_uuid] >= threshold})


def _guard_open(db: Session, principal: Any, req: ApprovalRequest) -> DraftPack:
    if not flow_enabled(db):
        raise SwitchedOff("The approval flow is switched off for the pilot until a root cause and fix are recorded.", reason_code="APPROVAL_FLOW_SWITCHED_OFF")
    refresh_request(db, req)
    if req.status == "superseded":
        _refuse(db, principal, req.company_id, "REQUEST_SUPERSEDED", S("superseded_while_viewing").replace("[ID]", req.superseded_by or ""), exc=Conflict, subject_id=req.id, details={"new_request_id": req.superseded_by})
    if req.status == "expired":
        _refuse(db, principal, req.company_id, "REQUEST_EXPIRED", S("request_expired"), exc=Conflict, subject_id=req.id)
    if req.status == "decided":
        _refuse(db, principal, req.company_id, "ALREADY_DECIDED", "This request has already been decided.", exc=Conflict, subject_id=req.id, event="ALREADY_DECIDED_REFUSED")
    if req.status == "blocked":
        _refuse(db, principal, req.company_id, req.status_reason or "AUTHORITY_UNCLEAR", S("authority_unclear"), subject_id=req.id)
    pack = db.get(DraftPack, req.pack_id)
    if pack is None:
        raise NotFound("draft not found", reason_code="NOT_FOUND")
    return pack


def _hash_check(db: Session, principal: Any, req: ApprovalRequest, pack: DraftPack, expected_hash: str | None) -> None:
    if not expected_hash or expected_hash != drafts.pack_hash(pack) or expected_hash != req.draft_content_hash:
        record_event(db, event_type="HASH_MISMATCH_REFUSED", category="approval", outcome="refused", reason_code="HASH_MISMATCH", actor_key=principal.actor_key, company_id=req.company_id, subject_type="approval_request", subject_id=req.id, details={"shown": short_hash(expected_hash), "current": short_hash(drafts.pack_hash(pack))})
        raise Conflict(S("hash_mismatch").replace("[ID]", short_hash(expected_hash)), reason_code="HASH_MISMATCH", details={"version_ref": short_hash(expected_hash)})


def _device_family(user_agent: str | None) -> str | None:
    ua = (user_agent or "").lower()
    if not ua:
        return None
    return "tablet" if "ipad" in ua or "tablet" in ua else "mobile" if "mobi" in ua or "android" in ua or "iphone" in ua else "desktop"


def approve(db: Session, principal: Any, company_id: str, request_id: str, *, expected_hash: str | None, reviewed_figures: bool = False, informed_unreviewed: bool = False, uaepass: str | None = "confirmed", user_agent: str | None = None, channel: str = "web/UAE PASS click-to-approve") -> dict:
    req = get_request(db, company_id, request_id)
    pack = _guard_open(db, principal, req)
    ent = entitlement(db, principal, req, pack)
    _hash_check(db, principal, req, pack, expected_hash)
    unreviewed = pack.review_status in NOT_REVIEWED
    if unreviewed and not informed_unreviewed:
        _refuse(db, principal, company_id, "INFORMED_DECISION_REQUIRED", "This draft has not been reviewed by a human. Confirm that you understand this and that you are responsible for the figures before approving.", exc=ValidationFailed, subject_id=req.id)
    if not reviewed_figures:
        raise ValidationFailed("Tick 'I have reviewed the figures' to continue.", reason_code="REVIEW_TICK_REQUIRED")
    if ent["rule"] == "two_together":
        mine = db.scalar(select(Approval).where(Approval.request_id == req.id, Approval.approver_uuid == principal.identity_uuid, Approval.decision == "approve", Approval.status.in_(("pending_joint", "active"))).limit(1))
        if mine is not None:
            _refuse(db, principal, company_id, "ALREADY_APPROVED_BY_YOU", "You have already approved this version. Another authorised person must approve it too.", exc=Conflict, subject_id=req.id)
    _uaepass(db, principal, req, uaepass)
    now = utcnow()
    due = req.due_date
    v = compute_valid_until(db, now, due)
    a = Approval(
        request_id=req.id, company_id=company_id, pack_id=pack.id, decision="approve", approver_uuid=principal.identity_uuid, approver_actor_key=principal.actor_key, approver_name=principal.display_name,
        assurance_level=principal.assurance_level, capacity=ent["capacity"], display_role=ent["display_role"], delegation_basis=ent["delegation_basis"], authority_evidence_ref=ent["holder"].id if ent["holder"] else None,
        action_approved="release_for_manual_filing", data_version_hash=drafts.pack_hash(pack), pack_version=pack.version, rule_version_ids=rule_version_ids(pack), ai_generated_label=pack.ai_label_en,
        human_review_status=pack.review_status, informed_unreviewed_decision=bool(unreviewed and informed_unreviewed), declaration_wording_version_id=DECLARATION_WORDING_VERSION, declaration_wording=DECLARATION_WORDING,
        channel=channel, session_ref=_ref(getattr(principal, "session_id", None)), device_family=_device_family(user_agent), decided_at=now, valid_until=v["valid_until"], validity_days=v["days"], capped_at_due_date=v["capped_at_due_date"],
        status="active",
    )
    joint_pending = False
    if ent["rule"] == "two_together":
        window = timedelta(days=_int(db, "approval.joint_window_days", validity_days(db)))
        others = [x for x in db.scalars(select(Approval).where(Approval.request_id == req.id, Approval.decision == "approve", Approval.status == "pending_joint", Approval.capacity != "delegate")) if x.data_version_hash == a.data_version_hash and now - x.decided_at <= window]
        if len({x.approver_uuid for x in others} | {principal.identity_uuid}) < ent["quorum"]:
            a.status = "pending_joint"
            joint_pending = True
    try:
        record_event(db, event_type="APPROVAL_RECORDED" if not joint_pending else "JOINT_APPROVAL_RECORDED", category="approval", actor_key=principal.actor_key, actor_role=ent["role"], company_id=company_id, subject_type="approval", subject_id=a.id, details={"request_id": req.id, "pack_id": pack.id, "version": pack.version, "hash": short_hash(a.data_version_hash), "capacity": a.capacity, "assurance_level": a.assurance_level, "wording_version": DECLARATION_WORDING_VERSION, "grant_id": (ent["delegation_basis"] or {}).get("grant_id")}, fail_closed=True)
    except AuditWriteError as e:
        raise Conflict(S("save_failed"), reason_code="SAVE_FAILED") from e
    db.add(a)
    db.flush()
    if joint_pending:
        return {"approval": approval_dict(a), "status": "pending_joint", "collected": len({x.approver_uuid for x in db.scalars(select(Approval).where(Approval.request_id == req.id, Approval.status == "pending_joint"))}), "required": ent["quorum"]}
    try:
        drafts.set_approval_status(db, pack.id, "approved_for_submission", actor=principal, expected_hash=a.data_version_hash)
    except Conflict as e:
        raise Conflict(S("hash_mismatch").replace("[ID]", short_hash(expected_hash)), reason_code="HASH_MISMATCH") from e
    for x in db.scalars(select(Approval).where(Approval.request_id == req.id, Approval.status == "pending_joint")):
        if x.id != a.id:
            x.valid_until = v["valid_until"]
            _set_approval(db, x, "active", "quorum_reached")
    _set_request(db, req, "decided", "APPROVED")
    req.decided_at = now
    if ent["grant"] is not None:
        if ent["grant"].scope_option == "single_return":
            ent["grant"].used_by_approval_id = a.id
        db.add(GrantEvent(grant_id=ent["grant"].id, event="delegate_approval_recorded", actor_uuid=principal.identity_uuid, details={"approval_id": a.id, "pack_id": pack.id}))
        record_event(db, event_type="NOTIFICATION_SENT", category="reminder", company_id=company_id, subject_type="approval", subject_id=a.id, details={"to": "owner", "kind": "delegate_approval_recorded", "grant_id": ent["grant"].id})
    db.flush()
    return {"approval": approval_dict(a), "status": "approved", "receipt": receipt(a), "warnings": (["due_date_closer_than_window"] if v["warn_due_closer"] else []) + (["due_date_passed"] if v["due_date_passed"] else [])}


def decline(db: Session, principal: Any, company_id: str, request_id: str, *, decision: str, reason: str | None, expected_hash: str | None, uaepass: str | None = "confirmed") -> dict:
    """Reject or request changes: reason 5-500 characters (trimmed); the draft goes back to preparation."""
    if decision not in ("reject", "request_changes"):
        raise ValidationFailed("unknown decision", reason_code="VALIDATION_FAILED")
    req = get_request(db, company_id, request_id)
    pack = _guard_open(db, principal, req)
    ent = entitlement(db, principal, req, pack)
    text = (reason or "").strip()
    lo, hi = _int(db, "approval.reason_min_chars", 5), _int(db, "approval.reason_max_chars", 500)
    if len(text) < lo or len(text) > hi:
        raise ValidationFailed(S("reason_required"), reason_code="REASON_REQUIRED", details={"min": lo, "max": hi})
    _hash_check(db, principal, req, pack, expected_hash)
    _uaepass(db, principal, req, uaepass)
    now = utcnow()
    a = Approval(request_id=req.id, company_id=company_id, pack_id=pack.id, decision=decision, reason=text, approver_uuid=principal.identity_uuid, approver_actor_key=principal.actor_key, approver_name=principal.display_name, assurance_level=principal.assurance_level, capacity=ent["capacity"], display_role=ent["display_role"], delegation_basis=ent["delegation_basis"], authority_evidence_ref=ent["holder"].id if ent["holder"] else None, data_version_hash=drafts.pack_hash(pack), pack_version=pack.version, rule_version_ids=rule_version_ids(pack), ai_generated_label=pack.ai_label_en, human_review_status=pack.review_status, declaration_wording_version_id=DECLARATION_WORDING_VERSION, session_ref=_ref(getattr(principal, "session_id", None)), decided_at=now, status="declined")
    db.add(a)
    for x in db.scalars(select(Approval).where(Approval.request_id == req.id, Approval.status == "pending_joint")):
        _set_approval(db, x, "withdrawn", "declined_by_other_holder")
    _set_request(db, req, "in_preparation", decision.upper())
    req.decided_at = now
    record_event(db, event_type="REJECTION_RECORDED" if decision == "reject" else "CHANGE_REQUEST_RECORDED", category="approval", actor_key=principal.actor_key, actor_role=ent["role"], company_id=company_id, subject_type="approval", subject_id=a.id, details={"request_id": req.id, "pack_id": pack.id, "reason_chars": len(text)})
    # draft returns to preparation (best effort through the drafts status model; nothing is overwritten)
    for to in ("under_review", "reviewed_with_changes"):
        try:
            drafts.transition(db, pack, to, principal, reason_code="other", reason_text=text)
            break
        except Exception:  # noqa: S112 - status model may not allow this transition from the current state
            continue
    db.flush()
    return {"approval": approval_dict(a), "status": "in_preparation", "message": S("decision_recorded")}


def remind_owner(db: Session, principal: Any, company_id: str, request_id: str) -> dict:
    """Delegate 'Remind the owner': at most 1 per request per 24 hours; logged with the delegate's name."""
    req = get_request(db, company_id, request_id)
    refresh_request(db, req)
    if req.status != "open":
        raise Conflict("This request is not open.", reason_code="REQUEST_CLOSED")
    hours = _int(db, "approval.remind_owner_rate_hours", 24)
    if req.last_reminder_at and utcnow() - req.last_reminder_at < timedelta(hours=hours):
        raise Conflict("The owner was already reminded in the last 24 hours.", reason_code="REMINDER_RATE_LIMITED")
    req.last_reminder_at = utcnow()
    record_event(db, event_type="REMINDER_SENT", category="reminder", actor_key=principal.actor_key, actor_role=role_on(principal, company_id), company_id=company_id, subject_type="approval_request", subject_id=req.id, details={"to": "owner", "kind": "remind_the_owner"})
    db.flush()
    return {"message": S("owner_reminded")}


# --- serialisation -----------------------------------------------------------------------------


def _iso(dt: datetime | date | None) -> str | None:
    return dt.isoformat() if dt else None


def approval_dict(a: Approval) -> dict:
    return {
        "approval_id": a.id, "request_id": a.request_id, "pack_id": a.pack_id, "decision": a.decision, "reason": a.reason, "status": a.status, "status_reason": a.status_reason,
        "approver_name": a.approver_name, "assurance_level": a.assurance_level, "capacity": a.capacity, "display_role": a.display_role, "delegation_basis": a.delegation_basis,
        "authority_evidence_ref": a.authority_evidence_ref, "action_approved": a.action_approved, "data_version_hash": a.data_version_hash, "short_hash": short_hash(a.data_version_hash),
        "pack_version": a.pack_version, "rule_version_ids": a.rule_version_ids, "ai_generated_label": a.ai_generated_label, "human_review_status": a.human_review_status,
        "informed_unreviewed_decision": a.informed_unreviewed_decision, "declaration_wording_version_id": a.declaration_wording_version_id, "channel": a.channel,
        "device_family": a.device_family, "session_ref": a.session_ref, "decided_at": _iso(a.decided_at), "valid_until": _iso(a.valid_until), "validity_days": a.validity_days,
        "capped_at_due_date": a.capped_at_due_date, "is_demo": a.is_demo,
    }


def receipt(a: Approval) -> dict:
    return {"approval_id": a.id, "who": a.approver_name, "role": a.display_role, "when_utc": _iso(a.decided_at), "version": a.pack_version, "data_version": short_hash(a.data_version_hash), "valid_until": _iso(a.valid_until), "validity_line": S("validity_line"), "platform_line": S("platform_line"), "message": S("decision_recorded")}


def request_dict(db: Session, req: ApprovalRequest, *, principal: Any | None = None, detail: bool = False) -> dict:
    pack = db.get(DraftPack, req.pack_id)
    approvals = list(db.scalars(select(Approval).where(Approval.request_id == req.id).order_by(Approval.decided_at)))
    cur = next((a for a in reversed(approvals) if a.decision == "approve" and a.status != "pending_joint"), None)
    fil = filing_status(db, req)
    valid = False
    if cur is not None:
        # once filing evidence is recorded the approval stands as it was at the gate (judged at that time)
        valid = True if fil["state"] != "not_filed" else approval_state(db, cur)[0]
    company = db.get(Company, req.company_id)
    out = {
        "request_id": req.id, "company_id": req.company_id, "company_name": {"en": company.trade_name_en, "ar": company.trade_name_ar} if company else None, "pack_id": req.pack_id,
        "submission_type": req.submission_type, "return_type": req.return_type, "period_id": req.period_id, "period_start": _iso(req.period_start), "period_end": _iso(req.period_end),
        "due_date": _iso(req.due_date), "due_date_source": req.due_date_source, "amounts": req.amounts, "rule_version": req.rule_version, "human_review_status": req.human_review_status,
        "human_review_label": drafts.STATUS_LABELS.get(req.human_review_status or "", None), "not_reviewed_by_human": (pack.review_status if pack else req.human_review_status) in NOT_REVIEWED and not (cur and valid),
        "ai_label": S("ai_draft_label"), "draft_content_hash": req.draft_content_hash, "short_hash": short_hash(req.draft_content_hash), "pack_version": req.pack_version,
        "current_pack_hash": drafts.pack_hash(pack) if pack else None, "authority_rule_type": req.authority_rule_type, "quorum_n": req.quorum_n, "entitled_approvers": req.entitled_approvers,
        "status": req.status, "status_reason": req.status_reason, "awaiting_owner": req.awaiting_owner, "requested_by": {"name": req.requested_by_name, "role": req.requested_by_role},
        "created_at": _iso(req.created_at), "link_expires_at": _iso(req.link_expires_at), "decided_at": _iso(req.decided_at), "superseded_by": req.superseded_by,
        "escalation_case_id": req.escalation_case_id, "is_demo": req.is_demo,
        "entitled_owner": next((e["name"] for e in (req.entitled_approvers or []) if e.get("kind") == "authority_holder"), None),
        "approval_valid": valid, "approved_by": approval_dict(cur) if cur else None,
        "joint_collected": len({a.approver_uuid for a in approvals if a.status == "pending_joint"}),
        "history": [approval_dict(a) for a in approvals],
        "filing": fil,
    }
    if principal is not None:
        out["entitlement"] = can_approve(db, principal, req, pack)
        out["uaepass_failures"] = int((req.uaepass_failures or {}).get(principal.identity_uuid, 0))
    if detail and pack is not None:
        out["pack"] = {"id": pack.id, "version": pack.version, "review_status": pack.review_status, "lines": pack.lines, "basis": pack.basis, "sources_count": len(pack.sources or []), "superseded": pack.superseded, "on_hold": pack.on_hold, "watermark": drafts.WATERMARK, "product_name": drafts.PRODUCT_NAME}
    return out


# --- E6-S2 delegate approval grants -------------------------------------------------------------


def grant_caps(db: Session, company_id: str, owner_holder: AuthorityHolder | None) -> dict:
    licence = db.scalar(select(Licence).where(Licence.company_id == company_id).order_by(Licence.created_at.desc()))
    caps = {"licence_expiry": _iso(licence.expiry_date) if licence and licence.expiry_date else None, "authority_end": _iso(owner_holder.valid_to) if owner_holder and owner_holder.valid_to else None}
    return caps


def grant_defaults(db: Session, company_id: str, owner_holder: AuthorityHolder | None, start: date | None = None) -> dict:
    start = start or dubai_today()
    max_days, default_days = _int(db, "approval.delegate_grant.max_days", 365), _int(db, "approval.delegate_grant.default_days", 90)
    caps = grant_caps(db, company_id, owner_holder)
    ends = [start + timedelta(days=max_days)] + [date.fromisoformat(v) for v in caps.values() if v]
    max_end = min(ends)
    return {"start_date": start.isoformat(), "end_date": min(start + timedelta(days=default_days), max_end).isoformat(), "max_end_date": max_end.isoformat(), "max_days": max_days, "default_days": default_days, "caps": caps, "scope_option": get_config(db, "approval.delegate_grant.default_scope", "single_return"), "reminder_days": _int(db, "approval.delegate_grant.reminder_days", 14)}


def _grant_refuse(db: Session, principal: Any, company_id: str, code: str, exc: type = Forbidden, message: str | None = None, details: dict | None = None) -> None:
    _refuse(db, principal, company_id, code, message or STRINGS.get(code, STRINGS["generic_error"])["en"], exc=exc, event="ENTITLEMENT_REFUSED", details=details)


def create_grant(db: Session, principal: Any, company_id: str, *, delegate_uuid: str, tax_types: list[str], scope_option: str = "single_return", period_id: str | None = None, start_date: date | None = None, end_date: date | None = None, max_amount_fils: int | None = None, submission_type: str = "return_pack", uaepass: str | None = "confirmed") -> DelegateApprovalGrant:
    role = role_on(principal, company_id)
    if role == "none" and owner_blocked(db, principal, company_id):
        _grant_refuse(db, principal, company_id, "NO_OWNER_ROLE")
    if role == "delegate":
        _grant_refuse(db, principal, company_id, "NOT_OWNER_DELEGATE")
    if role not in OWNER_LEVEL:
        _grant_refuse(db, principal, company_id, "NOT_OWNER_DELEGATE")
    from app.modules.delegates.service import authority_state

    if authority_state(db, company_id)["stale"]:
        _grant_refuse(db, principal, company_id, "STALE_DATA")
    require_step_up(db, principal, "grants.create")
    if uaepass not in (None, "confirmed"):
        _grant_refuse(db, principal, company_id, "REAUTH_FAILED", message=S("REAUTH_FAILED"))
    if not phase_b_on(db, company_id):
        _grant_refuse(db, principal, company_id, "RIGHT_SWITCHED_OFF", SwitchedOff, S("phase_b_off"))
    rule, _ = authority_rule(db, company_id)
    if rule == "unclear":
        _grant_refuse(db, principal, company_id, "AUTHORITY_UNCLEAR", message=S("authority_unclear"))
    if rule == "two_together":
        _grant_refuse(db, principal, company_id, "GRANT_NEEDS_JOINT_AUTHORITY", message="This company needs two authorised people for the act, so a grant needs both of them (to be confirmed).")
    holder = holder_for(db, company_id, principal)
    if holder is None or not _holder_valid(holder):
        _grant_refuse(db, principal, company_id, "NOT_AUTHORITY_HOLDER", message=S("view_only"))
    if not delegate_active(db, company_id, delegate_uuid):
        raise ValidationFailed("This person is not an active delegate for this company.", reason_code="NOT_A_DELEGATE")
    if submission_type != "return_pack" or not tax_types or any(t not in ("vat", "ct") for t in tax_types):
        raise ValidationFailed("Only VAT and corporate tax return packs can be covered by an approval right.", reason_code="SCOPE_NOT_ALLOWED")
    if scope_option not in ("single_return", "time_period"):
        raise ValidationFailed("unknown scope option", reason_code="VALIDATION_FAILED")
    if scope_option == "single_return" and not period_id:
        raise ValidationFailed("Choose the tax period for a single-return right.", reason_code="PERIOD_REQUIRED")
    today = dubai_today()
    d = grant_defaults(db, company_id, holder, start_date or today)
    start = start_date or today
    end = end_date or date.fromisoformat(d["end_date"])
    if start < today:
        raise ValidationFailed("The start date cannot be in the past.", reason_code="START_IN_PAST")
    if end <= start:
        raise ValidationFailed(S("dates_invalid"), reason_code="DATES_INVALID")
    if (end - start).days > d["max_days"]:
        raise ValidationFailed(S("grant_too_long").replace("[n]", str(d["max_days"])), reason_code="GRANT_TOO_LONG", details={"max_days": d["max_days"]})
    if end > date.fromisoformat(d["max_end_date"]):
        raise ValidationFailed("The end date is after the licence expiry or the end of the owner's authority.", reason_code="GRANT_END_AFTER_CAP", details={"max_end_date": d["max_end_date"], "caps": d["caps"]})
    delegate_name = None
    from app.modules.identity.models import Identity

    ident = db.get(Identity, delegate_uuid)
    delegate_name = ident.display_name if ident else None
    g = DelegateApprovalGrant(
        company_id=company_id, delegate_uuid=delegate_uuid, delegate_name=delegate_name, granting_owner_uuid=principal.identity_uuid, granting_owner_name=principal.display_name,
        granting_authority_ref=holder.id, authority_basis=f"{holder.capacity} per {holder.source_document}", scope_option=scope_option,
        scope_items=[{"submission_type": "return_pack", "tax_type": t, "period_id": period_id if scope_option == "single_return" else None} for t in tax_types],
        max_amount_fils=max_amount_fils, start_date=start, end_date=end, confirmation_wording_version=GRANT_WORDING_VERSION,
        step_up_proof={"assurance_level": principal.assurance_level, "session_ref": _ref(getattr(principal, "session_id", None)), "at": utcnow().isoformat(), "method": "UAE PASS re-confirm"},
    )
    db.add(g)
    db.flush()
    db.add(GrantEvent(grant_id=g.id, event="grant_created", actor_uuid=principal.identity_uuid, details={"scope_option": scope_option, "tax_types": tax_types}))
    record_event(db, event_type="GRANT_CREATED", category="approval", actor_key=principal.actor_key, actor_role=role, company_id=company_id, subject_type="delegate_grant", subject_id=g.id, details={"scope_option": scope_option, "tax_types": tax_types, "wording_version": GRANT_WORDING_VERSION})
    db.flush()
    return g


def revoke_grant(db: Session, principal: Any, company_id: str, grant_id: str) -> DelegateApprovalGrant:
    role = role_on(principal, company_id)
    if role == "delegate":
        _grant_refuse(db, principal, company_id, "NOT_OWNER_DELEGATE")
    if role not in OWNER_LEVEL:
        _grant_refuse(db, principal, company_id, "NO_OWNER_ROLE" if owner_blocked(db, principal, company_id) else "NOT_OWNER_DELEGATE")
    g = db.get(DelegateApprovalGrant, grant_id)
    if g is None or g.company_id != company_id:
        raise NotFound("grant not found", reason_code="NOT_FOUND")
    if g.status in ("revoked",):
        return g
    g.revoked_at, g.revoked_by_uuid = utcnow(), principal.identity_uuid
    _grant_status(db, g, "revoked", "owner_revoked", principal.identity_uuid)
    db.flush()
    return g


def grant_dict(g: DelegateApprovalGrant) -> dict:
    return {"grant_id": g.id, "company_id": g.company_id, "delegate_uuid": g.delegate_uuid, "delegate_name": g.delegate_name, "granting_owner_name": g.granting_owner_name, "authority_basis": g.authority_basis, "right": g.right, "scope_option": g.scope_option, "scope_items": g.scope_items, "max_amount_fils": g.max_amount_fils, "start_date": _iso(g.start_date), "end_date": _iso(g.end_date), "status": g.status, "status_reason": g.status_reason, "confirmation_wording_version": g.confirmation_wording_version, "step_up_proof": {k: v for k, v in (g.step_up_proof or {}).items() if k != "session_ref"}, "created_at": _iso(g.created_at), "revoked_at": _iso(g.revoked_at), "used_by_approval_id": g.used_by_approval_id, "is_demo": g.is_demo}


def sweep(db: Session, *, now: datetime | None = None) -> dict:
    """Scheduled sweep: request expiry/supersession, approval expiry/void, grant expiry, 14-day grant reminders,
    grant suspension on authority loss, grants of removed delegates. Reminders only; never approves anything."""
    now = now or utcnow()
    today = dubai_today()
    out = {"requests": 0, "approvals_void": 0, "grants_expired": 0, "grant_reminders": 0, "grants_suspended": 0}
    for req in list(db.scalars(select(ApprovalRequest).where(ApprovalRequest.status.in_(("open", "blocked"))))):
        before = req.status
        refresh_request(db, req)
        out["requests"] += int(req.status != before)
    for a in list(db.scalars(select(Approval).where(Approval.status == "active"))):
        if db.scalar(select(ManualFilingRecord).where(ManualFilingRecord.approval_id == a.id).limit(1)):
            continue  # already used for a filing record; the record stands as evidence
        ok, _ = approval_state(db, a, now=now)
        out["approvals_void"] += int(not ok)
    remind = _int(db, "approval.delegate_grant.reminder_days", 14)
    for g in list(db.scalars(select(DelegateApprovalGrant).where(DelegateApprovalGrant.status == "active"))):
        if g.end_date < today:
            _grant_status(db, g, "expired", "end_date_reached")
            out["grants_expired"] += 1
        elif not delegate_active(db, g.company_id, g.delegate_uuid):
            g.revoked_at = now
            _grant_status(db, g, "revoked", "delegate_removed")
        elif not grant_authority_valid(db, g):
            _grant_status(db, g, "suspended", "granting_authority_lost")
            out["grants_suspended"] += 1
        elif g.reminder_sent_at is None and (g.end_date - today).days <= remind:
            g.reminder_sent_at = now
            db.add(GrantEvent(grant_id=g.id, event="grant_reminder_14_days"))
            record_event(db, event_type="GRANT_REMINDER_SENT", category="reminder", company_id=g.company_id, subject_type="delegate_grant", subject_id=g.id, details={"channel": "in_portal", "days_before_end": remind})
            out["grant_reminders"] += 1
    record_event(db, event_type="APPROVAL_SWEEP_RUN", category="system", details=out)
    db.flush()
    return out


# --- E6-S3 pre-submission gate and manual filing path -------------------------------------------


def gate(db: Session, *, company_id: str, pack: DraftPack, approval_id: str | None, path: str, caller_type: str = "user", caller_key: str | None = None, switch_state: str | None = None, switch_block: str | None = None) -> Approval:
    """The single server-side check for every send or release path. Blocks (with a named cause) unless a valid,
    unexpired approval binds exactly this pack version. Every outcome is logged and counted (K23)."""
    a = db.get(Approval, approval_id) if approval_id else None
    cause = None
    if a is None or a.decision != "approve" or a.company_id != company_id:
        cause = "approval_missing"
    elif a.pack_id != pack.id:
        cause = "data_changed_since_approval"
    else:
        ok, cause = approval_state(db, a)
        if ok and pack.on_hold:
            cause = "approver_no_longer_has_rights"
    code = cause or switch_block
    db.add(GateDecision(company_id=company_id, pack_id=pack.id, data_version_hash=drafts.pack_hash(pack), approval_id=approval_id, path=path, caller_type=caller_type, caller_key=caller_key, switch_state=switch_state, outcome="block" if code else "pass", reason_code=code, tax_type=pack.tax_type))
    record_event(db, event_type="GATE_BLOCKED" if code else "GATE_PASSED", category="approval", outcome="refused" if code else "success", reason_code=(code or "").upper() or None, actor_key=caller_key, company_id=company_id, subject_type="draft_pack", subject_id=pack.id, details={"path": path, "caller_type": caller_type, "approval_id": approval_id, "switch": switch_state})
    db.flush()
    if cause:
        lab = BLOCKED_CAUSE_LABELS[cause]
        raise Conflict(f"Not sent: {lab['en']}.", reason_code="GATE_BLOCKED", details={"cause": cause, "next_step": lab["next_en"], "label": {"en": lab["en"], "ar": lab["ar"]}})
    if switch_block:
        raise SwitchedOff(S("submission_not_available"), reason_code=switch_block)
    assert a is not None
    return a


def _filing_entitlement(db: Session, principal: Any, req: ApprovalRequest, pack: DraftPack) -> dict | None:
    role = role_on(principal, req.company_id)
    if role in OWNER_LEVEL:
        if role == "owner":
            authorize(db, principal, "filing.record", company_id=req.company_id)
        return None
    if role == "delegate" and phase_b_on(db, req.company_id):
        due, _, _, _ = pack_due_date(db, pack)
        for g in db.scalars(select(DelegateApprovalGrant).where(DelegateApprovalGrant.company_id == req.company_id, DelegateApprovalGrant.delegate_uuid == principal.identity_uuid, DelegateApprovalGrant.status == "active")):
            if g.start_date <= dubai_today() <= g.end_date and any(i.get("tax_type") == pack.tax_type for i in g.scope_items or []) and grant_authority_valid(db, g):
                return {"delegate_name": principal.display_name, "granting_owner_name": g.granting_owner_name, "grant_date": _iso(g.created_at.date()), "grant_id": g.id}
    owner = next((h.display_name for h in ensure_authority(db, req.company_id) if h.active), "the owner")
    _refuse(db, principal, req.company_id, "NO_FILING_RIGHT", f"Only the owner or a delegate with approval rights can approve or record filing. Ask {owner} to do this.", subject_id=req.id)
    return None


def release_for_filing(db: Session, principal: Any, company_id: str, request_id: str, *, lang: str = "en") -> dict:
    """Download the prepared return for manual filing: released only through the gate, recorded with the
    approval ID. The pack stays marked 'Draft, not filed, not tax advice'."""
    req = get_request(db, company_id, request_id)
    pack = drafts.get_pack(db, req.pack_id)
    _filing_entitlement(db, principal, req, pack)
    a = current_approval(db, req)
    gate(db, company_id=company_id, pack=pack, approval_id=a.id if a else None, path="manual_release", caller_key=principal.actor_key)
    doc = drafts.export_pack(db, pack, principal, lang=lang)
    record_event(db, event_type="MANUAL_RELEASE_RECORDED", category="approval", actor_key=principal.actor_key, company_id=company_id, subject_type="approval", subject_id=a.id if a else None, details={"pack_id": pack.id})
    return doc | {"release": {"approval_id": a.id if a else None, "label": "Draft, not filed, not tax advice"}}


def _differences(pack: DraftPack, figures: dict | None) -> list[dict]:
    diffs = []
    for ln in pack.lines or []:
        if figures and ln["key"] in figures and figures[ln["key"]] is not None and int(figures[ln["key"]]) != (ln.get("value_fils") or 0):
            diffs.append({"key": ln["key"], "term": ln.get("term"), "prepared_fils": ln.get("value_fils"), "declared_fils": int(figures[ln["key"]])})
    return diffs


def _validate_filing(db: Session, *, outcome: str, filed_date: date | None, authority_reference: str | None, self_filed_confirmed: bool, receipt: dict | None, approval: Approval | None) -> dict:
    errors: dict[str, str] = {}
    if outcome == "filed":
        if filed_date is None:
            errors["filed_date"] = S("filed_date_rule")
        elif filed_date > dubai_today():
            errors["filed_date"] = S("filed_date_rule")
        elif approval is not None and filed_date < (approval.decided_at + GST_OFFSET).date():
            errors["filed_date"] = "The filing date cannot be before the approval date."
        if not self_filed_confirmed:
            errors["self_filed_confirmed"] = "Tick 'I filed this return myself on EmaraTax' to continue."
    if authority_reference and not REF_RE.match(authority_reference.strip()):
        errors["authority_reference"] = S("reference_rule")
    if receipt:
        max_mb = _int(db, "filing.receipt_upload_max_mb", 10)
        if int(receipt.get("size_bytes", 0)) > max_mb * 1024 * 1024 or receipt.get("content_type") not in RECEIPT_TYPES:
            errors["receipt"] = f"Attach a PDF, PNG or JPG file of up to {max_mb} MB."
    if errors:
        raise ValidationFailed("Check the highlighted fields.", reason_code="FORM_INVALID", details={"fields": errors})
    return {}


def record_filing(db: Session, principal: Any, company_id: str, request_id: str, *, outcome: str = "filed", filed_date: date | None = None, authority_reference: str | None = None, figures_as_filed: dict | None = None, self_filed_confirmed: bool = False, receipt: dict | None = None) -> ManualFilingRecord:
    """Owner-entered filing evidence. 'Filed' here always means owner-confirmed with the FTA reference, labelled
    'not verified by the tax authority'. Recording is not approving; the gate must pass first."""
    if outcome not in ("filed", "authority_unavailable"):
        raise ValidationFailed("unknown outcome", reason_code="VALIDATION_FAILED")
    req = get_request(db, company_id, request_id)
    pack = drafts.get_pack(db, req.pack_id)
    under_grant = _filing_entitlement(db, principal, req, pack)
    a = current_approval(db, req)
    _validate_filing(db, outcome=outcome, filed_date=filed_date, authority_reference=authority_reference, self_filed_confirmed=self_filed_confirmed, receipt=receipt, approval=a)
    gate(db, company_id=company_id, pack=pack, approval_id=a.id if a else None, path="manual_filing_record", caller_key=principal.actor_key)
    assert a is not None
    diffs = _differences(pack, figures_as_filed)
    state = "authority_unavailable" if outcome == "authority_unavailable" else ("filed_outside_values_differ" if diffs else "filed_outside_self_declared")
    rec = ManualFilingRecord(company_id=company_id, pack_id=pack.id, request_id=req.id, approval_id=a.id, data_version_hash=a.data_version_hash, tax_type=pack.tax_type, state=state, filed_date=filed_date, authority_reference=(authority_reference or "").strip() or None, figures_as_filed=figures_as_filed or None, differences=diffs or None, receipt_meta=({"name": receipt.get("name"), "size_bytes": receipt.get("size_bytes"), "content_type": receipt.get("content_type"), "label": S("attached_not_verified"), "demo_only": True} if receipt else None), self_filed_confirmed=bool(self_filed_confirmed), recorded_by_uuid=principal.identity_uuid, recorded_by_name=principal.display_name, recorded_by_role=role_on(principal, company_id), acting_under_grant=under_grant)
    db.add(rec)
    db.flush()
    if outcome == "filed":
        try:
            drafts.set_approval_status(db, pack.id, "filed_user_confirmed", actor=principal, expected_hash=a.data_version_hash, filing_reference=rec.authority_reference)
        except Conflict as e:
            raise Conflict(S("record_save_failed"), reason_code="SAVE_FAILED") from e
    record_event(db, event_type="MANUAL_FILING_RECORDED", category="approval", actor_key=principal.actor_key, actor_role=rec.recorded_by_role, company_id=company_id, subject_type="manual_filing", subject_id=rec.id, details={"approval_id": a.id, "state": state, "self_reported": True, "grant_id": (under_grant or {}).get("grant_id")})
    if diffs:
        record_event(db, event_type="VALUES_DIFFER_FLAGGED", category="approval", company_id=company_id, subject_type="manual_filing", subject_id=rec.id, details={"fields": [d["key"] for d in diffs]})
    db.flush()
    return rec


def edit_filing(db: Session, principal: Any, company_id: str, record_id: str, *, filed_date: date | None = None, authority_reference: str | None = None, figures_as_filed: dict | None = None) -> ManualFilingRecord:
    rec = db.get(ManualFilingRecord, record_id)
    if rec is None or rec.company_id != company_id:
        raise NotFound("record not found", reason_code="NOT_FOUND")
    req = get_request(db, company_id, rec.request_id) if rec.request_id else None
    pack = drafts.get_pack(db, rec.pack_id)
    if req is not None:
        _filing_entitlement(db, principal, req, pack)
    a = db.get(Approval, rec.approval_id) if rec.approval_id else None
    _validate_filing(db, outcome="filed" if rec.state != "authority_unavailable" else "authority_unavailable", filed_date=filed_date or rec.filed_date, authority_reference=authority_reference, self_filed_confirmed=True, receipt=None, approval=a)
    before = {"filed_date": _iso(rec.filed_date), "authority_reference": rec.authority_reference, "figures_as_filed": rec.figures_as_filed}
    if filed_date is not None:
        rec.filed_date = filed_date
    if authority_reference is not None:
        rec.authority_reference = authority_reference.strip() or None
    if figures_as_filed is not None:
        rec.figures_as_filed = figures_as_filed
        rec.differences = _differences(pack, figures_as_filed) or None
        if rec.state != "authority_unavailable":
            rec.state = "filed_outside_values_differ" if rec.differences else "filed_outside_self_declared"
    rec.edited_at, rec.edited_by_name = utcnow(), principal.display_name
    db.add(ManualFilingEdit(record_id=rec.id, before=before, after={"filed_date": _iso(rec.filed_date), "authority_reference": rec.authority_reference, "figures_as_filed": rec.figures_as_filed}, edited_by_uuid=principal.identity_uuid, edited_by_name=principal.display_name))
    record_event(db, event_type="MANUAL_FILING_EDITED", category="approval", actor_key=principal.actor_key, company_id=company_id, subject_type="manual_filing", subject_id=rec.id)
    db.flush()
    return rec


def filing_dict(rec: ManualFilingRecord, lang: str = "en") -> dict:
    when = rec.filed_date.isoformat() if rec.filed_date else ""
    if rec.state == "filed_outside_self_declared":
        banner = S("filed_self_declared", lang).replace("[name]", rec.recorded_by_name or "").replace("[الاسم]", rec.recorded_by_name or "").replace("[date, time]", when).replace("[التاريخ والوقت]", when)
    elif rec.state == "filed_outside_values_differ":
        banner = S("filed_values_differ", lang) + " " + S("values_differ_body", lang)
    else:
        banner = S("authority_unavailable", lang)
    return {"record_id": rec.id, "state": rec.state, "label": FILING_STATE_LABELS[rec.state], "banner": banner, "filed_date": _iso(rec.filed_date), "authority_reference": rec.authority_reference, "figures_as_filed": rec.figures_as_filed, "differences": rec.differences, "receipt": rec.receipt_meta, "recorded_by": rec.recorded_by_name, "recorded_by_role": rec.recorded_by_role, "acting_under_grant": rec.acting_under_grant, "recorded_at": _iso(rec.recorded_at), "edited": {"at": _iso(rec.edited_at), "by": rec.edited_by_name} if rec.edited_at else None, "verification": "self_reported", "not_verified_by_authority": True, "read_back": S("not_available"), "approval_id": rec.approval_id, "is_demo": rec.is_demo}


def filing_status(db: Session, req: ApprovalRequest, lang: str = "en") -> dict:
    rec = db.scalar(select(ManualFilingRecord).where(ManualFilingRecord.pack_id == req.pack_id).order_by(ManualFilingRecord.recorded_at.desc()).limit(1))
    if rec is not None:
        return filing_dict(rec, lang) | {"submitted_by": rec.recorded_by_name}
    return {"state": "not_filed", "label": FILING_STATE_LABELS["not_filed"], "banner": S("not_filed", lang), "note": S("submission_not_available", lang), "submit_control_rendered": False, "read_back": S("not_available"), "submitted_by": None}


def demo_fixtures(lang: str = "en") -> list[dict]:
    """Later-phase states (need a read-back channel): shown only as fixtures tagged 'Demo data'. The
    Unconfirmed wording follows Q120 (the 'Do not file manually yet' line is dropped)."""
    ar = lang == "ar"
    return [
        {"state": "sending", "tag": S("demo_data", lang), "label": "قيد الإرسال" if ar else "Sending", "banner": "قيد الإرسال. نتحقق من سجل الهيئة. يمكنك مغادرة الصفحة بأمان." if ar else "Sending. Checking the authority's record. You can safely leave this page.", "actions": []},
        {"state": "sent", "tag": S("demo_data", lang), "label": "أُرسل" if ar else "Sent", "banner": "أُرسل. نتحقق من سجل الهيئة." if ar else "Sent. Checking the authority's record.", "actions": ["view_attempts"]},
        {"state": "unconfirmed", "tag": S("demo_data", lang), "label": "غير مؤكد" if ar else "Unconfirmed", "banner": "تعذّر علينا تأكيد هذا الإقرار لدى الهيئة الاتحادية للضرائب. يُرجى التحقق من حالته في حسابكم على EmaraTax." if ar else "We could not confirm this return with the tax authority. Check its status in your EmaraTax account.", "caution": "Check EmaraTax before taking further steps.", "actions": ["open_emaratax", "record_what_you_see", "contact_support"]},
        {"state": "authority_confirmed", "tag": S("demo_data", lang), "label": "مؤكد من الهيئة الضريبية (بيانات تجريبية)" if ar else "Confirmed by the tax authority (Demo data)", "banner": "Demo data only. Never shown in Phase 1.", "authority_reference": "DEMO-REF-0001", "actions": ["copy_reference"]},
    ]
