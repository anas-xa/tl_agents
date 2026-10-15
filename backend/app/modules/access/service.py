"""Authorisation and Consent Enforcement Service (E1-S2).

One fail-closed decision point: ``authorize(principal, permission, company_id=...)``.
Permissions are role-based and company-scoped; delegate rights that are switched off in the pilot are
refused even when granted; specialists and auditors additionally need an active assignment and a
case-specific access grant (checked by the owning modules through ``require_grant``).
Role combinations that would create self-approval or break a firewall are refused at assignment.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import Forbidden, SwitchedOff
from app.modules.audit.service import record_event
from app.modules.companies.models import Company, CompanyRole
from app.modules.config.service import get_config

# --- permission matrix -------------------------------------------------------------------------
# Company-scoped roles
OWNER_PERMS = {
    "dashboard.view", "deadlines.view", "documents.view", "documents.download", "consent.view", "consent.grant",
    "consent.withdraw", "tax.view", "tax.prepare", "tax.correct", "returns.view", "returns.approve", "audit.view",
    "audit.request_review", "escalation.open", "escalation.view", "delegates.manage", "settings.manage",
    "subscription.view", "subscription.change", "reminders.manage", "uploads.manage", "links.manage",
    "complaints.open", "taxprofile.edit", "filing.record", "grants.create",
    "bookkeeping.quarantine.decide", "docguard.review",  # E5: owner-only quarantine decisions (drafts, documents)
    "returns.send_for_approval",  # E6-S1: the owner may also raise an approval request
}
REMOTE_OWNER_PERMS = {"dashboard.view", "deadlines.view", "documents.view", "documents.download", "reminders.manage", "settings.manage", "subscription.view", "consent.view", "escalation.view", "escalation.open", "audit.view", "tax.view", "returns.view", "complaints.open", "taxprofile.edit"}
DELEGATE_BASE_PERMS = {"dashboard.view", "deadlines.view", "documents.view", "documents.download", "consent.view", "tax.view", "tax.prepare", "tax.correct", "returns.view", "returns.send_for_approval", "audit.view", "escalation.open", "escalation.view", "uploads.manage", "links.manage", "portfolio.view", "settings.view_own", "taxprofile.edit", "subscription.view", "complaints.open"}
DELEGATE_RIGHT_PERMS = {"grant_consent": {"consent.grant", "consent.withdraw"}, "approve_submissions": {"returns.approve"}, "change_subscription": {"subscription.change"}}
AUDITOR_PERMS = {"engagements.view", "audit.review", "audit.record_review", "audit.sign", "audit.view", "documents.view"}
SPECIALIST_PERMS = {"cases.view_assigned", "cases.work", "documents.view"}
REVIEWER_PERMS = {"audit_trail.view", "agent_records.view", "audit_trail.export", "escalation_dashboard.view", "config.view", "delegates.history.view", "approval_compliance.view"}
# Staff roles
STAFF_PERMS: dict[str, set[str]] = {
    "det_admin": {"det.aggregates.view", "det.per_licence.view", "det.cohort.view", "escalation_dashboard.view", "audit_trail.view_summary", "config.view", "det.cohort.manage", "det.cases.decide", "det.billing.reconcile"},
    "det_pilot_manager": {"det.aggregates.view", "det.cohort.manage", "det.cohort.view", "det.per_licence.view", "config.view", "config.change_pilot", "cases.queue_fallback", "det.phase_switches", "det.cohort.approve", "det.cases.decide", "det.billing.reconcile", "cases.queue.view", "approval_compliance.view", "approval_compliance.resolve"},
    "det_complaint_handler": {"complaints.handle", "complaints.view"},
    "det_compliance_lead": {"approval_compliance.view", "det.aggregates.view", "cases.queue.view", "cases.work", "cases.view_assigned"},
    "compliance_reviewer": REVIEWER_PERMS,
    "licensed_auditor": {"engagements.view", "cases.queue.audit", "cases.queue.view", "cases.work", "cases.view_assigned"},
    "tax_specialist": {"cases.queue.tax", "cases.queue.view", "cases.work", "cases.view_assigned"},
    "legal_specialist": {"cases.queue.legal", "cases.queue.view", "cases.work", "cases.view_assigned"},
    "escalation_ops": {"cases.assign", "cases.view_metadata", "cases.queue_alerts", "cases.queue.view"},
    "platform_security_admin": {"staff_roles.manage", "config.change", "config.view", "residency.manage", "integrations.manage", "audit_trail.view", "probes.view"},
    "qeonix_product_owner": {"config.view", "config.change", "phase_map.record_demo", "approval_compliance.view", "integrations.manage", "residency.manage", "probes.view", "catalogue.manage", "approval_compliance.resolve"},
    "qeonix_audit_ops": {"audit.prepare", "engagements.view"},
}
COMPANY_ROLE_PERMS: dict[str, set[str]] = {
    "owner": OWNER_PERMS,
    "remote_owner": REMOTE_OWNER_PERMS,
    "delegate": DELEGATE_BASE_PERMS,
    "licensed_auditor": AUDITOR_PERMS,
    "specialist": SPECIALIST_PERMS,
    "compliance_reviewer": REVIEWER_PERMS,
}
# Permissions that need the highest identity assurance (approval acts), per decision in the brief.
STEP_UP_PERMS = {"consent.grant", "consent.withdraw", "returns.approve", "subscription.change", "grants.create", "delegates.manage"}

# Role combination rules (per company / engagement). A pair in this set is refused.
REFUSED_PAIRS = {
    frozenset({"owner", "specialist"}), frozenset({"delegate", "specialist"}), frozenset({"owner", "delegate"}),
    frozenset({"licensed_auditor", "specialist"}), frozenset({"licensed_auditor", "owner"}), frozenset({"licensed_auditor", "delegate"}),
    frozenset({"licensed_auditor", "remote_owner"}), frozenset({"remote_owner", "specialist"}), frozenset({"remote_owner", "delegate"}),
    frozenset({"compliance_reviewer", "licensed_auditor"}), frozenset({"compliance_reviewer", "specialist"}),
}
PERMITTED_PAIRS = {frozenset({"owner", "compliance_reviewer"}), frozenset({"delegate", "compliance_reviewer"})}


@dataclass
class Principal:
    identity_uuid: str
    actor_key: str
    display_name: str
    assurance_level: str
    profile_type: int
    language: str
    session_id: str
    company_roles: list[CompanyRole] = field(default_factory=list)
    staff_roles: list[str] = field(default_factory=list)
    det_match_result: str = "unmatched"

    def roles_for(self, company_id: str) -> list[CompanyRole]:
        return [r for r in self.company_roles if r.company_id == company_id]

    def company_ids(self) -> list[str]:
        return sorted({r.company_id for r in self.company_roles})

    def has_staff(self, *roles: str) -> bool:
        return any(r in self.staff_roles for r in roles)

    def primary_role(self) -> str:
        if self.staff_roles:
            return self.staff_roles[0]
        if self.company_roles:
            return self.company_roles[0].role
        return "none"


def permissions_for(db: Session, principal: Principal, company_id: str | None) -> set[str]:
    perms: set[str] = set()
    for role in principal.staff_roles:
        perms |= STAFF_PERMS.get(role, set())
    if company_id:
        for r in principal.roles_for(company_id):
            perms |= COMPANY_ROLE_PERMS.get(r.role, set())
            if r.role == "delegate":
                for right in r.rights or []:
                    if right in DELEGATE_RIGHT_PERMS and delegate_right_enabled(db, right):
                        perms |= DELEGATE_RIGHT_PERMS[right]
    return perms


def delegate_right_enabled(db: Session, right: str) -> bool:
    """Phase B delegate rights are built but switched off until the evidence rule is confirmed."""
    return bool(get_config(db, f"delegate_rights.{right}.enabled", False))


def authorize(db: Session, principal: Principal, permission: str, *, company_id: str | None = None, log: bool = True) -> None:
    perms = permissions_for(db, principal, company_id)
    if permission in perms:
        return
    # Explain a switched-off delegate right separately so the UI can show the disabled control with a reason.
    if company_id:
        for r in principal.roles_for(company_id):
            if r.role == "delegate":
                for right, rp in DELEGATE_RIGHT_PERMS.items():
                    if permission in rp and right in (r.rights or []) and not delegate_right_enabled(db, right):
                        if log:
                            record_event(db, event_type="ACCESS_REFUSED", category="access", outcome="refused", reason_code="RIGHT_SWITCHED_OFF", actor_key=principal.actor_key, actor_role=r.role, company_id=company_id, details={"permission": permission, "right": right})
                        raise SwitchedOff(f"delegate right '{right}' is switched off in the pilot", reason_code="RIGHT_SWITCHED_OFF", details={"right": right})
    if log:
        record_event(db, event_type="ACCESS_REFUSED", category="access", outcome="refused", reason_code="NO_PERMISSION", actor_key=principal.actor_key, actor_role=principal.primary_role(), company_id=company_id, details={"permission": permission})
    raise Forbidden("you do not have access to this action", reason_code="NO_PERMISSION", details={"permission": permission, "company_id": company_id})


def require_company_access(db: Session, principal: Principal, company_id: str) -> Company:
    """Company-level data isolation: the principal must hold a role on the company (staff roles never imply it)."""
    company = db.get(Company, company_id)
    if company is None or not principal.roles_for(company_id):
        record_event(db, event_type="ACCESS_REFUSED", category="access", outcome="refused", reason_code="NOT_YOUR_COMPANY", actor_key=principal.actor_key, company_id=company_id)
        raise Forbidden("company not available to you", reason_code="NOT_YOUR_COMPANY")
    return company


def require_step_up(db: Session, principal: Principal, permission: str) -> None:
    """Approval acts need the configured highest assurance level for the user's profile type."""
    if permission not in STEP_UP_PERMS:
        return
    required = get_config(db, "identity.approval_min_assurance_level", "SOP3")
    order = {"SOP1": 1, "SOP2": 2, "SOP3": 3}
    if order.get(principal.assurance_level, 0) < order.get(str(required), 3):
        record_event(db, event_type="ACCESS_REFUSED", category="access", outcome="refused", reason_code="LEVEL_TOO_LOW_FOR_ACTION", actor_key=principal.actor_key, details={"permission": permission, "required": required})
        raise Forbidden("your UAE PASS level is below the level needed for this action", reason_code="LEVEL_TOO_LOW_FOR_ACTION", details={"required_level": required})


def check_role_combination(db: Session, identity_uuid: str | None, company_id: str, new_role: str, *, staff_roles: list[str] | None = None) -> None:
    """Refuse role combinations that create self-approval or break a firewall (enforced at assignment)."""
    if staff_roles and "det_admin" in staff_roles:
        raise Forbidden("a DET administrator can never hold a company role", reason_code="ROLE_COMBINATION_REFUSED", details={"pair": ["det_admin", new_role]})
    if not identity_uuid:
        return
    company = db.get(Company, company_id)
    related_ids = {company_id}
    if company and company.related_entity_group:
        related_ids |= {c.id for c in db.scalars(select(Company).where(Company.related_entity_group == company.related_entity_group))}
    existing = list(db.scalars(select(CompanyRole).where(CompanyRole.identity_uuid == identity_uuid, CompanyRole.status.in_(("active", "invited")), CompanyRole.company_id.in_(related_ids))))
    for r in existing:
        if r.company_id != company_id and "licensed_auditor" not in (r.role, new_role):
            continue  # cross-entity checks apply only to the auditor firewall
        pair = frozenset({r.role, new_role})
        if len(pair) == 1:
            continue
        if pair in PERMITTED_PAIRS:
            continue
        if pair in REFUSED_PAIRS:
            raise Forbidden("this role combination is not allowed on the same company or a related entity", reason_code="ROLE_COMBINATION_REFUSED", details={"pair": sorted(pair), "company_id": r.company_id})


# --- E7 audit agent and documents (append-only additions) --------------------------------------------
OWNER_PERMS |= {"documents.issue", "documents.share"}
STAFF_PERMS["licensed_auditor"] |= {"audit.review", "audit.record_review", "audit.criteria.confirm"}
STAFF_PERMS["qeonix_audit_ops"] |= {"audit.assign", "audit.review_queue"}
STAFF_PERMS["det_pilot_manager"] |= {"audit.assign"}
STAFF_PERMS["tax_specialist"] |= {"audit.criteria.propose"}
STAFF_PERMS["platform_security_admin"] |= {"documents.revoke", "documents.switch", "audit.register.load"}
STAFF_PERMS["qeonix_product_owner"] |= {"documents.switch", "audit.criteria.publish"}
# E9-S1 SC14 KPIs: aggregate export, minimum group size (DET pilot manager), KPI calculation run log (reviewer).
STAFF_PERMS["det_admin"] |= {"det.aggregates.export"}
STAFF_PERMS["det_pilot_manager"] |= {"det.aggregates.export", "det.min_group_size.manage"}
STAFF_PERMS["compliance_reviewer"] |= {"det.kpi_runs.view"}
# E3 (dashboard, compliance agent, reminders): own reminder inbox/preferences for every company role that receives
# reminders; compliance pack preparation (owner, delegate; remote owners read-only) and owner-only pack approval.
OWNER_PERMS |= {"reminders.view", "compliance.prepare", "compliance.approve"}
REMOTE_OWNER_PERMS |= {"reminders.view"}
DELEGATE_BASE_PERMS |= {"reminders.view", "compliance.prepare"}
