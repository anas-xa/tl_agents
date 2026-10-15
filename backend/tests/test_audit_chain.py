"""The audit trail stays one unbroken hash chain when many requests write at the same time."""

from concurrent.futures import ThreadPoolExecutor

from app.core.db import SessionLocal
from app.modules.audit.service import record_event, verify_chain
from tests.conftest import sign_in


def _write(i: int) -> None:
    with SessionLocal() as db:
        record_event(db, event_type="CONCURRENCY_PROBE", category="system", details={"i": i})
        record_event(db, event_type="CONCURRENCY_PROBE", category="system", details={"i": i, "second": True})
        db.commit()


def test_parallel_writers_never_fork_the_chain(db):
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(_write, range(40)))
    intact, n = verify_chain(db)
    assert intact and n >= 80


def test_rolled_back_events_never_enter_the_chain(db):
    with SessionLocal() as s:
        record_event(s, event_type="WILL_ROLL_BACK", category="system")
        s.rollback()
    with SessionLocal() as s:
        record_event(s, event_type="KEPT", category="system")
        s.commit()
    intact, _ = verify_chain(db)
    assert intact


def test_parallel_page_loads_keep_integrity(client, db):
    sign_in(client, "khalid")
    cookie = client.cookies.get("qx_session")
    from fastapi.testclient import TestClient

    from app.main import app

    def load(path: str) -> int:
        with TestClient(app) as c:
            c.cookies.set("qx_session", cookie)
            return c.get(path).status_code

    paths = [f"/api/companies/co_alnoor/{p}" for p in ("dashboard", "obligations", "consents", "links", "approvals", "audit", "documents", "transactions")] * 3
    with ThreadPoolExecutor(max_workers=8) as pool:
        codes = list(pool.map(load, paths))
    assert all(c < 500 for c in codes), codes
    intact, _ = verify_chain(db)
    assert intact
