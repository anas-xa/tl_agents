"""Consent configuration (E4-S1/S2) and demo consents. ORDER 30."""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.time import utcnow
from app.demo import CO_ALNOOR, CO_BLUEDUNE, CO_SAFWA, PERSONA_UUIDS
from app.modules.config.service import ensure_config, ensure_rule
from app.modules.consent.models import Consent, ConsentWithdrawal
from app.modules.consent.service import _scope_key, build_grant_receipt, build_withdrawal_receipt

ORDER = 30

CONTROLLED_LISTS_V1 = {
    "version": 1,
    "purposes": ["bookkeeping_classification", "vat_return_preparation", "corporate_tax_return_preparation", "audit_preparation", "deadline_compliance"],
    "data_types": {
        "bank": ["account_balance", "transactions"],
        "erp": ["ledger", "invoices", "chart_of_accounts", "trial_balance"],
        "tax_authority": ["tax_profile", "return_status", "due_dates"],
        "e_invoice_provider": ["invoice_status"],
    },
}
RECEIPT_FIELDS_V1 = ["receipt_number", "version", "consent_id", "company", "purpose", "data_source", "accounts", "data_we_read", "data_we_do_not_read", "valid_from", "valid_until", "granted_by", "acting_as", "delegation_id", "delegated_by", "date_granted", "status", "how_to_withdraw", "capacity_and_assurance_level", "wording_version_ar_en", "utc_and_gulf_timestamps", "audit_entry_ref"]
RETENTION_CLASSES_V1 = [
    {"class": "A", "record_type": "raw bank data pulled or uploaded under consent", "instrument": None, "effective_date": None, "period": "30 days grace (placeholder)", "trigger": "consent_withdrawal", "duty_owner": "platform", "status": "provisional", "legal_hold": False},
    {"class": "B", "record_type": "filing and certificate evidence", "instrument": "statutory period, to be confirmed", "effective_date": None, "period": "7 years placeholder from end of relevant tax period", "trigger": "filing_date", "duty_owner": "company", "status": "to_be_confirmed", "legal_hold": True},
    {"class": "C", "record_type": "audit trail and consent receipts", "instrument": None, "effective_date": None, "period": "keep; personal fields minimised", "trigger": "licence_end", "duty_owner": "platform", "status": "to_be_confirmed", "legal_hold": True},
]


def seed(db: Session) -> None:
    eng = "Qeonix engineering lead"
    prod = "Qeonix product and compliance"
    ensure_config(db, "consent.gate.cache_max_seconds", 30, unit="seconds", owner=eng, status="provisional", label="illustrative, configurable")
    ensure_config(db, "consent.gate.push_invalidation_on_withdrawal", True, owner=eng, status="confirmed")
    ensure_config(db, "consent.gate.request_token_lifetime_max_seconds", 60, unit="seconds", owner=eng, status="provisional", label="illustrative")
    ensure_config(db, "consent.gate.simulate_unavailable", False, owner=eng, status="confirmed", label="engineering test hook: registry unreachable -> GATE_UNAVAILABLE")
    ensure_config(db, "consent.external_revocation_poll_interval_minutes", 15, unit="minutes", owner=eng, status="provisional", label="default; webhook where the provider offers one")
    ensure_config(db, "consent.max_duration_months", 12, unit="months", owner=prod, status="provisional", label="no hard-coded legal default; conservative working value until the CBUAE route and counsel confirm")
    ensure_config(db, "consent.expiry_reminder_offsets_days", [30, 7, 1], unit="days before", owner="Qeonix product owner", status="provisional", label="configurable")
    ensure_config(db, "consent.notice_offsets_days", [30, 7], unit="days before", owner="Qeonix product owner", status="provisional", label="Q47: notices to authority holders before consent or licence expiry")
    ensure_config(db, "consent.pause_limit_days", 90, unit="days", owner="Qeonix product owner", status="provisional", label="provisional; no legal basis; configuration only")
    ensure_config(db, "consent.subscription_grace_period_days", 30, unit="days", owner="Qeonix product owner", status="provisional", label="from the fee model")
    ensure_config(db, "consent.loading_slow_threshold_seconds", 10, unit="seconds", owner="Qeonix UX lead", status="provisional")
    ensure_config(db, "consent.controlled_lists", CONTROLLED_LISTS_V1, owner=prod, status="confirmed", label="versioned controlled purpose and data-type lists; adding never widens an existing consent", description="Consents pin list_version. Removing a value makes the gate deny that purpose/data type and notifies the owner.")
    ensure_config(db, "consent.wording_version", "2026-10-draft-1", owner="Legal (Trade Licensing Expert confirms)", status="provisional", label="consent wording AR/EN as drafted; provisional")
    ensure_config(db, "consent.receipt_template_version", "v1", owner="Qeonix product owner / Legal", status="provisional", label="provisional")
    ensure_config(db, "consent.receipt_template_fields", RECEIPT_FIELDS_V1, owner="Qeonix product owner / Legal", status="provisional", label="provisional")
    ensure_config(db, "consent.notice_schedule_version", "v1", owner="Qeonix product owner", status="provisional")
    ensure_config(db, "consent.k13_target_minutes", 5, unit="minutes", owner=eng, status="provisional", label="illustrative: withdrawn_at -> pulls_stopped_at")
    ensure_config(db, "consent.withdrawal.gate_block_max_seconds", 30, unit="seconds", owner=eng, status="provisional", label="illustrative (normally ~5 s via push invalidation)")
    ensure_config(db, "consent.withdrawal.last_possible_read_gap_seconds", 60, unit="seconds", owner=eng, status="provisional", label="illustrative = cache 30 + call timeout 30")
    ensure_config(db, "consent.withdrawal.bank_call_timeout_seconds", 30, unit="seconds", owner=eng, status="provisional", label="illustrative")
    ensure_config(db, "consent.withdrawal.alert_pulls_stopped_empty_after_minutes", 5, unit="minutes", owner="Qeonix operations", status="provisional", label="illustrative")
    ensure_config(db, "consent.withdrawal.alert_source_revocation_pending_after_minutes", 15, unit="minutes", owner="Qeonix operations", status="provisional", label="illustrative")
    ensure_config(db, "consent.withdrawal.source_revocation_retry_schedule", {"minutes": [1, 2, 4, 8, 16], "then_hourly_for_hours": 24, "then": "manual_ticket"}, owner="Qeonix operations", status="provisional", label="illustrative")
    ensure_config(db, "consent.withdrawal_receipt_template_version", "v1", owner="Qeonix product owner / Legal", status="provisional", label="provisional; counsel approves; plain, non-legal, bilingual")
    ensure_config(db, "consent.retention.deletion_grace_days", 30, unit="days", owner="owning role (to be named)", status="provisional", label="illustrative / provisional; raw purge schedule placeholder; never promised to the user as a date")
    ensure_config(db, "consent.retention.backup_expiry_window_days", 35, unit="days after live deletion", owner=eng, status="provisional", label="illustrative")
    ensure_config(db, "consent.retention.deletion_retry_policy", {"attempts": 5, "within_hours": 24, "backoff": True}, owner=eng, status="provisional", label="illustrative")
    ensure_config(db, "consent.retention.deletion_ops_alert_after_hours", 24, unit="hours", owner="Qeonix operations", status="provisional", label="illustrative")
    ensure_config(db, "consent.retention.filed_records_years", 7, unit="years from end of relevant tax period", owner="Trade Licensing Expert confirms", status="to_be_confirmed", label="provisional / to be confirmed")
    ensure_config(db, "consent.retention.classes", RETENTION_CLASSES_V1, owner="owning role per class", status="to_be_confirmed", label="two-class model (raw purge placeholder 30 d / legal hold 'statutory period, to be confirmed'); no promise of deletion")
    ensure_config(db, "consent.retention.per_record_class", {"tax_return_support": "statutory period, to be confirmed", "vat_records": "statutory period, to be confirmed", "audit_working_papers": "statutory period, to be confirmed", "consent_receipts": "statutory period, to be confirmed", "audit_logs": "statutory period, to be confirmed"}, owner="FTA / counsel", status="to_be_confirmed", label="placeholder")
    ensure_config(db, "consent.sms_opt_in_required", True, owner="Qeonix product owner", status="confirmed")
    ensure_config(db, "consent.request_right.expiry_days", 14, unit="days", owner="Qeonix product owner", status="provisional", label="request-right action expires; grants nothing")
    ensure_config(db, "consent.request_right.max_per_day", 3, unit="requests per person per company per day", owner="Qeonix product owner", status="provisional", label="rate limit")
    ensure_config(db, "consent.remote_owner_tax_consent_allowed", False, owner="Qeonix product owner", status="confirmed", label="Q72: remote owner cannot give or withdraw tax-data consent online in MVP")
    ensure_config(db, "consent.det_support_help_line", "DET support help line (number to be confirmed with DET)", owner="DET", status="to_be_confirmed", label="path recorded for owners abroad: 'unclear authority, action blocked'")
    ensure_config(db, "consent.provider_revocation.simulated_result", "confirmed", owner=eng, status="confirmed", label="engineering stub result once the Open Finance route is live")
    ensure_rule(db, "consent-retention-v1", "Retention rule register for data held under consent (two-class model)", instrument="statutory period, to be confirmed", status="to_be_confirmed", owner_role="Trade Licensing Expert / counsel", parameters={"classes": RETENTION_CLASSES_V1, "legal_hold_reasons": ["tax_record_keeping", "signed_audit_file", "audit_trail", "open_escalation"], "data_states": ["active", "withdrawn-restricted", "purged", "legal-hold", "expired-deleted"]})
    ensure_rule(db, "consent-authority-evidence-v1", "Authority-evidence model for consent acts (Q47)", instrument="DET licence record (signing rule)", status="provisional", owner_role="Qeonix product and compliance", parameters={"values": ["any_one", "joint", "unclear"], "unclear": "block Resume; show contact DET support", "joint": "joint number needed", "any_one": "any holder may resume or withdraw; any holder's withdrawal takes effect at once"})


def _consent(db: Session, **kw) -> Consent | None:
    key = _scope_key(kw["company_id"], kw["source"], kw.get("account_ids", []), kw["purpose"], kw.get("recipient"))
    if db.scalar(select(Consent).where(Consent.scope_key == key)) is not None:
        return None
    c = Consent(scope_key=key, is_demo=True, wording_version="2026-10-draft-1", list_version=1, **kw)
    db.add(c)
    db.flush()
    build_grant_receipt(db, c)
    return c


def seed_demo(db: Session) -> None:
    now = utcnow()
    khalid, priya = PERSONA_UUIDS["khalid"], PERSONA_UUIDS["priya"]
    # Al Noor: active ledger and invoice authorisation; bank consent pending because the bank route is not live
    _consent(db, company_id=CO_ALNOOR, consent_type="ledger_invoice_authorisation", source="erp", provider_name="File uploads (manual, unverified)", data_types=["ledger", "invoices", "trial_balance"], account_ids=[], purpose="bookkeeping_classification", valid_from=now - timedelta(days=35), expires_at=now + timedelta(days=330), status="active", grantor_identity_uuid=khalid, grantor_display_name="Khalid Al Mansoori", grantor_role="owner", grantor_capacity="authorised_signatory", identity_assurance_level="SOP3", granted_at=now - timedelta(days=35))
    _consent(db, company_id=CO_ALNOOR, consent_type="bank_data_open_finance", source="bank", provider_name="Demo Bank (fixture)", data_types=["account_balance", "transactions"], account_ids=["AE07DEMO0000000001234"], purpose="bookkeeping_classification", valid_from=now - timedelta(days=2), expires_at=now + timedelta(days=363), status="pending", status_reason="awaiting_provider_confirmation", grantor_identity_uuid=khalid, grantor_display_name="Khalid Al Mansoori", grantor_role="owner", grantor_capacity="authorised_signatory", identity_assurance_level="SOP3", granted_at=now - timedelta(days=2), external_status="pending")
    # Blue Dune: bank consent withdrawn on the platform; provider revocation still retrying (timeline step 3)
    bd = _consent(db, company_id=CO_BLUEDUNE, consent_type="bank_data_open_finance", source="bank", provider_name="Demo Bank (fixture)", data_types=["transactions"], account_ids=["AE12DEMO0000000005678"], purpose="vat_return_preparation", valid_from=now - timedelta(days=60), expires_at=now + timedelta(days=300), status="withdrawn_on_platform", status_reason="withdrawn_by_holder", grantor_identity_uuid=priya, grantor_display_name="Priya Raman", grantor_role="owner", grantor_capacity="authorised_signatory", identity_assurance_level="SOP3", granted_at=now - timedelta(days=60), external_consent_id="ALT-DEMO-5678", external_status="active", withdrawn_at=now - timedelta(days=3))
    if bd is not None:
        w = ConsentWithdrawal(consent_id=bd.consent_id, version=1, company_id=CO_BLUEDUNE, withdrawn_at=now - timedelta(days=3), withdrawer_identity_uuid=priya, withdrawer_display_name="Priya Raman", withdrawer_role="remote_owner", provider_revocation_status="retrying", revocation_attempt_count=2, next_retry_at=now + timedelta(minutes=30), jobs_cancelled=1, pulls_stopped_at=now - timedelta(days=3) + timedelta(minutes=2), deletion_scheduled_at=now - timedelta(days=3), deletion_due_at=now + timedelta(days=27), k13_class="normal", ops_alert_raised=True)
        db.add(w)
        db.flush()
        r = build_withdrawal_receipt(db, bd, w)
        w.receipt_ref = r.receipt_id
    # Safwa: licence expired -> consent paused (licence_expired)
    _consent(db, company_id=CO_SAFWA, consent_type="ledger_invoice_authorisation", source="erp", provider_name="File uploads (manual, unverified)", data_types=["ledger", "invoices"], account_ids=[], purpose="bookkeeping_classification", valid_from=now - timedelta(days=200), expires_at=now + timedelta(days=160), status="paused", status_reason="licence_expired", grantor_identity_uuid=khalid, grantor_display_name="Khalid Al Mansoori", grantor_role="owner", grantor_capacity="authorised_signatory", identity_assurance_level="SOP3", granted_at=now - timedelta(days=200), paused_at=now - timedelta(days=10))
    db.flush()

