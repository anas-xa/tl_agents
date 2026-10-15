"""Outbox dispatch for committed licence events.

The licence-event handler (``service.intake_event``) only writes a queue row. Downstream modules (E2-S2
subscriptions) register a consumer here and are run *after* the event is committed and acknowledged, in a
separate unit of work. The handler itself never imports or calls subscription or billing code (contract test
in ``tests/test_subscriptions.py``).
"""

from __future__ import annotations

from collections.abc import Callable

from sqlalchemy.orm import Session

OUTBOX_CONSUMERS: list[Callable[[Session], int]] = []


def register_consumer(fn: Callable[[Session], int]) -> Callable[[Session], int]:
    if fn not in OUTBOX_CONSUMERS:
        OUTBOX_CONSUMERS.append(fn)
    return fn


def dispatch(db: Session) -> int:
    """Run every registered consumer once; each consumer handles its own retries and dead-lettering."""
    n = 0
    for fn in list(OUTBOX_CONSUMERS):
        n += int(fn(db) or 0)
    db.commit()
    return n


def dispatch_in_new_session() -> int:
    """Background-task entry point: runs after the intake response was sent (asynchronous after commit)."""
    from app.core.db import SessionLocal

    with SessionLocal() as db:
        return dispatch(db)
