"""KPI calculators (pure functions over normalised facts; no database access, no HTTP).

Each calculator returns a *raw* record: ``state`` (value | no_data | not_applicable), ``value``, ``numerator``,
``denominator``, ``size`` (licences behind the figure, used by suppression), ``value_kind`` (count | rate |
amount), ``dominance`` (largest single-licence contribution per amount), ``flags`` and ``tables`` (sub-breakdowns
that the service passes through the shared suppression engine). Raw records never leave the server: the
service turns them into suppressed value records.

Fact shapes are documented in ``facts.py``. All money is integer fils; rounding half-up happens only at
presentation, except the K2 recognised view which splits each line with the last month taking the remainder.
"""

from __future__ import annotations

import calendar
from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import Any

from app.core.time import to_dubai

ENROLMENT_MODES = ("opt_in", "default_on_with_opt_out")
FINAL_STATES = ("value",)


# --- periods -----------------------------------------------------------------------------------------------


def period_bounds(period_key: str) -> tuple[date, date]:
    y, m = (int(x) for x in period_key.split("-"))
    return date(y, m, 1), date(y, m, calendar.monthrange(y, m)[1])


def period_of(d: date) -> str:
    return f"{d.year:04d}-{d.month:02d}"


def shift_period(period_key: str, months: int) -> str:
    y, m = (int(x) for x in period_key.split("-"))
    idx = y * 12 + (m - 1) + months
    return f"{idx // 12:04d}-{idx % 12 + 1:02d}"


def months_between(a: str, b: str) -> int:
    ya, ma = (int(x) for x in a.split("-"))
    yb, mb = (int(x) for x in b.split("-"))
    return (yb * 12 + mb) - (ya * 12 + ma)


def rate(num: float, den: float) -> float | None:
    if not den:
        return None
    return round(num * 100.0 / den, 1)


def half_up_div(num: int, den: int) -> int:
    if den == 0:
        return 0
    sign = -1 if (num < 0) ^ (den < 0) else 1
    num, den = abs(num), abs(den)
    return sign * ((2 * num + den) // (2 * den))


def distribute(amount_fils: int, months: int) -> list[int]:
    """Equal integer parts; the last month takes the rounding remainder (100/3 -> 33, 33, 34)."""
    try:
        from app.modules.subscriptions.service import distribute as _d

        return _d(amount_fils, months)
    except ImportError:  # pragma: no cover
        months = max(1, months)
        base = amount_fils // months
        return [base] * (months - 1) + [amount_fils - base * (months - 1)]


def _raw(**kw: Any) -> dict:
    base = {"state": "value", "value": None, "numerator": None, "denominator": None, "size": 0, "value_kind": "count", "dominance": {}, "flags": {}, "tables": [], "counts": {}, "extra": {}}
    base.update(kw)
    return base


def active_at(s: dict, day: date) -> bool:
    start, end = s.get("active_from"), s.get("active_to")
    return start is not None and start <= day and (end is None or end >= day)


def _table(tid: str, dims: list[str], rows: list[dict], **kw: Any) -> dict:
    return {"id": tid, "dims": dims, "rows": rows, **kw}


# --- K1 -----------------------------------------------------------------------------------------------------


def k1(subs: list[dict], period: str, today: date) -> dict:
    start, end = period_bounds(period)
    as_of = min(end, today)
    if not subs:
        return _raw(state="no_data")
    existing = [s for s in subs if (s.get("created_on") or s.get("active_from") or start) <= as_of]
    active = [s for s in existing if active_at(s, as_of)]
    split = [{"enrolment_basis": m, "count": sum(1 for s in active if s["enrolment_basis"] == m)} for m in ENROLMENT_MODES]
    status_rows = [
        {"status": "opted_out", "count": sum(1 for s in existing if s.get("status") == "opted_out")},
        {"status": "held_for_review", "count": sum(1 for s in existing if s.get("status") == "held_for_review")},
        {"status": "unpaid", "count": sum(1 for s in active if s.get("unpaid"))},
    ]
    return _raw(
        value=len(active), numerator=len(active), size=len(active), value_kind="count",
        extra={"as_of": as_of.isoformat(), "blocked_licences": 0, "note": "an unpaid or held subscription is never a blocked licence"},
        tables=[
            _table("enrolment_split", ["enrolment_basis"], split, merge_other=False),
            _table("subscription_status_counts", ["status"], status_rows, merge_other=False, include_total=False, rules={"complementary": False}),
        ],
    )


# --- K2 -----------------------------------------------------------------------------------------------------


def _lines(subs: list[dict]):
    for s in subs:
        for ln in s.get("lines") or []:
            yield s, ln


def k2(subs: list[dict], period: str, today: date) -> dict:
    if not subs:
        return _raw(state="no_data")
    in_period = [(s, ln) for s, ln in _lines(subs) if ln.get("confirmed", True) and period_of(ln["date"]) == period]
    pending = sum(1 for _s, ln in _lines(subs) if not ln.get("confirmed", True) and period_of(ln["date"]) == period)
    # recognised view: every confirmed charge line spread over its term months starting at its invoice month
    recognised = 0
    for _s, ln in _lines(subs):
        if not ln.get("confirmed", True):
            continue
        idx = months_between(period_of(ln["date"]), period)
        if ln["kind"] == "credit_note":
            recognised += ln["net"] if idx == 0 else 0
            continue
        parts = distribute(ln["net"], max(1, int(ln.get("term_months") or 12)))
        if 0 <= idx < len(parts):
            recognised += parts[idx]
    if not in_period:
        return _raw(state="not_applicable", na_reason="no_invoices", value_kind="amount", extra={"recognised_fils": recognised, "pending_confirmation_lines": pending})
    charges = [(s, ln) for s, ln in in_period if ln["kind"] == "charge"]
    credits = [(s, ln) for s, ln in in_period if ln["kind"] == "credit_note"]
    billed = sum(ln["net"] for _s, ln in charges)
    credit_total = sum(ln["net"] for _s, ln in credits)  # credit notes carry negative amounts
    net_billed = billed + credit_total
    gross = sum(ln["gross"] for _s, ln in in_period)
    per_sub: dict[str, int] = defaultdict(int)
    for s, ln in in_period:
        per_sub[s["key"]] += ln["net"]
    normalised = sum(half_up_div(ln["net"] * 12, max(1, int(ln.get("term_months") or 12))) for _s, ln in charges)
    vat_unconfirmed = any(ln.get("vat") is None for _s, ln in in_period)
    fallback = sum(1 for _s, ln in in_period if ln.get("date_source") == "billing_line_timestamp")
    top = max((abs(v) for v in per_sub.values()), default=0)
    return _raw(
        value=net_billed, numerator=net_billed, size=len(per_sub), value_kind="amount",
        dominance={"value": top},
        flags={"vat_treatment_unconfirmed": vat_unconfirmed, "billing_line_timestamp_fallback": fallback > 0},
        counts={"billing_line_timestamp_fallback_lines": fallback, "pending_confirmation_lines": pending},
        extra={"billed_fils": billed, "credit_notes_fils": credit_total, "net_billed_fils": net_billed, "gross_fils": gross, "recognised_fils": recognised, "normalised_annual_fils": normalised, "pending_confirmation_lines": pending, "basis": "invoice-date month", "projection_label": "arithmetic, not a forecast"},
        amounts={"billed_fils": billed, "credit_notes_fils": credit_total, "net_billed_fils": net_billed, "recognised_fils": recognised, "normalised_annual_fils": normalised},
    )


# --- K3 -----------------------------------------------------------------------------------------------------


def k3(subs: list[dict], period: str, today: date, *, cutoff_days: int | None, payment_term_days: int | None) -> dict:
    if not subs:
        return _raw(state="no_data")
    start, end = period_bounds(period)
    lines = [(s, ln) for s, ln in _lines(subs) if ln.get("confirmed", True) and ln["kind"] == "charge" and period_of(ln["date"]) == period]
    if not lines:
        return _raw(state="not_applicable", na_reason="no_invoices", value_kind="rate")
    billed = sum(ln["gross"] for _s, ln in lines)
    cancelling = sum(ln.get("refunded", 0) for _s, ln in lines if ln.get("refund_cancels_charge"))
    partial_refunds = sum(ln.get("refunded", 0) for _s, ln in lines if not ln.get("refund_cancels_charge"))
    col_final = sum(ln.get("collected_final", 0) for _s, ln in lines)
    col_platform = sum(ln.get("collected_platform", 0) for _s, ln in lines)
    denominator = billed - cancelling
    collected_total = col_final + col_platform
    per_sub_billed: dict[str, int] = defaultdict(int)
    per_sub_col: dict[str, int] = defaultdict(int)
    for s, ln in lines:
        per_sub_billed[s["key"]] += ln["gross"]
        per_sub_col[s["key"]] += ln.get("collected_final", 0) + ln.get("collected_platform", 0)
    if denominator <= 0:
        return _raw(state="not_applicable", na_reason="no_invoices", value_kind="rate", size=len(per_sub_billed))
    refunds = cancelling + partial_refunds  # net collected = collected - every refund (cancelling ones also leave the denominator)
    final_rate = rate(col_final - refunds, denominator)
    prov_rate = rate(collected_total - refunds, denominator)
    gross_rate = rate(collected_total, billed)
    cutoff = end + timedelta(days=int(cutoff_days)) if cutoff_days is not None else None
    period_open = cutoff is None or today <= cutoff
    in_term = payment_term_days is not None and any(ln["date"] + timedelta(days=int(payment_term_days)) >= today for _s, ln in lines)
    platform_share = rate(col_platform, collected_total) if collected_total else 0.0
    provisional = col_platform > 0 or period_open or in_term
    return _raw(
        value=final_rate, numerator=col_final - refunds, denominator=denominator, size=len(per_sub_billed), value_kind="rate",
        dominance={"denominator": max(per_sub_billed.values(), default=0), "numerator": max(per_sub_col.values(), default=0)},
        flags={"provisional": provisional, "final": not provisional, "platform_derived_share": platform_share, "period_open": period_open, "invoices_in_payment_term": in_term, "allocation_basis_label": "platform-derived (alloc-v1)" if col_platform else "DET-reported"},
        extra={"provisional_rate_incl_platform_derived": prov_rate, "gross_collection_rate": gross_rate, "net_collection_rate": prov_rate, "final_bases": ["billing-line", "invoice-single-line"]},
        amounts={"billed_fils": billed, "cancelling_refunds_fils": cancelling, "partial_refunds_fils": partial_refunds, "collected_final_fils": col_final, "collected_platform_derived_fils": col_platform},
    )


# --- K4 -----------------------------------------------------------------------------------------------------


def _window_start(s: dict) -> date | None:
    return s.get("invoice_date") or s.get("active_from")


def k4_flags(s: dict, *, window_days: int, until: date, since: date | None, params: dict) -> dict:
    """Evaluate the k4-v1 flags of one subscription (events inside the observation window, and inside
    [since, until] when the denominator rule is period based)."""
    ws = _window_start(s)
    we = ws + timedelta(days=window_days) if ws else None
    excluded_reasons = set(params.get("excluded_refund_reasons") or [])
    counted_reasons = set(params.get("counted_refund_reasons") or [])
    counted_categories = set(params.get("counted_complaint_categories") or [])
    out = {"refunded": False, "opted_out": False, "complained": False, "opt_out_status": None, "excluded": defaultdict(int)}

    def in_window(d: date) -> str:
        if ws is None or d < ws or (since is not None and d < since) or d > until:
            return "outside"
        if d > we:
            return "after_window"
        return "in"

    for r in s.get("refunds") or []:
        w = in_window(r["at"])
        if w == "outside":
            continue
        if r.get("reason") in excluded_reasons:
            out["excluded"]["refund_technical"] += 1
        elif counted_reasons and r.get("reason") not in counted_reasons:
            out["excluded"]["refund_unmapped"] += 1
        elif w == "after_window":
            out["excluded"]["after_window"] += 1
        else:
            out["refunded"] = True
    oo = s.get("opt_out")
    if oo:
        w = in_window(oo["at"])
        if w == "in":
            out["opted_out"] = True  # a rejected request stays counted as a request, marked rejected
            out["opt_out_status"] = oo.get("status", "pending")
        elif w == "after_window":
            out["excluded"]["after_window"] += 1
    for c in s.get("complaints") or []:
        w = in_window(c["at"])
        if w == "outside":
            continue
        cat = c.get("category") or "uncategorised"
        if cat == "uncategorised":
            out["excluded"]["complaint_uncategorised"] += 1
        elif cat not in counted_categories:
            out["excluded"]["complaint_non_subscription"] += 1
        elif w == "after_window":
            out["excluded"]["after_window"] += 1
        else:
            out["complained"] = True
    out["primary"] = "refunded" if out["refunded"] else "opted_out" if out["opted_out"] else "complained" if out["complained"] else None
    return out


def k4(subs: list[dict], period: str, today: date, params: dict) -> dict:
    if not subs:
        return _raw(state="no_data")
    start, end = period_bounds(period)
    window = int(params.get("observation_window_days", 90))
    rule = params.get("denominator_rule", "active_at_start_plus_started")
    if rule == "invoice_month_cohort":
        denom = [s for s in subs if s.get("invoice_date") and period_of(s["invoice_date"]) == period]
        since, until = None, today
    elif rule == "active_any_time":
        denom = [s for s in subs if s.get("active_from") and s["active_from"] <= end and (s.get("active_to") is None or s["active_to"] >= start)]
        since, until = start, min(end, today)
    else:  # active at period start + started in the period (spec default)
        denom = [s for s in subs if active_at(s, start) or (s.get("active_from") and start <= s["active_from"] <= end)]
        since, until = start, min(end, today)
    if not denom:
        return _raw(state="not_applicable", na_reason="no_subscriptions_in_period", value_kind="rate")
    evals = [(s, k4_flags(s, window_days=window, until=until, since=since, params=params)) for s in denom]
    window_open = any(_window_start(s) and _window_start(s) + timedelta(days=window) > today for s, _e in evals)
    flagged = [e for _s, e in evals if e["primary"]]
    excluded: dict[str, int] = defaultdict(int)
    for _s, e in evals:
        for k, v in e["excluded"].items():
            excluded[k] += v
    by_mode = []
    for m in ENROLMENT_MODES:
        group = [e for s, e in evals if s["enrolment_basis"] == m]
        by_mode.append({"enrolment_basis": m, "count": len(group), "flagged": sum(1 for e in group if e["primary"]), "rate": rate(sum(1 for e in group if e["primary"]), len(group))})
    primary_rows = [{"primary_reason": r, "count": sum(1 for e in flagged if e["primary"] == r)} for r in ("refunded", "opted_out", "complained")]
    flag_rows = [{"flag": f"flag_{r}", "count": sum(1 for _s, e in evals if e[r])} for r in ("refunded", "opted_out", "complained")]
    oo_rows = [{"optout_status": st, "count": sum(1 for _s, e in evals if e["opted_out"] and e["opt_out_status"] == st)} for st in ("det_confirmed", "pending", "rejected")]
    headline_basis = params.get("opt_out_headline", "requests")
    return _raw(
        value=rate(len(flagged), len(denom)), numerator=len(flagged), denominator=len(denom), size=len(denom), value_kind="rate",
        flags={"provisional": window_open, "final": not window_open, "window_state": "open" if window_open else "closed", "default_on_not_applicable": not any(s["enrolment_basis"] == "default_on_with_opt_out" for s in denom)},
        extra={"rule_version": params.get("rule_version", "k4-v1"), "config_version": params.get("config_version"), "observation_window_days": window, "denominator_rule": rule, "opt_out_headline": headline_basis, "precedence": ["refunded", "opted_out", "complained"]},
        counts={k: excluded.get(k, 0) for k in ("refund_technical", "refund_unmapped", "complaint_non_subscription", "complaint_uncategorised", "after_window")},
        tables=[
            _table("by_enrolment_mode", ["enrolment_basis"], by_mode, merge_other=False, count_keys=["flagged"], rate_keys={"rate": ("flagged", "count")}),
            _table("primary_reason", ["primary_reason"], primary_rows, merge_other=False),
            _table("flags", ["flag"], flag_rows, merge_other=False, include_total=False, rules={"complementary": False}),
            _table("optout_status", ["optout_status"], oo_rows, merge_other=False),
        ],
    )


# --- K5 -----------------------------------------------------------------------------------------------------


def k5(subs: list[dict], period: str, today: date) -> dict:
    if not subs:
        return _raw(state="no_data")
    start, end = period_bounds(period)
    due = [s for s in subs if s.get("renewal_due") and start <= s["renewal_due"] <= end and not s.get("cancelled_before_term_end")]
    if not due:
        ever_due = [s for s in subs if s.get("renewal_due") and s["renewal_due"] <= end]
        future = sorted(s["renewal_due"] for s in subs if s.get("renewal_due") and s["renewal_due"] > end)
        next90 = sum(1 for d in future if d <= today + timedelta(days=90))
        if not ever_due:
            return _raw(state="not_applicable", na_reason="no_renewals_due_yet", value_kind="rate", extra={"first_due_date": future[0].isoformat() if future else None}, counts={"due_next_90_days": next90})
        return _raw(state="not_applicable", na_reason="no_renewals_due_in_period", value_kind="rate", counts={"due_next_90_days": next90})
    renewed = [s for s in due if s.get("renewed")]
    by_basis = [{"enrolment_basis": m, "count": sum(1 for s in due if s["enrolment_basis"] == m), "renewed": sum(1 for s in renewed if s["enrolment_basis"] == m)} for m in ENROLMENT_MODES]
    for r in by_basis:
        r["rate"] = rate(r["renewed"], r["count"])
    markers = sorted({s.get("renewal_choice_marker") or "n/a" for s in due})
    by_marker = [{"renewal_choice_marker": mk, "count": sum(1 for s in due if (s.get("renewal_choice_marker") or "n/a") == mk), "renewed": sum(1 for s in renewed if (s.get("renewal_choice_marker") or "n/a") == mk)} for mk in markers]
    for r in by_marker:
        r["rate"] = rate(r["renewed"], r["count"])
    return _raw(
        value=rate(len(renewed), len(due)), numerator=len(renewed), denominator=len(due), size=len(due), value_kind="rate",
        flags={"provisional": today <= end},
        counts={"cancelled_before_term_end": sum(1 for s in subs if s.get("renewal_due") and start <= s["renewal_due"] <= end and s.get("cancelled_before_term_end"))},
        extra={"attribution": "cohort stamped at creation"},
        tables=[
            _table("by_enrolment_basis", ["enrolment_basis"], by_basis, merge_other=False, count_keys=["renewed"], rate_keys={"rate": ("renewed", "count")}),
            _table("by_renewal_choice_marker", ["renewal_choice_marker"], by_marker, count_keys=["renewed"], rate_keys={"rate": ("renewed", "count")}),
        ],
    )


# --- K6 -----------------------------------------------------------------------------------------------------


def k6_band(f: dict, *, grace_days: int | None) -> str:
    done = f.get("renewal_completed_at")
    prior = f["prior_expiry"]
    if done is not None:
        day = to_dubai(done).date() if isinstance(done, datetime) else done
        if day <= prior:
            return "on_time"
        if grace_days is not None and day <= prior + timedelta(days=int(grace_days)):
            return "renewed_in_grace"
        return "renewed_late"
    return "blocked" if f.get("block_reason_code") else "not_renewed"


def k6(renewals: list[dict], period: str, today: date, params: dict) -> dict:
    if not renewals:
        return _raw(state="no_data")
    start, end = period_bounds(period)
    mapping = {str(k).upper(): v for k, v in (params.get("status_mapping") or {}).items()}
    exclusions = {cat: {str(x).upper() for x in vals} for cat, vals in (params.get("exclusions") or {}).items()}
    suspended_rule = params.get("suspended_rule", "exclude")
    grace = params.get("grace_days")
    counts: dict[str, int] = defaultdict(int)
    bands: dict[str, int] = defaultdict(int)
    denom = 0
    early = 0
    for f in renewals:
        if f.get("issuing_authority", "DET") != "DET" or f.get("licence_type", "mainland") != "mainland":
            counts["out_of_scope"] += 1
            continue
        if not f.get("prior_expiry") or not (start <= f["prior_expiry"] <= end):
            continue
        raw = str(f.get("raw_status") or "").upper()
        if raw not in mapping:
            counts["unmapped_status"] += 1  # unknown + alert; never counted
            continue
        if raw in exclusions.get("cancelled_before_expiry", set()):
            counts["cancelled_before_expiry"] += 1
            continue
        if raw in exclusions.get("suspended", set()):
            if suspended_rule == "exclude":
                counts["suspended_excluded"] += 1
                continue
            counts["blocked"] += 1
            bands["blocked"] += 1
            denom += 1
            continue
        b = k6_band(f, grace_days=grace)
        bands[b] += 1
        if b == "blocked":
            counts["blocked"] += 1
        denom += 1
        done = f.get("renewal_completed_at")
        if b == "on_time" and done is not None and (to_dubai(done).date() if isinstance(done, datetime) else done) < f["prior_expiry"]:
            early += 1
    if denom == 0:
        return _raw(state="not_applicable", na_reason="no_expiries_in_period", value_kind="rate", counts=dict(counts))
    final_after = int(params.get("final_after_days", 30))
    provisional = today <= end + timedelta(days=final_after)
    band_rows = [{"band": b, "count": bands.get(b, 0)} for b in ("on_time", "renewed_in_grace", "renewed_late", "not_renewed", "blocked")]
    return _raw(
        value=rate(bands.get("on_time", 0), denom), numerator=bands.get("on_time", 0), denominator=denom, size=denom, value_kind="rate",
        flags={"provisional": provisional, "final": not provisional, "unmapped_status_alert": counts.get("unmapped_status", 0) > 0, "grace_length": "unknown" if grace is None else grace},
        counts={**{k: counts.get(k, 0) for k in ("cancelled_before_expiry", "suspended_excluded", "blocked", "unmapped_status", "out_of_scope")}, "early_renewals": early},
        extra={"suspended_rule": suspended_rule, "cutoff_zone": "Asia/Dubai", "signal": "renewal_completed_at"},
        tables=[_table("bands", ["band"], band_rows, merge_other=False)],
    )


# --- K7 / K8 ------------------------------------------------------------------------------------------------

MEASURABLE_DUE_SOURCES = ("FTA_NOTICE", "FTA_PORTAL_STATUS", "RULE_DERIVED")
MEASURABLE_FILED_SOURCES = ("company_reported_receipt", "fta_status")


def k78(returns: list[dict], period: str, today: date, params: dict, *, which: str) -> dict:
    if not returns:
        return _raw(state="no_data")
    start, end = period_bounds(period)
    min_share = float(params.get("min_measurable_share", 60))
    min_returns = int(params.get("min_returns", 30))
    due, measured, unverified, late, on_time, ext = [], [], 0, 0, 0, 0
    by_source: dict[str, int] = defaultdict(int)
    not_measurable: dict[str, int] = defaultdict(int)
    computed_only = 0
    for r in returns:
        d = r.get("due_used") or r.get("statutory_due")
        if d is None or not (start <= d <= end):
            continue
        due.append(r)
        by_source[r.get("deadline_source") or "unknown"] += 1
        if r.get("extension_recorded"):
            ext += 1
        if r.get("deadline_source") == "RULE_DERIVED":
            computed_only += 1
        owner_only = r.get("deadline_source") == "OWNER_ENTERED" or r.get("filed_source") == "owner_declaration"
        if owner_only:
            unverified += 1
            not_measurable["owner_entered_only"] += 1
            continue
        if r.get("filed_date") is None or r.get("filed_source") not in MEASURABLE_FILED_SOURCES:
            not_measurable["filed_date_not_available"] += 1
            continue
        if r.get("deadline_source") not in MEASURABLE_DUE_SOURCES:
            not_measurable["due_date_not_determinable"] += 1
            continue
        measured.append(r)
        if r["filed_date"] > d:
            late += 1
        else:
            on_time += 1
    if not due:
        return _raw(state="not_applicable", na_reason="no_returns_due", value_kind="rate")
    share = rate(len(measured), len(due)) or 0.0
    rate_shown = share >= min_share and len(measured) >= min_returns
    num = late if which == "K7" else on_time
    return _raw(
        value=rate(num, len(measured)) if (rate_shown and measured) else None, numerator=num, denominator=len(measured), size=len(due), value_kind="rate",
        flags={"partial": share < 100.0, "coverage_share": share, "rate_shown": rate_shown, "counts_only": not rate_shown, "source_label": "owner-reported, not FTA-verified", "provisional": today <= end},
        tables=[
            _table("coverage", ["measurability"], [{"measurability": "measured", "count": len(measured)}, {"measurability": "not_measurable", "count": len(due) - len(measured)}], merge_other=False),
            # owner-entered-only returns are the 'unverified' row: excluded from the headline, shown separately
            _table("not_measurable_reasons", ["reason"], [{"reason": "unverified_owner_entered_only", "count": unverified}, {"reason": "filed_date_not_available", "count": not_measurable.get("filed_date_not_available", 0)}, {"reason": "due_date_not_determinable", "count": not_measurable.get("due_date_not_determinable", 0)}], merge_other=False),
            _table("by_deadline_source", ["deadline_source"], [{"deadline_source": k, "count": v} for k, v in sorted(by_source.items())]),
        ],
        counts={"due": len(due), "extension_recorded": ext},
        extra={"coverage_text": {"measured": len(measured), "due": len(due)}, "min_measurable_share": min_share, "min_returns": min_returns},
    )


# --- K19 ----------------------------------------------------------------------------------------------------

K19_STATUSES = ("draft", "in_review", "signed", "rejected")
NOT_CURRENT = ("superseded", "revoked", "withdrawn")


def k19(deliverables: list[dict], params: dict) -> dict:
    sig_table = params.get("sig_table") or {}
    excluded_types = set(params.get("excluded_types") or [])
    rows = [d for d in deliverables if d.get("type") not in excluded_types]
    if not rows:
        return _raw(state="no_data")
    req, no_sig = [], defaultdict(int)
    for d in rows:
        required = sig_table.get(d.get("type"), True)  # unknown type: fail closed (signature required)
        if required:
            req.append(d)
        elif d.get("status") not in NOT_CURRENT:
            no_sig[d.get("type")] += 1
    current = [d for d in req if d.get("status") not in NOT_CURRENT]
    status_rows = [{"status": st, "count": sum(1 for d in current if d.get("status") == st)} for st in K19_STATUSES]
    issued = sum(1 for d in current if d.get("status") == "issued")
    unsigned_released = sum(1 for d in req if (d.get("released") or d.get("status") == "issued") and not d.get("signed"))
    denom = sum(1 for d in current if d.get("status") in ("draft", "in_review", "signed", "issued"))
    signed = sum(1 for d in current if d.get("status") in ("signed", "issued"))
    mix_total = sum(r["count"] for r in status_rows)  # headline = total of the status mix table (no differencing between tables)
    return _raw(
        value=mix_total, numerator=signed, denominator=denom, size=mix_total, value_kind="count",
        flags={"unsigned_release_alert": unsigned_released > 0},
        counts={"issued_audit_reports": issued, "not_current": sum(1 for d in req if d.get("status") in NOT_CURRENT), "unsigned_releases": unsigned_released},
        extra={"signed_share": rate(signed, denom), "rule_version": params.get("rule_version", "sig-v1"), "no_signature_required_by_type": dict(no_sig)},
        tables=[
            _table("status_mix", ["status"], status_rows, merge_other=False),
            _table("no_signature_required", ["type"], [{"type": t, "count": c} for t, c in sorted(no_sig.items())], merge_other=True, include_total=False),
        ],
    )


# --- K20 ----------------------------------------------------------------------------------------------------

K20_STATES = ("likely_required", "likely_not_required", "cannot_determine")


def k20(evaluations: list[dict], active_keys: set[str], tax_period: str | None) -> dict:
    if not active_keys and not evaluations:
        return _raw(state="no_data")
    periods = sorted({e["period"] for e in evaluations})
    tp = tax_period or (periods[-1] if periods else None)
    latest: dict[str, dict] = {}
    for e in evaluations:
        if e["period"] != tp or e["licence_key"] not in active_keys:
            continue
        cur = latest.get(e["licence_key"])
        if cur is None or e["evaluated_at"] > cur["evaluated_at"]:
            latest[e["licence_key"]] = e
    evaluated = len(latest)
    not_yet = len(active_keys - set(latest))
    if evaluated == 0:
        return _raw(state="not_applicable", na_reason="not_yet_evaluated", value_kind="rate", counts={"not_yet_evaluated": not_yet})
    rows = [{"result": st, "count": sum(1 for e in latest.values() if e["result"] == st)} for st in K20_STATES]
    for r in rows:
        r["share"] = rate(r["count"], evaluated)
        r["_evaluated"] = evaluated
    required = rows[0]["count"]
    return _raw(
        value=rate(required, evaluated), numerator=required, denominator=evaluated, size=evaluated, value_kind="rate",
        counts={"not_yet_evaluated": not_yet},
        extra={"tax_period": tp, "rule": "latest evaluation per licence per period", "label": "indicator, not a legal determination"},
        tables=[_table("by_result", ["result"], rows, merge_other=False, rate_keys={"share": ("count", "_evaluated")})],
    )


# --- K29 ----------------------------------------------------------------------------------------------------


def k29(subs: list[dict], as_of: date, params: dict) -> dict:
    window = int(params.get("window_days", 30))
    qualifying = set(params.get("qualifying_events") or [])
    active = [s for s in subs if active_at(s, as_of)]
    if not active:
        return _raw(state="no_data") if not subs else _raw(state="not_applicable", na_reason="no_active_licences", value_kind="rate")
    since = as_of - timedelta(days=window)
    users = [s for s in active if any(e["type"] in qualifying and since < e["at"] <= as_of for e in (s.get("events") or []))]
    return _raw(value=rate(len(users), len(active)), numerator=len(users), denominator=len(active), size=len(active), value_kind="rate", extra={"window_days": window, "qualifying_events": sorted(qualifying), "excluded": "system-generated events"})
