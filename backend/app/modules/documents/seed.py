"""Documents seeds (ORDER 75): sig-v1 table, verification limits, switches; demo documents for Al Noor (Demo data)."""

from __future__ import annotations

from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.demo import CO_ALNOOR
from app.modules.config.service import ensure_config, ensure_rule
from app.modules.documents import service as svc
from app.modules.documents.models import IssuedDocument

ORDER = 75
TL = "Tech Lead"


def seed(db: Session) -> None:
    c = ensure_config
    c(db, "documents.auditors_report.enabled", False, owner="Qeonix product owner", status="confirmed", label="Auditor's report type built but switched off; toggled only by a Qeonix platform administrator with a second administrator's approval")
    c(db, "documents.issue_switch.demo", False, owner="Qeonix product owner", status="confirmed", label="signed-path issue stays OFF in demo; ON only in a test environment with a seeded signer and snapshot")
    c(db, "documents.verify.rate_limit_per_ip_per_minute", 30, unit="requests/min", owner=TL, status="confirmed", label="settled")
    c(db, "documents.verify.rate_limit_per_code_per_hour", 10, unit="lookups/hour", owner=TL, status="confirmed", label="settled")
    c(db, "documents.verify.lockout", {"failed": 10, "window_minutes": 10, "lockout_minutes": 15}, owner=TL, status="confirmed", label="10 failed lookups in 10 min -> 15 min lockout, generic bilingual message")
    c(db, "documents.verify.code_format", "16 Crockford base32, 80 bits CSPRNG, no expiry", owner=TL, status="confirmed")
    c(db, "documents.issue.approval_validity_hours", 24, unit="h", owner=TL, status="confirmed")
    c(db, "documents.issue.auto_retries", 3, owner=TL, status="confirmed", label="idempotent by approval id + data version")
    c(db, "documents.hash.algorithm", "SHA-256 per language file + canonical payload + manifest", owner=TL, status="confirmed")
    c(db, "documents.chain_check.schedule", "nightly", owner=TL, status="confirmed")
    c(db, "documents.register.daily_check", "daily, alert only", owner=TL, status="confirmed")
    c(db, "documents.bilingual.table", "bilingual-fields-v1", owner="DDE", status="provisional", label="default, configurable")
    c(db, "documents.amounts.rounding", "AED 2dp, round half up once at final figure", owner="DDE", status="provisional", label="illustrative")
    c(db, "documents.precedence_clause.version", "pc-v1", owner="PM", status="provisional", label="working assumption: Arabic prevails on platform-authored documents only; never on auditor-signed documents")
    c(db, "documents.retention.per_record_class", {"issued_document": {"start_event": "later of issue and revocation", "duration": None, "legal_hold": False}}, owner="TLE/counsel", status="to_be_confirmed", label="[OPEN]; duration empty until confirmed; revoked/superseded never deleted")
    ensure_rule(db, "sig-v1", "Deliverable types and signature requirement (sig-v1)", version="v1", instrument="set with audit expert and TLE; Federal Law 12/2014 (confirm)", status="provisional", owner_role="audit expert + TLE", effective_from=date(2025, 1, 1), parameters={"types": svc.SIG_V1, "missing_type": "signature required (fail closed)"})
    ensure_rule(db, "bilingual-fields-v1", "Bilingual key fields and normalisation", version="v1", instrument="internal rule", status="provisional", owner_role="DDE", effective_from=date(2025, 1, 1), parameters={"normalise": ["Arabic-Indic and Western digits", "ISO Gregorian dates", "AED two decimals in fils", "NFC names, diacritics and letter variants"], "blocking": ["company names per language from the DET record", "licence number", "TRN", "tax period", "amounts", "dates", "document type", "status"]})
    db.flush()


class _Actor:
    identity_uuid = None
    display_name = "Qeonix platform (AI agent, Demo data)"
    actor_key = None


def seed_demo(db: Session) -> None:
    if db.scalar(select(IssuedDocument.id).where(IssuedDocument.company_id == CO_ALNOOR).limit(1)) is not None:
        return
    actor = _Actor()
    # Superseded + current licence-and-subscription confirmation (the first is kept with status 'superseded').
    svc.issue_document(db, CO_ALNOOR, "licence_subscription_confirmation", {**svc.build_source_record(db, CO_ALNOOR, "licence_subscription_confirmation"), "generated_date": date.today().replace(day=1).isoformat()}, actor, is_demo=True)
    svc.issue_document(db, CO_ALNOOR, "licence_subscription_confirmation", svc.build_source_record(db, CO_ALNOOR, "licence_subscription_confirmation"), actor, is_demo=True)
    svc.issue_document(db, CO_ALNOOR, "compliance_status_report", svc.build_source_record(db, CO_ALNOOR, "compliance_status_report"), actor, is_demo=True)
    try:
        from app.modules.drafts.models import DraftPack

        pack = db.scalar(select(DraftPack).where(DraftPack.company_id == CO_ALNOOR).order_by(DraftPack.created_at.desc()).limit(1))
        if pack is not None:
            svc.issue_tax_pack_draft(db, pack.id, actor, is_demo=True)
    except ImportError:  # pragma: no cover
        pass
    db.flush()
