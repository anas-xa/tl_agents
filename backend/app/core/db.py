"""Database session management (SQLAlchemy 2.0, sync)."""

from __future__ import annotations

from collections.abc import Generator

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.settings import get_settings


class Base(DeclarativeBase):
    pass


def _make_engine(url: str):
    kwargs: dict = {"future": True}
    if url.startswith("sqlite:///"):
        # A fresh checkout has no data folder (it is git-ignored): create it so the first start works.
        from pathlib import Path

        Path(url.removeprefix("sqlite:///")).parent.mkdir(parents=True, exist_ok=True)
    if url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
    engine = create_engine(url, **kwargs)
    if url.startswith("sqlite"):

        @event.listens_for(engine, "connect")
        def _fk_on(dbapi_connection, _record):  # pragma: no cover - driver hook
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    return engine


engine = _make_engine(get_settings().database_url)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, class_=Session)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    """Create all tables. Models must be imported before this is called (see app.models)."""
    from app import models  # noqa: F401  (registers all ORM models)

    Base.metadata.create_all(bind=engine)


def schema_drift(bind=None) -> list[str]:
    """Columns the models define but the database lacks (create_all adds missing tables, never columns).

    An existing database from an older version would otherwise fail on the first write to a changed table.
    """
    from sqlalchemy import inspect

    from app import models  # noqa: F401

    insp = inspect(bind or engine)
    existing_tables = set(insp.get_table_names())
    missing: list[str] = []
    for table in Base.metadata.sorted_tables:
        if table.name not in existing_tables:
            missing.append(table.name)
            continue
        have = {c["name"] for c in insp.get_columns(table.name)}
        missing.extend(f"{table.name}.{c.name}" for c in table.columns if c.name not in have)
    return missing


def ensure_current_schema(*, rebuild_if_outdated: bool, bind=None) -> list[str]:
    """Create missing tables; if columns are missing, rebuild (demo data only) or stop with a clear message.

    Returns the drift that was found (empty when the schema was already current).
    """
    import logging

    from app import models  # noqa: F401

    bind = bind or engine
    Base.metadata.create_all(bind=bind)
    drift = schema_drift(bind)
    if not drift:
        return []
    shown = ", ".join(drift[:8]) + (" ..." if len(drift) > 8 else "")
    if not rebuild_if_outdated:
        raise RuntimeError(
            f"The database was created by an older version and is missing: {shown}. "
            "Migrate it, or for a demo database delete it and start again."
        )
    logging.getLogger("qeonix").warning("Database is from an older version (missing %s); rebuilding it with fresh demo data.", shown)
    Base.metadata.drop_all(bind=bind)
    Base.metadata.create_all(bind=bind)
    return drift
