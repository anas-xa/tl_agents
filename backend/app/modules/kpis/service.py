"""SC14 DET KPI service (E9-S1 F1-F6): computation, suppression, logging, export, per-licence view, settings.

Every figure goes through ``app.modules.kpis.suppression`` (the one shared engine), so the screen, the API and
the CSV export carry the same cells. Every view, export, per-licence view, refusal and configuration change is
written to the audit trail with references and codes only (no figures).
"""

from __future__ import annotations

import csv
import io
from collections import defaultdict
from datetime import date, timedelta
from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.core.errors import Forbidden, NotFound, ValidationFailed
from app.core.time import dubai_today, to_dubai, utcnow
from app.modules.access.service import Principal
from app.modules.audit.service import record_event
from app.modules.config.service import config_history, get_config, rule_params, set_config
from app.modules.kpis import calculators as calc
from app.modules.kpis import suppression as sup
from app.modules.kpis.catalogue import CATALOGUE_VERSION, KPI_INDEX, definitions
from app.modules.kpis.facts import data_version, fixture_facts, licence_facts_active_keys, platform_facts
from app.modules.kpis.models import KpiCalculationRun, KpiExport, KpiFixtureLicence
from app.modules.kpis.strings import STRINGS, bi

INCLUDE_FIXTURE = "det_dashboard.include_demo_fixture"
PERIOD_MONTHS = 12
SERIES_MONTHS = 6
BREAKDOWN_DIMS = ("month", "cohort", "wave", "enrolment_basis", "licence_category", "payment_status", "payment_method")
SUB_KPIS = ("K1", "K2", "K3", "K4", "K5", "K29")


# --- configuration -------------------------------------------------------------------------------------------


def params(db: Session) -> dict:
    """All calculator parameters, read from versioned configuration (nothing hard-coded)."""
    excluded = (get_config(db, "k4.refund_reason_mapping", {}) or {}).get("excluded", ["failed_payment", "duplicate_payment", "technical_error"])
    categories = get_config(db, "complaint.categories", []) or []
    k4_rule = rule_params(db, "k4-v1", {})
    return {
        "k3_cutoff_days": get_config(db, "k3.provisional_cutoff_days", None),
        "k3_payment_term_days": get_config(db, "det_dashboard.k3_payment_term_days", 30),
        "cancelling_refund_reasons": get_config(db, "det_dashboard.k3_cancelling_refund_reasons", []),
        "complaint_categories": categories,
        "qualifying_events": get_config(db, "det_dashboard.k29_qualifying_events", []),
        "k4": {
            "rule_version": get_config(db, "k4.rule_version", "k4-v1"),
            "config_version": f"k4@{get_config(db, 'k4.rule_version', 'k4-v1')}/window={get_config(db, 'k4.observation_window_days', 90)}",
            "observation_window_days": int(get_config(db, "k4.observation_window_days", k4_rule.get("observation_window_days", 90)) or 90),
            "excluded_refund_reasons": excluded,
            "counted_refund_reasons": get_config(db, "det_dashboard.k4_counted_refund_reasons", []),
            "counted_complaint_categories": [c["code"] for c in categories if c.get("k4")] if categories else get_config(db, "det_dashboard.k4_counted_complaint_categories", []),
            "denominator_rule": get_config(db, "det_dashboard.k4_denominator_rule", "active_at_start_plus_started"),
            "opt_out_headline": get_config(db, "det_dashboard.k4_opt_out_headline", "requests"),
        },
        "k6": {
            "status_mapping": (get_config(db, "det_intake.status_mapping", {}) or {}).get("map", {}),
            "exclusions": get_config(db, "det_intake.k6_status_mapping", {}) or {},
            "suspended_rule": get_config(db, "det_dashboard.k6_suspended_rule", "exclude"),
            "grace_days": get_config(db, "det_dashboard.k6_grace_length_days", None),
            "final_after_days": get_config(db, "det_dashboard.k6_final_after_days", 30),
        },
        "k78": {"min_measurable_share": get_config(db, "det_dashboard.k7k8_min_measurable_share", 60), "min_returns": get_config(db, "det_dashboard.k7k8_min_returns", 30)},
        "k19": {"sig_table": get_config(db, "det_dashboard.k19_signature_required", {}), "excluded_types": get_config(db, "det_dashboard.k19_excluded_types", []), "rule_version": "sig-v1"},
        "k29": {"window_days": get_config(db, "det_dashboard.k29_window_days", 30), "qualifying_events": get_config(db, "det_dashboard.k29_qualifying_events", [])},
    }


def load_facts(db: Session, cfg: dict | None = None) -> dict:
    """Demo fixture (labelled 'Demo data') when switched on and present, otherwise the platform modules."""
    cfg = cfg or params(db)
    if bool(get_config(db, INCLUDE_FIXTURE, False)) and db.scalar(select(KpiFixtureLicence.id).limit(1)) is not None:
        facts = fixture_facts(db)
    else:
        facts = platform_facts(db, cfg)
    facts["data_version"] = data_version({k: facts.get(k) for k in ("subs", "renewals", "returns", "deliverables", "evaluations")})
    return facts


# --- periods and filters --------------------------------------------------------------------------------------


def available_periods(today: date | None = None) -> list[str]:
    cur = calc.period_of(today or dubai_today())
    return [calc.shift_period(cur, -i) for i in range(PERIOD_MONTHS)]


def validate_filters(facts: dict, period: str | None, cohort: str | None, payment_status: str | None, today: date) -> dict:
    periods = available_periods(today)
    period = period or periods[0]
    if period not in periods:
        raise ValidationFailed("only fixed monthly periods are available", reason_code="PERIOD_NOT_ALLOWED", details={"allowed": periods})
    return {"period": period, "cohort": cohort or None, "payment_status": payment_status or None}


def filter_facts(facts: dict, filters: dict) -> dict:
    out = dict(facts)
    cohort, pstatus = filters.get("cohort"), filters.get("payment_status")
    if cohort:
        for k in ("subs", "renewals", "returns", "deliverables", "evaluations"):
            out[k] = [f for f in facts.get(k, []) if f.get("cohort") == cohort]
    if pstatus:
        out["subs"] = [s for s in out["subs"] if any(ln.get("payment_status") == pstatus for ln in s.get("lines") or [])]
    return out


def filter_options(facts: dict) -> dict:
    return {
        "cohorts": sorted({s.get("cohort") for s in facts.get("subs", []) if s.get("cohort")}),
        "payment_statuses": sorted({ln.get("payment_status") for s in facts.get("subs", []) for ln in s.get("lines") or [] if ln.get("payment_status")}),
    }


def population(facts: dict) -> int:
    return len(facts.get("subs", []))


# --- raw computation -------------------------------------------------------------------------------------------


def compute_raw(kpi_id: str, facts: dict, period: str, today: date, cfg: dict) -> dict:
    subs = facts.get("subs", [])
    if kpi_id == "K1":
        return calc.k1(subs, period, today)
    if kpi_id == "K2":
        return calc.k2(subs, period, today)
    if kpi_id == "K3":
        return calc.k3(subs, period, today, cutoff_days=cfg["k3_cutoff_days"], payment_term_days=cfg["k3_payment_term_days"])
    if kpi_id == "K4":
        return calc.k4(subs, period, today, cfg["k4"])
    if kpi_id == "K5":
        return calc.k5(subs, period, today)
    if kpi_id == "K6":
        return calc.k6(facts.get("renewals", []), period, today, cfg["k6"])
    if kpi_id in ("K7", "K8"):
        return calc.k78(facts.get("returns", []), period, today, cfg["k78"], which=kpi_id)
    if kpi_id == "K19":
        return calc.k19(facts.get("deliverables", []), cfg["k19"])
    if kpi_id == "K20":
        _s, end = calc.period_bounds(period)
        return calc.k20(facts.get("evaluations", []), licence_facts_active_keys(subs, min(end, today)), None)
    if kpi_id == "K29":
        _s, end = calc.period_bounds(period)
        return calc.k29(subs, min(end, today), cfg["k29"])
    raise NotFound("unknown KPI", reason_code="KPI_NOT_FOUND")


# --- presentation with suppression -----------------------------------------------------------------------------

SAFE_EXTRA = {
    "K1": ("as_of", "note"), "K2": ("basis", "projection_label"), "K3": ("final_bases",), "K4": ("rule_version", "config_version", "observation_window_days", "denominator_rule", "opt_out_headline", "precedence"),
    "K5": ("attribution", "first_due_date"), "K6": ("suspended_rule", "cutoff_zone", "signal"), "K7": ("coverage_text", "min_measurable_share", "min_returns"), "K8": ("coverage_text", "min_measurable_share", "min_returns"),
    "K19": ("signed_share", "rule_version"), "K20": ("tax_period", "rule", "label"), "K29": ("window_days", "qualifying_events", "excluded"),
}
RATE_EXTRA = {"K3": ("provisional_rate_incl_platform_derived", "gross_collection_rate", "net_collection_rate")}


def _dominated(amount: int | None, top: int | None, rules: dict) -> bool:
    if not rules.get("dominance", True) or not amount:
        return False
    return (top or 0) / abs(amount) > float(rules.get("dominance_share", 0.5))


def present(kdef: dict, raw: dict | None, n: int, rules: dict, *, period: str, facts: dict, previous: dict | None = None) -> dict:
    kid = kdef["kpi_id"]
    rec: dict[str, Any] = {
        "kpi_id": kid, "name": {"en": kdef["name_en"], "ar": kdef["name_ar"]}, "definition": {"en": kdef["definition_en"], "ar": kdef["definition_ar"]}, "formula_text": kdef["formula_text"],
        "unit": kdef["unit"], "target": kdef["target"], "refresh_period": kdef["refresh_period"], "sources": kdef["source_list"], "rule_version_id": kdef["rule_version_id"],
        "release_state": kdef["release_state"], "planned_phase_label": kdef["planned_phase_label"], "group": kdef["group"], "is_fairness_indicator": kdef["is_fairness_indicator"],
        "dimensions": kdef["dimensions"], "period_key": period, "catalogue_version": kdef.get("catalogue_version", CATALOGUE_VERSION),
    }
    if kdef["release_state"] != "live":
        rec.update(state="not_yet_available", message=bi("not_yet_available", x=kdef["planned_phase_label"] or "—"))
        return rec
    assert raw is not None
    missing = facts.get("missing", {}).get(kid, [])
    total_sources = len(kdef["source_list"]) if missing else 0
    rec["flags"] = {"stale": False, "restated": False, "partial": bool(missing)}
    if missing:
        m = max(total_sources, len(missing) + 1)
        rec["flags"].update(sources_included_n=m - len(missing), sources_total_m=m, missing_sources=missing)
        rec["partial_message"] = bi("partial", n=m - len(missing), m=m)
    rec["state"] = raw["state"]
    if raw["state"] == "no_data":
        rec["message"] = bi("no_data")
        return rec
    counts = {k: sup.suppress_count(v, n) for k, v in (raw.get("counts") or {}).items()}
    if raw["state"] == "not_applicable":
        rec.update(message=bi("not_applicable"), na_reason=raw.get("na_reason"), na_reason_text=bi(f"na.{raw.get('na_reason')}") if f"na.{raw.get('na_reason')}" in STRINGS else None, counts=counts)
        rec["extra"] = {k: v for k, v in (raw.get("extra") or {}).items() if k in SAFE_EXTRA.get(kid, ())}
        return rec
    size = raw.get("size") or 0
    kind = raw["value_kind"]
    hidden_value = False
    if kind == "count":
        cell = sup.suppress_count(raw["value"], n, zero_shown=True)
        hidden_value = bool(cell and cell["suppressed"])
    elif kind == "amount":
        hidden_value = size < n or _dominated(raw["value"], raw["dominance"].get("value"), rules)
        state = "suppressed_dominance" if (size >= n and hidden_value) else "suppressed_fewer_than_N"
        cell = sup.suppressed_cell(n, state) if hidden_value else sup.shown_cell(raw["value"])
    else:  # rate
        # a rate of counts also reveals its complement (denominator - numerator): both must be >= N or zero
        num_small = kid not in ("K3",) and (sup.is_small(raw.get("numerator"), n) or sup.is_small((raw.get("denominator") or 0) - (raw.get("numerator") or 0), n))
        dom = kid == "K3" and (_dominated(raw.get("denominator"), raw["dominance"].get("denominator"), rules) or _dominated(raw.get("numerator"), raw["dominance"].get("numerator"), rules))
        hidden_value = size < n or num_small or dom
        cell = sup.suppressed_cell(n, "suppressed_dominance" if (dom and size >= n and not num_small) else "suppressed_fewer_than_N") if hidden_value else sup.shown_cell(raw["value"])
    rec["value"] = cell
    if kind == "rate" and kid != "K3":
        if size < n:
            rec["numerator"] = rec["denominator"] = sup.suppressed_cell(n)
        else:
            rec["numerator"] = sup.suppressed_cell(n) if num_small else sup.suppress_count(raw.get("numerator"), n)
            rec["denominator"] = sup.suppress_count(raw.get("denominator"), n)
    if kid == "K19":
        signed_small = size < n or sup.is_small(raw.get("numerator"), n) or sup.is_small((raw.get("denominator") or 0) - (raw.get("numerator") or 0), n)
        (raw.get("extra") or {})["signed_share"] = None if signed_small else (raw.get("extra") or {}).get("signed_share")
    rec["counts"] = counts
    amounts = raw.get("amounts") or {}
    if amounts:
        rec["amounts_fils"] = {k: (sup.suppressed_cell(n, cell["cell_state"]) if hidden_value else sup.shown_cell(v)) for k, v in amounts.items()}
    flags = dict(raw.get("flags") or {})
    if kid == "K3" and hidden_value:
        flags.pop("platform_derived_share", None)
    rec["flags"].update(flags)
    rec["extra"] = {k: v for k, v in (raw.get("extra") or {}).items() if k in SAFE_EXTRA.get(kid, ())}
    for k in RATE_EXTRA.get(kid, ()):
        rec["extra"][k] = sup.suppressed_cell(n) if hidden_value else sup.shown_cell((raw.get("extra") or {}).get(k))
    rec["breakdowns"] = {}
    for t in raw.get("tables") or []:
        rec["breakdowns"][t["id"]] = sup.suppress_table(
            t["rows"], t["dims"], [], n, count_keys=t.get("count_keys", ()), amount_keys=t.get("amount_keys", ()), rate_keys=t.get("rate_keys"),
            merge_other=t.get("merge_other"), include_total=t.get("include_total", True), rules={**rules, **(t.get("rules") or {})},
        )
    if kid == "K4":
        _k4_consistency(rec, n)
        if rec["flags"].get("window_state") == "open":
            rec["window_message"] = bi("window_open")
    if kid == "K3" and rec["flags"].get("provisional"):
        rec["provisional_message"] = bi("provisional_k3")
    if kid == "K2" and rec["flags"].get("vat_treatment_unconfirmed"):
        rec["vat_message"] = bi("vat_unconfirmed")
    if kid in ("K7", "K8"):
        rec["source_label"] = bi("owner_reported")
        ct = (raw.get("extra") or {}).get("coverage_text") or {}
        if size >= n and not sup.is_small(ct.get("measured"), n) and not sup.is_small((ct.get("due") or 0) - (ct.get("measured") or 0), n):
            rec["coverage_message"] = bi("based_on", measured=ct.get("measured"), due=ct.get("due"))
        else:
            rec["extra"].pop("coverage_text", None)
            rec["flags"].pop("coverage_share", None)
        if not raw["flags"].get("rate_shown"):
            rec["value"] = None
            rec["counts_only"] = True
    if kid == "K19" and raw["flags"].get("unsigned_release_alert"):
        rec["alert"] = bi("unsigned_release_alert")
    if kid == "K6" and raw["flags"].get("unmapped_status_alert"):
        rec["alert"] = bi("unmapped_status_alert")
    # trend vs previous fixed period (suppressed if either group is below N)
    if previous is not None and previous.get("state") == "value" and not hidden_value and kind in ("count", "rate", "amount") and raw.get("value") is not None and previous.get("value") is not None:
        prev_hidden = (previous.get("size") or 0) < n or (kind == "rate" and kid != "K3" and (sup.is_small(previous.get("numerator"), n) or sup.is_small((previous.get("denominator") or 0) - (previous.get("numerator") or 0), n)))
        if prev_hidden:
            rec["trend"] = sup.suppressed_cell(n)
        else:
            diff = raw["value"] - previous["value"]
            rec["trend"] = sup.suppress_difference(round(diff, 1) if isinstance(diff, float) else diff, previous.get("size") or 0, size, n)
    return rec


def _k4_consistency(rec: dict, n: int) -> None:
    """flag_refunded always equals the primary 'refunded' count (highest precedence): hide both together."""
    prim = rec["breakdowns"].get("primary_reason", {})
    flags = rec["breakdowns"].get("flags", {})
    p_ref = next((r for r in prim.get("rows", []) if r.get("primary_reason") == "refunded"), None)
    if p_ref is None and prim.get("state") == "not_shown_group_too_small":
        p_ref = {"count": sup.suppressed_cell(n)}
    for r in flags.get("rows", []):
        if r.get("flag") == "flag_refunded" and p_ref is not None and p_ref["count"].get("suppressed"):
            r["count"] = sup.suppressed_cell(n, p_ref["count"]["cell_state"])
            r["cell_state"] = p_ref["count"]["cell_state"]
            flags["notice"] = True
    by_mode = rec["breakdowns"].get("by_enrolment_mode", {})
    for r in by_mode.get("rows", []):
        if r.get("enrolment_basis") == "default_on_with_opt_out" and not r["count"].get("suppressed") and r["count"].get("value") == 0:
            r["state"] = "not_applicable"
            r["na_reason_text"] = bi("na.no_default_on")
    if rec["flags"].get("default_on_not_applicable"):
        rec["default_on_message"] = bi("na.no_default_on")


# --- calculation runs (restatements) ---------------------------------------------------------------------------


def record_run(db: Session, kpi_id: str, period: str, raw: dict, source: str, today: date) -> dict:
    value_hash = data_version({"value": raw.get("value"), "numerator": raw.get("numerator"), "denominator": raw.get("denominator"), "counts": raw.get("counts")})
    dv = data_version(raw)
    last = db.scalar(select(KpiCalculationRun).where(KpiCalculationRun.kpi_id == kpi_id, KpiCalculationRun.period_key == period, KpiCalculationRun.data_source == source).order_by(desc(KpiCalculationRun.created_at)).limit(1))
    _start, end = calc.period_bounds(period)
    closed = today > end + timedelta(days=int(get_config(db, "k3.provisional_cutoff_days", 30) or 30))
    if last is not None and last.data_version == dv:
        return {"restated": last.restated, "restatement_note": last.restatement_note, "run_id": last.run_id}
    restated = bool(last is not None and last.period_closed and last.value_hash != value_hash)
    note = STRINGS["restated"]["en"] if restated else None
    run = KpiCalculationRun(kpi_id=kpi_id, period_key=period, data_source=source, rule_version=KPI_INDEX[kpi_id]["rule_version_id"], catalogue_version=CATALOGUE_VERSION, data_version=dv, value_hash=value_hash, period_closed=closed, restated=restated or bool(last and last.restated), restatement_note=note or (last.restatement_note if last else None), supersedes_run_id=last.run_id if last else None)
    db.add(run)
    db.flush()
    record_event(db, event_type="KPI_CALCULATION_RUN", category="system", subject_type="kpi", subject_id=kpi_id, details={"run_id": run.run_id, "kpi_id": kpi_id, "period": period, "rule_version": run.rule_version, "data_version": dv, "restated": restated, "source": source})
    return {"restated": run.restated, "restatement_note": run.restatement_note, "run_id": run.run_id}


# --- dashboard ---------------------------------------------------------------------------------------------------


def _meta(db: Session, facts: dict, n: int, rules: dict) -> dict:
    now = utcnow()
    demo = facts["source"] == "demo_fixture"
    return {
        "data_source": facts["source"], "source_label": bi("demo_data") if demo else bi("pilot_data"), "demo_data": demo,
        "refresh_time": now.isoformat(), "data_as_of": to_dubai(now).isoformat(timespec="minutes"), "timezone": "Asia/Dubai", "data_version": facts["data_version"],
        "catalogue_version": CATALOGUE_VERSION, "suppression": {"min_group_size": n, "label": bi("n_label", n=n), "status": "provisional, set by DET", "rule_id": sup.RULE_ID, "rules": {k: rules[k] for k in ("primary", "complementary", "filter_blocking", "totals_only_when_at_least_n", "dominance", "merge_other")}},
        "banner": bi("banner"), "revenue_note": bi("revenue_note"), "projection_label": bi("projection"), "coming_later": bi("coming_later"), "empty": bi("empty"),
        "loading_slow_after_seconds": get_config(db, "det_dashboard.loading_slow_after_seconds", 10),
    }


def dashboard(db: Session, principal: Principal, *, period: str | None = None, cohort: str | None = None, payment_status: str | None = None, log: bool = True) -> dict:
    today = dubai_today()
    cfg = params(db)
    facts = load_facts(db, cfg)
    n = sup.min_group_size(db)
    rules = sup.suppression_rules(db)
    filters = validate_filters(facts, period, cohort, payment_status, today)
    payload: dict[str, Any] = {**_meta(db, facts, n, rules), "filters": filters, "periods": available_periods(today), "filter_options": filter_options(facts), "can_manage_n": "det.min_group_size.manage" in _perms(db, principal), "can_export": "det.aggregates.export" in _perms(db, principal)}
    filtered = filter_facts(facts, filters)
    any_filter = bool(filters["cohort"] or filters["payment_status"])
    if any_filter and sup.filter_blocked(population(filtered), n, rules):
        payload.update(state="blocked", blocked=sup.blocked_result(n), kpis=[{"kpi_id": d["kpi_id"], "name": {"en": d["name_en"], "ar": d["name_ar"]}, "definition": {"en": d["definition_en"], "ar": d["definition_ar"]}, "group": d["group"], "release_state": d["release_state"], "planned_phase_label": d["planned_phase_label"], "state": "blocked" if d["release_state"] == "live" else "not_yet_available", "message": bi("not_yet_available", x=d["planned_phase_label"] or "—") if d["release_state"] != "live" else None} for d in definitions(db)])
    else:
        payload["state"] = "empty" if not facts.get("subs") else "ready"
        kpis = []
        prev_period = calc.shift_period(filters["period"], -1)
        for d in definitions(db):
            if d["release_state"] != "live":
                kpis.append(present(d, None, n, rules, period=filters["period"], facts=filtered))
                continue
            try:
                raw = compute_raw(d["kpi_id"], filtered, filters["period"], today, cfg)
                prev = compute_raw(d["kpi_id"], filtered, prev_period, today, cfg) if d["kpi_id"] not in ("K19", "K20") else None
                rec = present(d, raw, n, rules, period=filters["period"], facts=filtered, previous=prev)
                if not any_filter and raw["state"] == "value":
                    run = record_run(db, d["kpi_id"], filters["period"], raw, facts["source"], today)
                    rec["flags"]["restated"] = run["restated"]
                    if run["restated"]:
                        rec["restatement_note"] = bi("restated")
            except Exception as exc:  # noqa: BLE001 - one failing KPI never blocks the others
                rec = {"kpi_id": d["kpi_id"], "name": {"en": d["name_en"], "ar": d["name_ar"]}, "definition": {"en": d["definition_en"], "ar": d["definition_ar"]}, "group": d["group"], "release_state": d["release_state"], "state": "error", "error_code": type(exc).__name__}
            kpis.append(rec)
        payload["kpis"] = kpis
    if log:
        record_event(db, event_type="DET_DASHBOARD_VIEWED", category="data_access", actor_key=principal.actor_key, actor_role=principal.primary_role(), details={"screen": "SC14", "kpi_ids": [k["kpi_id"] for k in payload["kpis"]], "filters": filters, "data_version": facts["data_version"], "min_group_size": n, "state": payload["state"]})
    return payload


def _perms(db: Session, principal: Principal) -> set[str]:
    from app.modules.access.service import permissions_for

    return permissions_for(db, principal, None)


# --- breakdowns ---------------------------------------------------------------------------------------------------


def _row_from_raw(kid: str, raw: dict) -> dict:
    if raw["state"] != "value":
        return {"count": raw.get("size") or 0}
    if kid in ("K1", "K19"):
        return {"count": raw.get("size") or 0}
    if kid == "K2":
        return {"count": raw["size"], "net_billed_fils": raw["value"], "max_contribution": {"net_billed_fils": raw["dominance"].get("value", 0)}}
    if kid == "K3":
        am = raw.get("amounts") or {}
        return {"count": raw["size"], "billed_fils": raw["denominator"], "collected_fils": raw["numerator"], "rate": raw["value"], "max_contribution": {"billed_fils": raw["dominance"].get("denominator", 0), "collected_fils": raw["dominance"].get("numerator", 0)}, "_platform": am.get("collected_platform_derived_fils", 0)}
    if kid in ("K7", "K8"):
        return {"count": raw["size"], "measured": raw.get("denominator") or 0, "numerator": raw["numerator"]}
    return {"count": raw["size"], "numerator": raw["numerator"], "denominator": raw["denominator"], "rate": raw["value"]}


def _table_spec(kid: str) -> dict:
    if kid in ("K1", "K19"):
        return {}
    if kid == "K2":
        return {"amount_keys": ["net_billed_fils"]}
    if kid == "K3":
        return {"amount_keys": ["billed_fils", "collected_fils"], "rate_keys": {"rate": ("collected_fils", "billed_fils")}}
    if kid in ("K7", "K8"):
        return {"count_keys": ["measured", "numerator"]}
    return {"count_keys": ["numerator", "denominator"], "rate_keys": {"rate": ("numerator", "denominator")}}


def _group_value(kid: str, fact: dict, dim: str) -> list[str]:
    if dim == "payment_status":
        return sorted({ln.get("payment_status") or "unknown" for ln in fact.get("lines") or []}) or ["unknown"]
    if dim == "payment_method":
        return [fact.get("payment_method") or "unknown"]
    return [fact.get(dim) or "unknown"]


def breakdown(db: Session, kpi_id: str, dimension: str, facts: dict, period: str, today: date, cfg: dict, n: int, rules: dict) -> dict:
    kdef = next(d for d in definitions(db) if d["kpi_id"] == kpi_id)
    if dimension not in kdef["dimensions"]:
        raise ValidationFailed("this breakdown is not available for this figure", reason_code="DIMENSION_NOT_ALLOWED", details={"allowed": kdef["dimensions"]})
    spec = _table_spec(kpi_id)
    rows: list[dict] = []
    if dimension == "month":
        for i in range(SERIES_MONTHS - 1, -1, -1):
            p = calc.shift_period(period, -i)
            raw = compute_raw(kpi_id, facts, p, today, cfg)
            rows.append({"month": p, **_row_from_raw(kpi_id, raw)})
        # a time series is never merged into 'Other': primary + complementary only
        table = sup.suppress_table(rows, ["month"], [], n, merge_other=False, include_total=False, rules=rules, **spec)
        # keep empty months visible as structure (size 0 rows are dropped by the engine)
        present_months = {r["month"] for r in table["rows"]}
        table["rows"] = sorted(table["rows"] + [{"month": r["month"], "cell_state": "no_data"} for r in rows if r["month"] not in present_months], key=lambda r: r["month"])
        return table
    key = {"K6": "renewals", "K7": "returns", "K8": "returns", "K19": "deliverables", "K20": "evaluations"}.get(kpi_id, "subs")
    groups: dict[str, list[dict]] = defaultdict(list)
    for f in facts.get(key, []):
        for g in _group_value(kpi_id, f, dimension):
            groups[g].append(f)
    for g, members in sorted(groups.items()):
        sub_facts = dict(facts)
        sub_facts[key] = members
        if kpi_id == "K20":
            sub_facts["subs"] = [s for s in facts.get("subs", []) if s.get(dimension) == g]
        raw = compute_raw(kpi_id, sub_facts, period, today, cfg)
        rows.append({dimension: g, **_row_from_raw(kpi_id, raw)})
    return sup.suppress_table(rows, [dimension], [], n, rules=rules, **spec)


def kpi_detail(db: Session, principal: Principal, kpi_id: str, *, dimension: str | None, period: str | None, cohort: str | None, payment_status: str | None, log: bool = True) -> dict:
    kid = kpi_id.upper()
    if kid not in KPI_INDEX:
        raise NotFound("unknown KPI", reason_code="KPI_NOT_FOUND")
    if dimension and ("," in dimension or dimension not in BREAKDOWN_DIMS):
        _refuse(db, principal, target=f"kpi:{kid}:{dimension}", reason="DIMENSION_NOT_ALLOWED")
        raise ValidationFailed("only one allowed dimension can be used; cross-tabs of three or more dimensions are not available", reason_code="DIMENSION_NOT_ALLOWED")
    today = dubai_today()
    cfg = params(db)
    facts = load_facts(db, cfg)
    n = sup.min_group_size(db)
    rules = sup.suppression_rules(db)
    filters = validate_filters(facts, period, cohort, payment_status, today)
    kdef = next(d for d in definitions(db) if d["kpi_id"] == kid)
    filtered = filter_facts(facts, filters)
    out: dict[str, Any] = {**_meta(db, facts, n, rules), "filters": filters, "dimension": dimension}
    if (filters["cohort"] or filters["payment_status"]) and sup.filter_blocked(population(filtered), n, rules):
        out.update(state="blocked", blocked=sup.blocked_result(n), kpi={"kpi_id": kid, "state": "blocked"})
    elif kdef["release_state"] != "live":
        out.update(state="ready", kpi=present(kdef, None, n, rules, period=filters["period"], facts=filtered))
    else:
        raw = compute_raw(kid, filtered, filters["period"], today, cfg)
        out.update(state="ready", kpi=present(kdef, raw, n, rules, period=filters["period"], facts=filtered))
        if dimension:
            out["breakdown"] = breakdown(db, kid, dimension, filtered, filters["period"], today, cfg, n, rules)
    if log:
        record_event(db, event_type="DET_DASHBOARD_VIEWED", category="data_access", actor_key=principal.actor_key, actor_role=principal.primary_role(), subject_type="kpi", subject_id=kid, details={"screen": "SC14", "kpi_id": kid, "dimension": dimension, "filters": filters, "data_version": facts["data_version"], "min_group_size": n})
    return out


def _refuse(db: Session, principal: Principal, *, target: str, reason: str) -> None:
    record_event(db, event_type="ACCESS_REFUSED", category="access", outcome="refused", reason_code=reason, actor_key=principal.actor_key, actor_role=principal.primary_role(), details={"target": target})


# --- export --------------------------------------------------------------------------------------------------------

ROW_LEVEL_TARGETS = ("licence", "company", "row", "transaction", "bank", "tax_calculation", "return_draft", "audit_working_file", "audit_report", "document")


def _cell_csv(cell: Any, lang: str, reveal_n: bool, n: int) -> tuple[str, str]:
    if cell is None:
        return "", ""
    if isinstance(cell, dict) and "cell_state" in cell:
        if cell.get("suppressed"):
            c = cell if reveal_n else sup.suppressed_cell(n, cell["cell_state"], reveal_n=False)
            return sup.cell_text(c, lang), cell["cell_state"]
        return sup.cell_text(cell, lang), "shown"
    return str(cell), ""


def export_csv(db: Session, principal: Principal, body: dict) -> tuple[str, str]:
    level = (body.get("level") or "aggregate").lower()
    if level != "aggregate" or level in ROW_LEVEL_TARGETS:
        _refuse(db, principal, target=f"export:{level}", reason="COMPANY_DETAIL_NOT_AVAILABLE")
        db.commit()
        raise Forbidden(STRINGS["company_detail_refused"]["en"], reason_code="COMPANY_DETAIL_NOT_AVAILABLE", details={"message": bi("company_detail_refused")})
    lang = "ar" if body.get("language") == "ar" else "en"
    n = sup.min_group_size(db)
    rules = sup.suppression_rules(db)
    reveal_n = bool(rules.get("reveal_n_in_exports", True))
    kpi_ids = [k.upper() for k in (body.get("kpi_ids") or [])] or None
    dimension = body.get("dimension")
    dash = dashboard(db, principal, period=body.get("period"), cohort=body.get("cohort"), payment_status=body.get("payment_status"), log=False)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["# " + dash["source_label"][lang]])
    w.writerow(["# " + dash["banner"][lang]])
    w.writerow(["# " + (dash["suppression"]["label"][lang] if reveal_n else "Minimum group size applies (provisional, set by DET)")])
    w.writerow(["# data_version", dash["data_version"], "data_as_of", dash["data_as_of"], "period", dash["filters"]["period"], "cohort", dash["filters"]["cohort"] or "", "payment_status", dash["filters"]["payment_status"] or ""])
    w.writerow(["kpi_id", "kpi_name", "section", "group", "measure", "value", "cell_state"])
    rows = 0
    if dash["state"] == "blocked":
        w.writerow(["", "", "notice", "", "", dash["blocked"]["notice_" + lang], "blocked"])
        rows += 1
    for k in dash["kpis"]:
        if kpi_ids and k["kpi_id"] not in kpi_ids:
            continue
        name = k["name"][lang]
        if k.get("state") in ("not_yet_available", "blocked", "no_data", "not_applicable", "error"):
            msg = (k.get("message") or {}).get(lang, "") if isinstance(k.get("message"), dict) else ""
            w.writerow([k["kpi_id"], name, "headline", "", "state", msg or k.get("state"), k.get("state")])
            rows += 1
            continue
        txt, st = _cell_csv(k.get("value"), lang, reveal_n, n)
        w.writerow([k["kpi_id"], name, "headline", "", "value", txt, st])
        rows += 1
        for measure in ("numerator", "denominator"):
            if k.get(measure):
                txt, st = _cell_csv(k[measure], lang, reveal_n, n)
                w.writerow([k["kpi_id"], name, "headline", "", measure, txt, st])
                rows += 1
        for cname, cell in (k.get("counts") or {}).items():
            txt, st = _cell_csv(cell, lang, reveal_n, n)
            w.writerow([k["kpi_id"], name, "counts", "", cname, txt, st])
            rows += 1
        for aname, cell in (k.get("amounts_fils") or {}).items():
            txt, st = _cell_csv(cell, lang, reveal_n, n)
            w.writerow([k["kpi_id"], name, "amounts_fils", "", aname, txt, st])
            rows += 1
        for tid, table in (k.get("breakdowns") or {}).items():
            rows += _write_table(w, k["kpi_id"], name, tid, table, lang, reveal_n, n)
    if dimension and kpi_ids and len(kpi_ids) == 1 and dash["state"] != "blocked":
        det = kpi_detail(db, principal, kpi_ids[0], dimension=dimension, period=body.get("period"), cohort=body.get("cohort"), payment_status=body.get("payment_status"), log=False)
        if det.get("breakdown"):
            rows += _write_table(w, kpi_ids[0], KPI_INDEX[kpi_ids[0]]["name_" + lang], f"by_{dimension}", det["breakdown"], lang, reveal_n, n)
    exp = KpiExport(actor_key=principal.actor_key, kpi_ids=kpi_ids or [k["kpi_id"] for k in dash["kpis"]], filters=dash["filters"], dimension=dimension, data_version=dash["data_version"], min_group_size=n, row_count=rows)
    db.add(exp)
    db.flush()
    record_event(db, event_type="DET_DASHBOARD_EXPORTED", category="data_access", actor_key=principal.actor_key, actor_role=principal.primary_role(), subject_type="kpi_export", subject_id=exp.export_id, details={"export_id": exp.export_id, "kpi_ids": exp.kpi_ids, "filters": exp.filters, "dimension": dimension, "data_version": exp.data_version, "min_group_size": n})
    return buf.getvalue(), exp.export_id


def _write_table(w: Any, kid: str, name: str, tid: str, table: dict, lang: str, reveal_n: bool, n: int) -> int:
    rows = 0
    if table.get("state") == "not_shown_group_too_small" or table.get("state") == "blocked":
        w.writerow([kid, name, tid, "", "state", sup.NOT_SHOWN_LABEL[lang], "not_shown_group_too_small"])
        rows += 1
    for r in table.get("rows", []):
        group = "|".join(str(r.get(d)) for d in table.get("dims", []))
        if r.get("cell_state") == "merged_other_combined":
            group = r.get("label_" + lang, group)
        for key, cell in r.items():
            if isinstance(cell, dict) and "cell_state" in cell:
                txt, st = _cell_csv(cell, lang, reveal_n, n)
                w.writerow([kid, name, tid, group, key, txt, st])
                rows += 1
    if table.get("total"):
        for key, cell in table["total"].items():
            if isinstance(cell, dict) and "cell_state" in cell:
                txt, st = _cell_csv(cell, lang, reveal_n, n)
                w.writerow([kid, name, tid, "total", key, txt, st])
                rows += 1
    if table.get("notice"):
        w.writerow([kid, name, tid, "", "notice", table.get("notice_" + lang, ""), "notice"])
        rows += 1
    return rows


# --- per-licence operational view -------------------------------------------------------------------------------------

PER_LICENCE_FIELDS = (
    "licence_number", "trade_name_en", "trade_name_ar", "issuing_authority", "licence_status", "issue_date", "expiry_date",
    "subscription_status", "subscription_badge", "billing_status", "collection_status", "enrolment_mode", "subscription_start", "subscription_end",
    "cohort", "wave", "open_support_cases",
)


def per_licence_view(db: Session, principal: Principal, licence_number: str) -> dict:
    """DET admin per-licence view: identity, status, subscription and billing status, enrolment mode and dates,
    cohort and the open support case count. Never usage, tax/deadline/filing, escalation, survey reasons,
    document names, bank or financial data. Every view is logged and visible to the reviewer."""
    from app.modules.licences.models import Licence

    lic = db.scalar(select(Licence).where(Licence.licence_number == licence_number))
    if lic is None:
        record_event(db, event_type="DET_PER_LICENCE_LOOKUP", category="data_access", outcome="not_found", actor_key=principal.actor_key, actor_role=principal.primary_role(), details={"found": False})
        raise NotFound("no licence with this number", reason_code="LICENCE_NOT_FOUND")
    sub_status: dict[str, Any] = {}
    try:
        from app.modules.subscriptions.service import det_status_for_licence

        sub_status = det_status_for_licence(db, licence_number)
    except ImportError:  # pragma: no cover
        sub_status = {}
    cohort = wave = None
    mode = {"opted_in": "opt_in", "default_on": "default_on_with_opt_out"}.get(sub_status.get("enrolment_basis") or "", sub_status.get("enrolment_basis"))
    try:
        from app.modules.cohorts.models import Cohort, CohortMembership

        m = db.scalar(select(CohortMembership).where(CohortMembership.licence_number == licence_number).order_by(desc(CohortMembership.enrolled_at)).limit(1))
        if m is not None:
            c = db.scalar(select(Cohort).where(Cohort.cohort_id == m.cohort_id, Cohort.is_current.is_(True)))
            if c is not None:
                cohort, wave = c.code, c.wave
                mode = mode or c.enrolment_mode
    except ImportError:  # pragma: no cover
        pass
    term = (sub_status.get("term") or "|").split("|")
    open_cases = int(sub_status.get("open_cases") or 0)
    try:
        from app.modules.subscriptions.models import Complaint

        open_cases += len(list(db.scalars(select(Complaint.id).where(Complaint.licence_number == licence_number, Complaint.status.in_(("received", "in_review"))))))
    except ImportError:  # pragma: no cover
        pass
    view = {
        "licence_number": lic.licence_number, "trade_name_en": lic.trade_name_en, "trade_name_ar": lic.trade_name_ar, "issuing_authority": lic.issuing_authority,
        "licence_status": lic.status, "issue_date": lic.issue_date.isoformat() if lic.issue_date else None, "expiry_date": lic.expiry_date.isoformat() if lic.expiry_date else None,
        "subscription_status": sub_status.get("subscription_status"), "subscription_badge": sub_status.get("subscription_badge"), "billing_status": sub_status.get("billing_status"),
        "collection_status": sub_status.get("collection_status"), "enrolment_mode": mode, "subscription_start": term[0] or None, "subscription_end": term[1] if len(term) > 1 and term[1] else None,
        "cohort": cohort or ((sub_status.get("cohort_stamp") or "").split("-")[0] or None), "wave": wave, "open_support_cases": open_cases,
    }
    view = {k: view.get(k) for k in PER_LICENCE_FIELDS}  # allow-list: nothing else ever leaves
    record_event(db, event_type="DET_PER_LICENCE_VIEWED", category="data_access", actor_key=principal.actor_key, actor_role=principal.primary_role(), company_id=lic.company_id, licence_number=lic.licence_number, subject_type="licence", subject_id=lic.id, details={"fields": list(PER_LICENCE_FIELDS)})
    return {"licence": view, "logged": True, "note": {"en": "This view is logged and visible to the compliance reviewer.", "ar": "يتم تسجيل هذا العرض ويمكن لمراجع الامتثال الاطلاع عليه."}}


# --- settings ----------------------------------------------------------------------------------------------------------


def settings_view(db: Session, principal: Principal) -> dict:
    n = sup.min_group_size(db)
    hist = config_history(db, sup.CONFIG_KEY)
    return {
        "min_group_size": n, "min": sup.N_MIN, "max": sup.N_MAX, "label": bi("n_label", n=n), "status": "provisional, set by DET", "owner": "DET pilot manager",
        "can_manage": "det.min_group_size.manage" in _perms(db, principal),
        "history": [{"version": h.version, "value": h.value, "changed_by": h.changed_by, "effective_from": h.effective_from.isoformat() if h.effective_from else None, "created_at": h.created_at.isoformat() if getattr(h, "created_at", None) else None} for h in hist],
        "later_phase_kpis_enabled": bool(get_config(db, "det_dashboard.later_phase_kpis.enabled", False)),
        "include_demo_fixture": bool(get_config(db, INCLUDE_FIXTURE, False)),
    }


def set_min_group_size(db: Session, principal: Principal, value: Any, *, reason: str | None, consulted_compliance_lead: bool) -> dict:
    n = sup.validate_n(value)
    old = sup.min_group_size(db)
    if not reason or not str(reason).strip():
        raise ValidationFailed("a reason is required for this change", reason_code="REASON_REQUIRED")
    entry = set_config(db, sup.CONFIG_KEY, n, changed_by=principal.actor_key, change_reason=str(reason)[:255], status="provisional", label="provisional, set by DET")
    record_event(db, event_type="CONFIG_CHANGED", category="config", actor_key=principal.actor_key, actor_role=principal.primary_role(), subject_type="config", subject_id=sup.CONFIG_KEY, config_version=f"{sup.CONFIG_KEY}@{entry.version}", details={"key": sup.CONFIG_KEY, "old": old, "new": n, "version": entry.version, "consulted": "det_compliance_lead" if consulted_compliance_lead else None})
    return settings_view(db, principal)


def calculation_runs(db: Session, principal: Principal, limit: int = 200) -> list[dict]:
    rows = list(db.scalars(select(KpiCalculationRun).order_by(desc(KpiCalculationRun.created_at)).limit(limit)))
    record_event(db, event_type="KPI_RUN_LOG_VIEWED", category="data_access", actor_key=principal.actor_key, actor_role=principal.primary_role(), details={"rows": len(rows)})
    return [{"run_id": r.run_id, "kpi_id": r.kpi_id, "period": r.period_key, "source": r.data_source, "rule_version": r.rule_version, "catalogue_version": r.catalogue_version, "data_version": r.data_version, "period_closed": r.period_closed, "restated": r.restated, "restatement_note": r.restatement_note, "supersedes_run_id": r.supersedes_run_id, "created_at": r.created_at.isoformat()} for r in rows]
