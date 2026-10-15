"""Reference-data seed: configuration keys, rule register entries and retention classes.

Idempotent: existing keys are left untouched (their versions are history).
Feature modules add their own seeds through ``SEEDERS``.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date

from sqlalchemy.orm import Session

from app.modules.audit.models import RetentionClass
from app.modules.config.service import ensure_config, ensure_rule

SEEDERS: list[Callable[[Session], None]] = []


def seeder(fn: Callable[[Session], None]) -> Callable[[Session], None]:
    SEEDERS.append(fn)
    return fn


def seed_reference_data(db: Session) -> None:
    # Identity and session (E1-S1, Q3/Q258): configurable defaults, owner = Qeonix platform security lead.
    ensure_config(db, "identity.min_assurance_level", "SOP2", owner="Qeonix platform security lead", status="provisional", label="Assumption: SOP2 is the verified level; confirm with the UAE PASS programme (TDRA) and DET", description="Minimum UAE PASS assurance level for sign-in.", effective_from=date(2025, 1, 1))
    ensure_config(db, "identity.approval_min_assurance_level", "SOP3", owner="Qeonix platform security lead", status="provisional", label="Highest level the agreement permits for consent, approval and subscription changes", unit="level")
    ensure_config(db, "identity.pending_signin_expiry_minutes", 5, unit="minutes", owner="Qeonix platform security lead", status="provisional", label="illustrative, configurable for production")
    ensure_config(db, "identity.session_idle_timeout_minutes", 15, unit="minutes", owner="Qeonix platform security lead", status="provisional", label="illustrative, configurable for production")
    ensure_config(db, "identity.session_warning_minutes", 2, unit="minutes", owner="Qeonix platform security lead", status="provisional")
    ensure_config(db, "identity.session_max_length_hours", 8, unit="hours", owner="Qeonix platform security lead", status="provisional")
    ensure_config(db, "identity.staff_invitation_days", 7, unit="days", owner="Qeonix platform security lead", status="provisional")
    ensure_config(db, "identity.signin_audit_retention_months", 24, unit="months", owner="Qeonix platform security lead", status="to_be_confirmed", label="for production: confirm with counsel and DET; personal fields removed at 12 months")
    ensure_config(db, "identity.signin_personal_fields_pseudonymise_months", 12, unit="months", status="to_be_confirmed", label="for production: confirm with counsel and DET")
    ensure_config(db, "privacy_notice.version", "2025-01", owner="Qeonix product owner", status="provisional")
    # Delegate rights (Phase B): built, switched off per right until the evidence rule is confirmed.
    for right in ("grant_consent", "approve_submissions", "change_subscription"):
        ensure_config(db, f"delegate_rights.{right}.enabled", False, owner="Qeonix product owner", status="to_be_confirmed", label="Off until the FTA, the Central Bank route or licensed provider and DET confirm the evidence rule")
    ensure_config(db, "delegate.reconfirmation_window_days", 30, unit="days", owner="Qeonix product owner", status="provisional", label="product rule, not a DET rule; view-only during the window")
    # Audit-log retention (E1-S3): per log class, with 'to be confirmed' labels.
    ensure_config(db, "retention.security_log_days", 90, unit="days", owner="Compliance and audit-trail reviewer", status="to_be_confirmed", label="to be confirmed with DET")
    ensure_config(db, "retention.outside_uae_flag_days", 90, unit="days", owner="Compliance and audit-trail reviewer", status="to_be_confirmed", label="to be confirmed with DET")
    ensure_config(db, "retention.approvals_and_consent_months", None, unit="months", owner="Compliance and audit-trail reviewer", status="to_be_confirmed", label="separate, longer value; empty until confirmed")
    for log_class, months, pseud, basis in (
        ("standard", None, None, "to be confirmed by counsel"),
        ("sign_in", 24, 12, "legitimate operation of the service (PDPL Art. 4 basis to be confirmed)"),
        ("approval", None, None, "legal obligation to evidence approvals; period to be confirmed"),
        ("consent", None, None, "legal obligation to evidence consent; period to be confirmed"),
        ("security", 3, None, "security of processing; 90 days illustrative"),
    ):
        if db.get(RetentionClass, log_class) is None:
            db.add(RetentionClass(log_class=log_class, retention_months=months, pseudonymise_after_months=pseud, legal_basis=basis, status="to_be_confirmed" if months is None else "provisional", label="to be confirmed with DET and counsel"))
    # Notification channels (decision): in-portal baseline, minimal email, optional SMS with opt-in, WhatsApp off.
    ensure_config(db, "notifications.channels", {"portal": True, "email": True, "sms": False, "whatsapp": False}, owner="Qeonix product owner", status="provisional", label="WhatsApp off until DET and data-protection counsel confirm")
    # Accessibility standard assumption.
    ensure_config(db, "accessibility.standard", "WCAG 2.2 AA", owner="Qeonix product owner", status="provisional", label="assumed DET standard until DET states otherwise")
    ensure_rule(db, "min-assurance-v1", "Minimum UAE PASS assurance level for sign-in", instrument="UAE PASS service terms (to be confirmed)", status="provisional", owner_role="Qeonix platform security lead", parameters={"min_level": "SOP2", "approval_level": "SOP3"})
    for fn in SEEDERS:
        fn(db)
    from app.discovery import run_seeds

    run_seeds(db)
    db.flush()
