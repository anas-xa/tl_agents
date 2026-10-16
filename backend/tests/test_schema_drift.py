"""An existing database from an older version: demo databases are rebuilt, any other stops with a clear error."""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine, text

from app.core.db import ensure_current_schema, schema_drift


def _old_database(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'old.db'}")
    with engine.begin() as conn:  # audit_events as it was before the commit-time sealing column existed
        conn.execute(text("CREATE TABLE audit_events (id VARCHAR(40) PRIMARY KEY, event_type VARCHAR(80))"))
        conn.execute(text("INSERT INTO audit_events (id, event_type) VALUES ('ev_old', 'SIGN_IN')"))
    return engine


def test_current_database_has_no_drift(db):
    assert schema_drift(db.get_bind()) == []


def test_outdated_database_is_reported(tmp_path):
    engine = _old_database(tmp_path)
    drift = schema_drift(engine)
    assert "audit_events.seq" in drift
    assert "audit_events.id" not in drift


def test_outdated_non_demo_database_is_never_touched(tmp_path):
    engine = _old_database(tmp_path)
    with pytest.raises(RuntimeError, match="older version"):
        ensure_current_schema(rebuild_if_outdated=False, bind=engine)
    with engine.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM audit_events")).scalar() == 1


def test_outdated_demo_database_is_rebuilt(tmp_path):
    engine = _old_database(tmp_path)
    drift = ensure_current_schema(rebuild_if_outdated=True, bind=engine)
    assert "audit_events.seq" in drift
    assert schema_drift(engine) == []
    with engine.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM audit_events")).scalar() == 0
