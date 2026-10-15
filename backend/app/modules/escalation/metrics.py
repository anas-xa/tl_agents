"""K21 human escalation rate and K22 escalation turnaround (E8-S4), computed from the workflow log only.

Join key is the escalation id. Aggregates only; suppression at N (provisional 10) with complementary
suppression; specialist breakdowns use coded role labels; no company identifiers, no case drill-down.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.time import to_dubai, utcnow
from app.modules.config.service import get_config
from app.modules.escalation.calendar import age_band, calendar_coverage, working_days_between
from app.modules.escalation.models import (
    DISCRETIONARY_REASONS,
    MANDATORY_REASONS,
    REASON_CODES,
    CaseEvent,
    CasePause,
    EscalationCase,
    WorkItem,
)

ROLE_LABELS = {"tax": "Tax specialist lead", "auditor": "Licensed auditor firm", "lawyer": "Licensed lawyer route", "compliance": "DET compliance"}
KPI_MODULES = ("tax", "audit", "compliance")  # legal reported separately, never in the tax/audit denominator


def _mean(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 1) if values else None


def _suppress_cells(cells: dict[str, dict], n: int, count_key: str = "escalated") -> dict[str, dict]:
    """Mark cells below N as 'fewer than N'; if exactly one cell is suppressed, suppress the total too so it
    cannot be recovered by subtraction (complementary suppression)."""
    out = {}
    suppressed = 0
    for key, cell in cells.items():
        if key == "total":
            continue
        if 0 < cell.get(count_key, 0) < n:  # zero reveals nothing: shown as 0 / 'not applicable'
            out[key] = {"suppressed": True, "fewer_than": n}
            suppressed += 1
        else:
            out[key] = {**cell, "suppressed": False}
    if "total" in cells:
        total = cells["total"]
        if 0 < total.get(count_key, 0) < n or suppressed == 1:
            out["total"] = {"suppressed": True, "fewer_than": n}
        else:
            out["total"] = {**total, "suppressed": False}
    return out


def _k21_cell(total: int, escalated: int, events: int) -> dict:
    if total == 0:
        return {"total": 0, "escalated": escalated, "events": events, "rate_per_100": None, "note": "not_applicable"}
    return {"total": total, "escalated": escalated, "events": events, "rate_per_100": round(escalated / total * 100, 1)}


def compute_aggregates(db: Session, *, period_from: date, period_to: date, module: str | None = None, reason: str | None = None, specialist_type: str | None = None, priority: str | None = None, now: datetime | None = None) -> dict:
    now = now or utcnow()
    from app.modules.kpis.suppression import min_group_size

    n = min_group_size(db)
    coverage = calendar_coverage(db, period_from, period_to)
    start_dt = datetime.combine(period_from, datetime.min.time()) - timedelta(hours=4)  # Dubai-local day boundaries
    end_dt = datetime.combine(period_to + timedelta(days=1), datetime.min.time()) - timedelta(hours=4)

    # --- K21: cohort by work item opened date (legal separately) -------------------------------------
    items = list(db.scalars(select(WorkItem).where(WorkItem.case_opened_at >= start_dt, WorkItem.case_opened_at < end_dt)))
    if module:
        items = [i for i in items if i.module == module]
    item_ids = {i.id for i in items}
    esc_all = list(db.scalars(select(EscalationCase)))
    esc_by_item: dict[str, list[EscalationCase]] = defaultdict(list)
    for c in esc_all:
        if c.work_item_id in item_ids:
            esc_by_item[c.work_item_id].append(c)
    k21_by_module: dict[str, dict] = {}
    k21_by_reason: dict[str, dict] = {}
    mandatory = {"mandatory_by_law": {"total": 0, "escalated": 0, "events": 0}, "discretionary": {"total": 0, "escalated": 0, "events": 0}, "other": {"total": 0, "escalated": 0, "events": 0}}
    tot_all, esc_count_all, ev_all = 0, 0, 0
    for mod in ("tax", "audit", "compliance", "legal"):
        mod_items = [i for i in items if i.module == mod]
        esc_items = [i for i in mod_items if esc_by_item.get(i.id)]
        if reason:
            esc_items = [i for i in esc_items if any(c.escalation_reason == reason for c in esc_by_item[i.id])]
        if specialist_type:
            esc_items = [i for i in esc_items if any(c.specialist_type == specialist_type for c in esc_by_item[i.id])]
        if priority:
            esc_items = [i for i in esc_items if any(c.priority == priority for c in esc_by_item[i.id])]
        events = sum(len(esc_by_item.get(i.id, [])) for i in esc_items)
        k21_by_module[mod] = _k21_cell(len(mod_items), len(esc_items), events)
        if mod in KPI_MODULES:
            tot_all += len(mod_items)
            esc_count_all += len(esc_items)
            ev_all += events
    for i in items:
        for c in esc_by_item.get(i.id, []):
            code = c.escalation_reason if c.escalation_reason in REASON_CODES else "unclassified"
            cell = k21_by_reason.setdefault(code, {"total": 0, "escalated": 0, "events": 0})
            cell["escalated"] += 1
            cell["events"] += 1
            group = "mandatory_by_law" if code in MANDATORY_REASONS else "discretionary" if code in DISCRETIONARY_REASONS else "other"
            mandatory[group]["escalated"] += 1
            mandatory[group]["events"] += 1
    for cell in list(k21_by_reason.values()) + list(mandatory.values()):
        cell["total"] = tot_all
        cell["rate_per_100"] = round(cell["escalated"] / tot_all * 100, 1) if tot_all else None
    k21_by_module["total"] = _k21_cell(tot_all, esc_count_all, ev_all)

    # --- K22: escalations escalated in period, from the workflow log ------------------------------------
    esc = [c for c in esc_all if start_dt <= c.escalated_at < end_dt]
    if module:
        esc = [c for c in esc if c.module == module]
    if reason:
        esc = [c for c in esc if c.escalation_reason == reason]
    if specialist_type:
        esc = [c for c in esc if c.specialist_type == specialist_type]
    if priority:
        esc = [c for c in esc if c.priority == priority]
    esc_ids = [c.case_id for c in esc]
    pauses: dict[str, list[CasePause]] = defaultdict(list)
    for p in db.scalars(select(CasePause).where(CasePause.case_id.in_(esc_ids))) if esc_ids else []:
        pauses[p.case_id].append(p)
    resolved_events = {e.escalation_id for e in db.scalars(select(CaseEvent).where(CaseEvent.escalation_id.in_(esc_ids), CaseEvent.event_type == "resolved"))} if esc_ids else set()
    dq = {"closed_before_opened": 0, "missing_closed_time": 0, "log_event_missing": 0, "key_missing_or_duplicate": 0}
    seen_ids: set[str] = set()
    resolved_active, resolved_raw, first_resp = [], [], []
    by_dim: dict[str, dict[str, dict]] = {"module": defaultdict(lambda: {"active": [], "raw": [], "first": [], "escalated": 0}), "role_label": defaultdict(lambda: {"active": [], "raw": [], "first": [], "escalated": 0}), "priority": defaultdict(lambda: {"active": [], "raw": [], "first": [], "escalated": 0})}
    withdrawn = closed_no_consent = outcome_c = 0
    open_count = 0
    age_bands: dict[str, int] = defaultdict(int)
    provisional_hit = coverage["provisional"]
    for c in esc:
        if not c.case_id or c.case_id in seen_ids:
            dq["key_missing_or_duplicate"] += 1
            continue
        seen_ids.add(c.case_id)
        dims = {"module": c.module, "role_label": ROLE_LABELS.get(c.specialist_type, "other"), "priority": c.priority}
        for d, k in dims.items():
            by_dim[d][k]["escalated"] += 1
        if c.status == "rejected":
            withdrawn += 1
            continue
        if c.status == "closed_no_consent":
            closed_no_consent += 1
            continue
        if c.status == "resolved":
            if c.resolved_at is None:
                dq["missing_closed_time"] += 1
                continue
            if c.resolved_at < c.escalated_at:
                dq["closed_before_opened"] += 1
                continue
            if c.case_id not in resolved_events:
                dq["log_event_missing"] += 1
                continue
            raw = working_days_between(db, c.escalated_at, c.resolved_at)
            paused = round(sum(working_days_between(db, p.started_at, p.ended_at or c.resolved_at) for p in pauses.get(c.case_id, [])), 1)
            active = round(max(raw - paused, 0.0), 1)
            if c.resolution_outcome == "c":
                outcome_c += 1
            resolved_active.append(active)
            resolved_raw.append(raw)
            for d, k in dims.items():
                by_dim[d][k]["active"].append(active)
                by_dim[d][k]["raw"].append(raw)
            if c.first_response_at:
                fr = working_days_between(db, c.escalated_at, c.first_response_at)
                first_resp.append(fr)
                for d, k in dims.items():
                    by_dim[d][k]["first"].append(fr)
            continue
        if c.status == "closed":
            if c.closed_at is None:
                dq["missing_closed_time"] += 1
            continue
        open_count += 1
        age_bands[age_band(working_days_between(db, c.escalated_at, now))] += 1
        if c.first_response_at:
            fr = working_days_between(db, c.escalated_at, c.first_response_at)
            first_resp.append(fr)
            for d, k in dims.items():
                by_dim[d][k]["first"].append(fr)

    def k22_cells(dim: str) -> dict[str, dict]:
        cells = {}
        for k, v in by_dim[dim].items():
            cells[k] = {"escalated": v["escalated"], "resolved": len(v["active"]), "active_working_days": _mean(v["active"]), "raw_working_days": _mean(v["raw"]), "first_response_working_days": _mean(v["first"])}
        cells["total"] = {"escalated": len(seen_ids), "resolved": len(resolved_active), "active_working_days": _mean(resolved_active), "raw_working_days": _mean(resolved_raw), "first_response_working_days": _mean(first_resp)}
        return _suppress_cells(cells, n)

    headline_suppressed = 0 < len(seen_ids) < n
    k22_headline = {"suppressed": True, "fewer_than": n} if headline_suppressed else {"suppressed": False, "active_working_days": _mean(resolved_active), "raw_working_days": _mean(resolved_raw), "first_response_working_days": _mean(first_resp), "resolved": len(resolved_active), "no_data": not resolved_active}
    by_module_cells = _suppress_cells({k: v for k, v in k21_by_module.items() if k != "legal"}, n)
    k21_headline = by_module_cells["total"]
    age_cells = {b: {"escalated": cnt} for b, cnt in age_bands.items()}
    age_cells["total"] = {"escalated": open_count}
    return {
        "period": {"from": period_from.isoformat(), "to": period_to.isoformat(), "months": sorted({(period_from + timedelta(days=i)).strftime("%Y-%m") for i in range(0, (period_to - period_from).days + 1)})},
        "filters": {"module": module, "reason": reason, "specialist_type": specialist_type, "priority": priority},
        "suppression": {"min_group_size": n, "status": "provisional", "technique": "fewer_than_n_with_complementary_suppression"},
        "k21": {"headline": k21_headline, "by_module": by_module_cells, "by_reason": _suppress_cells({**k21_by_reason, "total": {"total": tot_all, "escalated": esc_count_all, "events": ev_all}}, n), "mandatory_vs_discretionary": _suppress_cells({**mandatory, "total": {"total": tot_all, "escalated": sum(v["escalated"] for v in mandatory.values()), "events": ev_all}}, n), "legal_separate": _suppress_cells({"legal": k21_by_module["legal"]}, n), "open_in_cohort_flag": "provisional until cohort closes", "target": None},
        "k22": {"headline": k22_headline, "by_module": k22_cells("module"), "by_role_label": k22_cells("role_label"), "by_priority": k22_cells("priority"), "withdrawn_count": withdrawn if withdrawn >= n or withdrawn == 0 else {"suppressed": True, "fewer_than": n}, "closed_no_consent_count": closed_no_consent if closed_no_consent >= n or closed_no_consent == 0 else {"suppressed": True, "fewer_than": n}, "outcome_c_count": outcome_c if outcome_c >= n or outcome_c == 0 else {"suppressed": True, "fewer_than": n}, "open": {"count": open_count if open_count >= n or open_count == 0 else {"suppressed": True, "fewer_than": n}, "age_bands": _suppress_cells(age_cells, n), "age_band_values": "to be confirmed"}, "convention": get_config(db, "working_day.convention", {}), "target": None},
        "data_quality": {"counter": sum(dq.values()), **dq},
        "calendar": {"version": coverage["version"], "missing": coverage["calendar_missing"], "missing_years": coverage["missing_years"], "provisional": provisional_hit, "provisional_dates": coverage["provisional_dates"], "timezone": "Asia/Dubai", "basis": "working days on the Dubai government calendar"},
        "refresh": {"last_refreshed_at": now.isoformat(), "schedule": get_config(db, "refresh.schedule", "weekly"), "stale": False, "refreshed_dubai": to_dubai(now).isoformat()},
        "labels": {"empty": "No escalated cases in this period. Try a wider date range.", "fewer_than": f"fewer than {n} cases", "no_data": "no data", "not_applicable": "not applicable"},
        "empty": len(seen_ids) == 0 and esc_count_all == 0,
    }
