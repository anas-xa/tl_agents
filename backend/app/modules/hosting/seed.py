"""Seeds for hosting / residency (E1-S4): configuration keys, rules, checklist document, key register,
demo inventory (blocked variant by default), demo K12 link events."""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.time import utcnow
from app.modules.config.service import ensure_config, ensure_rule, get_config
from app.modules.hosting import service
from app.modules.hosting.models import LinkEvent, ResidencyInventory

ORDER = 8


def seed(db: Session) -> None:
    sec = "Qeonix security owner"
    ensure_config(db, "hosting.residency_check_mode", "UAE region", owner="DET / DESC", status="to_be_confirmed", label="OPEN: 'UAE region' vs 'Dubai Government cloud / DESC-accredited'")
    ensure_config(db, "hosting.inventory_max_age_hours", 24, unit="hours", owner="Tech Lead", status="provisional", label="inventory older than this is stale and never passes")
    ensure_config(db, "hosting.generator.simulate", "ok", owner="Tech Lead", status="provisional", label="test hook: ok | failed | timed_out | unavailable")
    ensure_config(db, "hosting.demo_inventory_variant", "blocked", owner="Qeonix product owner", status="provisional", label="Demo data: 'blocked' (one backup component unknown) or 'pass'")
    ensure_config(db, "hosting.key_service.simulate_unavailable", False, owner=sec, status="provisional", label="test hook: key service unavailable -> fail closed")
    ensure_config(db, "hosting.tls.min_version", "1.2", owner=sec, status="provisional", label="assumption: TLS 1.2 minimum, 1.3 preferred; forward-secret AEAD suites only; SSL/TLS 1.0/1.1 and plaintext refused and logged; mTLS internal")
    ensure_config(db, "hosting.tls.preferred_version", "1.3", owner=sec, status="provisional")
    ensure_config(db, "hosting.tls.cipher_policy", "forward-secret AEAD only", owner=sec, status="provisional")
    ensure_config(db, "hosting.tls.mtls_internal", True, owner=sec, status="provisional", label="service-to-service, DB, queue, backups, replication")
    ensure_config(db, "hosting.keys.kek_rotation_months", 12, unit="months", owner=sec, status="provisional", label="security owner may shorten, not lengthen; DEKs re-wrapped at each rotation")
    ensure_config(db, "hosting.keys.credential_tls_rotation_days", 90, unit="days", owner=sec, status="provisional")
    ensure_config(db, "hosting.keys.compromise_rotation_deadline_hours", 24, unit="hours", owner=sec, status="provisional", label="illustrative, for production; tested on a shortened schedule")
    ensure_config(db, "hosting.keys.rotation_test_budget_minutes", 30, unit="minutes", owner="Tech Lead", status="provisional", label="zero failed requests and zero data-loss events under continuous load")
    ensure_config(db, "hosting.egress.allow_list", [], owner=f"{sec} + DET security approver (two-person)", status="confirmed", label="empty until each UAE-hosted integration from the brief is added")
    ensure_config(db, "hosting.egress.policy_enabled", True, owner=sec, status="confirmed", label="production disable not allowed; non-production disable needs two approvals and lapses after 24 h")
    ensure_config(db, "hosting.egress.pending_change_expiry_working_days", 5, unit="working days", owner=sec, status="provisional")
    ensure_config(db, "hosting.egress.nonprod_disable_lapse_hours", 24, unit="hours", owner=sec, status="provisional")
    ensure_config(db, "hosting.egress.alert_creation_seconds", 60, unit="seconds", owner=sec, status="provisional", label="alert created within the blocking call")
    ensure_config(db, "hosting.egress.alert_ack_hours_company_data", 1, unit="hours", owner=sec, status="provisional", label="next working day for other components; unacknowledged escalates to the security owner")
    ensure_config(db, "hosting.egress.det_security_approvers", [], owner="DET", status="to_be_confirmed", label="designation held by named DET administrators")
    ensure_config(db, "hosting.support_access_rule", "production access only by named, logged staff on UAE-located controlled endpoints via bastion with just-in-time approval", owner=sec, status="provisional")
    ensure_config(db, "hosting.follow_the_sun_support.enabled", False, owner=sec, status="to_be_confirmed", label="disabled; needs DET and counsel written approval")
    ensure_config(db, "hosting.evidence_export.enabled", False, owner="UX", status="provisional", label="later phase")
    ensure_config(db, "hosting.evidence_export_max_mb", 50, unit="MB", owner="UX", status="provisional", label="illustrative, configurable")
    ensure_config(db, "hosting.release.require_probe_test", False, owner="Tech Lead", status="provisional", label="for production: 30 consecutive minutes with zero failed probes blocks the release when false")
    ensure_config(db, "hosting.owner_statement.approved_wording", "q277_placeholder", owner="Qeonix product owner", status="to_be_confirmed", label="Q277 placeholder pending DET and counsel approval; 'release_approved' variant after release approval")
    ensure_config(db, "hosting.k12_window_hours", 720, unit="hours", owner="Domain Data Expert", status="provisional", label="assumption: 30 x 24 h from onboarding_at (GST), day 30 inclusive")
    ensure_config(db, "hosting.k12_cohort_version", "k12-v1", owner="Domain Data Expert", status="provisional")
    ensure_config(db, "hosting.manual_upload_retention", None, owner="Counsel", status="to_be_confirmed", label="Proposed - pending confirmation")
    ensure_rule(db, "residency-v1", "Residency working definition (UAE infrastructure + UAE jurisdiction + no export of any copy)", instrument="PDPL FDL 45/2021; Dubai Law 26/2015 + DESC; CBUAE Circular 7/2023; FTA terms; DET data-sharing agreement; FDL 46/2021", status="provisional", owner_role="Trade Licensing Expert", parameters={"unknown_location": "fail", "non_uae_subprocessor_or_egress": "fail", "claims_banned": ["compliant", "DESC-approved", "hosted in the UAE without qualification"]})
    ensure_rule(db, "k12-v1", "Onboarding checklist completion (Q362)", instrument="product rule", status="provisional", owner_role="Domain Data Expert", parameters={"window_hours": 720, "required": ["det_licence_record", "fta_tax_profile|fta_profile_manual", "bank_feed|ledger_connection|manual_upload"], "point_in_time_at_mark": True})
    ensure_rule(db, "egress-v1", "Default-deny egress with two-person allow-list changes", instrument="platform security policy", status="provisional", owner_role="Qeonix security owner", parameters={"default": "deny", "approvers": ["qeonix_security_owner", "det_security_approver"], "expiry_working_days": 5})
    service.ensure_checklist(db)
    for key_id, key_type in (("kek-1", "kek"), ("dek-db-1", "dek"), ("svc-cred-api-1", "service_credential"), ("tls-cert-portal-1", "tls_cert")):
        service.ensure_key(db, key_id, key_type)
    db.flush()


def seed_demo(db: Session) -> None:
    from app.demo import CO_ALNOOR, CO_BLUEDUNE, CO_GULFTECH, CO_SAFWA

    if db.scalar(select(ResidencyInventory).where(ResidencyInventory.is_demo.is_(True)).limit(1)) is None:
        variant = str(get_config(db, "hosting.demo_inventory_variant", "blocked"))
        service.generate_inventory(db, actor_key="seed", variant=variant, is_demo=True)
        service.run_release_check(db, actor_key="seed")
    if db.scalar(select(LinkEvent).limit(1)) is not None:
        return
    now = utcnow()
    # Al Noor: onboarded 40 days ago, complete via the manual path within the window.
    t0 = now - timedelta(days=40)
    service.ensure_cohort_row(db, CO_ALNOOR, onboarding_at=t0, onboarding_id="onb_alnoor_1")
    service.record_link_event(db, CO_ALNOOR, "det_licence_record", "activated", "det_mock", event_at=t0 + timedelta(hours=1))
    service.record_link_event(db, CO_ALNOOR, "fta_profile_manual", "activated", "owner_entry", event_at=t0 + timedelta(days=3))
    service.record_link_event(db, CO_ALNOOR, "manual_upload", "activated", "manual_upload", event_at=t0 + timedelta(days=5))
    # Blue Dune: onboarded 20 days ago, window open, bank pending.
    t1 = now - timedelta(days=20)
    service.ensure_cohort_row(db, CO_BLUEDUNE, onboarding_at=t1, onboarding_id="onb_bluedune_1")
    service.record_link_event(db, CO_BLUEDUNE, "det_licence_record", "activated", "det_mock", event_at=t1 + timedelta(hours=1))
    service.record_link_event(db, CO_BLUEDUNE, "fta_profile_manual", "activated", "owner_entry", event_at=t1 + timedelta(days=2))
    service.record_link_event(db, CO_BLUEDUNE, "bank_feed", "requested", "bank", event_at=t1 + timedelta(days=4))
    # Safwa: onboarded 90 days ago, window expired with links missing.
    t2 = now - timedelta(days=90)
    service.ensure_cohort_row(db, CO_SAFWA, onboarding_at=t2, onboarding_id="onb_safwa_1")
    service.record_link_event(db, CO_SAFWA, "det_licence_record", "activated", "det_mock", event_at=t2 + timedelta(hours=1))
    # Gulf Tech: window not started (licence service activation scheduled, onboarding_at in the future).
    service.ensure_cohort_row(db, CO_GULFTECH, onboarding_at=now + timedelta(days=7), onboarding_id="onb_gulftech_pending")
    db.flush()
