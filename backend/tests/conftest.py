from __future__ import annotations

import os
import shutil
import tempfile
from collections.abc import Iterator

import pytest

_tmp = tempfile.mkdtemp(prefix="qeonix-test-")
os.environ.setdefault("QEONIX_DATABASE_URL", f"sqlite:///{_tmp}/test.db")
os.environ.setdefault("QEONIX_ENVIRONMENT", "test")
os.environ.setdefault("QEONIX_UPLOAD_DIR", f"{_tmp}/uploads")
os.environ.setdefault("QEONIX_SECRET_KEY", "test-secret")
os.environ.setdefault("QEONIX_UAEPASS_ISSUER", "http://testserver/mock-uaepass")
os.environ.setdefault("QEONIX_UAEPASS_REDIRECT_URI", "http://testserver/api/auth/callback")
os.environ.setdefault("QEONIX_FRONTEND_BASE_URL", "http://front.test")

from fastapi.testclient import TestClient  # noqa: E402

from app.core.db import Base, SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.seed import seed_reference_data  # noqa: E402


_DB_FILE = os.environ["QEONIX_DATABASE_URL"].removeprefix("sqlite:///")
_TEMPLATE = f"{_tmp}/template.db"


def _build_template() -> None:
    """Schema + reference seed + demo seed, built once per test session."""
    from app import models  # noqa: F401

    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        seed_reference_data(db)
        from app.demo import seed_demo

        seed_demo(db)
        db.commit()
    engine.dispose()
    shutil.copyfile(_DB_FILE, _TEMPLATE)


def _clear_process_caches() -> None:
    """In-memory caches are keyed on database state; a fresh database needs fresh caches."""
    from app.modules.consent import service as consent_service

    consent_service._GATE_CACHE.clear()


@pytest.fixture(autouse=True)
def fresh_db() -> Iterator[None]:
    """Every test starts from an identical copy of the seeded template database."""
    if not os.path.exists(_TEMPLATE):
        _build_template()
    engine.dispose()
    shutil.copyfile(_TEMPLATE, _DB_FILE)
    _clear_process_caches()
    yield
    engine.dispose()


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(app, follow_redirects=False) as c:
        yield c


@pytest.fixture
def db() -> Iterator:
    with SessionLocal() as session:
        yield session


def sign_in(client: TestClient, persona: str, language: str = "en", variant: str | None = None, invite: str | None = None) -> dict:
    """Drive the full OIDC flow against the mock provider and return the callback outcome."""
    params = {"language": language}
    if invite:
        params["invite"] = invite
    start = client.post("/api/auth/start", params=params).json()
    from urllib.parse import parse_qs, urlparse

    q = parse_qs(urlparse(start["redirect_url"]).query)
    auth_params = {"state": q["state"][0], "nonce": q["nonce"][0], "redirect_uri": q["redirect_uri"][0], "code_challenge": q["code_challenge"][0], "persona": persona}
    if variant:
        auth_params["variant"] = variant
    r = client.get("/mock-uaepass/authorize", params=auth_params)
    assert r.status_code == 302, r.text
    location = r.headers["location"]
    cb = client.get(location.replace("http://testserver", ""))
    assert cb.status_code == 302, cb.text
    target = cb.headers["location"]
    out = {"target": target, "query": parse_qs(urlparse(target).query), "ok": "/auth/complete" in target}
    if out["ok"]:
        out["session"] = client.cookies.get("qx_session")
    return out


@pytest.fixture
def signed_in():
    def _do(client: TestClient, persona: str, **kw) -> dict:
        res = sign_in(client, persona, **kw)
        assert res["ok"], res
        return res

    return _do
