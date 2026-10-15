"""Privacy-safe aggregation: ONE shared suppression engine for every DET aggregate path (E9-S1 F2).

Used for the SC14 screen, the API, exports and scheduled reports so that the same cells are hidden
everywhere. Rules (versioned in rule ``det-suppression-v1``; N in ``det_dashboard.min_group_size``):

1. Primary suppression: a group (or a count cell) below N is hidden and shown as 'Fewer than N', never as
   a number. A measured zero is shown as zero (it describes no licence).
2. Complementary suppression: while the hidden cells of a breakdown add up to less than N and the total is
   published, the next-smallest visible cell is hidden too (covers 'exactly one hidden cell recoverable by
   subtraction' and subtraction across time series: a month series is never merged, only suppressed).
3. Filter blocking: a filter that narrows the population below N blocks the whole result (no numbers).
4. Totals are shown only when the total itself is >= N.
5. Stepwise small-cohort rule: notice -> merge only the small categories into one 'Other (combined)' line
   when that line reaches N (and at least one other category stays visible) -> otherwise the whole
   breakdown is 'not shown, group too small'. Categories are never merged across dimensions.
6. No cross-tab of three or more dimensions when any cell is below N.
7. Amounts also follow the dominance rule: an amount cell where one licence contributes more than the
   configured share is hidden.
8. Suppressed values never appear in the payload: hidden cells carry a label only, no value key.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Any

from sqlalchemy.orm import Session

from app.core.errors import ValidationFailed

CONFIG_KEY = "det_dashboard.min_group_size"
RULE_ID = "det-suppression-v1"
DEFAULT_N = 10
N_MIN, N_MAX = 3, 50
OTHER_KEY = "other_combined"
DEFAULT_RULES: dict[str, Any] = {
    "primary": True,
    "complementary": True,
    "filter_blocking": True,
    "totals_only_when_at_least_n": True,
    "max_dimensions_when_small": 2,
    "merge_other": True,
    "dominance": True,
    "dominance_share": 0.5,
    "reveal_n_in_exports": True,
    "zero_cells_shown": True,
    "rounding": None,
}
NOTICES = {
    "suppressed": {"en": "Fewer than {n} licences (hidden to protect privacy)", "ar": "أقل من {n} رخص (مخفي لحماية الخصوصية)"},
    "merged": {"en": "Includes groups with fewer than {n} licences.", "ar": "تشمل مجموعات تضم أقل من {n} رخص."},
    "combined_or_hidden": {"en": "Some groups are combined or hidden to protect privacy.", "ar": "تم دمج بعض المجموعات أو إخفاؤها لحماية الخصوصية."},
}
OTHER_LABEL = {"en": "Other (combined)", "ar": "أخرى (مجمّعة)"}
NOT_SHOWN_LABEL = {"en": "Not shown, group too small", "ar": "غير معروض، المجموعة صغيرة جداً"}


# --- configuration ---------------------------------------------------------------------------------------


def validate_n(value: Any) -> int:
    try:
        n = int(value)
    except (TypeError, ValueError):
        raise ValidationFailed("the minimum group size must be a whole number", reason_code="MIN_GROUP_SIZE_INVALID") from None
    if n < N_MIN or n > N_MAX or str(value).strip() not in (str(n), f"{n}.0"):
        raise ValidationFailed(f"the minimum group size must be between {N_MIN} and {N_MAX}", reason_code="MIN_GROUP_SIZE_OUT_OF_RANGE", details={"min": N_MIN, "max": N_MAX})
    return n


def min_group_size(db: Session) -> int:
    from app.modules.config.service import get_config

    value = get_config(db, CONFIG_KEY, DEFAULT_N)
    try:
        return validate_n(value)
    except ValidationFailed:
        return DEFAULT_N  # fail safe: an invalid stored value never lowers protection below the default


def suppression_rules(db: Session | None) -> dict:
    if db is None:
        return dict(DEFAULT_RULES)
    from app.modules.config.service import rule_params

    return {**DEFAULT_RULES, **rule_params(db, RULE_ID, {})}


# --- cells -----------------------------------------------------------------------------------------------


def suppressed_cell(n: int, state: str = "suppressed_fewer_than_N", *, reveal_n: bool = True) -> dict:
    """A hidden cell: a label only, never the value."""
    if reveal_n:
        label_en, label_ar = f"Fewer than {n}", f"أقل من {n}"
    else:
        label_en, label_ar = "Fewer than the minimum group size", "أقل من الحد الأدنى لحجم المجموعة"
    if state == "not_shown_group_too_small":
        label_en, label_ar = NOT_SHOWN_LABEL["en"], NOT_SHOWN_LABEL["ar"]
    return {"suppressed": True, "cell_state": state, "label_en": label_en, "label_ar": label_ar}


def shown_cell(value: Any) -> dict:
    return {"suppressed": False, "cell_state": "shown", "value": value}


def is_small(value: int | float | None, n: int, *, zero_shown: bool = True) -> bool:
    if value is None:
        return False
    if zero_shown and value == 0:
        return False
    return value < n


def suppress_count(value: int | None, n: int, *, zero_shown: bool = True) -> dict | None:
    """A single published count (headline or tile)."""
    if value is None:
        return None
    return suppressed_cell(n) if is_small(value, n, zero_shown=zero_shown) else shown_cell(value)


def suppress_value(value: Any, group_size: int, n: int) -> dict:
    """A value derived from a group (rate, amount, mean): shown only when the group is >= N."""
    return suppressed_cell(n) if group_size < n else shown_cell(value)


def suppress_difference(diff: Any, size_a: int, size_b: int, n: int) -> dict:
    """Time-series / cohort comparisons: a change is suppressed if either underlying group is below N."""
    return suppressed_cell(n) if (size_a < n or size_b < n) else shown_cell(diff)


def filter_blocked(population: int, n: int, rules: dict | None = None) -> bool:
    """A filter (or combination) that narrows the population below N blocks the whole result."""
    r = rules or DEFAULT_RULES
    return bool(r.get("filter_blocking", True)) and population < n


def blocked_result(n: int) -> dict:
    return {"state": "blocked", "n": n, "notice": True, "notice_key": "suppressed", "notice_en": NOTICES["suppressed"]["en"].format(n=n), "notice_ar": NOTICES["suppressed"]["ar"].format(n=n)}


def cell_text(cell: dict | None, lang: str = "en") -> str:
    if cell is None:
        return ""
    if cell.get("suppressed"):
        return cell["label_ar" if lang == "ar" else "label_en"]
    v = cell.get("value")
    return "" if v is None else str(v)


# --- tables ----------------------------------------------------------------------------------------------


def _hide_until_safe(sizes: list[float], hidden: set[int], n: int, *, publish_total: bool) -> set[int]:
    """Complementary suppression: while the hidden cells add up to less than N (so a single small cell could
    be recovered from the published total), hide the next-smallest visible non-zero cell."""
    if not hidden or not publish_total:
        return set()
    added: set[int] = set()
    while sum(abs(sizes[i]) for i in hidden | added) < n:
        visible = [i for i in range(len(sizes)) if i not in hidden and i not in added and sizes[i] != 0]
        if not visible:
            break
        added.add(min(visible, key=lambda i: (abs(sizes[i]), i)))
    return added


def _rate(num: Any, den: Any) -> float | None:
    if not den:
        return None
    return round(float(num) * 100.0 / float(den), 1)


def suppress_table(
    rows: Sequence[dict],
    dims: Sequence[str],
    value_keys: Iterable[str] = (),
    n: int | None = None,
    *,
    size_key: str = "count",
    count_keys: Iterable[str] = (),
    amount_keys: Iterable[str] = (),
    rate_keys: dict[str, tuple[str, str]] | None = None,
    dominance_key: str = "max_contribution",
    merge_other: bool | None = None,
    include_total: bool = True,
    rules: dict | None = None,
) -> dict:
    """Apply the shared suppression rules to a breakdown.

    ``rows``: one dict per group with the dimension values, ``size_key`` (number of licences in the group),
    and the value keys. ``count_keys`` are counts that are cells in their own right (hidden when < N);
    ``amount_keys`` are sums subject to the dominance rule (``dominance_key`` holds the largest single-licence
    contribution per amount key, as a dict); ``rate_keys`` map a rate to its (numerator, denominator) keys and
    are recomputed for merged/total rows and hidden whenever a dependency is hidden.
    """
    r = {**DEFAULT_RULES, **(rules or {})}
    n = int(n or DEFAULT_N)
    zero_shown = bool(r.get("zero_cells_shown", True))
    count_keys, amount_keys = list(count_keys), list(amount_keys)
    rate_keys = dict(rate_keys or {})
    keys = [size_key] + [k for k in dict.fromkeys(list(value_keys) + count_keys + amount_keys + list(rate_keys)) if k != size_key]
    summable = [size_key] + count_keys + amount_keys
    if merge_other is None:
        merge_other = bool(r.get("merge_other", True))
    src = [dict(x) for x in rows if (x.get(size_key) or 0) > 0]
    total_size = sum(int(x.get(size_key) or 0) for x in src)
    out: dict[str, Any] = {"n": n, "dims": list(dims), "state": "shown", "rows": [], "total": None, "notice": False, "notice_key": None}
    states: set[str] = set()

    def total_row(rows_: list[dict]) -> dict:
        t: dict[str, Any] = {k: sum((x.get(k) or 0) for x in rows_) for k in summable}
        dom: dict[str, float] = {}
        for x in rows_:
            for ak, v in (x.get(dominance_key) or {}).items():
                dom[ak] = max(dom.get(ak, 0), v)
        t[dominance_key] = dom
        for rk, (nk, dk) in rate_keys.items():
            t[rk] = _rate(t.get(nk, 0), t.get(dk, 0))
        return t

    def render(row: dict, hidden_keys: dict[str, str]) -> dict:
        cells: dict[str, Any] = {d: row.get(d) for d in dims}
        for k in keys:
            if k in hidden_keys:
                cells[k] = suppressed_cell(n, hidden_keys[k])
            else:
                cells[k] = shown_cell(row.get(k))
        return cells

    small_dims = len(dims) >= 3 and any(is_small(x.get(size_key), n) for x in src)
    if len(dims) > int(r.get("max_dimensions_when_small", 2)) and small_dims:
        out.update(state="not_shown_group_too_small", notice=True, notice_key="combined_or_hidden", rows=[])
        states.add("not_shown_group_too_small")
    else:
        small = [i for i, x in enumerate(src) if is_small(x.get(size_key), n)]
        row_hidden: dict[int, str] = {i: "suppressed_fewer_than_N" for i in small} if r.get("primary", True) else {}
        if small and merge_other and len(dims) == 1:
            combined = sum(src[i][size_key] for i in small)
            if combined >= n and len(small) < len(src):
                kept = [x for i, x in enumerate(src) if i not in small]
                other = total_row([src[i] for i in small])
                other[dims[0]] = OTHER_KEY
                other["_merged"] = True
                src = kept + [other]
                row_hidden = {}
                states.add("merged_other_combined")
                out["notice_key"] = "merged"
            else:
                out.update(state="not_shown_group_too_small", notice=True, notice_key="combined_or_hidden", rows=[])
                states.add("not_shown_group_too_small")
                src = []
        elif small and r.get("complementary", True):
            extra = _hide_until_safe([x[size_key] for x in src], set(row_hidden), n, publish_total=total_size >= n)
            for i in extra:
                row_hidden[i] = "complementary_suppressed"
        # cell-level: counts and amounts inside visible rows
        cell_hidden: dict[int, dict[str, str]] = {i: {k: st for k in keys} for i, st in row_hidden.items()}
        for i in range(len(src)):
            cell_hidden.setdefault(i, {})
        visible_rows = [i for i in range(len(src)) if i not in row_hidden]
        for ck in count_keys:
            vals = [src[i].get(ck) or 0 for i in range(len(src))]
            prim = {i for i in visible_rows if is_small(vals[i], n, zero_shown=zero_shown)}
            col_total = sum(vals)
            comp = _hide_until_safe(vals, prim | set(row_hidden), n, publish_total=col_total >= n) if (prim and r.get("complementary", True)) else set()
            for i in prim:
                cell_hidden[i][ck] = "suppressed_fewer_than_N"
            for i in comp - set(row_hidden):
                cell_hidden[i][ck] = "complementary_suppressed"
        if r.get("dominance", True):
            share = float(r.get("dominance_share", 0.5))
            for ak in amount_keys:
                dom_hidden = set()
                for i in visible_rows:
                    amt = abs(src[i].get(ak) or 0)
                    top = (src[i].get(dominance_key) or {}).get(ak, 0)
                    if amt and top / amt > share:
                        dom_hidden.add(i)
                comp: set[int] = set()
                if len(dom_hidden) == 1 and r.get("complementary", True):
                    # one hidden amount is recoverable from the published total: hide the next-smallest too
                    others = [i for i in visible_rows if i not in dom_hidden and (src[i].get(ak) or 0) != 0]
                    if others:
                        comp = {min(others, key=lambda i: (abs(src[i].get(ak) or 0), i))}
                for i in dom_hidden:
                    cell_hidden[i][ak] = "suppressed_dominance"
                for i in comp - set(row_hidden):
                    cell_hidden[i][ak] = "complementary_suppressed"
        for rk, (nk, dk) in rate_keys.items():
            for i in range(len(src)):
                if rk not in cell_hidden[i] and (nk in cell_hidden[i] or dk in cell_hidden[i]):
                    cell_hidden[i][rk] = cell_hidden[i].get(nk) or cell_hidden[i].get(dk) or "suppressed_fewer_than_N"
        for i, row in enumerate(src):
            cells = render(row, cell_hidden[i])
            cells["cell_state"] = "merged_other_combined" if row.get("_merged") else row_hidden.get(i, "shown")
            if row.get("_merged"):
                cells["label_en"], cells["label_ar"] = OTHER_LABEL["en"], OTHER_LABEL["ar"]
            out["rows"].append(cells)
            states |= {v for v in cell_hidden[i].values()}
            states.add(cells["cell_state"])
        if states - {"shown", "merged_other_combined"}:
            out["notice"] = True
            out["notice_key"] = "combined_or_hidden" if (out["notice_key"] == "merged" or "complementary_suppressed" in states) else (out["notice_key"] or "suppressed")
        elif out["notice_key"] == "merged":
            out["notice"] = True
    if include_total and total_size > 0:
        t = total_row([dict(x) for x in rows if (x.get(size_key) or 0) > 0])
        hidden: dict[str, str] = {}
        if r.get("totals_only_when_at_least_n", True) and total_size < n:
            hidden = {k: "suppressed_fewer_than_N" for k in keys}
        else:
            for ck in count_keys:
                if is_small(t.get(ck), n, zero_shown=zero_shown):
                    hidden[ck] = "suppressed_fewer_than_N"
            if r.get("dominance", True):
                for ak in amount_keys:
                    amt = abs(t.get(ak) or 0)
                    if amt and (t[dominance_key].get(ak, 0) / amt) > float(r.get("dominance_share", 0.5)):
                        hidden[ak] = "suppressed_dominance"
            for rk, (nk, dk) in rate_keys.items():
                if nk in hidden or dk in hidden:
                    hidden[rk] = hidden.get(nk) or hidden.get(dk) or "suppressed_fewer_than_N"
        out["total"] = render(t, hidden)
        out["total"]["cell_state"] = "suppressed_fewer_than_N" if total_size < n else "shown"
        if hidden:
            states.add("suppressed_fewer_than_N")
            out["notice"] = True
            out["notice_key"] = out["notice_key"] or "suppressed"
    out["cell_states"] = sorted(states)
    if out["notice_key"]:
        out["notice_en"] = NOTICES[out["notice_key"]]["en"].format(n=n)
        out["notice_ar"] = NOTICES[out["notice_key"]]["ar"].format(n=n)
    return out


def contains_value(payload: Any, value: Any) -> bool:
    """Test/inspection helper: does ``value`` appear anywhere as a value in a payload?"""
    if isinstance(payload, dict):
        return any(contains_value(v, value) for v in payload.values())
    if isinstance(payload, (list, tuple)):
        return any(contains_value(v, value) for v in payload)
    return payload == value and not isinstance(payload, bool)
