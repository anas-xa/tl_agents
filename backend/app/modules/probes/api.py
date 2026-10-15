"""Probe endpoints (E1-S9): synthetic probe targets, admin probe view, DET availability (K26)."""

from __future__ import annotations

from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.api.deps import require_staff
from app.core.db import get_db
from app.core.time import utcnow
from app.modules.access.service import Principal
from app.modules.audit.service import record_event
from app.modules.probes import service
from app.modules.probes.models import PeakWindow, ProbeRecord

router = APIRouter(prefix="/api", tags=["probes"])


# --- synthetic targets: no company data, test identity only ------------------------------------------


@router.get("/probes/synthetic/sign_in")
def synthetic_sign_in(lang: str = "en", db: Session = Depends(get_db)):
    """Test-only sign-in path: exercises the sign-in start logic and rolls it back (never a real UAE PASS)."""
    from app.modules.identity.service import start_signin

    url, _state = start_signin(db, language="ar" if lang == "ar" else "en")
    db.rollback()
    return {"marker": service.CONTENT_MARKER, "check": "sign_in", "language": lang, "redirect_present": bool(url)}


@router.get("/probes/synthetic/dashboard")
def synthetic_dashboard(lang: str = "en"):
    return {"marker": service.CONTENT_MARKER, "check": "dashboard", "language": lang, "panels": ["licence", "subscription", "deadlines"], "company": "probe-test-company", "note": "synthetic test company, no real company data"}


@router.get("/probes/synthetic/documents")
def synthetic_documents(lang: str = "en"):
    return {"marker": service.CONTENT_MARKER, "check": "documents", "language": lang, "documents": [], "company": "probe-test-company"}


# --- admin / DET -------------------------------------------------------------------------------------


def _rec(r: ProbeRecord) -> dict:
    return {"probe_id": r.probe_id, "minute_ts": r.minute_ts.isoformat(), "minute_local": r.minute_local, "check_type": r.check_type, "result": r.result, "language": r.language, "latency_ms": r.latency_ms, "reason": r.reason, "runner": r.runner}


@router.get("/admin/probes")
def admin_probes(minutes: int = Query(120, ge=1, le=1440), principal: Principal = Depends(require_staff("probes.view")), db: Session = Depends(get_db)):
    now = utcnow()
    rows = list(db.scalars(select(ProbeRecord).where(ProbeRecord.minute_ts >= now - timedelta(minutes=minutes)).order_by(desc(ProbeRecord.minute_ts)).limit(minutes * 6)))
    return {
        "interval_seconds": 60, "timeout_seconds": 5, "synthetic_identity": service.SYNTHETIC_IDENTITY,
        "tile": service.operations_tile(db), "release_test": service.release_probe_test(db),
        "records": [_rec(r) for r in rows], "windows": [service.window_dict(w) for w in service.windows_effective(db)],
    }


@router.post("/admin/probes/run")
def admin_run(principal: Principal = Depends(require_staff("probes.view")), db: Session = Depends(get_db)):
    recs = service.run_probes(db)
    record_event(db, event_type="PROBE_RUN", category="system", actor_key=principal.actor_key, details={"minute_ts": recs[0].minute_ts.isoformat() if recs else None, "results": {f"{r.check_type}:{r.language}": r.result for r in recs}})
    db.commit()
    return [_rec(r) for r in recs]


@router.get("/det/availability")
def det_availability(period: str = "day", window_id: str | None = None, start: datetime | None = None, end: datetime | None = None, principal: Principal = Depends(require_staff("det.aggregates.view")), db: Session = Depends(get_db)):
    """K26 for the selected period: 'window' (window_id), 'day', 'week', 'month' or explicit start/end (UTC)."""
    now = utcnow()
    if period == "window" and window_id:
        w = db.get(PeakWindow, window_id)
        if w is None:
            from app.core.errors import NotFound

            raise NotFound("peak window not found")
        p_start, p_end = w.start_at, w.end_at
    elif start and end:
        p_start, p_end = start, end
    else:
        days = {"day": 1, "week": 7, "month": 30}.get(period, 1)
        p_start, p_end = service.floor_minute(now - timedelta(days=days)), service.floor_minute(now) + timedelta(minutes=1)
    k26 = service.compute_k26(db, p_start, p_end)
    data = {"period": period, "k26": k26, "tile": service.operations_tile(db), "timeline": service.timeline(db, p_start, p_end), "windows": [service.window_dict(w) for w in service.windows_effective(db)], "wording": {"title": "K26: portal availability during peak windows", "down": "Down: a probe failed in that minute", "no_data": "No data: the probe service was not running; this minute is not counted as up", "versions": "Peak windows follow the current rule and calendar reference (version shown)", "identity": "Probes use a test company with no real company data"}}
    record_event(db, event_type="DET_AVAILABILITY_VIEWED", category="data_access", actor_key=principal.actor_key, actor_role=principal.primary_role(), details={"period": period, "state": k26["state"]})
    db.commit()
    return data
