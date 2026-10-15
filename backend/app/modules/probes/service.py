"""Probe runner, minute availability, K26 computation, operations tile and the release probe test (E1-S9)."""

from __future__ import annotations

import time
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.core.ids import new_id
from app.core.time import DUBAI, to_dubai, utcnow
from app.modules.audit.service import record_event
from app.modules.config.service import get_config
from app.modules.probes.models import CHECK_TYPES, LANGUAGES, PeakWindow, ProbeRecord

SYNTHETIC_IDENTITY = "probe-synthetic"  # never a real UAE PASS identity; excluded from K1 and K29
CONTENT_MARKER = "qeonix-probe-ok"


def floor_minute(dt: datetime) -> datetime:
    return dt.replace(second=0, microsecond=0)


def local_str(dt: datetime) -> str:
    return to_dubai(dt).strftime("%Y-%m-%dT%H:%M")


# --- probe runner -------------------------------------------------------------------------------

ProbeCheck = Callable[[str, str], tuple[str, int | None, str | None]]  # (check_type, language) -> (result, latency, reason)


def default_check(check_type: str, language: str, *, timeout_s: float = 5.0) -> tuple[str, int | None, str | None]:
    """Call the app's own endpoints in-process with the synthetic identity (no call leaves the host)."""
    from fastapi.testclient import TestClient

    from app.main import app

    path = {"sign_in": "/api/probes/synthetic/sign_in", "dashboard": "/api/probes/synthetic/dashboard", "documents": "/api/probes/synthetic/documents"}[check_type]
    started = time.perf_counter()
    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.get(path, params={"lang": language}, headers={"x-probe-identity": SYNTHETIC_IDENTITY}, timeout=timeout_s)
    except Exception as exc:  # timeout or transport failure
        return "down", None, "timeout" if "timeout" in str(exc).lower() else "transport_error"
    latency = int((time.perf_counter() - started) * 1000)
    if resp.status_code >= 500:
        return "down", latency, "http_5xx"
    try:
        ok = resp.json().get("marker") == CONTENT_MARKER
    except Exception:
        ok = False
    return ("up" if ok else "down"), latency, (None if ok else "content_marker")


def run_probes(db: Session, *, at: datetime | None = None, check: ProbeCheck | None = None, probe_service_healthy: bool = True, dependency_down: str | None = None) -> list[ProbeRecord]:
    """One record per check type per language for the minute. Probe service down -> 'no_data' rows."""
    minute = floor_minute(at or utcnow())
    timeout_s = float(get_config(db, "probes.timeout_seconds", 5) or 5)
    check = check or (lambda c, lang: default_check(c, lang, timeout_s=timeout_s))
    out: list[ProbeRecord] = []
    for check_type in CHECK_TYPES:
        for lang in LANGUAGES:
            existing = db.scalar(select(ProbeRecord).where(ProbeRecord.minute_ts == minute, ProbeRecord.check_type == check_type, ProbeRecord.language == lang))
            if existing is not None:
                out.append(existing)
                continue
            if not probe_service_healthy:
                result, latency, reason = "no_data", None, "probe_service_down"
            elif dependency_down:
                result, latency, reason = "no_data", None, dependency_down
            else:
                result, latency, reason = check(check_type, lang)
            rec = ProbeRecord(minute_ts=minute, minute_local=local_str(minute), check_type=check_type, result=result, language=lang, latency_ms=latency, reason=reason)
            db.add(rec)
            out.append(rec)
    db.flush()
    return out


# --- minute availability ------------------------------------------------------------------------


def minute_statuses(db: Session, start: datetime, end: datetime) -> dict[tuple[datetime, str], dict]:
    """(minute, language) -> {status: up|down|no_data|unmeasured, failed: [...], reason}. A minute is
    available for a language only when every check type for that language passed."""
    rows = list(db.scalars(select(ProbeRecord).where(ProbeRecord.minute_ts >= start, ProbeRecord.minute_ts < end)))
    groups: dict[tuple[datetime, str], list[ProbeRecord]] = {}
    for r in rows:
        groups.setdefault((r.minute_ts, r.language), []).append(r)
    out: dict[tuple[datetime, str], dict] = {}
    m = floor_minute(start)
    while m < end:
        for lang in LANGUAGES:
            recs = groups.get((m, lang), [])
            if not recs:
                out[(m, lang)] = {"status": "unmeasured", "failed": [], "reason": "no_record"}
            elif any(r.result == "no_data" for r in recs):
                out[(m, lang)] = {"status": "no_data", "failed": [], "reason": next(r.reason for r in recs if r.result == "no_data")}
            else:
                failed = [r.check_type for r in recs if r.result == "down"]
                missing = [c for c in CHECK_TYPES if c not in {r.check_type for r in recs}]
                if failed or missing:
                    out[(m, lang)] = {"status": "down", "failed": failed + missing, "reason": "probe_failed" if failed else "check_missing"}
                else:
                    out[(m, lang)] = {"status": "up", "failed": [], "reason": None}
        m += timedelta(minutes=1)
    return out


# --- peak windows ----------------------------------------------------------------------------------


def windows_effective(db: Session) -> list[PeakWindow]:
    return list(db.scalars(select(PeakWindow).where(PeakWindow.status == "active").order_by(PeakWindow.start_at)))


def window_in_force(w: PeakWindow, minute: datetime) -> bool:
    d = to_dubai(minute).date()
    return w.effective_from <= d and (w.effective_to is None or d < w.effective_to) and w.start_at <= minute < w.end_at


def next_window(db: Session, after: datetime) -> PeakWindow | None:
    return db.scalar(select(PeakWindow).where(PeakWindow.status == "active", PeakWindow.start_at >= after).order_by(PeakWindow.start_at).limit(1))


def window_dict(w: PeakWindow) -> dict:
    return {"window_id": w.window_id, "window_code": w.window_code, "name_en": w.name_en, "name_ar": w.name_ar, "window_type": w.window_type, "start_at": w.start_at.isoformat(), "end_at": w.end_at.isoformat(), "start_local": w.start_local, "end_local": w.end_local, "config_version": w.config_version, "version": w.version, "effective_from": w.effective_from.isoformat(), "effective_to": w.effective_to.isoformat() if w.effective_to else None, "status": w.status, "placeholder": w.placeholder, "reason": w.reason, "total_minutes": int((w.end_at - w.start_at).total_seconds() // 60)}


# --- K26 --------------------------------------------------------------------------------------------


def _stats() -> dict:
    return {"measured_minutes": 0, "available_minutes": 0, "down_minutes": 0, "no_data_minutes": 0, "unmeasured_minutes": 0, "total_minutes": 0}


def _finish(st: dict, threshold: float) -> dict:
    st["availability_pct"] = round(100.0 * st["available_minutes"] / st["measured_minutes"], 3) if st["measured_minutes"] else None
    not_measured = st["no_data_minutes"] + st["unmeasured_minutes"]
    st["incomplete_measurement"] = st["total_minutes"] > 0 and (not_measured / st["total_minutes"]) > threshold
    return st


def compute_k26(db: Session, period_start: datetime, period_end: datetime) -> dict:
    """K26 = available minutes / measured minutes inside peak windows only, per window per language.
    No window -> null (never 0% / 100%); partial windows clipped and labelled; overlaps counted once."""
    threshold = float(get_config(db, "probes.unmeasured_threshold", 0.01) or 0.01)
    target = float(get_config(db, "probes.k26_target_pct", 99.9) or 99.9)
    windows = [w for w in windows_effective(db) if w.start_at < period_end and w.end_at > period_start]
    nxt = next_window(db, period_end)
    base = {"period_start": period_start.isoformat(), "period_end": period_end.isoformat(), "target_pct": target, "target_label": "working assumption, reported not enforced", "next_window": window_dict(nxt) if nxt else None, "config_version": str(get_config(db, "probes.peak_window_config_version", "peak-v1"))}
    if not windows:
        return {**base, "state": "no_window", "value": None, "message": "No peak window in this period", "languages": {}, "combined": None, "windows": []}
    statuses = minute_statuses(db, max(period_start, min(w.start_at for w in windows)), min(period_end, max(w.end_at for w in windows)))
    headline = {lang: _stats() for lang in LANGUAGES}
    combined = _stats()
    per_window = {w.window_id: {lang: _stats() for lang in LANGUAGES} for w in windows}
    m = floor_minute(max(period_start, min(w.start_at for w in windows)))
    end = min(period_end, max(w.end_at for w in windows))
    while m < end:
        in_windows = [w for w in windows if window_in_force(w, m)]
        if in_windows:
            lang_states = {lang: statuses[(m, lang)]["status"] for lang in LANGUAGES}
            for lang, st in lang_states.items():
                for bucket in [headline[lang]] + [per_window[w.window_id][lang] for w in in_windows]:
                    _count(bucket, st)
            all_up = all(st == "up" for st in lang_states.values())
            any_down = any(st == "down" for st in lang_states.values())
            comb_state = "down" if any_down else ("up" if all_up else ("no_data" if "no_data" in lang_states.values() else "unmeasured"))
            _count(combined, comb_state)
        m += timedelta(minutes=1)
    windows_out = []
    for w in windows:
        covered_start, covered_end = max(w.start_at, period_start), min(w.end_at, period_end)
        full = int((w.end_at - w.start_at).total_seconds() // 60)
        covered = int((covered_end - covered_start).total_seconds() // 60)
        windows_out.append({**window_dict(w), "partial": covered < full, "partial_label": "Partial window" if covered < full else None, "covered_minutes": covered, "full_minutes": full, "languages": {lang: _finish(per_window[w.window_id][lang], threshold) for lang in LANGUAGES}})
    langs = {lang: _finish(headline[lang], threshold) for lang in LANGUAGES}
    comb = _finish(combined, threshold)
    state = "incomplete" if comb["incomplete_measurement"] else "measured"
    return {**base, "state": state, "value": comb["availability_pct"], "message": "Incomplete measurement" if state == "incomplete" else None, "languages": langs, "combined": comb, "windows": windows_out}


def _count(bucket: dict, st: str) -> None:
    bucket["total_minutes"] += 1
    if st == "up":
        bucket["measured_minutes"] += 1
        bucket["available_minutes"] += 1
    elif st == "down":
        bucket["measured_minutes"] += 1
        bucket["down_minutes"] += 1
    elif st == "no_data":
        bucket["no_data_minutes"] += 1
    else:
        bucket["unmeasured_minutes"] += 1


def timeline(db: Session, start: datetime, end: datetime, *, limit: int = 1440) -> list[dict]:
    start = max(start, end - timedelta(minutes=limit))
    statuses = minute_statuses(db, start, end)
    windows = windows_effective(db)
    out = []
    m = floor_minute(start)
    while m < end:
        bands = [w.window_code for w in windows if window_in_force(w, m)]
        out.append({"minute_ts": m.isoformat(), "minute_local": local_str(m), "ar": statuses[(m, "ar")], "en": statuses[(m, "en")], "peak_windows": bands})
        m += timedelta(minutes=1)
    return out


# --- operations tile and release test -------------------------------------------------------------


def operations_tile(db: Session) -> dict:
    last = db.scalar(select(ProbeRecord).order_by(desc(ProbeRecord.minute_ts)).limit(1))
    if last is None:
        return {"state": "no_probes_yet", "message": "Probes start when the platform goes live. K26 will appear after the first peak window.", "checks": {}, "last_checked": None}
    recs = list(db.scalars(select(ProbeRecord).where(ProbeRecord.minute_ts == last.minute_ts)))
    checks = {f"{r.check_type}:{r.language}": {"result": r.result, "latency_ms": r.latency_ms, "reason": r.reason} for r in recs}
    results = {r.result for r in recs}
    state = "no_data" if "no_data" in results else ("down" if "down" in results else ("up" if results == {"up"} else "degraded"))
    return {"state": state, "message": None, "checks": checks, "last_checked": last.minute_ts.isoformat(), "last_checked_local": local_str(last.minute_ts), "synthetic_identity_note": "Probes use a test company with no real company data"}


def release_probe_test(db: Session, *, minutes: int | None = None, end: datetime | None = None) -> dict:
    """Release rule: N consecutive minutes (default 30, config) with zero failed probes in both languages."""
    minutes = minutes or int(get_config(db, "probes.release_window_minutes", 30) or 30)
    if end is None:
        last = db.scalar(select(ProbeRecord).order_by(desc(ProbeRecord.minute_ts)).limit(1))
        if last is None:
            return {"passed": False, "minutes_required": minutes, "minutes_checked": 0, "failures": [], "reason": "no_probe_records"}
        end = last.minute_ts + timedelta(minutes=1)
    start = end - timedelta(minutes=minutes)
    statuses = minute_statuses(db, start, end)
    failures = [{"minute_ts": m.isoformat(), "language": lang, **st} for (m, lang), st in statuses.items() if st["status"] != "up"]
    return {"passed": not failures, "minutes_required": minutes, "minutes_checked": minutes, "window_start": start.isoformat(), "window_end": end.isoformat(), "failures": failures[:50], "failure_count": len(failures)}


# --- peak-window seeding helpers -------------------------------------------------------------------


def shift_working_days(d: date, n: int) -> date:
    step = 1 if n > 0 else -1
    remaining = abs(n)
    while remaining:
        d += timedelta(days=step)
        if d.weekday() < 5:
            remaining -= 1
    return d


def dubai_midnight_utc(d: date) -> datetime:
    return datetime(d.year, d.month, d.day, tzinfo=DUBAI).astimezone(UTC).replace(tzinfo=None)


def ensure_window(db: Session, *, code: str, name_en: str, name_ar: str, window_type: str, start: date, end_exclusive: date, anchor: date | None, lead: int | None, tail: int | None, reason: str, config_version: str = "peak-v1", placeholder: bool = False, effective_from: date = date(2025, 1, 1)) -> PeakWindow:
    start_at, end_at = dubai_midnight_utc(start), dubai_midnight_utc(end_exclusive)
    existing = db.scalar(select(PeakWindow).where(PeakWindow.window_code == code, PeakWindow.start_at == start_at, PeakWindow.config_version == config_version))
    if existing is not None:
        return existing
    w = PeakWindow(window_id=new_id("pw"), window_code=code, name_en=name_en, name_ar=name_ar, window_type=window_type, start_at=start_at, end_at=end_at, start_local=f"{start.isoformat()}T00:00", end_local=f"{end_exclusive.isoformat()}T00:00", anchor_date=anchor, lead_days=lead, tail_days=tail, holiday_shift_rule="official holidays shift the anchor to the next working day; Ramadan does not move windows", reason=reason, config_version=config_version, effective_from=effective_from, placeholder=placeholder, created_by="seed")
    db.add(w)
    db.flush()
    return w


def record_window_change(db: Session, w: PeakWindow, actor_key: str | None) -> None:
    record_event(db, event_type="PEAK_WINDOW_VERSIONED", category="config", actor_key=actor_key, subject_type="peak_window", subject_id=w.window_id, config_version=w.config_version, details={"window_code": w.window_code, "version": w.version})
