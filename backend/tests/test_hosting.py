from __future__ import annotations

import importlib.util
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import select

from app.core.errors import Forbidden
from app.core.time import utcnow
from app.demo import CO_ALNOOR, CO_BLUEDUNE, CO_GULFTECH, CO_SAFWA
from app.modules.audit.models import AuditEvent
from app.modules.companies.models import Company
from app.modules.config.service import set_config
from app.modules.hosting import egress, service
from app.modules.hosting.models import EgressBlockAlert, ResidencyComponent, ResidencyInventory
from tests.conftest import sign_in

T0 = datetime(2026, 1, 1, 0, 0, 0)
D = timedelta(days=1)


def _events(db, event_type):
    return list(db.scalars(select(AuditEvent).where(AuditEvent.event_type == event_type)))


# --- residency inventory and release decision -------------------------------------------------------


def test_unknown_component_blocks_release_and_panel_wording(client, db):
    sign_in(client, "adel")
    r = client.get("/api/hosting/residency")
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["state"] == "ok" and data["unknown_location_count"] == 1
    assert data["cards"]["hosting"] == {"en": "Needs attention: 1 component", "ar": "يحتاج إلى انتباه: مكوّن واحد"}
    dec = data["release_decision"]
    assert dec["result"] == "blocked"
    assert dec["reasons"][0]["en"] == "Blocked: UAE location not recorded for Encrypted backup vault"
    assert dec["reasons"][0]["ar"].startswith("محظور: لم يتم تسجيل موقع الاستضافة في الإمارات للمكوّن")
    assert dec["next_step"]["en"] == "Next step: record the UAE location or replace the component, then request a review."
    assert data["cards"]["release"]["en"].startswith("Release blocked: ")
    assert len(data["components"]) == 10 and sum(c["status"] == "fail" for c in data["components"]) == 1
    assert data["evidence_export"]["available"] is False
    assert "Pass" not in data["cards"]["hosting"]["en"]


def test_pass_variant_release_passes_and_owner_statement_approved(client, db):
    set_config(db, "hosting.demo_inventory_variant", "pass", changed_by="test")
    db.commit()
    sign_in(client, "adel")
    r = client.post("/api/hosting/residency/refresh")
    assert r.status_code == 200, r.text
    assert r.json()["release_decision"]["result"] == "pass"
    assert r.json()["summary"]["cards"]["release"]["en"] == "Release check passed"
    sign_in(client, "khalid")
    st = client.get("/api/hosting/residency-statement").json()
    assert st["state"] == "approved"
    assert st["en"] == "Your company data is stored and processed on infrastructure located in the UAE. Local AI models are used and your data is not sent to external AI services."
    assert st["label"].startswith("Proposed wording")


def test_stale_inventory_never_passes_and_generator_failure_blocks(client, db):
    set_config(db, "hosting.demo_inventory_variant", "pass", changed_by="test")
    db.commit()
    sign_in(client, "adel")
    assert client.post("/api/hosting/residency/refresh").json()["release_decision"]["result"] == "pass"
    set_config(db, "hosting.generator.simulate", "failed", changed_by="test")
    db.commit()
    out = client.post("/api/hosting/residency/refresh").json()
    assert out["generation"]["status"] == "failed"
    assert out["release_decision"]["result"] == "blocked"
    codes = {x["code"] for x in out["release_decision"]["reasons"]}
    assert "GENERATOR_UNAVAILABLE" in codes and "STALE_INVENTORY" in codes
    summary = out["summary"]
    assert summary["state"] == "generation_failed" and summary["inventory"]["stale"] is True
    assert summary["message"]["en"].startswith("We could not generate the residency inventory. No data was changed.")
    assert summary["last_successful_check_at"] is not None
    assert summary["cards"]["hosting"] == {"en": "Not confirmed", "ar": "غير مؤكد"}
    # the owner statement falls back to 'Residency under review'
    sign_in(client, "priya")
    st = client.get("/api/hosting/residency-statement").json()
    assert st["state"] == "under_review" and st["en"] == "Residency under review"
    assert _events(db, "RESIDENCY_INVENTORY_GENERATION_FAILED")


def test_key_service_unavailable_blocks_release_and_refuses_key_use(client, db):
    set_config(db, "hosting.demo_inventory_variant", "pass", changed_by="test")
    set_config(db, "hosting.key_service.simulate_unavailable", True, changed_by="test")
    db.commit()
    dec = service.run_release_check(db, actor_key="test")
    assert dec.result == "blocked" and any(r["code"] == "KEY_SERVICE_UNAVAILABLE" for r in dec.reasons)
    with pytest.raises(Exception) as exc:
        service.key_use(db, "dek-db-1", purpose="read", actor_key="test")
    assert exc.value.reason_code == "KEY_SERVICE_UNAVAILABLE"
    assert _events(db, "KEY_USE_REFUSED")


def test_owner_statement_neutral_without_inventory_and_under_review_by_default(client, db):
    assert service.owner_residency_statement(db)["state"] == "under_review"
    for c in db.scalars(select(ResidencyComponent)):
        db.delete(c)
    for i in db.scalars(select(ResidencyInventory)):
        db.delete(i)
    db.commit()
    st = service.owner_residency_statement(db)
    assert st["state"] == "neutral" and st["en"].startswith("Our service is designed to keep your data in the UAE")
    sign_in(client, "sara")
    panel = client.get("/api/hosting/residency").json()
    assert panel["state"] == "no_inventory"
    assert panel["message"]["en"].startswith("No residency evidence yet.")
    assert panel["cards"]["hosting"] == {"en": "Not yet available", "ar": "غير متاح بعد"}


def test_residency_panel_access_matrix(client, db):
    sign_in(client, "layla")
    assert client.get("/api/hosting/residency").status_code == 403
    sign_in(client, "khalid")
    assert client.get("/api/hosting/residency").status_code == 403
    assert client.get("/api/hosting/residency-statement").status_code == 200
    sign_in(client, "noura")  # compliance reviewer: read-only
    assert client.get("/api/hosting/residency").status_code == 200
    assert client.get("/api/hosting/checklist").json()["note"].startswith("Working definition")
    assert client.post("/api/hosting/release-checks").status_code == 403


# --- egress -----------------------------------------------------------------------------------------


def test_egress_guard_blocks_non_allow_listed_host_logs_and_alerts(db):
    assert egress.guard("http://localhost:11434/api/generate", db) == "localhost"
    with pytest.raises(egress.EgressBlocked) as exc:
        egress.guard("https://telemetry.outside-host.net/collect", db, component_ref="local-model")
    assert exc.value.reason_code == "EGRESS_BLOCKED"
    ev = _events(db, "EGRESS_BLOCKED")
    assert ev and ev[-1].details["host"] == "telemetry.outside-host.net" and ev[-1].log_class == "security"
    alert = db.scalar(select(EgressBlockAlert))
    assert alert is not None and alert.status == "open" and alert.recipient_role == "qeonix_security_on_call"
    assert alert.ack_due_at <= alert.created_at + timedelta(hours=1)
    assert egress.escalate_overdue_alerts(db, now=utcnow() + timedelta(hours=2)) == 1
    assert _events(db, "EGRESS_ALERT_ESCALATED")


def test_egress_guard_without_session_and_det_admin_counts_only(client, db):
    with pytest.raises(egress.EgressBlocked):
        egress.guard("https://fonts.outside-host.net/css")
    sign_in(client, "adel")
    r = client.post("/api/hosting/egress/test", json={"url": "https://cdn.outside-host.net/x.js"})
    assert r.status_code == 403 and r.json()["error"] == "EGRESS_BLOCKED"
    sign_in(client, "sara")
    r = client.get("/api/hosting/egress/alerts").json()
    assert r["alerts"] is None and r["counts"]["total"] == 2


def test_two_person_allow_list_change(client, db):
    sign_in(client, "adel")
    c = client.post("/api/hosting/egress/changes", json={"hosts": ["Nebras.UAE-Hosted.ae"], "reason": "Open Finance hub"}).json()
    assert c["status"] == "pending" and c["proposed_list"] == ["nebras.uae-hosted.ae"]
    r = client.post(f"/api/hosting/egress/changes/{c['change_id']}/approve", json={"change_hash": c["change_hash"]})
    assert r.status_code == 403 and r.json()["error"] == "REQUESTER_IS_APPROVER"
    sign_in(client, "lina")  # Qeonix security owner slot
    r = client.post(f"/api/hosting/egress/changes/{c['change_id']}/approve", json={"change_hash": "deadbeef"})
    assert r.status_code == 422 and r.json()["error"] == "CHANGE_HASH_MISMATCH"
    r = client.post(f"/api/hosting/egress/changes/{c['change_id']}/approve", json={"change_hash": c["change_hash"], "fresh_auth": False})
    assert r.status_code == 403 and r.json()["error"] == "REAUTH_REQUIRED"
    r = client.post(f"/api/hosting/egress/changes/{c['change_id']}/approve", json={"change_hash": c["change_hash"]})
    assert r.status_code == 200 and r.json()["approver_1_key"] and r.json()["status"] == "pending"
    r = client.post(f"/api/hosting/egress/changes/{c['change_id']}/approve", json={"change_hash": c["change_hash"]})
    assert r.status_code == 403 and r.json()["error"] == "SAME_PERSON_BOTH_APPROVALS"
    sign_in(client, "sara")  # DET security approver
    r = client.post(f"/api/hosting/egress/changes/{c['change_id']}/approve", json={"change_hash": c["change_hash"]})
    assert r.status_code == 200 and r.json()["status"] == "applied"
    sign_in(client, "adel")
    state = client.get("/api/hosting/egress").json()
    assert "nebras.uae-hosted.ae" in state["allow_list"]
    assert egress.guard("https://nebras.uae-hosted.ae/api", db) == "nebras.uae-hosted.ae"
    assert _events(db, "EGRESS_ALLOW_LIST_CHANGED")


def test_allow_list_change_edit_clears_approvals_and_expires_after_five_working_days(db):
    c = egress.propose_allow_list_change(db, requester_key="req", hosts=["a.ae"], reason="x")
    egress.approve_allow_list_change(db, c.change_id, approver_key="sec", approver_role="qeonix_security_owner", change_hash_seen=c.change_hash)
    c2 = egress.propose_allow_list_change(db, requester_key="req", hosts=["a.ae", "b.ae"], reason="edit", supersedes=c.change_id)
    assert c.status == "superseded" and c2.approver_1_key is None
    assert c2.expires_at.weekday() < 5 and c2.expires_at > utcnow() + timedelta(days=4)
    c2.expires_at = utcnow() - timedelta(minutes=1)
    db.flush()
    assert egress.expire_pending_changes(db) == 1 and c2.status == "expired"
    assert _events(db, "EGRESS_CHANGE_EXPIRED")[-1].details["requester_notified"] is True
    with pytest.raises(Exception) as exc:
        egress.approve_allow_list_change(db, c2.change_id, approver_key="sec", approver_role="qeonix_security_owner", change_hash_seen=c2.change_hash)
    assert exc.value.reason_code == "CHANGE_NOT_PENDING"
    # withdrawal by the requester only
    c3 = egress.propose_allow_list_change(db, requester_key="req", hosts=["c.ae"], reason="y")
    with pytest.raises(Forbidden):
        egress.withdraw_allow_list_change(db, c3.change_id, requester_key="someone-else")
    assert egress.withdraw_allow_list_change(db, c3.change_id, requester_key="req").status == "withdrawn"


def test_nonprod_policy_disable_needs_two_people_and_lapses(db, monkeypatch):
    with pytest.raises(Exception) as exc:
        egress.set_policy_disabled_nonprod(db, approver_1_key="a", approver_2_key="a", reason="t")
    assert exc.value.reason_code == "SAME_PERSON_BOTH_APPROVALS"
    value = egress.set_policy_disabled_nonprod(db, approver_1_key="a", approver_2_key="b", reason="load test")
    assert egress.policy_enabled(db) is False
    set_config(db, egress.POLICY_ENABLED_KEY, {**value, "lapses_at": (utcnow() - timedelta(minutes=1)).isoformat()}, changed_by="t")
    assert egress.policy_enabled(db) is True
    monkeypatch.setattr(egress.get_settings(), "environment", "production")
    with pytest.raises(Exception) as exc:
        egress.set_policy_disabled_nonprod(db, approver_1_key="a", approver_2_key="b", reason="t")
    assert exc.value.reason_code == "EGRESS_DISABLE_NOT_ALLOWED"
    monkeypatch.setattr(egress.get_settings(), "environment", "test")


def test_dependency_check_passes_on_repo(tmp_path):
    path = Path(__file__).resolve().parents[1] / "scripts" / "dependency_check.py"
    spec = importlib.util.spec_from_file_location("dependency_check", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    out = mod.run()
    assert out["result"] == "pass", out["findings"]
    assert mod.host_internal("localhost") and not mod.host_internal("api.some-vendor.com")
    # a planted external reference is caught
    (tmp_path / "backend" / "app").mkdir(parents=True)
    (tmp_path / "backend" / "app" / "bad.py").write_text("import requests\nURL = 'https://api.some-vendor.com/v1'\n")
    mod.ROOT = tmp_path
    out = mod.run()
    assert out["result"] == "fail" and out["findings"][0]["kind"] == "external_endpoint"


# --- keys -------------------------------------------------------------------------------------------


def test_key_rotation_steps_audited_resume_and_compromise(client, db):
    sign_in(client, "adel")
    r = client.post("/api/hosting/keys/kek-1/rotate", json={"fail_at_step": "rewrap_started"})
    assert r.status_code == 409 and r.json()["error"] == "KEY_ROTATION_STEP_FAILED"
    keys = {k["key_id"]: k for k in client.get("/api/hosting/keys").json()}
    assert keys["kek-1"]["version"] == 1 and keys["kek-1"]["status"] == "rewrapping"
    assert keys["kek-1"]["rotation_state"]["last_audited_step"] == "new_version_created"
    r = client.post("/api/hosting/keys/kek-1/rotate", json={"resume": True})
    assert r.status_code == 200 and r.json()["version"] == 2 and r.json()["status"] == "active"
    steps = [e.details["step"] for e in _events(db, "KEY_ROTATION_STEP")]
    assert steps == ["new_version_created", "rewrap_started", "rewrap_completed", "old_version_retired"]
    assert _events(db, "KEY_ROTATION_RESUMED") and _events(db, "KEY_ROTATED")
    # rollback keeps the old version valid
    client.post("/api/hosting/keys/dek-db-1/rotate", json={"fail_at_step": "rewrap_completed"})
    r = client.post("/api/hosting/keys/dek-db-1/rollback")
    assert r.json()["version"] == 1 and r.json()["status"] == "active"
    # compromise declared by the security owner only
    r = client.post("/api/hosting/keys/tls-cert-portal-1/compromise")
    assert r.status_code == 200 and r.json()["rotation_completed_at"]
    ev = _events(db, "KEY_COMPROMISE_DECLARED")[-1]
    assert set(ev.details) >= {"who", "when", "key_id", "deadline_at"}
    assert datetime.fromisoformat(ev.details["deadline_at"]) - datetime.fromisoformat(ev.details["when"]) == timedelta(hours=24)
    sign_in(client, "lina")
    assert client.post("/api/hosting/keys/kek-1/compromise").status_code == 403


# --- K12 onboarding checklist ---------------------------------------------------------------------


def _company(db, cid: str, onboarding_at: datetime):
    db.add(Company(id=cid, trade_name_en=cid, trade_name_ar=cid, onboarding_at=onboarding_at, onboarding_id=f"onb_{cid}"))
    db.flush()
    service.ensure_cohort_row(db, cid, onboarding_at=onboarding_at, onboarding_id=f"onb_{cid}")
    return cid


def _links(db, cid, *, data_source="manual_upload", at=None):
    service.record_link_event(db, cid, "det_licence_record", "activated", "det", event_at=T0 + timedelta(hours=1))
    service.record_link_event(db, cid, "fta_profile_manual", "activated", "owner_entry", event_at=T0 + 2 * D)
    service.record_link_event(db, cid, data_source, "activated", data_source, event_at=at or T0 + 5 * D)


def test_k12_case_a_all_active_at_day_30_complete(db):
    cid = _company(db, "co_k12_a", T0)
    _links(db, cid)
    st = service.k12_status(db, cid, now=T0 + 31 * D)
    assert st["state"] == "complete" and st["complete_at_mark"] is True
    assert st["window_end"] == (T0 + 30 * D).isoformat()
    assert st["complete_via_manual_path_only"] is True
    assert [link["chip"]["en"] for link in st["links"]] == ["Linked", "Linked", "Linked"]


def test_k12_case_b_withdrawn_day_20_not_complete_achieved_then_lost(db):
    cid = _company(db, "co_k12_b", T0)
    _links(db, cid)
    service.record_link_event(db, cid, "manual_upload", "revoked", "manual_upload", event_at=T0 + 20 * D)
    st = service.k12_status(db, cid, now=T0 + 31 * D)
    assert st["state"] == "expired_missing" and st["achieved_then_lost"] is True
    assert st["message"]["en"].startswith("Your 30-day setup window ended on 31 January 2026. These links are still missing: Bank feed, ledger connection or manual upload.")
    assert st["based_on_incomplete_data"] is True and st["buttons"] == [{"en": "Link now", "ar": "اربط الآن"}]


def test_k12_case_c_withdrawn_but_ledger_active_complete(db):
    cid = _company(db, "co_k12_c", T0)
    _links(db, cid)
    service.record_link_event(db, cid, "manual_upload", "revoked", "manual_upload", event_at=T0 + 20 * D)
    service.record_link_event(db, cid, "ledger_connection", "activated", "ledger", event_at=T0 + 21 * D)
    assert service.k12_status(db, cid, now=T0 + 31 * D)["state"] == "complete"


def test_k12_case_d_2359_day_30_complete_but_plus_one_minute_not(db):
    a = _company(db, "co_k12_d1", T0)
    _links(db, a, at=T0 + 30 * D - timedelta(minutes=1))
    assert service.k12_status(db, a, now=T0 + 31 * D)["state"] == "complete"
    b = _company(db, "co_k12_d2", T0)
    _links(db, b, at=T0 + 30 * D)
    st = service.k12_status(db, b, now=T0 + 31 * D)
    assert st["complete_at_mark"] is False and st["state"] == "completed_after_window" and st["completed_after_window_days"] == 30


def test_k12_case_e_renewal_same_row_and_f_restart_same_row(db):
    cid = _company(db, "co_k12_ef", T0)
    row = service.record_renewal(db, cid)
    assert row.onboarding_id == "onb_co_k12_ef" and row.onboarding_at == T0
    row = service.record_restart(db, cid, at=T0 + 3 * D)
    assert row.restart_count == 1 and row.onboarding_id == "onb_co_k12_ef" and row.onboarding_at == T0
    assert service.k12_status(db, cid, now=T0 + 4 * D)["restart_count"] == 1


def test_k12_case_g_opt_out_day_12_excluded_as_exited(db):
    cid = _company(db, "co_k12_g", T0)
    service.record_exit(db, cid, reason="opted_out", at=T0 + 12 * D)
    st = service.k12_status(db, cid, now=T0 + 31 * D)
    assert st["state"] == "exited" and st["det_label"]["en"] == "Exited before day 30"
    agg = service.k12_aggregate(db, now=T0 + 31 * D)
    assert agg["states"].get("exited", 0) >= 1


def test_k12_case_h_resubscribe_new_row_earlier_closed(db):
    cid = _company(db, "co_k12_h", T0)
    _links(db, cid)
    new = service.record_resubscribe(db, cid, new_onboarding_id="onb_co_k12_h_2", at=T0 + 60 * D)
    old = db.get(type(new), "onb_co_k12_h")
    assert old.status == "closed" and new.onboarding_at == T0 + 60 * D
    st = service.k12_status(db, cid, now=T0 + 61 * D)
    assert st["onboarding_id"] == "onb_co_k12_h_2" and st["state"] == "window_open"
    assert [link["status"] for link in st["links"]] == ["missing", "missing", "missing"]


def test_k12_case_i_revoked_then_reactivated_complete_if_active_at_mark(db):
    cid = _company(db, "co_k12_i", T0)
    _links(db, cid)
    service.record_link_event(db, cid, "manual_upload", "revoked", "manual_upload", event_at=T0 + 10 * D)
    service.record_link_event(db, cid, "manual_upload", "reactivated", "manual_upload", event_at=T0 + 25 * D)
    assert service.k12_status(db, cid, now=T0 + 31 * D)["state"] == "complete"


def test_k12_case_j_twenty_days_ago_window_open(db):
    cid = _company(db, "co_k12_j", T0)
    st = service.k12_status(db, cid, now=T0 + 20 * D)
    assert st["state"] == "window_open" and st["days_left"] == 10 and st["det_label"]["en"] == "Window still open"


def test_k12_demo_fixtures_and_api_states(client, db):
    assert service.k12_status(db, CO_ALNOOR)["state"] == "complete"
    assert service.k12_status(db, CO_SAFWA)["state"] == "expired_missing"
    gt = service.k12_status(db, CO_GULFTECH)
    assert gt["state"] == "not_started" and gt["message"]["en"].startswith("Your setup window starts once your licence service is activated.")
    assert gt["links"][0]["chip"] == {"en": "Not started", "ar": "لم يبدأ"} and gt["links"][0]["action_enabled"] is False
    sign_in(client, "priya")
    bd = client.get(f"/api/companies/{CO_BLUEDUNE}/k12").json()
    assert bd["state"] == "window_open" and bd["viewer_role"] == "owner"
    data_link = bd["links"][2]
    assert data_link["status"] == "pending" and data_link["chip"]["en"] == "Pending"
    assert data_link["pending_message"]["en"].startswith("Waiting for your bank to confirm.")
    assert bd["buttons"] == [{"en": "Link now", "ar": "اربط الآن"}]
    sign_in(client, "omar")
    bd = client.get(f"/api/companies/{CO_BLUEDUNE}/k12").json()
    assert bd["viewer_role"] == "delegate" and bd["buttons"] == [{"en": "Ask the owner", "ar": "اطلب من المالك"}]
    assert client.get(f"/api/companies/{CO_SAFWA}/k12").status_code == 403
    sign_in(client, "sara")
    agg = client.get("/api/hosting/k12/aggregate").json()
    assert agg["labels"]["window_not_started"]["en"] == "Window not started"
    assert agg["states"]["not_started"] == 1 and agg["states"]["expired_missing"] == 1 and agg["link_sources"]["manual_upload"] >= 1
    assert client.get(f"/api/companies/{CO_ALNOOR}/k12").status_code == 403  # DET admin never sees company-level data


def test_k12_invalid_vocabulary_refused(db):
    with pytest.raises(Exception) as exc:
        service.record_link_event(db, CO_ALNOOR, "bank_scrape", "activated")
    assert exc.value.reason_code == "LINK_TYPE_INVALID"
