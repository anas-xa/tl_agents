from __future__ import annotations

from sqlalchemy import select

from app.modules.audit.models import AuditEvent
from app.modules.audit.service import verify_chain
from tests.conftest import sign_in


def _events(db, reason=None):
    stmt = select(AuditEvent).where(AuditEvent.event_type == "SIGN_IN")
    if reason:
        stmt = stmt.where(AuditEvent.reason_code == reason)
    return list(db.scalars(stmt))


def test_owner_signs_in_and_sees_only_own_companies(client, db):
    res = sign_in(client, "khalid", language="ar")
    assert res["ok"], res
    me = client.get("/api/auth/me").json()
    assert me["display_name"] == "Khalid Al Mansoori"
    assert me["det_match_result"] == "matched"
    assert sorted(c["company_id"] for c in me["companies"]) == ["co_alnoor", "co_safwa"]
    assert all("owner" in c["roles"] for c in me["companies"])
    assert me["language"] == "ar"
    ev = _events(db)
    assert ev and ev[-1].outcome == "success" and ev[-1].language == "ar"
    assert ev[-1].details["assurance_level"] == "SOP3"
    assert ev[-1].config_version.startswith("identity.min_assurance_level@v")
    assert ev[-1].ip_truncated is None or ev[-1].ip_truncated.endswith("/24")


def test_no_company_role_gets_session_without_data(client, db):
    res = sign_in(client, "noroles")
    assert res["ok"] and res["query"].get("no_company") == ["1"]
    me = client.get("/api/auth/me").json()
    assert me["companies"] == [] and me["staff_roles"] == []
    assert _events(db, "NO_COMPANY_ROLE")


def test_sop1_refused_level_too_low(client, db):
    res = sign_in(client, "sop1")
    assert not res["ok"]
    assert res["query"]["reason"] == ["LEVEL_TOO_LOW"] and res["query"]["ref"][0]
    assert client.cookies.get("qx_session") is None
    assert _events(db, "LEVEL_TOO_LOW")


def test_remote_owner_visitor_profile_uses_same_flow(client):
    res = sign_in(client, "priya")
    assert res["ok"]
    me = client.get("/api/auth/me").json()
    assert me["profile_type"] == 2 and me["companies"][0]["roles"] == ["remote_owner"]


def test_owner_without_emirates_id_gets_no_owner_role(client, db):
    res = sign_in(client, "noeid")
    assert res["ok"] and res["query"].get("no_company") == ["1"]
    me = client.get("/api/auth/me").json()
    assert me["companies"] == []
    assert _events(db, "DET_MATCH_FAIL")


def test_delegate_roles_scoped_per_company(client):
    sign_in(client, "omar")
    me = client.get("/api/auth/me").json()
    by_id = {c["company_id"]: c for c in me["companies"]}
    assert set(by_id) == {"co_alnoor", "co_bluedune", "co_gulftech"}
    assert by_id["co_alnoor"]["roles"] == ["delegate"]
    assert "returns.approve" not in by_id["co_alnoor"]["permissions"]
    assert "tax.prepare" in by_id["co_alnoor"]["permissions"]


def test_invalid_expired_and_reused_state(client, db):
    cb = client.get("/api/auth/callback", params={"state": "unknown", "code": "x"})
    assert cb.status_code == 302 and "reason=STATE_INVALID" in cb.headers["location"]
    res = sign_in(client, "khalid")
    assert res["ok"]
    # replay the same callback: state already used
    from urllib.parse import parse_qs, urlparse

    start = client.post("/api/auth/start").json()
    q = parse_qs(urlparse(start["redirect_url"]).query)
    r = client.get("/mock-uaepass/authorize", params={"state": q["state"][0], "nonce": q["nonce"][0], "redirect_uri": q["redirect_uri"][0], "code_challenge": q["code_challenge"][0], "persona": "khalid"})
    loc = r.headers["location"].replace("http://testserver", "")
    client.get(loc)
    again = client.get(loc)
    assert "reason=STATE_INVALID" in again.headers["location"]
    assert _events(db, "STATE_INVALID")


def test_expired_pending_signin(client, db):
    from datetime import timedelta
    from urllib.parse import parse_qs, urlparse

    from app.modules.identity.models import PendingSignIn

    start = client.post("/api/auth/start").json()
    q = parse_qs(urlparse(start["redirect_url"]).query)
    import hashlib

    p = db.get(PendingSignIn, hashlib.sha256(q["state"][0].encode()).hexdigest())
    p.expires_at = p.expires_at - timedelta(minutes=30)
    db.commit()
    cb = client.get("/api/auth/callback", params={"state": q["state"][0], "code": "x"})
    assert "reason=STATE_EXPIRED" in cb.headers["location"]


def test_invalid_assertions_are_rejected(client, db):
    for variant in ("expired", "wrong_issuer", "wrong_audience", "bad_signature"):
        res = sign_in(client, "khalid", variant=variant)
        assert not res["ok"] and res["query"]["reason"] == ["ASSERTION_INVALID"], variant
    assert len(_events(db, "ASSERTION_INVALID")) == 4


def test_user_cancels_at_uaepass(client, db):
    from urllib.parse import parse_qs, urlparse

    start = client.post("/api/auth/start").json()
    q = parse_qs(urlparse(start["redirect_url"]).query)
    r = client.get("/mock-uaepass/authorize", params={"state": q["state"][0], "nonce": q["nonce"][0], "redirect_uri": q["redirect_uri"][0], "action": "cancel"})
    cb = client.get(r.headers["location"].replace("http://testserver", ""))
    assert "reason=CANCELLED" in cb.headers["location"]
    assert _events(db, "CANCELLED")


def test_cancel_on_interstitial_discards_state(client):
    start = client.post("/api/auth/start").json()
    assert client.post("/api/auth/cancel", params={"state": start["state"]}).json()["ok"]
    cb = client.get("/api/auth/callback", params={"state": start["state"], "code": "x"})
    assert "reason=STATE_INVALID" in cb.headers["location"]


def test_signout_and_session_timing(client):
    sign_in(client, "khalid")
    timing = client.post("/api/auth/keepalive").json()
    assert timing["idle_timeout_minutes"] == 15 and timing["warning_minutes"] == 2
    assert client.post("/api/auth/signout").json()["ok"]
    assert client.get("/api/auth/me").status_code == 401


def test_idle_timeout_ends_session(client, db):
    from datetime import timedelta

    from app.modules.identity.models import UserSession

    res = sign_in(client, "khalid")
    s = db.get(UserSession, res["session"])
    s.last_seen_at = s.last_seen_at - timedelta(minutes=20)
    db.commit()
    r = client.get("/api/auth/me")
    assert r.status_code == 401 and r.json()["error"] == "SESSION_ENDED"


def test_audit_chain_intact_after_signins(client, db):
    sign_in(client, "khalid")
    sign_in(client, "sop1")
    intact, n = verify_chain(db)
    assert intact and n >= 2


def test_failure_alert_after_repeated_refusals(client, db):
    from app.modules.identity.models import OperationalAlert

    for _ in range(5):
        sign_in(client, "sop1")
    assert db.scalar(select(OperationalAlert)) is not None


def test_staff_invitation_two_person_rule_and_binding(client, db):
    sign_in(client, "adel")
    bad = client.post("/api/admin/staff-roles", json={"role": "compliance_reviewer", "work_email": "new@example.ae", "approver": "uuid-adel-secadmin"})
    assert bad.status_code == 422 and bad.json()["error"] == "SECOND_APPROVER_REQUIRED"
    self_assign = client.post("/api/admin/staff-roles", json={"role": "compliance_reviewer", "work_email": "adel@example.ae", "approver": "someone-else"})
    assert self_assign.status_code == 403 and self_assign.json()["error"] == "SELF_ASSIGNMENT"
    ok = client.post("/api/admin/staff-roles", json={"role": "compliance_reviewer", "work_email": "tariq@example.ae", "approver": "lina", "reason": "pilot reviewer"})
    assert ok.status_code == 200, ok.text
    token = ok.json()["invitation_token"]
    client.post("/api/auth/signout")
    res = sign_in(client, "noroles", invite=token)
    assert res["ok"]
    me = client.get("/api/auth/me").json()
    assert me["staff_roles"] == ["compliance_reviewer"]
    assert "audit_trail.view" in me["staff_permissions"]


def test_det_admin_cannot_read_company_detail_in_audit_trail(client):
    sign_in(client, "sara")
    r = client.get("/api/admin/audit-trail")
    assert r.status_code == 200
    assert all("company_id" not in e and "details" not in e for e in r.json()["events"])
    sign_in(client, "noura")
    r = client.get("/api/admin/audit-trail")
    assert r.status_code == 200 and any("details" in e for e in r.json()["events"])


def test_config_change_needs_second_approver_and_is_versioned(client):
    sign_in(client, "adel")
    r = client.put("/api/admin/config/identity.min_assurance_level", json={"value": "SOP3", "change_reason": "test"})
    assert r.status_code == 422
    r = client.put("/api/admin/config/identity.min_assurance_level", json={"value": "SOP3", "change_reason": "test", "approved_by": "lina"})
    assert r.status_code == 200 and r.json()["version"] == 2
    hist = client.get("/api/admin/config/identity.min_assurance_level/history").json()
    assert [h["version"] for h in hist] == [1, 2]
    client.post("/api/auth/signout")
    res = sign_in(client, "priya")  # SOP2 now below the minimum
    assert not res["ok"] and res["query"]["reason"] == ["LEVEL_TOO_LOW"]


def test_refused_cross_company_request_is_kept_in_audit_trail(client, db):
    from app.modules.audit.models import AuditEvent

    sign_in(client, "priya")
    r = client.get("/api/companies/co_alnoor/dashboard")
    assert r.status_code == 403
    db.expire_all()
    refused = db.scalars(select(AuditEvent).where(AuditEvent.event_type == "ACCESS_REFUSED", AuditEvent.company_id == "co_alnoor")).all()
    assert refused and refused[-1].reason_code == "NOT_YOUR_COMPANY"


def test_explicit_language_choice_this_visit_overrides_profile(client, db):
    from app.modules.identity.models import Identity

    sign_in(client, "khalid", language="en")
    client.post("/api/auth/signout")
    # a plain sign-in in Arabic keeps the saved profile language
    sign_in(client, "khalid", language="ar")
    assert db.get(Identity, "uuid-khalid-owner").language == "en"
    client.post("/api/auth/signout")
    # an explicit choice on SC1 wins and is saved to the profile
    start = client.post("/api/auth/start", params={"language": "ar", "explicit_language": "true"}).json()
    from urllib.parse import parse_qs, urlparse

    q = parse_qs(urlparse(start["redirect_url"]).query)
    r = client.get("/mock-uaepass/authorize", params={"state": q["state"][0], "nonce": q["nonce"][0], "redirect_uri": q["redirect_uri"][0], "code_challenge": q["code_challenge"][0], "persona": "khalid"})
    client.get(r.headers["location"].replace("http://testserver", ""))
    db.expire_all()
    assert db.get(Identity, "uuid-khalid-owner").language == "ar"
    assert client.get("/api/auth/me").json()["language"] == "ar"


def test_one_port_mode_serves_portal_and_keeps_api(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from app.core.settings import get_settings
    from app.main import create_app

    (tmp_path / "assets").mkdir()
    (tmp_path / "index.html").write_text("<html>portal</html>")
    (tmp_path / "assets" / "app.js").write_text("console.log(1)")
    monkeypatch.setattr(get_settings(), "serve_frontend", True)
    monkeypatch.setattr(get_settings(), "static_dir", str(tmp_path))
    with TestClient(create_app()) as c:
        assert c.get("/").text == "<html>portal</html>"
        assert c.get("/deadlines").text == "<html>portal</html>"  # client-side route falls back to index
        assert c.get("/assets/app.js").text == "console.log(1)"
        assert c.get("/api/health").json()["status"] == "ok"
        assert c.get("/api/nope").status_code == 404
        assert c.get("/../../etc/passwd").text == "<html>portal</html>"  # no path traversal
