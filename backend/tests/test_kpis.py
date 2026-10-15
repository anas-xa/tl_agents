"""E9-S1 SC14 DET KPIs: shared suppression engine, KPI maths, access, logging, export, per-licence view."""

from __future__ import annotations

import csv
import io
from datetime import date, datetime, timedelta

import pytest
from sqlalchemy import select

from app.core.errors import ValidationFailed
from app.modules.kpis import calculators as calc
from app.modules.kpis import suppression as sup
from tests.conftest import sign_in

TODAY = date(2027, 6, 20)


def _walk_cells(obj, out):
    if isinstance(obj, dict):
        if "cell_state" in obj and "suppressed" in obj:
            out.append(obj)
        for v in obj.values():
            _walk_cells(v, out)
    elif isinstance(obj, list):
        for v in obj:
            _walk_cells(v, out)
    return out


def _assert_no_hidden_values(payload):
    cells = _walk_cells(payload, [])
    for c in cells:
        if c["suppressed"]:
            assert "value" not in c, c
            assert c["label_en"].startswith("Fewer than") or c["label_en"].startswith("Not shown")
    return cells


def _set(db, key, value):
    from app.modules.config.service import set_config

    set_config(db, key, value, changed_by="test")
    db.commit()


# --- suppression engine -------------------------------------------------------------------------------------


@pytest.mark.parametrize("n", [5, 10, 20])
def test_primary_and_complementary_suppression(n):
    rows = [{"cohort": "A", "count": n - 1}, {"cohort": "B", "count": n + 3}, {"cohort": "C", "count": 3 * n}]
    t = sup.suppress_table(rows, ["cohort"], [], n, merge_other=False)
    by = {r["cohort"]: r for r in t["rows"]}
    assert by["A"]["count"] == sup.suppressed_cell(n)
    assert by["A"]["count"]["label_en"] == f"Fewer than {n}"
    assert "value" not in by["A"]["count"]
    # exactly one hidden cell would be recoverable from the total: the next smallest is hidden too
    assert by["B"]["cell_state"] == "complementary_suppressed" and "value" not in by["B"]["count"]
    assert by["C"]["count"]["value"] == 3 * n
    assert t["total"]["count"]["value"] == (n - 1) + (n + 3) + 3 * n
    assert t["notice"] is True
    assert not sup.contains_value(t, n - 1) and not sup.contains_value(t, n + 3)


@pytest.mark.parametrize("n", [5, 10, 20])
def test_two_hidden_cells_summing_to_n_need_no_extra_hiding(n):
    rows = [{"m": "a", "count": n - 1}, {"m": "b", "count": n - 2}, {"m": "c", "count": 2 * n}, {"m": "d", "count": 4 * n}]
    t = sup.suppress_table(rows, ["m"], [], n, merge_other=False)
    states = {r["m"]: r["cell_state"] for r in t["rows"]}
    assert states == {"a": "suppressed_fewer_than_N", "b": "suppressed_fewer_than_N", "c": "shown", "d": "shown"}


@pytest.mark.parametrize("n", [5, 10, 20])
def test_total_shown_only_when_at_least_n(n):
    small = sup.suppress_table([{"x": "a", "count": n - 2}, {"x": "b", "count": 1}], ["x"], [], n, merge_other=False)
    assert small["total"]["count"]["suppressed"] is True
    big = sup.suppress_table([{"x": "a", "count": n}, {"x": "b", "count": n}], ["x"], [], n)
    assert big["total"]["count"]["value"] == 2 * n


@pytest.mark.parametrize("n", [5, 10, 20])
def test_stepwise_other_combined_then_not_shown(n):
    rows = [{"cat": "big", "count": 5 * n}, {"cat": "mid", "count": 2 * n}, {"cat": "s1", "count": n - 1}, {"cat": "s2", "count": 2}]
    t = sup.suppress_table(rows, ["cat"], [], n)
    cats = [r["cat"] for r in t["rows"]]
    assert sup.OTHER_KEY in cats and "s1" not in cats and "s2" not in cats
    other = next(r for r in t["rows"] if r["cat"] == sup.OTHER_KEY)
    assert other["cell_state"] == "merged_other_combined" and other["count"]["value"] == n + 1
    assert other["label_en"] == "Other (combined)"
    assert "big" in cats and "mid" in cats  # never merge everything into 'Other'
    assert t["notice_key"] == "merged"
    # when 'Other' cannot reach N without swallowing every category: the whole breakdown is not shown
    t2 = sup.suppress_table([{"cat": "a", "count": n - 1}, {"cat": "b", "count": 2}], ["cat"], [], n)
    assert t2["state"] == "not_shown_group_too_small" and t2["rows"] == []
    assert t2["notice_en"] == "Some groups are combined or hidden to protect privacy."


def test_no_cross_dimension_merging_and_no_three_dimension_crosstab():
    n = 10
    rows = [{"a": "x", "b": "p", "count": 4}, {"a": "x", "b": "q", "count": 30}, {"a": "y", "b": "p", "count": 25}]
    t = sup.suppress_table(rows, ["a", "b"], [], n)
    assert all(r["a"] in ("x", "y") and r["b"] in ("p", "q") for r in t["rows"])  # coded categories never merged across dimensions
    assert all(r["cell_state"] != "merged_other_combined" for r in t["rows"])
    t3 = sup.suppress_table([{"a": 1, "b": 2, "c": 3, "count": 4}, {"a": 1, "b": 2, "c": 4, "count": 40}], ["a", "b", "c"], [], n)
    assert t3["state"] == "not_shown_group_too_small" and t3["rows"] == []


def test_dominance_rule_on_amounts():
    rows = [
        {"g": "a", "count": 12, "amt": 1_000_000, "max_contribution": {"amt": 800_000}},
        {"g": "b", "count": 15, "amt": 500_000, "max_contribution": {"amt": 60_000}},
        {"g": "c", "count": 20, "amt": 700_000, "max_contribution": {"amt": 50_000}},
    ]
    t = sup.suppress_table(rows, ["g"], [], 10, amount_keys=["amt"], merge_other=False)
    by = {r["g"]: r for r in t["rows"]}
    assert by["a"]["amt"]["cell_state"] == "suppressed_dominance"
    assert by["b"]["amt"]["cell_state"] == "complementary_suppressed"
    assert by["c"]["amt"]["value"] == 700_000
    assert not sup.contains_value(t, 1_000_000) and not sup.contains_value(t, 500_000)


def test_rate_hides_small_numerator_and_small_complement():
    rows = [{"g": "a", "count": 40, "num": 38}, {"g": "b", "count": 50, "num": 20}]
    t = sup.suppress_table(rows, ["g"], [], 10, count_keys=["num"], rate_keys={"rate": ("num", "count")}, merge_other=False)
    by = {r["g"]: r for r in t["rows"]}
    assert by["a"]["num"]["suppressed"] and by["a"]["rate"]["suppressed"]  # 2 not flagged would be revealed
    assert by["b"]["num"]["suppressed"]  # complementary within the column (total published)


def test_filter_blocking_and_difference_and_n_range():
    assert sup.filter_blocked(9, 10) and not sup.filter_blocked(10, 10)
    assert sup.suppress_difference(5, 9, 40, 10)["suppressed"] is True
    assert sup.suppress_difference(5, 12, 40, 10) == sup.shown_cell(5)
    for bad in (2, 51, "x", 10.5):
        with pytest.raises(ValidationFailed):
            sup.validate_n(bad)
    assert sup.validate_n(3) == 3 and sup.validate_n(50) == 50
    assert sup.suppressed_cell(7) == {"suppressed": True, "cell_state": "suppressed_fewer_than_N", "label_en": "Fewer than 7", "label_ar": "أقل من 7"}


# --- KPI maths on small hand-built fixtures -----------------------------------------------------------------


def _sub(key, *, basis="opt_in", inv=date(2027, 3, 10), net=60000, vat=3000, term=12, **kw):
    line = {"kind": "charge", "date": inv, "date_source": "invoice_date", "net": net, "vat": vat, "gross": net + (vat or 0), "term_months": term, "payment_status": "collected", "collected_final": net + (vat or 0), "collected_platform": 0, "refunded": 0, "refund_cancels_charge": False, "confirmed": True}
    line.update(kw.pop("line", {}))
    s = {"key": key, "cohort": "C", "wave": "1b", "enrolment_basis": basis, "licence_category": "Commercial", "status": "active", "active_from": inv, "active_to": inv + timedelta(days=364), "invoice_date": inv, "lines": [line], "opt_out": None, "refunds": [], "complaints": [], "events": []}
    s.update(kw)
    return s


def test_k2_billed_and_recognised_views():
    a = _sub("a", inv=date(2027, 3, 10), net=100, vat=None, term=3)
    b = _sub("b", inv=date(2027, 3, 31), net=60000, vat=3000, term=12)
    b["lines"].append({**b["lines"][0], "kind": "credit_note", "date": date(2027, 4, 2), "net": -60000, "vat": -3000, "gross": -63000})
    mar = calc.k2([a, b], "2027-03", TODAY)
    assert mar["value"] == 60100 and mar["extra"]["billed_fils"] == 60100
    assert mar["flags"]["vat_treatment_unconfirmed"] is True
    assert mar["extra"]["normalised_annual_fils"] == 400 + 60000
    assert mar["extra"]["recognised_fils"] == 33 + 5000
    apr = calc.k2([a, b], "2027-04", TODAY)
    assert apr["extra"]["credit_notes_fils"] == -60000 and apr["value"] == -60000  # credit note in the month issued, March not restated
    may = calc.k2([a, b], "2027-05", TODAY)
    assert may["extra"]["recognised_fils"] == 34 + 5000  # last month takes the rounding remainder
    assert calc.k2([a, b], "2027-07", TODAY)["state"] == "not_applicable"


def test_k3_final_vs_provisional_and_refunds():
    a = _sub("a", line={"collected_final": 63000})
    b = _sub("b", line={"collected_final": 0, "collected_platform": 63000})
    c = _sub("c", line={"collected_final": 63000, "refunded": 63000, "refund_cancels_charge": True})
    d = _sub("d", line={"collected_final": 63000, "refunded": 10000, "refund_cancels_charge": False})
    r = calc.k3([a, b, c, d], "2027-03", TODAY, cutoff_days=30, payment_term_days=30)
    # denominator: billed 4 x 63000 - cancelling refund 63000; final numerator: final bases minus goodwill refund
    assert r["denominator"] == 189000
    # net collected = collected - every refund; only the cancelling refund also leaves the denominator
    assert r["value"] == round((63000 * 3 - 63000 - 10000) * 100 / 189000, 1)
    assert r["extra"]["provisional_rate_incl_platform_derived"] == round((63000 * 4 - 63000 - 10000) * 100 / 189000, 1)
    assert r["extra"]["gross_collection_rate"] == 100.0
    assert r["flags"]["provisional"] is True and r["flags"]["platform_derived_share"] == 25.0
    closed = calc.k3([a, c, d], "2027-03", TODAY, cutoff_days=30, payment_term_days=30)
    assert closed["flags"]["provisional"] is False and closed["flags"]["final"] is True


K4_PARAMS = {"observation_window_days": 90, "excluded_refund_reasons": ["failed_payment", "duplicate_payment", "technical_error"], "counted_refund_reasons": ["opt_out", "complaint"], "counted_complaint_categories": ["charge", "opt_out"], "denominator_rule": "invoice_month_cohort", "rule_version": "k4-v1"}


def test_k4_precedence_window_and_exclusions():
    inv = date(2027, 1, 10)
    triple = _sub("t", basis="default_on_with_opt_out", inv=inv, refunds=[{"at": inv + timedelta(days=5), "reason": "opt_out"}], opt_out={"at": inv + timedelta(days=4), "status": "det_confirmed"}, complaints=[{"at": inv + timedelta(days=6), "category": "charge"}])
    tech = _sub("x", basis="default_on_with_opt_out", inv=inv, refunds=[{"at": inv + timedelta(days=2), "reason": "failed_payment"}])
    late = _sub("l", basis="default_on_with_opt_out", inv=inv, opt_out={"at": inv + timedelta(days=95), "status": "pending"})
    rejected = _sub("r", basis="default_on_with_opt_out", inv=inv, opt_out={"at": inv + timedelta(days=10), "status": "rejected"})
    other = _sub("o", inv=inv, complaints=[{"at": inv + timedelta(days=3), "category": "service_quality"}, {"at": inv + timedelta(days=3), "category": "uncategorised"}])
    r = calc.k4([triple, tech, late, rejected, other], "2027-01", TODAY, K4_PARAMS)
    assert r["numerator"] == 2 and r["denominator"] == 5  # triple (refunded) + rejected request
    prim = {x["primary_reason"]: x["count"] for x in r["tables"][1]["rows"]}
    assert prim == {"refunded": 1, "opted_out": 1, "complained": 0}
    flags = {x["flag"]: x["count"] for x in r["tables"][2]["rows"]}
    assert flags == {"flag_refunded": 1, "flag_opted_out": 2, "flag_complained": 1}
    oo = {x["optout_status"]: x["count"] for x in r["tables"][3]["rows"]}
    assert oo == {"det_confirmed": 1, "pending": 0, "rejected": 1}
    assert r["counts"]["refund_technical"] == 1 and r["counts"]["after_window"] == 1
    assert r["counts"]["complaint_non_subscription"] == 1 and r["counts"]["complaint_uncategorised"] == 1
    assert r["flags"]["window_state"] == "closed"
    modes = {x["enrolment_basis"]: x for x in r["tables"][0]["rows"]}
    assert modes["default_on_with_opt_out"]["count"] == 4 and modes["opt_in"]["flagged"] == 0
    # window still open -> provisional; opt-out at zero works; no default-on -> not applicable split
    fresh = calc.k4([_sub("f", inv=TODAY - timedelta(days=5))], calc.period_of(TODAY), TODAY, K4_PARAMS)
    assert fresh["flags"]["window_state"] == "open" and fresh["value"] == 0.0 and fresh["flags"]["default_on_not_applicable"] is True


def test_k5_retention_and_no_renewals_due_yet():
    subs = [_sub(f"s{i}", renewal_due=date(2027, 5, 10), renewed=i < 7, renewal_choice_marker="active_choice" if i < 3 else "carry_over") for i in range(10)]
    subs.append(_sub("c", renewal_due=date(2027, 5, 12), cancelled_before_term_end=True))
    r = calc.k5(subs, "2027-05", TODAY)
    assert (r["numerator"], r["denominator"], r["value"]) == (7, 10, 70.0)
    assert r["counts"]["cancelled_before_term_end"] == 1
    none = calc.k5([_sub("n", renewal_due=date(2028, 3, 1))], "2027-05", TODAY)
    assert none["state"] == "not_applicable" and none["na_reason"] == "no_renewals_due_yet" and none["extra"]["first_due_date"] == "2028-03-01"


K6_PARAMS = {"status_mapping": {"RENEWED": "active", "ACTIVE": "active", "EXPIRED": "expired", "SUSPENDED": "suspended", "CANCELLED": "cancelled"}, "exclusions": {"cancelled_before_expiry": ["CANCELLED"], "suspended": ["SUSPENDED"]}, "suspended_rule": "exclude", "grace_days": 10}


def test_k6_bands_dubai_day_and_exclusions():
    exp = date(2027, 5, 20)

    def f(key, done=None, raw="RENEWED", **kw):
        return {"key": key, "issuing_authority": "DET", "licence_type": "mainland", "prior_expiry": kw.pop("prior", exp), "renewal_completed_at": done, "raw_status": raw, "block_reason_code": kw.pop("block", None), **kw}

    facts = [
        f("early", datetime(2027, 5, 1, 6)),
        f("on_day", datetime(2027, 5, 20, 19, 30)),  # 23:30 Dubai on the expiry day: on time
        f("next_day_dubai", datetime(2027, 5, 20, 20, 30)),  # 00:30 Dubai next day: late (within grace)
        f("grace", datetime(2027, 5, 25, 6)),
        f("late", datetime(2027, 6, 15, 6)),
        f("cancelled", None, raw="CANCELLED"),
        f("renewed_after_cancellation", datetime(2027, 6, 1, 6), raw="CANCELLED"),
        f("suspended", None, raw="SUSPENDED"),
        f("ejari", None, raw="EXPIRED", block="blocked_by_ejari"),
        f("free_zone", datetime(2027, 5, 1, 6), licence_type="free_zone"),
        f("unmapped", None, raw="DET_NEW_STATUS"),
        f("expiry_changed", datetime(2027, 5, 18, 6), prior=date(2027, 5, 19)),  # baseline = expiry in force before renewal
        f("other_month", datetime(2027, 4, 1, 6), prior=date(2027, 4, 2)),
    ]
    r = calc.k6(facts, "2027-05", TODAY, K6_PARAMS)
    bands = {x["band"]: x["count"] for x in r["tables"][0]["rows"]}
    assert bands == {"on_time": 3, "renewed_in_grace": 2, "renewed_late": 1, "not_renewed": 0, "blocked": 1}
    assert r["denominator"] == 7 and r["value"] == round(300 / 7, 1)
    assert r["counts"]["cancelled_before_expiry"] == 2 and r["counts"]["suspended_excluded"] == 1
    assert r["counts"]["out_of_scope"] == 1 and r["counts"]["unmapped_status"] == 1 and r["flags"]["unmapped_status_alert"] is True
    assert r["counts"]["early_renewals"] == 2
    assert r["flags"]["provisional"] is True  # within 30 days after month end
    unknown_grace = calc.k6(facts, "2027-05", TODAY, {**K6_PARAMS, "grace_days": None})
    assert {x["band"]: x["count"] for x in unknown_grace["tables"][0]["rows"]}["renewed_late"] == 3
    kept = calc.k6(facts, "2027-05", TODAY, {**K6_PARAMS, "suspended_rule": "keep_in_denominator"})
    assert kept["denominator"] == 8 and kept["counts"]["blocked"] == 2


def _ret(i, *, filed=True, late=False, source="RULE_DERIVED", filed_source="company_reported_receipt", ext=False):
    due = date(2027, 5, 28)
    return {"key": f"r{i}", "tax_type": "vat_return", "statutory_due": due, "due_used": due, "deadline_source": source, "filed_date": (due + timedelta(days=3) if late else due - timedelta(days=1)) if filed else None, "filed_source": filed_source if filed else None, "extension_recorded": ext}


def test_k7_k8_measurability_thresholds():
    params = {"min_measurable_share": 60, "min_returns": 30}
    rets = [_ret(i, late=i < 3) for i in range(30)] + [_ret(100 + i, filed=False) for i in range(8)] + [_ret(200 + i, source="OWNER_ENTERED", filed_source="owner_declaration") for i in range(2)]
    rets.append(_ret(300, source="FTA_NOTICE", ext=True))
    k7 = calc.k78(rets, "2027-05", TODAY, params, which="K7")
    k8 = calc.k78(rets, "2027-05", TODAY, params, which="K8")
    assert k7["counts"]["due"] == 41 and k7["denominator"] == 31
    reasons = {x["reason"]: x["count"] for x in k7["tables"][1]["rows"]}
    assert reasons == {"unverified_owner_entered_only": 2, "filed_date_not_available": 8, "due_date_not_determinable": 0}
    assert k7["flags"]["rate_shown"] is True and k7["value"] == round(300 / 31, 1) and k8["value"] == round(2800 / 31, 1)
    assert k7["flags"]["partial"] is True and k7["counts"]["extension_recorded"] == 1
    assert k7["flags"]["source_label"] == "owner-reported, not FTA-verified"
    # below 60% measurable -> counts only
    low = calc.k78([_ret(i) for i in range(30)] + [_ret(100 + i, filed=False) for i in range(25)], "2027-05", TODAY, params, which="K7")
    assert low["flags"]["rate_shown"] is False and low["value"] is None
    # >= 60% measurable but fewer than 30 returns -> counts only
    few = calc.k78([_ret(i) for i in range(25)], "2027-05", TODAY, params, which="K8")
    assert few["flags"]["rate_shown"] is False and few["value"] is None and few["flags"]["partial"] is False
    # not measurable never counted as late or on time
    only_unfiled = calc.k78([_ret(i, filed=False) for i in range(40)], "2027-05", TODAY, params, which="K7")
    assert only_unfiled["numerator"] == 0 and only_unfiled["denominator"] == 0


def test_k19_fail_closed_and_zero_unsigned_releases():
    params = {"sig_table": {"audit_file_draft": True, "management_summary": False}, "excluded_types": ["tax_return_draft"]}
    items = [{"type": "audit_file_draft", "status": s, "signed": s in ("signed", "issued"), "released": s == "issued"} for s in ("draft", "draft", "in_review", "signed", "rejected", "issued", "superseded")]
    items += [{"type": "brand_new_type", "status": "draft", "signed": False}, {"type": "management_summary", "status": "draft"}, {"type": "tax_return_draft", "status": "draft"}]
    r = calc.k19(items, params)
    mix = {x["status"]: x["count"] for x in r["tables"][0]["rows"]}
    assert mix == {"draft": 3, "in_review": 1, "signed": 1, "rejected": 1}  # unknown type counted (fail closed)
    assert r["counts"]["issued_audit_reports"] == 1 and r["counts"]["not_current"] == 1
    assert r["counts"]["unsigned_releases"] == 0 and r["flags"]["unsigned_release_alert"] is False
    assert r["extra"]["no_signature_required_by_type"] == {"management_summary": 1}
    bad = calc.k19(items + [{"type": "audit_file_draft", "status": "issued", "signed": False, "released": True}], params)
    assert bad["counts"]["unsigned_releases"] == 1 and bad["flags"]["unsigned_release_alert"] is True


def test_k20_latest_evaluation_and_k29_usage():
    ev = [
        {"licence_key": "a", "period": "FY2026", "result": "likely_not_required", "evaluated_at": datetime(2027, 3, 1)},
        {"licence_key": "a", "period": "FY2026", "result": "likely_required", "evaluated_at": datetime(2027, 4, 1)},
        {"licence_key": "b", "period": "FY2026", "result": "cannot_determine", "evaluated_at": datetime(2027, 4, 1)},
    ]
    r = calc.k20(ev, {"a", "b", "c"}, None)
    assert (r["numerator"], r["denominator"], r["counts"]["not_yet_evaluated"]) == (1, 2, 1)
    subs = [_sub("u", inv=date(2027, 1, 1), events=[{"type": "SIGN_IN", "at": TODAY - timedelta(days=3)}]), _sub("v", inv=date(2027, 1, 1), events=[{"type": "REMINDER_SENT", "at": TODAY}]), _sub("w", inv=date(2027, 1, 1), events=[{"type": "SIGN_IN", "at": TODAY - timedelta(days=40)}])]
    u = calc.k29(subs, TODAY, {"window_days": 30, "qualifying_events": ["SIGN_IN"]})
    assert (u["numerator"], u["denominator"]) == (1, 3)


# --- API: dashboard, access, logging ---------------------------------------------------------------------------


def test_det_admin_dashboard_live_and_later_tiles(client, db):
    sign_in(client, "sara")
    r = client.get("/api/det/kpis")
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["demo_data"] is True and data["source_label"]["en"] == "Demo data"
    assert data["banner"]["en"] == "Aggregate figures only. Company financial detail is not available to your role."
    kp = {k["kpi_id"]: k for k in data["kpis"]}
    for kid in ("K1", "K2", "K3", "K4", "K19"):
        assert kp[kid]["release_state"] == "live" and kp[kid]["group"] == "live"
        assert kp[kid]["definition"]["en"] and kp[kid]["unit"] and kp[kid]["refresh_period"]
    assert kp["K1"]["value"]["value"] >= 100
    for kid in ("K5", "K6", "K7", "K8", "K20", "K29"):
        assert kp[kid]["state"] == "not_yet_available" and kp[kid]["group"] == "later" and "value" not in kp[kid]
    assert kp["K5"]["message"]["en"] == "Not yet available. Planned for Phase 1H."
    assert kp["K3"]["definition"]["en"] == "Payments collected ÷ amounts billed, for the selected period."
    assert kp["K4"]["extra"]["rule_version"] == "k4-v1" and "config_version" in kp["K4"]["extra"]
    assert set(kp["K4"]["breakdowns"]) >= {"by_enrolment_mode", "primary_reason", "flags", "optout_status"}
    assert kp["K1"]["breakdowns"]["subscription_status_counts"]["rows"]
    assert data["suppression"]["min_group_size"] == 10
    _assert_no_hidden_values(data)
    text = r.text.lower()
    assert "audit certificate" not in text and "fx-0" not in text and "det-10" not in text
    from app.modules.audit.models import AuditEvent

    ev = db.scalar(select(AuditEvent).where(AuditEvent.event_type == "DET_DASHBOARD_VIEWED").order_by(AuditEvent.id.desc()))
    assert ev is not None and ev.details["data_version"] == data["data_version"] and "filters" in ev.details


def test_later_phase_switch_flips_tiles_without_layout_change(client, db):
    sign_in(client, "sara")
    before = [(k["kpi_id"], k["group"]) for k in client.get("/api/det/kpis").json()["kpis"]]
    _set(db, "det_dashboard.later_phase_kpis.enabled", True)
    after = client.get("/api/det/kpis").json()["kpis"]
    assert [(k["kpi_id"], k["group"]) for k in after] == before
    kp = {k["kpi_id"]: k for k in after}
    for kid in ("K5", "K6", "K7", "K8"):
        assert kp[kid]["release_state"] == "live" and kp[kid]["state"] != "not_yet_available"
    assert kp["K20"]["state"] == "not_yet_available"
    assert kp["K7"]["source_label"]["en"] == "owner-reported, not FTA-verified"


def test_access_matrix(client):
    sign_in(client, "khalid")
    assert client.get("/api/det/kpis").status_code == 403
    assert client.get("/api/det/licences/DET-1023456").status_code == 403
    client.cookies.clear()
    sign_in(client, "noura")
    assert client.get("/api/det/kpis").status_code == 403
    r = client.get("/api/det/licences/DET-1023456")
    assert r.status_code == 403 and "1023456" not in r.text
    assert client.get("/api/det/kpis/runs").status_code == 200
    client.cookies.clear()
    sign_in(client, "faisal")
    assert client.get("/api/det/kpis").status_code == 200


def test_refusals_are_logged(client, db):
    sign_in(client, "khalid")
    client.get("/api/det/kpis")
    from app.modules.audit.models import AuditEvent

    ev = db.scalar(select(AuditEvent).where(AuditEvent.event_type == "ACCESS_REFUSED").order_by(AuditEvent.id.desc()))
    assert ev is not None and ev.details.get("permission") == "det.aggregates.view"


def test_per_licence_view_allow_list_and_logging(client, db):
    from app.modules.kpis.service import PER_LICENCE_FIELDS

    sign_in(client, "sara")
    r = client.get("/api/det/licences/DET-1023456")
    assert r.status_code == 200, r.text
    lic = r.json()["licence"]
    assert set(lic) == set(PER_LICENCE_FIELDS)
    assert lic["licence_number"] == "DET-1023456" and lic["enrolment_mode"] == "opt_in"
    body = r.text.lower()
    for banned in ("fils", "amount", "usage", "deadline", "filing", "tax", "escalation_reason", "document", "iban", "bank", "reason"):
        assert banned not in body, banned
    look = client.get("/api/det/licences", params={"licence_number": "DET-1023456"})
    assert look.status_code == 200 and look.json()["results"][0]["licence_number"] == "DET-1023456"
    assert client.get("/api/det/licences").status_code == 422
    from app.modules.audit.models import AuditEvent

    evs = list(db.scalars(select(AuditEvent).where(AuditEvent.event_type == "DET_PER_LICENCE_VIEWED")))
    assert len(evs) == 2 and evs[0].licence_number == "DET-1023456" and evs[0].category == "data_access"
    client.cookies.clear()
    sign_in(client, "noura")
    trail = client.get("/api/audit-trail", params={"event_type": "DET_PER_LICENCE_VIEWED"})
    assert trail.status_code in (200, 404)  # reviewer reads the trail through the audit-trail viewer


def test_company_financial_detail_refused_for_det_admin(client, db):
    from app.demo import CO_ALNOOR

    sign_in(client, "sara")
    assert client.get(f"/api/companies/{CO_ALNOOR}/transactions").status_code == 403
    r = client.post("/api/det/kpis/export", json={"level": "licence"})
    assert r.status_code == 403 and r.json()["error"] == "COMPANY_DETAIL_NOT_AVAILABLE"
    assert r.json()["message"] == "Company financial detail is not available to this role."
    from app.modules.audit.models import AuditEvent

    ev = db.scalar(select(AuditEvent).where(AuditEvent.reason_code == "COMPANY_DETAIL_NOT_AVAILABLE"))
    assert ev is not None and ev.outcome == "refused"


def test_breakdowns_allowed_dimensions_and_fixed_periods(client):
    sign_in(client, "sara")
    r = client.get("/api/det/kpis/K1", params={"dimension": "licence_category"})
    assert r.status_code == 200, r.text
    b = r.json()["breakdown"]
    assert any(row["cell_state"] == "merged_other_combined" for row in b["rows"])
    assert b["notice"] is True and b["notice_en"] == "Includes groups with fewer than 10 licences."
    assert all(row["licence_category"] in ("Commercial", "Professional", sup.OTHER_KEY) for row in b["rows"])
    month = client.get("/api/det/kpis/K2", params={"dimension": "month"}).json()["breakdown"]
    assert all(row.get("cell_state") != "merged_other_combined" for row in month["rows"])
    _assert_no_hidden_values(month)
    assert client.get("/api/det/kpis/K1", params={"dimension": "trade_name"}).status_code == 422
    assert client.get("/api/det/kpis/K1", params={"dimension": "cohort,wave"}).status_code == 422
    assert client.get("/api/det/kpis/K19", params={"dimension": "payment_method"}).status_code == 422
    assert client.get("/api/det/kpis", params={"period": "2019-01"}).status_code == 422
    assert client.get("/api/det/kpis/K99").status_code == 404


def test_filter_isolating_small_group_is_blocked(client, db):
    sign_in(client, "sara")
    r = client.get("/api/det/kpis", params={"cohort": "WAVE1A"}).json()
    assert r["state"] == "blocked" and r["blocked"]["notice_en"] == "Fewer than 10 licences (hidden to protect privacy)"
    assert all("value" not in k for k in r["kpis"])
    ok = client.get("/api/det/kpis", params={"cohort": "PILOT1"}).json()
    assert ok["state"] == "ready"
    _set(db, "det_dashboard.min_group_size", 5)
    assert client.get("/api/det/kpis", params={"cohort": "WAVE1A"}).json()["state"] == "ready"


@pytest.mark.parametrize("n", [5, 10, 20])
def test_dashboard_payload_and_export_identical_and_clean_at_n(client, db, n):
    _set(db, "det_dashboard.min_group_size", n)
    sign_in(client, "sara")
    data = client.get("/api/det/kpis").json()
    assert data["suppression"]["min_group_size"] == n
    _assert_no_hidden_values(data)
    exp = client.post("/api/det/kpis/export", json={})
    assert exp.status_code == 200 and exp.headers["content-type"].startswith("text/csv")
    rows = list(csv.reader(io.StringIO(exp.text)))
    assert rows[0][0] == "# Demo data"
    header = rows.index(["kpi_id", "kpi_name", "section", "group", "measure", "value", "cell_state"])
    body = rows[header + 1:]
    for row in body:
        if row[6] and row[6] not in ("shown", "notice", "") and row[6].startswith(("suppressed", "complementary", "not_shown")):
            assert not any(ch.isdigit() for ch in row[5].replace(str(n), "")), row
    screen = {k["kpi_id"]: k for k in data["kpis"]}
    for row in body:
        if row[2] == "headline" and row[4] == "value":
            v = screen[row[0]].get("value")
            if v and not v["suppressed"]:
                assert row[5] == str(v["value"])
            elif v:
                assert row[5] == v["label_en"]


def test_export_logged_with_export_id(client, db):
    sign_in(client, "sara")
    r = client.post("/api/det/kpis/export", json={"kpi_ids": ["K1"], "dimension": "licence_category"})
    assert r.status_code == 200
    eid = r.headers["x-export-id"]
    assert "Other (combined)" in r.text
    from app.modules.audit.models import AuditEvent
    from app.modules.kpis.models import KpiExport

    assert db.get(KpiExport, eid) is not None
    ev = db.scalar(select(AuditEvent).where(AuditEvent.event_type == "DET_DASHBOARD_EXPORTED"))
    assert ev.details["export_id"] == eid and ev.details["kpi_ids"] == ["K1"] and "data_version" in ev.details


def test_min_group_size_change_is_audited(client, db):
    sign_in(client, "sara")
    assert client.put("/api/det/settings/min-group-size", json={"value": 20, "reason": "x"}).status_code == 403
    client.cookies.clear()
    sign_in(client, "faisal")
    assert client.put("/api/det/settings/min-group-size", json={"value": 2, "reason": "too low"}).status_code == 422
    assert client.put("/api/det/settings/min-group-size", json={"value": 51, "reason": "too high"}).status_code == 422
    r = client.put("/api/det/settings/min-group-size", json={"value": 20, "reason": "DET decision", "consulted_compliance_lead": True})
    assert r.status_code == 200 and r.json()["min_group_size"] == 20
    from app.modules.audit.models import AuditEvent

    ev = db.scalar(select(AuditEvent).where(AuditEvent.event_type == "CONFIG_CHANGED", AuditEvent.subject_id == "det_dashboard.min_group_size"))
    assert ev.details["old"] == 10 and ev.details["new"] == 20 and ev.actor_key and ev.occurred_at
    assert client.get("/api/det/kpis").json()["suppression"]["min_group_size"] == 20
    assert client.get("/api/det/settings").json()["history"][-1]["value"] == 20


def test_platform_mode_without_demo_fixture(client, db):
    _set(db, "det_dashboard.include_demo_fixture", False)
    sign_in(client, "sara")
    data = client.get("/api/det/kpis").json()
    assert data["data_source"] == "platform" and data["demo_data"] is False and data["source_label"]["en"] == "Pilot data"
    k1 = next(k for k in data["kpis"] if k["kpi_id"] == "K1")
    assert k1["state"] in ("value", "no_data")
    if k1["state"] == "value":
        assert k1["value"]["suppressed"] is True and "value" not in k1["value"]  # a handful of real demo subscriptions < N
    _assert_no_hidden_values(data)


def test_calculation_runs_and_restatement(db):
    from app.modules.kpis.models import KpiCalculationRun
    from app.modules.kpis.service import record_run

    raw = {"value": 50.0, "numerator": 10, "denominator": 20, "counts": {}}
    old_period = calc.shift_period(calc.period_of(TODAY), -3)
    record_run(db, "K3", old_period, raw, "platform", TODAY)
    again = record_run(db, "K3", old_period, raw, "platform", TODAY)
    assert again["restated"] is False
    late = record_run(db, "K3", old_period, {**raw, "value": 60.0, "numerator": 12}, "platform", TODAY)
    assert late["restated"] is True and "Restated" in late["restatement_note"]
    runs = list(db.scalars(select(KpiCalculationRun).where(KpiCalculationRun.kpi_id == "K3")))
    assert len(runs) == 2 and runs[1].supersedes_run_id == runs[0].run_id  # closed period kept, never overwritten
