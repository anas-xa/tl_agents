"""E2-S1 reference configuration (all versioned, owner DET pilot manager for values) and demo intake events."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.time import utcnow
from app.modules.config.service import ensure_config, ensure_rule
from app.modules.licences.models import Licence, LicenceEvent, LicenceEventOutbox

ORDER = 10
PM = "DET pilot manager"


def seed(db: Session) -> None:
    ensure_config(db, "det.interface_type", "file", owner=PM, status="to_be_confirmed", label="[OPEN] DET interface type (api / file / dxp); manual file adapter is the fallback", unit="enum")
    ensure_config(db, "det_intake.shared_secret", "det-intake-dev-secret", owner="Qeonix platform security lead", status="provisional", label="dev placeholder; replaced per environment; header X-DET-Intake-Secret")
    ensure_config(db, "det_intake.status_mapping", {"version": "v1", "map": {"ACTIVE": "active", "ISSUED": "active", "RENEWED": "active", "EXPIRED": "expired", "SUSPENDED": "suspended", "CANCELLED": "cancelled", "UNDER_RENEWAL": "under_renewal"}}, owner=PM, status="to_be_confirmed", label="placeholder set, not the DET list; unmapped raw values map to 'unknown' for operations review", description="DET raw status value to platform status. Raw values are stored unchanged.")
    ensure_config(db, "det_intake.event_type_mapping", {"version": "v1", "map": {"ISSUED": "issued", "ISSUANCE": "issued", "RENEWED": "renewed", "RENEWAL": "renewed", "AMENDED": "amended", "AMENDMENT": "amended", "EXPIRED": "expired", "SUSPENDED": "suspended", "SUSPENSION": "suspended", "REINSTATED": "reinstated", "CANCELLED": "cancelled", "CANCELLATION": "cancelled", "TRANSFERRED": "transferred", "TRANSFER": "transferred"}}, owner=PM, status="to_be_confirmed", label="placeholder set, not the DET list; unmapped event types are held for review")
    ensure_config(db, "det_intake.k6_status_mapping", {"cancelled_before_expiry": ["CANCELLED"], "suspended": ["SUSPENDED"]}, owner=PM, status="to_be_confirmed", label="placeholder until DET supplies its status list; K6 excludes these from the denominator")
    ensure_config(db, "det_intake.renewal_completed_statuses", ["ISSUED", "ACTIVE"], owner=PM, status="to_be_confirmed", label="placeholder DET status 'issued' marks a renewal as completed; payment is never the signal")
    ensure_config(db, "det_intake.in_scope_authorities", ["DET"], owner=PM, status="provisional", label="issuing-authority field is the primary in-scope test")
    ensure_config(db, "det_intake.free_zone_authorities", ["DMCC", "JAFZA", "DAFZA", "DIFC", "IFZA", "MEYDAN"], owner=PM, status="provisional", label="free-zone authorities are out of scope with reason; list illustrative")
    ensure_config(db, "det_intake.licence_number_pattern", r"^DET-\d+$", owner=PM, status="to_be_confirmed", label="synthetic DET number format for Phase 1 fixtures; real format to be confirmed by DET")
    ensure_config(db, "det_intake.field_mapping", {"version": "v1", "map": {"licence_number": "licence_number", "issuing_authority": "issuing_authority", "licence_type": "licence_type", "status": "status", "expiry_date": "expiry_date", "issue_date": "issue_date", "activities": "activities", "legal_form": "legal_form", "category": "category"}}, owner=PM, status="to_be_confirmed", label="DET field names to platform fields; only this changes if DET's names differ")
    ensure_config(db, "intake.freshness_window_hours", 24, unit="hours", owner=PM, status="provisional", label="illustrative, configurable (per field max age)")
    ensure_config(db, "intake.retry_schedule_minutes", [1, 5, 15], unit="minutes", owner=PM, status="provisional", label="illustrative, for production; exponential backoff")
    ensure_config(db, "intake.retry_max_attempts_per_cycle", 5, unit="count", owner=PM, status="provisional", label="illustrative")
    ensure_config(db, "intake.alert_after_failed_cycles", 3, unit="cycles", owner=PM, status="provisional", label="configurable; alert after 3 consecutive failed cycles")
    ensure_config(db, "intake.alert_after_failure_duration_minutes", 30, unit="minutes", owner=PM, status="provisional", label="configurable; whichever comes first")
    ensure_config(db, "intake.alt_retry_schedule", ["5m", "15m", "1h", "4h", "12h"], owner=PM, status="provisional", label="superseded by intake.retry_schedule_minutes; kept as configurable alternative (Q14)")
    ensure_config(db, "intake.run_interval_hours", 4, unit="hours", owner=PM, status="provisional", label="configurable")
    ensure_config(db, "intake.full_reconciliation", {"schedule": "nightly", "window_hours": 4}, owner=PM, status="provisional", label="configurable")
    ensure_config(db, "intake.chunk_size", 1000, unit="licences", owner=PM, status="provisional", label="resumable from last completed chunk")
    ensure_config(db, "intake.design_volume", {"register": 300000, "changed_per_peak_day": 25000}, owner=PM, status="provisional", label="load test on synthetic data in Phase 1")
    ensure_config(db, "intake.pending_renewal_watch_hours", 48, unit="hours", owner=PM, status="provisional", label="then escalate to operations; configurable")
    ensure_config(db, "intake.overdue_renewal_flag_days", 7, unit="days", owner=PM, status="provisional", label="days after expiry before the owner is flagged 'overdue licence renewal'")
    ensure_config(db, "det.grace_period_days", None, unit="days", owner=PM, status="to_be_confirmed", label="[OPEN] DET grace period; no illustrative claim is shown to buyers")
    ensure_config(db, "match.pending_first_review_working_days", 1, unit="working days", owner=PM, status="provisional", label="target")
    ensure_config(db, "match.pending_resolution_working_days", 3, unit="working days", owner=PM, status="provisional", label="target")
    ensure_config(db, "match.pending_escalation_working_days", 5, unit="working days", owner=PM, status="provisional", label="target; escalates to the DET pilot manager")
    ensure_config(db, "sc3.check_again_cooldown_seconds", 60, unit="seconds", owner="Qeonix product owner", status="provisional", label="configurable")
    ensure_config(db, "sc3.retry_now_delay_seconds", 30, unit="seconds", owner="Qeonix product owner", status="provisional", label="configurable")
    ensure_config(db, "sc3.loading_timeout_seconds", 10, unit="seconds", owner="Qeonix product owner", status="provisional", label="configurable; then the failure state")
    ensure_config(db, "sc3.history_window_months", 24, unit="months", owner="Qeonix product owner", status="provisional", label="illustrative, for production; 'Show older' control")
    ensure_config(db, "licence.legal_basis_register", {"licence_read": "government_function", "subscription": "contract", "bank_data": "explicit_consent"}, owner="DET + counsel", status="to_be_confirmed", label="legal basis per data purpose; DET and counsel decide")
    ensure_config(db, "licence.retention", {"change_history": "life of subscription + period after (to be confirmed)", "audit_entries": "longer than business data (to be confirmed)", "tax_records_years": 7}, owner="DET + counsel", status="to_be_confirmed", label="provisional; agree with DET and counsel (confirm instrument for the 7-year period)")
    ensure_rule(db, "k6-v1", "K6 on-time licence renewal rate", instrument="DET renewal semantics (to be confirmed)", status="provisional", owner_role=PM, parameters={"version": "k6-v1", "cutoff_zone": "Asia/Dubai", "signal": "renewal_completed_at", "baseline": "expiry in force before the renewal transaction", "excludes": ["cancelled_before_expiry", "suspended"]})
    ensure_rule(db, "det-status-mapping-v1", "DET status mapping table", instrument="DET data specification (to be confirmed)", status="to_be_confirmed", owner_role=PM, parameters={"version": "v1", "note": "placeholder value set, not the DET list"})


def _iso(d: date | None) -> str | None:
    return d.isoformat() if d else None


def seed_demo(db: Session) -> None:
    from app.modules.licences.service import intake_event

    if db.scalar(select(LicenceEvent).where(LicenceEvent.event_id == "DEMO-EV-ALNOOR-REN-1")) is not None:
        return
    today = date.today()
    alnoor = db.get(Licence, "lic_alnoor")
    bluedune = db.get(Licence, "lic_bluedune")
    safwa = db.get(Licence, "lic_safwa")
    gulftech = db.get(Licence, "lic_gulftech")
    if not all((alnoor, bluedune, safwa, gulftech)):
        return
    # Rewind the fixtures to the state before their last DET event so the intake replays it faithfully.
    for lic in (alnoor, bluedune, safwa):
        lic.scope = "in_scope"
        lic.expiry_date = lic.previous_expiry_date
    gulftech.scope = "in_scope"
    gulftech.term_start_date = gulftech.previous_expiry_date + timedelta(days=1)
    db.flush()

    def ev(event_id: str, lic: Licence, raw_type: str, ref: str, effective: date, *, new_expiry: date | None = None, completed: date | None = None, status: str = "ISSUED", extra: dict | None = None) -> dict:
        p = {
            "event_id": event_id,
            "licence_number": lic.licence_number,
            "event_type": raw_type,
            "det_reference": ref,
            "det_sequence": 1,
            "effective_date": _iso(effective),
            "det_event_date": _iso(effective),
            "new_expiry_date": _iso(new_expiry),
            "new_term_start_date": _iso(effective) if raw_type in ("ISSUED", "RENEWED") else None,
            "renewal_completed_at": datetime.combine(completed, time(10, 30)).isoformat() + "Z" if completed else None,
            "payment_received_at": datetime.combine(completed - timedelta(days=1), time(9, 0)).isoformat() + "Z" if completed else None,
            "licence": {"issuing_authority": "DET", "licence_type": "mainland", "trade_name_en": lic.trade_name_en, "trade_name_ar": lic.trade_name_ar, "legal_form": lic.legal_form, "category": lic.category, "activities": lic.activities, "issue_date": _iso(lic.issue_date), "expiry_date": _iso(new_expiry or lic.expiry_date), "status": status},
        }
        if extra:
            p.update(extra)
        return p

    # Al Noor: early renewal (on time), new term from the day after the old expiry.
    intake_event(db, ev("DEMO-EV-ALNOOR-REN-1", alnoor, "RENEWED", "REF-AN-R1", alnoor.previous_expiry_date + timedelta(days=1), new_expiry=today + timedelta(days=45), completed=alnoor.previous_expiry_date - timedelta(days=2)), source="demo")
    # Blue Dune: renewal completed five days after the old expiry (late; grace period is [OPEN]).
    intake_event(db, ev("DEMO-EV-BLUEDUNE-REN-1", bluedune, "RENEWED", "REF-BD-R1", bluedune.previous_expiry_date + timedelta(days=1), new_expiry=today + timedelta(days=200), completed=bluedune.previous_expiry_date + timedelta(days=5)), source="demo")
    # Safwa: renewal on expiry day last year, then expired ten days ago (expired-in-grace, not cancelled).
    intake_event(db, ev("DEMO-EV-SAFWA-REN-1", safwa, "RENEWED", "REF-SF-R1", safwa.previous_expiry_date + timedelta(days=1), new_expiry=today - timedelta(days=10), completed=safwa.previous_expiry_date), source="demo")
    intake_event(db, ev("DEMO-EV-SAFWA-EXP-1", safwa, "EXPIRED", "REF-SF-E1", today - timedelta(days=10), status="EXPIRED"), source="demo")
    # Gulf Tech: amendment (activity added).
    intake_event(db, ev("DEMO-EV-GULFTECH-AMD-1", gulftech, "AMENDED", "REF-GT-A1", today - timedelta(days=30), status="ACTIVE", extra={"licence": {"issuing_authority": "DET", "licence_type": "mainland", "activities": ["IT systems trading", "Software", "Cloud services"], "status": "ACTIVE"}}), source="demo")
    # Held for review: a record with no issuing authority (unclassified) and one with an unmapped DET status.
    intake_event(db, {"event_id": "DEMO-EV-HELD-AUTH-1", "licence_number": "DET-7781001", "event_type": "ISSUED", "det_reference": "REF-HELD-1", "effective_date": _iso(today - timedelta(days=3)), "new_expiry_date": _iso(today + timedelta(days=362)), "licence": {"issuing_authority": "", "licence_type": "mainland", "trade_name_en": "Held Example Trading", "trade_name_ar": "مثال محتجز للتجارة", "status": "ISSUED"}}, source="demo")
    intake_event(db, {"event_id": "DEMO-EV-HELD-STATUS-1", "licence_number": "DET-5099001", "event_type": "ISSUED", "det_reference": "REF-HELD-2", "effective_date": _iso(today - timedelta(days=2)), "new_expiry_date": _iso(today + timedelta(days=363)), "licence": {"issuing_authority": "DET", "licence_type": "mainland", "trade_name_en": "Unmapped Status Example LLC", "trade_name_ar": "مثال حالة غير مطابقة ذ.م.م", "status": "PENDING_INSPECTION"}}, source="demo")
    # Free-zone record: out of scope, logged with reason, hidden from owners.
    intake_event(db, {"event_id": "DEMO-EV-FZ-1", "licence_number": "DMCC-44120", "event_type": "ISSUED", "det_reference": "REF-FZ-1", "effective_date": _iso(today - timedelta(days=5)), "new_expiry_date": _iso(today + timedelta(days=360)), "licence": {"issuing_authority": "DMCC", "licence_type": "free_zone", "trade_name_en": "Free Zone Example DMCC", "trade_name_ar": "مثال منطقة حرة", "status": "ACTIVE"}}, source="demo")
    # Demo subscriptions are seeded explicitly by the subscriptions module: mark the demo outbox rows consumed.
    for row in db.scalars(select(LicenceEventOutbox).where(LicenceEventOutbox.event_id.like("DEMO-EV-%"))):
        row.consumed_at = utcnow()
        row.last_error = "demo fixture: subscription seeded by subscriptions.seed_demo"
    db.flush()
