"""E3-S1 SC3 dashboard aggregate and E3-S5 remote-owner view."""

from __future__ import annotations

import importlib.util
from datetime import timedelta

from conftest import sign_in

from app.core.time import utcnow
from app.demo import CO_ALNOOR, CO_BLUEDUNE, CO_GULFTECH, CO_SAFWA, PERSONA_UUIDS
from app.modules.audit.models import AuditEvent
from app.modules.config.service import set_config
from app.modules.dashboard import service as ds

PANELS = ["tax_status", "audit_status", "deadlines", "documents", "compliance"]


def _panel(body: dict, name: str) -> dict:
    return next(p for p in body["panels"] if p["panel"] == name)


def test_owner_dashboard_five_panels_with_source_and_freshness(client):
    sign_in(client, "khalid")
    r = client.get(f"/api/companies/{CO_ALNOOR}/dashboard")
    assert r.status_code == 200, r.text
    body = r.json()
    assert [p["panel"] for p in body["panels"]] == PANELS and body["panel_order"] == PANELS
    for p in body["panels"]:
        assert p["freshness_state"] in ("fresh", "last_known", "cannot_be_confirmed", "not_available", "could_not_be_loaded", "not_linked_yet")
        if p["freshness_state"] not in ("not_available", "could_not_be_loaded"):
            assert p["source"] and p["last_updated"]
    assert body["acting_as"]["label"]["en"] == "Acting as: Owner" and body["view"] == "owner"
    dl = _panel(body, "deadlines")["data"]
    types = {i["obligation_type"] for i in dl["items"]}
    assert {"vat_return", "licence_renewal", "ejari_renewal"} <= types
    assert body["k10_tile"]["en"] == "Not yet measured"
    ai_steps = [s for s in body["next_steps"] if s["ai_prepared"]]
    assert ai_steps and all(s.get("status_label") for s in ai_steps)
    comp = _panel(body, "compliance")
    assert comp["freshness_state"] in ("fresh", "last_known") and comp["source"] == "DET"
    tax = _panel(body, "tax_status")["data"]
    assert tax["lines"] and all(line["unconfirmed"] for line in tax["lines"]) and tax["sbr"]["kind"] == "may_apply"
    assert "may apply" in tax["sbr"]["text"]["en"] and "eligible" not in str(tax).lower()


def test_freshness_states_per_panel_never_merged(db):
    from app.modules.licences.models import Licence

    now = utcnow()
    assert ds.freshness_for(db, "licence_subscription", now - timedelta(minutes=5), now)["state"] == "fresh"
    assert ds.freshness_for(db, "licence_subscription", now - timedelta(hours=3), now)["state"] == "last_known"
    assert ds.freshness_for(db, "licence_subscription", now - timedelta(hours=40), now)["state"] == "cannot_be_confirmed"
    assert ds.freshness_for(db, "ejari", now - timedelta(days=8), now)["state"] == "cannot_be_confirmed"
    lic = db.query(Licence).filter_by(company_id=CO_ALNOOR).one()
    lic.last_det_refresh_at = now - timedelta(hours=40)
    db.flush()

    class P:  # minimal owner principal
        identity_uuid = PERSONA_UUIDS["khalid"]
        actor_key = "k"
        display_name = "Khalid"
        session_id = "s"

        def roles_for(self, cid):
            from app.modules.companies.models import CompanyRole

            return db.query(CompanyRole).filter_by(company_id=cid, identity_uuid=PERSONA_UUIDS["khalid"]).all()

        def primary_role(self):
            return "owner"

    p = ds.load_panel(db, P(), CO_ALNOOR, "compliance")
    assert p["freshness_state"] == "cannot_be_confirmed" and p["stale_flag"] and p["last_good_time"]
    d = ds.load_panel(db, P(), CO_ALNOOR, "deadlines")
    assert d["freshness_state"] == "fresh"  # each panel carries its own state


def test_source_timeout_no_cache_then_cache(client, db):
    sign_in(client, "khalid")
    set_config(db, "dashboard.simulate_timeout_panels", ["tax_status"], changed_by="test")
    db.commit()
    body = client.get(f"/api/companies/{CO_SAFWA}/dashboard").json()
    tax = _panel(body, "tax_status")
    assert tax["freshness_state"] == "not_available" and tax["reason_code"] == "SOURCE_TIMEOUT_NO_CACHE" and tax["retry"]
    assert _panel(body, "deadlines")["freshness_state"] in ("fresh", "last_known")  # a slow source never blocks others
    db.expire_all()
    assert db.query(AuditEvent).filter_by(event_type="SOURCE_TIMEOUT_NO_CACHE", company_id=CO_SAFWA).count() == 1
    set_config(db, "dashboard.simulate_timeout_panels", [], changed_by="test")
    db.commit()
    client.get(f"/api/companies/{CO_SAFWA}/dashboard")  # fills the cache
    set_config(db, "dashboard.simulate_timeout_panels", ["tax_status"], changed_by="test")
    db.commit()
    tax2 = _panel(client.get(f"/api/companies/{CO_SAFWA}/dashboard").json(), "tax_status")
    assert tax2["freshness_state"] == "last_known" and tax2["from_cache"] and tax2["data"]


def test_panel_failure_is_isolated(client, monkeypatch):
    sign_in(client, "khalid")

    def boom(*a, **k):
        raise RuntimeError("documents store down")

    monkeypatch.setitem(ds.BUILDERS, "documents", boom)
    body = client.get(f"/api/companies/{CO_ALNOOR}/dashboard").json()
    assert _panel(body, "documents")["freshness_state"] == "could_not_be_loaded"
    assert _panel(body, "deadlines")["freshness_state"] != "could_not_be_loaded"


def test_delegate_locked_placeholders_and_request_access(client):
    sign_in(client, "omar")
    body = client.get(f"/api/companies/{CO_ALNOOR}/dashboard").json()
    assert [p["panel"] for p in body["panels"]] == PANELS  # same order, placeholders in place
    comp = _panel(body, "compliance")
    assert comp["freshness_state"] == "not_shared" and comp["message"]["en"] == "Not shared with you. Ask the owner."
    assert "data" not in comp and "last_updated" not in comp  # no status, counts or dates
    assert body["acting_as"]["role"] == "delegate" and body["acting_as"]["label"]["en"].startswith("Acting as: Delegate for")
    dl = _panel(body, "deadlines")["data"]
    assert dl["withheld_count"] > 0 and dl["withheld_note"]["en"] == "Some obligations are not shared with you."
    assert {i["obligation_type"] for i in dl["items"]} <= {"vat_return", "ct_return"}
    r1 = client.post(f"/api/companies/{CO_ALNOOR}/dashboard/request-access", json={"panel": "compliance"}).json()
    r2 = client.post(f"/api/companies/{CO_ALNOOR}/dashboard/request-access", json={"panel": "compliance"}).json()
    assert r1["state"] == "sent" and r1["sent_at"] == r2["sent_at"]
    again = _panel(client.get(f"/api/companies/{CO_ALNOOR}/dashboard").json(), "compliance")
    assert again["request_access"]["state"] == "sent"


def test_owner_switches_panel_off_per_delegate(client, db):
    from app.modules.companies.models import CompanyRole

    role = db.query(CompanyRole).filter_by(company_id=CO_ALNOOR, identity_uuid=PERSONA_UUIDS["omar"]).one()
    sign_in(client, "khalid")
    r = client.put(f"/api/companies/{CO_ALNOOR}/dashboard/delegate-panels", json={"role_id": role.id, "panel": "tax_status", "visible": False})
    assert r.status_code == 200, r.text
    client.cookies.clear()
    sign_in(client, "omar")
    assert _panel(client.get(f"/api/companies/{CO_ALNOOR}/dashboard").json(), "tax_status")["freshness_state"] == "not_shared"


def test_company_isolation_and_det_admin_denied(client):
    sign_in(client, "khalid")
    assert client.get(f"/api/companies/{CO_BLUEDUNE}/dashboard").status_code == 403
    client.cookies.clear()
    sign_in(client, "omar")
    assert client.get(f"/api/companies/{CO_SAFWA}/dashboard").status_code == 403
    client.cookies.clear()
    sign_in(client, "sara")
    r = client.get(f"/api/companies/{CO_ALNOOR}/dashboard")
    assert r.status_code == 403 and "panels" not in r.json()


def test_audit_panel_not_yet_assessed_until_audit_agent(client):
    sign_in(client, "khalid")
    audit = _panel(client.get(f"/api/companies/{CO_ALNOOR}/dashboard").json(), "audit_status")
    if importlib.util.find_spec("app.modules.auditagent") is None:
        assert audit["data"]["state"] == "not_yet_assessed" and audit["data"]["state_label"]["en"] == "Not yet assessed"
    assert audit["data"]["note"]["en"] == "Indicator only, not a legal determination. Audit is not required for every licence."
    assert "sign_off" not in str(audit["data"]) or audit["data"].get("sign_off") is None


def test_safwa_banner_and_alerts(client):
    sign_in(client, "khalid")
    body = client.get(f"/api/companies/{CO_SAFWA}/dashboard").json()
    assert body["licence_banner"]["kind"] == "licence_expired" and "Renewal is done with DET" in body["licence_banner"]["text"]["en"]
    assert any(a["kind"] == "ejari_lapsed" for a in body["alerts"])
    tax = _panel(body, "tax_status")["data"]
    assert tax["sbr"]["kind"] == "not_available" and "based on declared data" in tax["sbr"]["text"]["en"]


def test_remote_owner_view_and_codes(client, db):
    sign_in(client, "priya")
    body = client.get(f"/api/companies/{CO_BLUEDUNE}/dashboard").json()
    assert body["view"] == "remote_owner" and body["acting_as"]["owner_abroad"] is True
    remote = body["remote"]
    assert {c["state"] for c in remote["approval_cards"]} == {"waiting", "approved", "declined", "expired"}
    assert all(c["is_demo"] for c in remote["approval_cards"]) and remote["allowed_areas"] == ["dashboard", "reminders", "deadlines"]
    assert remote["generic_denial"]["en"].startswith("We could not sign you in to this service.")
    r = client.post(f"/api/companies/{CO_BLUEDUNE}/remote-agent/prepare_return")
    assert r.status_code == 403 and r.json()["error"] == "FEATURE_DISABLED"
    db.expire_all()
    ev = db.query(AuditEvent).filter_by(event_type="FEATURE_SWITCH_DENIAL").one()
    assert set(ev.details) == {"request_id", "endpoint", "switch", "switch_state", "result", "country_code"}
    assert client.post(f"/api/companies/{CO_BLUEDUNE}/dashboard/approval-cards/demo-card-waiting/approve").status_code == 200
    r = client.post(f"/api/companies/{CO_BLUEDUNE}/dashboard/approval-cards/demo-card-expired/approve")
    assert r.status_code == 409 and r.json()["error"] == "REQUEST_EXPIRED"
    from app.modules.identity.models import UserSession

    sess = db.query(UserSession).filter_by(session_id=client.cookies.get("qx_session")).one()
    sess.created_at = utcnow() - timedelta(minutes=20)
    sess.step_up_at = None
    db.commit()
    r = client.post(f"/api/companies/{CO_BLUEDUNE}/dashboard/approval-cards/demo-card-waiting/approve")
    assert r.status_code == 401 and r.json()["error"] == "REAUTH_REQUIRED"
    client.cookies.clear()
    sign_in(client, "omar")
    r = client.post(f"/api/companies/{CO_BLUEDUNE}/dashboard/approval-cards/demo-card-waiting/approve")
    assert r.status_code == 403 and r.json()["error"] == "APPROVAL_NOT_PERMITTED"


def test_remembered_company_revalidated(client, db):
    sign_in(client, "omar")
    client.get(f"/api/companies/{CO_GULFTECH}/dashboard")
    assert client.get("/api/me/remembered-company").json() == {"state": "remembered", "company_id": CO_GULFTECH, "note": None}
    from app.modules.companies.models import CompanyRole

    db.query(CompanyRole).filter_by(company_id=CO_GULFTECH, identity_uuid=PERSONA_UUIDS["omar"]).one().status = "revoked"
    db.commit()
    client.cookies.clear()
    sign_in(client, "omar")
    out = client.get("/api/me/remembered-company").json()
    assert out["state"] == "chooser" and out["note"]["en"].startswith("The company you used last time is no longer available")
    db.expire_all()
    assert db.query(AuditEvent).filter_by(event_type="REMEMBERED_COMPANY_DELETED").count() == 1
    client.cookies.clear()
    sign_in(client, "priya")
    assert client.get("/api/me/remembered-company").json()["state"] == "single"


def test_portfolio_sorted_by_nearest_deadline(client):
    sign_in(client, "omar")
    rows = client.get("/api/me/portfolio").json()["companies"]
    assert {r["company_id"] for r in rows} == {CO_ALNOOR, CO_BLUEDUNE, CO_GULFTECH}
    nearest = [r["nearest_days_left"] if r["nearest_days_left"] is not None else 10**6 for r in rows]
    assert nearest == sorted(nearest)
    assert all(r["access_limits"] for r in rows) and all(not r["can_approve"] for r in rows)
