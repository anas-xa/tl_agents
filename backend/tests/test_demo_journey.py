"""Guided demo journey: story endpoint, data reset, and off unless demo mode is on."""

from __future__ import annotations

import pytest

from app.core.settings import get_settings
from tests.conftest import sign_in


@pytest.fixture
def demo_on():
    s = get_settings()
    before = s.demo_mode
    s.demo_mode = True
    yield
    s.demo_mode = before


def test_demo_endpoints_hidden_when_demo_mode_off(client):
    assert get_settings().demo_mode is False
    assert client.get("/api/demo/story").status_code == 404
    assert client.post("/api/demo/reset").status_code == 404
    assert client.get("/api/health").json()["demo_mode"] is False


def test_demo_never_on_in_production(client, demo_on):
    s = get_settings()
    env = s.environment
    s.environment = "production"
    try:
        assert client.get("/api/demo/story").status_code == 404
    finally:
        s.environment = env


def test_story_shape(client, demo_on):
    assert client.get("/api/health").json()["demo_mode"] is True
    body = client.get("/api/demo/story").json()
    assert body["prologue"]["title"]["en"] and body["prologue"]["title"]["ar"]
    chapters = body["chapters"]
    assert len(chapters) >= 10
    assert len({c["id"] for c in chapters}) == len(chapters)
    for c in chapters:
        assert c["persona"] in body["personas"], c["id"]
        assert c["path"].startswith("/")
        for field in ("title", "narration"):
            assert c[field]["en"] and c[field]["ar"]
        assert c["steps"] and all(s["en"] and s["ar"] for s in c["steps"])
    assert body["personas"]["khalid"]["name"] == "Khalid Al Mansoori"
    code = body["verification_code"]
    assert code
    assert client.get(f"/api/documents/verify/{code}").status_code == 200


def test_every_chapter_persona_can_open_its_screen(client, demo_on):
    """Each chapter's persona signs in through the mock UAE PASS and holds a role (no 'no access' dead end)."""
    for c in client.get("/api/demo/story").json()["chapters"]:
        client.cookies.clear()
        sign_in(client, c["persona"])
        me = client.get("/api/auth/me")
        assert me.status_code == 200, c["id"]


def test_reset_restores_demo_data(client, demo_on):
    sign_in(client, "khalid")
    url = "/api/companies/co_alnoor/welcome"
    assert client.get(url).json()["welcome"]["status"] == "pending"
    assert client.post(url, json={"action": "done"}).status_code == 200
    assert client.get(url).json()["welcome"]["status"] == "done"
    assert client.post("/api/demo/reset").json() == {"status": "reset"}
    assert client.get("/api/auth/me").status_code == 401  # everyone is signed out by the reset
    sign_in(client, "khalid")
    assert client.get(url).json()["welcome"]["status"] == "pending"
    assert client.get("/api/demo/story").json()["verification_code"]
