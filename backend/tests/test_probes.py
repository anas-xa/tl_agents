from __future__ import annotations

from datetime import date, datetime, timedelta

from sqlalchemy import select

from app.modules.probes import service
from app.modules.probes.models import PeakWindow, ProbeRecord
from tests.conftest import sign_in

M0 = datetime(2026, 3, 2, 6, 0, 0)  # a Monday, 10:00 Asia/Dubai


def _window(db, start, minutes, code="t_window", config_version="peak-v1"):
    w = PeakWindow(window_code=code, name_en=f"Test window {code}", name_ar=f"نافذة اختبار {code}", window_type="fixed_date", start_at=start, end_at=start + timedelta(minutes=minutes), config_version=config_version, effective_from=date(2025, 1, 1), created_by="test")
    db.add(w)
    db.flush()
    return w


def _fill(db, start, minutes, *, down=None, no_data=None):
    """down / no_data: {minute_offset: [(check, lang), ...]} or {minute_offset: 'all'}."""
    for i in range(minutes):
        m = start + timedelta(minutes=i)
        if no_data and i in no_data:
            service.run_probes(db, at=m, probe_service_healthy=False)
            continue
        bad = set((down or {}).get(i, []))
        service.run_probes(db, at=m, check=lambda c, lang, bad=bad: ("down", 120, "http_5xx") if (c, lang) in bad else ("up", 120, None))


def test_minute_available_only_if_all_probes_for_language_pass(db):
    _fill(db, M0, 3, down={1: [("dashboard", "ar")]})
    st = service.minute_statuses(db, M0, M0 + timedelta(minutes=3))
    assert st[(M0, "ar")]["status"] == "up" and st[(M0 + timedelta(minutes=1), "ar")] == {"status": "down", "failed": ["dashboard"], "reason": "probe_failed"}
    assert st[(M0 + timedelta(minutes=1), "en")]["status"] == "up"
    recs = list(db.scalars(select(ProbeRecord).where(ProbeRecord.minute_ts == M0)))
    assert len(recs) == 6 and {r.check_type for r in recs} == {"sign_in", "dashboard", "documents"}
    assert all(r.latency_ms == 120 for r in recs) and all(r.probe_id.startswith("prb_") for r in recs)


def test_no_data_and_unmeasured_minutes_never_count_as_up(db):
    _window(db, M0, 10)
    _fill(db, M0, 8, no_data={3: "all"}, down={5: [("sign_in", "en")]})  # minutes 8 and 9 have no record
    k = service.compute_k26(db, M0, M0 + timedelta(minutes=10))
    en = k["languages"]["en"]
    assert en["total_minutes"] == 10 and en["no_data_minutes"] == 1 and en["unmeasured_minutes"] == 2
    assert en["measured_minutes"] == 7 and en["down_minutes"] == 1 and en["availability_pct"] == round(100 * 6 / 7, 3)
    assert k["languages"]["ar"]["availability_pct"] == 100.0
    assert k["state"] == "incomplete" and k["message"] == "Incomplete measurement"
    assert k["combined"]["availability_pct"] == round(100 * 6 / 7, 3)


def test_k26_per_window_partial_overlap_and_no_window(db):
    w1 = _window(db, M0, 10, code="w1")
    _window(db, M0 + timedelta(minutes=5), 10, code="w2")  # overlaps w1 for 5 minutes
    _fill(db, M0, 15, down={2: [("dashboard", "ar"), ("dashboard", "en")]})
    k = service.compute_k26(db, M0, M0 + timedelta(minutes=15))
    assert k["state"] == "measured" and k["combined"]["total_minutes"] == 15  # overlap counted once in the headline
    assert k["combined"]["down_minutes"] == 1 and k["value"] == round(100 * 14 / 15, 3)
    by_code = {w["window_code"]: w for w in k["windows"]}
    assert by_code["w1"]["languages"]["en"]["total_minutes"] == 10 and by_code["w1"]["languages"]["en"]["down_minutes"] == 1
    assert by_code["w2"]["languages"]["en"]["total_minutes"] == 10 and by_code["w2"]["languages"]["en"]["down_minutes"] == 0
    assert by_code["w1"]["partial"] is False and by_code["w1"]["config_version"] == "peak-v1"
    # partial window: period covers only the first 5 minutes of w1
    k2 = service.compute_k26(db, M0, M0 + timedelta(minutes=5))
    w = next(x for x in k2["windows"] if x["window_code"] == "w1")
    assert w["partial"] is True and w["partial_label"] == "Partial window" and w["covered_minutes"] == 5 and w["full_minutes"] == 10
    # period with no window: null value, never 0% or 100%, next window listed
    k3 = service.compute_k26(db, M0 - timedelta(hours=2), M0 - timedelta(hours=1))
    assert k3["state"] == "no_window" and k3["value"] is None and k3["message"] == "No peak window in this period"
    assert k3["next_window"]["window_id"] == w1.window_id
    assert k3["target_pct"] == 99.9


def test_window_version_in_force_at_minute(db):
    old = _window(db, M0, 10, code="vat", config_version="peak-v0")
    old.effective_to = date(2026, 3, 2)  # retired from the measured day onwards
    new = _window(db, M0 + timedelta(minutes=5), 5, code="vat", config_version="peak-v1")
    new.supersedes_window_id = old.window_id
    db.flush()
    _fill(db, M0, 10)
    k = service.compute_k26(db, M0, M0 + timedelta(minutes=10))
    assert k["combined"]["total_minutes"] == 5  # only the version in force counts


def test_release_test_requires_consecutive_minutes_with_zero_failures(db):
    _fill(db, M0, 5)
    out = service.release_probe_test(db, minutes=5, end=M0 + timedelta(minutes=5))
    assert out["passed"] is True and out["minutes_required"] == 5
    _fill(db, M0 + timedelta(minutes=5), 3, down={1: [("documents", "ar")]})
    out = service.release_probe_test(db, minutes=5, end=M0 + timedelta(minutes=8))
    assert out["passed"] is False and out["failure_count"] == 1 and out["failures"][0]["language"] == "ar"
    assert service.release_probe_test(db, minutes=2, end=M0 + timedelta(minutes=5))["passed"] is True


def test_demo_fixture_has_seven_minute_arabic_outage_and_tile_states(db):
    from app.core.time import utcnow

    now = service.floor_minute(utcnow())
    st = service.minute_statuses(db, now - timedelta(hours=24), now)
    ar_down = [m for (m, lang), s in st.items() if lang == "ar" and s["status"] == "down"]
    en_down = [m for (m, lang), s in st.items() if lang == "en" and s["status"] == "down"]
    assert len(ar_down) == 7 and en_down == []
    assert all(st[(m, "ar")]["failed"] == ["dashboard"] for m in ar_down)
    tile = service.operations_tile(db)
    assert tile["state"] == "up" and tile["checks"]["sign_in:ar"]["result"] == "up"
    assert service.release_probe_test(db)["passed"] is True  # the outage is older than 30 minutes


def test_probe_runner_calls_own_endpoints_in_process_with_synthetic_identity(client, db):
    sign_in(client, "adel")
    r = client.post("/api/admin/probes/run")
    assert r.status_code == 200, r.text
    recs = r.json()
    assert len(recs) == 6 and all(x["result"] == "up" for x in recs) and all(x["latency_ms"] is not None for x in recs)
    admin = client.get("/api/admin/probes").json()
    assert admin["synthetic_identity"] == "probe-synthetic" and admin["tile"]["state"] == "up"
    assert any(w["window_code"] == "vat_q_deadline" for w in admin["windows"]) and any(w["window_code"] == "ct_30sep" for w in admin["windows"])
    assert any(w["placeholder"] for w in admin["windows"] if w["window_code"] == "renewal_cohort")
    # synthetic targets expose no company data and carry the content marker
    s = client.get("/api/probes/synthetic/dashboard", params={"lang": "ar"}).json()
    assert s["marker"] == "qeonix-probe-ok" and s["company"] == "probe-test-company"


def test_det_availability_endpoint_access(client, db):
    sign_in(client, "sara")
    r = client.get("/api/det/availability", params={"period": "day"})
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["k26"]["state"] in ("no_window", "measured", "incomplete") and data["tile"]["state"] == "up"
    assert data["wording"]["title"] == "K26: portal availability during peak windows"
    assert len(data["timeline"]) <= 1441 and "peak_windows" in data["timeline"][0]
    assert data["k26"]["value"] is None or 0 <= data["k26"]["value"] <= 100
    sign_in(client, "khalid")
    assert client.get("/api/det/availability").status_code == 403
    assert client.get("/api/admin/probes").status_code == 403
    sign_in(client, "layla")
    assert client.get("/api/det/availability").status_code == 403
