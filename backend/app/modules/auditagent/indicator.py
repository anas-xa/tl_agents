"""E7-S2 audit-required indicator (never a legal determination, never a sales prompt).

Criteria are versioned data (seed v1: Ministerial Decision 84/2025 [REG, confirm]): revenue strictly above the
threshold for the single tax period, Qualifying Free Zone Person, tax group. Revenue source order: ledger >
e-invoice (cross-check only) > owner-declared ('declared, unverified'). Near-threshold band (edges inclusive),
source conflicts and non-standard periods whose 12-month equivalent falls on the other side give
'cannot determine' and open a visible escalation case. The owner can acknowledge, hide the banner, dispute the
underlying data or ask for a human review; the owner can never dismiss or override the result.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import Forbidden, NotFound, SwitchedOff, ValidationFailed
from app.core.time import utcnow
from app.modules.audit.service import record_event
from app.modules.auditagent.models import (
    DISPUTE_CODES,
    OWNER_ACTIONS,
    QFZP_VALUES,
    TAX_GROUP_VALUES,
    AuditCriteriaVersion,
    AuditFlagAction,
    AuditInputs,
    AuditRequiredResult,
    AuditRevenueFigure,
    RecomputeJob,
)
from app.modules.auditagent.strings import both, s
from app.modules.config.service import get_config

AED = 100
CASE_REASONS = {"near_threshold": "low_confidence", "at_threshold": "low_confidence", "source_conflict": "data_conflict", "non_standard_period": "data_conflict"}
CHECKLIST = {
    "legal_form": {"en": "Add legal form", "ar": "أضف الشكل القانوني", "gloss_en": "Legal form: how your company is registered, such as LLC.", "gloss_ar": "الشكل القانوني: طريقة تسجيل شركتك، مثل ذ.م.م."},
    "tax_period": {"en": "Add tax period", "ar": "أضف الفترة الضريبية"},
    "annual_revenue": {"en": "Add annual revenue", "ar": "أضف الإيرادات السنوية"},
    "revenue_confirmation": {"en": "Confirm annual revenue", "ar": "أكّد الإيرادات السنوية"},
    "tax_group_status": {"en": "Part of a corporate tax group?", "ar": "هل الشركة جزء من مجموعة ضريبية؟"},
    "qfzp_status": {"en": "Qualifying Free Zone Person status", "ar": "صفة الشخص المؤهل في المنطقة الحرة"},
    "full_period_revenue": {"en": "Add revenue for the full tax period", "ar": "أضف الإيرادات للفترة الضريبية كاملة"},
    "fresh_revenue": {"en": "Refresh revenue data", "ar": "حدّث بيانات الإيرادات"},
}
RETRY_BACKOFF_MIN = [1, 5, 30, 120]


class InjectedFailure(RuntimeError):
    """Raised by tests through ``FAIL_HOOK`` to exercise the retry and dead-letter path."""


FAIL_HOOK: Any = None


# --- criteria governance (four-eyes, server side) ---------------------------------------------------------


def criteria_for(db: Session, period_start: date | None) -> AuditCriteriaVersion | None:
    rows = list(db.scalars(select(AuditCriteriaVersion).order_by(AuditCriteriaVersion.effective_date.desc())))
    if period_start:
        for r in rows:
            if r.effective_date <= period_start:
                return r
    return rows[-1] if rows else None


def propose_criteria(db: Session, *, version_id: str, instrument: str, effective_date: date, triggers: dict, proposer: str, proposer_role: str, **kw: Any) -> AuditCriteriaVersion:
    if proposer_role != "tax_specialist":
        raise Forbidden("only a tax specialist may propose criteria", reason_code="CRITERIA_PROPOSER_ROLE")
    row = AuditCriteriaVersion(id=version_id, instrument=instrument, effective_date=effective_date, effective_scope=kw.pop("effective_scope", "financial years starting on or after the effective date"), triggers=triggers, status="proposed", proposed_by=proposer, proposed_by_role=proposer_role, **kw)
    db.add(row)
    db.flush()
    record_event(db, event_type="CRITERIA_PROPOSED", category="config", actor_role=proposer_role, subject_type="audit_criteria", subject_id=version_id)
    return row


def confirm_criteria(db: Session, version_id: str, *, confirmer: str, confirmer_role: str) -> AuditCriteriaVersion:
    row = db.get(AuditCriteriaVersion, version_id)
    if row is None:
        raise NotFound("criteria version not found", reason_code="NOT_FOUND")
    if confirmer_role != "licensed_auditor":
        raise Forbidden("criteria are confirmed by a licensed audit expert", reason_code="CRITERIA_CONFIRMER_ROLE")
    if confirmer == row.proposed_by:
        raise Forbidden("the proposer cannot confirm the same criteria version", reason_code="FOUR_EYES_REQUIRED")
    row.status, row.confirmed_by, row.confirmed_at = "confirmed", confirmer, utcnow()
    record_event(db, event_type="CRITERIA_CONFIRMED", category="config", actor_role=confirmer_role, subject_type="audit_criteria", subject_id=version_id)
    return row


def publish_criteria(db: Session, version_id: str, *, publisher_role: str) -> AuditCriteriaVersion:
    row = db.get(AuditCriteriaVersion, version_id)
    if row is None:
        raise NotFound("criteria version not found", reason_code="NOT_FOUND")
    if publisher_role in ("owner", "remote_owner", "delegate", "det_admin"):
        raise Forbidden("owners, delegates and DET administrators cannot publish criteria", reason_code="CRITERIA_PUBLISH_ROLE")
    if row.status != "confirmed" or not row.effective_date:
        raise ValidationFailed("publishing needs confirmation and an effective date", reason_code="CRITERIA_NOT_CONFIRMED")
    row.status, row.published_at = "published", utcnow()
    record_event(db, event_type="CRITERIA_PUBLISHED", category="config", actor_role=publisher_role, subject_type="audit_criteria", subject_id=version_id)
    return row


def criteria_dict(c: AuditCriteriaVersion) -> dict:
    return {"id": c.id, "instrument": c.instrument, "effective_date": c.effective_date.isoformat(), "effective_scope": c.effective_scope, "triggers": c.triggers, "near_threshold_band_pct": c.near_threshold_band_pct, "projection_band_pct": c.projection_band_pct, "revenue_source_tolerance_pct": c.revenue_source_tolerance_pct, "short_period_mode": c.short_period_mode, "status": c.status, "proposed_by": c.proposed_by, "confirmed_by": c.confirmed_by, "published_at": c.published_at.isoformat() if c.published_at else None, "label": c.label}


# --- inputs ----------------------------------------------------------------------------------------------


def _months(start: date, end: date) -> int:
    return max(1, round(((end - start).days + 1) / 30.4375))


def _latest_ended_fy(db: Session, company_id: str, today: date) -> tuple[date, date]:
    from app.modules.companies.models import Company

    co = db.get(Company, company_id)
    m, d = (co.financial_year_end_month, co.financial_year_end_day) if co else (12, 31)
    end = date(today.year, m, d)
    if end >= today:
        end = date(today.year - 1, m, d)
    return date(end.year - 1, m, d) + timedelta(days=1), end


def _tax_profile(db: Session, company_id: str):
    try:
        from app.modules.tax.models import TaxEntityProfile

        return db.get(TaxEntityProfile, company_id)
    except ImportError:  # pragma: no cover
        return None


def _verified_tax_group(db: Session, company_id: str) -> str | None:
    """EmaraTax-sourced profile (datalinks) wins over manual declarations; returns yes/no or None."""
    try:
        from app.modules.datalinks.service import current_tax_profiles
    except ImportError:  # pragma: no cover
        return None
    for p in current_tax_profiles(db, company_id):
        if p.tax_type == "ct" and p.verification_tag == "verified_by_source" and p.member_relationship in ("member", "representative", "not_member"):
            return "no" if p.member_relationship == "not_member" else "yes"
    return None


def resolve_inputs(db: Session, company_id: str, *, today: date | None = None) -> dict:
    today = today or date.today()
    inp = db.get(AuditInputs, company_id)
    prof = _tax_profile(db, company_id)
    out: dict[str, Any] = {"has_profile": bool(inp or prof), "notes": []}
    if inp and inp.period_start and inp.period_end:
        out["period_start"], out["period_end"], out["period_confirmed"] = inp.period_start, inp.period_end, inp.period_confirmed
    elif prof is not None:
        ps, pe = _latest_ended_fy(db, company_id, today)
        out["period_start"], out["period_end"], out["period_confirmed"] = ps, pe, True
    else:
        out["period_start"] = out["period_end"] = None
        out["period_confirmed"] = False
    tg, tg_state = None, "not_declared_unverified"
    if inp and inp.tax_group_member:
        tg, tg_state = inp.tax_group_member, inp.tax_group_state
    elif prof is not None and prof.ct_status in ("tax_group", "standalone_mainland", "qfzp"):
        tg, tg_state = ("yes" if prof.ct_status == "tax_group" else "no"), "self_declared_unverified"
    verified = _verified_tax_group(db, company_id)
    if verified is not None:
        if tg is not None and tg != verified:
            out["notes"].append("emaratax_conflict_emaratax_wins")
        tg, tg_state = verified, "fta_confirmed"
    out["tax_group"] = tg if tg in ("yes", "no") else "unknown"
    out["tax_group_state"] = tg_state
    qfzp = inp.qfzp if inp else ("yes" if prof is not None and prof.ct_status == "qfzp" else str(get_config(db, "auditagent.qfzp.default_mainland", "not_applicable")))
    out["qfzp"] = qfzp
    out["qfzp_state"] = inp.qfzp_state if inp else "not_declared_unverified"
    figures: list[dict] = []
    if out["period_start"]:
        ps, pe = out["period_start"], out["period_end"]
        for f in db.scalars(select(AuditRevenueFigure).where(AuditRevenueFigure.company_id == company_id, AuditRevenueFigure.is_current.is_(True), AuditRevenueFigure.period_start == ps, AuditRevenueFigure.period_end == pe)):
            figures.append({"source": f.source, "amount_fils": f.amount_fils, "vat_fils": f.vat_fils, "net_fils": f.amount_fils - (f.vat_fils or 0), "covers_full_period": f.covers_full_period, "owner_confirmed": f.owner_confirmed, "as_of": f.as_of.isoformat(), "label": "declared, unverified" if f.source == "owner_declared" else None})
        sources = {f["source"] for f in figures}
        if "ledger" not in sources:
            led = _ledger_revenue(db, company_id, ps, pe)
            if led:
                figures.append(led)
        if "owner_declared" not in sources and prof is not None:
            od = _declared_revenue(db, company_id, prof, ps, pe)
            if od:
                figures.append(od)
    out["figures"] = figures
    return out


def _ledger_revenue(db: Session, company_id: str, ps: date, pe: date) -> dict | None:
    try:
        from app.modules.bookkeeping.service import confirmed_transactions
    except ImportError:  # pragma: no cover
        return None
    rows = [(c, t) for c, t in confirmed_transactions(db, company_id, ps, pe) if (c.final_ledger_account or "").startswith("4") and t.direction == "in"]
    if not rows:
        return None
    months = {(t.txn_date.year, t.txn_date.month) for _, t in rows}
    gross = sum(t.aed_amount_fils for _, t in rows)
    vat = sum((t.vat_amount_stated_fils or round(t.aed_amount_fils * 5 / 105)) if c.final_vat_code == "SR" else 0 for c, t in rows)
    need = _months(ps, pe)
    return {"source": "ledger", "amount_fils": gross, "vat_fils": vat, "net_fils": gross - vat, "covers_full_period": len(months) >= need, "owner_confirmed": True, "as_of": utcnow().isoformat(), "months_covered": len(months), "label": None}


def _declared_revenue(db: Session, company_id: str, prof: Any, ps: date, pe: date) -> dict | None:
    try:
        from app.modules.tax.models import TaxPeriodRevenue
    except ImportError:  # pragma: no cover
        return None
    row = db.scalar(select(TaxPeriodRevenue).where(TaxPeriodRevenue.company_id == company_id, TaxPeriodRevenue.period_start == ps, TaxPeriodRevenue.period_end == pe))
    if row is not None:
        return {"source": "owner_declared", "amount_fils": row.revenue_fils, "vat_fils": 0, "net_fils": row.revenue_fils, "covers_full_period": True, "owner_confirmed": row.confirmed_by is not None, "as_of": (row.confirmed_at or utcnow()).isoformat(), "label": "declared, unverified"}
    if prof.revenue_fils is not None:
        return {"source": "owner_declared", "amount_fils": prof.revenue_fils, "vat_fils": 0, "net_fils": prof.revenue_fils, "covers_full_period": True, "owner_confirmed": prof.revenue_confirmed_at is not None, "as_of": (prof.revenue_confirmed_at or prof.updated_at).isoformat(), "label": "declared, unverified"}
    return None


# --- evaluation -------------------------------------------------------------------------------------------


def compute(db: Session, company_id: str, inputs: dict, crit: AuditCriteriaVersion, *, now: datetime | None = None) -> dict:
    """Pure evaluation of the resolved inputs under one criteria version."""
    now = now or utcnow()
    thr = int(crit.triggers.get("revenue_threshold_fils", 50_000_000 * AED))
    band_cfg = get_config(db, "auditagent.criteria.near_threshold_band_pct", None)
    band = int(crit.near_threshold_band_pct if band_cfg is None else band_cfg)
    tol_cfg = get_config(db, "auditagent.revenue.source_tolerance_pct", None)
    tol = float(crit.revenue_source_tolerance_pct if tol_cfg is None else tol_cfg)
    lower, upper = thr * (100 - band) // 100, thr * (100 + band) // 100
    cd: list[str] = []
    checklist: list[str] = []
    caveats: list[str] = []
    reasons: list[str] = []
    out: dict[str, Any] = {"revenue_source": None, "governing_revenue_fils": None, "twelve_month_equivalent_fils": None, "period_months": None, "near_threshold": False}

    def add(code: str, item: str | None = None) -> None:
        if code not in cd:
            cd.append(code)
        if item and item not in checklist:
            checklist.append(item)

    if not inputs.get("has_profile"):
        add("missing_profile", "legal_form")
    if inputs.get("tax_group") == "yes" and crit.triggers.get("tax_group", True):
        reasons.append("tax_group")
    if inputs.get("qfzp") == "yes" and crit.triggers.get("qfzp", True):
        reasons.append("qualifying_free_zone_person")
    ps, pe = inputs.get("period_start"), inputs.get("period_end")
    if not ps or not pe or not inputs.get("period_confirmed"):
        add("missing_profile", "tax_period")
    else:
        out["period_months"] = _months(ps, pe)
    figures = inputs.get("figures") or []
    full = [f for f in figures if f["covers_full_period"]]
    if not figures:
        add("missing_profile", "annual_revenue")
    elif not full:
        add("coverage_failure", "full_period_revenue")  # partial period = missing, not prorated
    else:
        order = ["ledger", "e_invoice", "owner_declared"] if get_config(db, "auditagent.revenue.einvoice_primary_allowed", False) else ["ledger", "owner_declared"]
        governing = next((f for src in order for f in full if f["source"] == src), None)
        if governing is None:
            add("missing_profile", "annual_revenue")
        else:
            net = int(governing["net_fils"])
            out["revenue_source"], out["governing_revenue_fils"] = governing["source"], net
            stale_days = int(get_config(db, "auditagent.revenue.stale_after_days", 180) or 180)
            if datetime.fromisoformat(governing["as_of"]) < now - timedelta(days=stale_days):
                add("stale_data", "fresh_revenue")
            if not governing.get("owner_confirmed"):
                add("missing_profile", "revenue_confirmation")
            for other in full:
                if other is governing:
                    continue
                o = int(other["net_fils"])
                gap = abs(net - o) / max(net, o, 1) * 100
                if gap > tol:
                    if (net > thr) != (o > thr):  # lower-ranked never silently overrides: disagreement across the threshold
                        add("source_conflict")
                    else:
                        caveats.append("source_discrepancy_same_result")
            months = out["period_months"]
            if months and months != 12:
                eq = net * 12 // months
                out["twelve_month_equivalent_fils"] = eq
                if (net > thr) != (eq > thr):
                    add("non_standard_period")
            if lower <= net <= upper:
                out["near_threshold"] = True
                add("near_threshold")
                if net == thr:
                    add("at_threshold")
            elif net > thr and crit.triggers.get("revenue_threshold", True):
                reasons.append("revenue_threshold")
    if inputs.get("tax_group") == "unknown" and not reasons:
        add("missing_profile", "tax_group_status")
        caveats.append("revenue_only")
    if inputs.get("qfzp") == "unknown":
        add("missing_profile", "qfzp_status")
    structural = [r for r in reasons if r in ("tax_group", "qualifying_free_zone_person")]
    if structural:
        result = "likely_required"  # tax group / QFZP: likely required regardless of revenue
    elif reasons and not cd:
        result = "likely_required"
    elif cd:
        result = "cannot_determine"
    else:
        result = "likely_not_required"
    if result != "cannot_determine":
        cd, checklist = [], []
    out.update({"result": result, "reasons": reasons, "cannot_determine_reasons": cd, "checklist": checklist, "caveats": caveats, "notes": inputs.get("notes", [])})
    return out


def _canon(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, default=str, separators=(",", ":"))


def latest_result(db: Session, company_id: str) -> AuditRequiredResult | None:
    return db.scalar(select(AuditRequiredResult).where(AuditRequiredResult.company_id == company_id, AuditRequiredResult.is_latest.is_(True)).order_by(AuditRequiredResult.evaluated_at.desc()).limit(1))


def evaluate(db: Session, company_id: str, *, cause: str = "input_changed", actor_key: str | None = None, today: date | None = None, is_demo: bool = False) -> AuditRequiredResult:
    """Idempotent by (company, period, input_version_hash, criteria_version). History is kept; notify on change only."""
    if FAIL_HOOK is not None:
        FAIL_HOOK(company_id)
    inputs = resolve_inputs(db, company_id, today=today)
    crit = criteria_for(db, inputs.get("period_start"))
    if crit is None:
        raise ValidationFailed("no criteria version loaded", reason_code="CRITERIA_MISSING")
    input_hash = hashlib.sha256(_canon({k: v for k, v in inputs.items() if k != "notes"} | {"figures": [{k: v for k, v in f.items() if k != "as_of"} for f in inputs.get("figures", [])]}).encode()).hexdigest()
    period_key = f"{inputs.get('period_start')}_{inputs.get('period_end')}"
    run_key = hashlib.sha256(f"{company_id}|{period_key}|{input_hash}|{crit.id}|{crit.status}".encode()).hexdigest()
    existing = db.scalar(select(AuditRequiredResult).where(AuditRequiredResult.run_key == run_key))
    if existing is not None:
        existing.not_refreshed = False
        return existing  # repeat run with the same idempotency key writes nothing new
    res = compute(db, company_id, inputs, crit)
    prev = latest_result(db, company_id)
    licence_id = None
    try:
        from app.modules.licences.models import Licence

        lic = db.scalar(select(Licence).where(Licence.company_id == company_id).limit(1))
        licence_id = lic.id if lic else None
    except ImportError:  # pragma: no cover
        pass
    row = AuditRequiredResult(
        company_id=company_id, licence_id=licence_id, period_start=inputs.get("period_start"), period_end=inputs.get("period_end"), period_months=res["period_months"],
        result=res["result"], reasons=res["reasons"], cannot_determine_reasons=res["cannot_determine_reasons"], checklist=res["checklist"], caveats=res["caveats"] + [f"note:{n}" for n in res["notes"]],
        criteria_version_id=crit.id, instrument=crit.instrument, confirmation_state="confirmed" if crit.status in ("confirmed", "published") and crit.confirmed_by else "indicative_pending_expert_confirmation",
        revenue_source=res["revenue_source"], revenue_figures=inputs.get("figures", []), governing_revenue_fils=res["governing_revenue_fils"], twelve_month_equivalent_fils=res["twelve_month_equivalent_fils"],
        near_threshold=res["near_threshold"], input_version_hash=input_hash, run_key=run_key, previous_result=prev.result if prev else None, change_cause=cause if prev and prev.result != res["result"] else None, is_demo=is_demo,
    )
    if prev is not None:
        prev.is_latest = False
        row.acknowledged_at = prev.acknowledged_at if prev.result == res["result"] else None
        row.acknowledged_by = prev.acknowledged_by if prev.result == res["result"] else None
        row.banner_hidden_at = prev.banner_hidden_at if prev.result == res["result"] else None
    db.add(row)
    db.flush()
    record_event(db, event_type="FLAG_COMPUTED", category="agent", actor_key=actor_key, company_id=company_id, subject_type="audit_required_result", subject_id=row.id, details={"result": row.result, "reasons": row.reasons, "cannot_determine": row.cannot_determine_reasons, "criteria_version": crit.id, "cause": cause})
    if prev is not None and prev.result != row.result:
        record_event(db, event_type="FLAG_CHANGED", category="agent", company_id=company_id, subject_type="audit_required_result", subject_id=row.id, details={"old": prev.result, "new": row.result, "cause": cause})
        record_event(db, event_type="NOTIFICATION_SENT", category="reminder", company_id=company_id, subject_type="audit_required_result", subject_id=row.id, details={"kind": "audit_indicator_changed"})
    case_reason = next((CASE_REASONS[c] for c in row.cannot_determine_reasons if c in CASE_REASONS), None)
    if row.result == "cannot_determine" and case_reason:
        row.case_id = _open_case(db, company_id, row, case_reason, actor_key)
    db.flush()
    return row


def _open_case(db: Session, company_id: str, row: AuditRequiredResult, reason: str, actor_key: str | None, *, event_id: str | None = None, opened_by: str = "agent", trigger_source: str = "agent_output") -> str | None:
    try:
        from app.modules.escalation.service import open_case
    except ImportError:  # pragma: no cover
        return None
    case = open_case(db, company_id=company_id, module="audit", reason_code=reason, matter_key=f"audit_required|{row.period_end}", event_id=event_id or f"arr-{row.run_key[:20]}", opened_by=opened_by, opened_by_key=actor_key, trigger_source=trigger_source, trigger_rule_id="audit_required", linked_item_id=row.id, period_ref=str(row.period_end), details={"cannot_determine": row.cannot_determine_reasons})
    record_event(db, event_type="CASE_OPENED", category="escalation", actor_key=actor_key, company_id=company_id, subject_type="audit_required_result", subject_id=row.id, details={"case_id": case.case_id, "reason": reason})
    return case.case_id


# --- recompute queue with retries ---------------------------------------------------------------------------


def request_recompute(db: Session, company_id: str, cause: str, *, run_now: bool = True, now: datetime | None = None) -> RecomputeJob:
    now = now or utcnow()
    job = db.scalar(select(RecomputeJob).where(RecomputeJob.company_id == company_id, RecomputeJob.status.in_(("pending", "retrying"))))
    if job is None:  # coalesced per company + period
        job = RecomputeJob(company_id=company_id, cause=cause, next_attempt_at=now)
        db.add(job)
        db.flush()
    if run_now:
        run_recompute_jobs(db, now=now, company_id=company_id)
    return job


def run_recompute_jobs(db: Session, *, now: datetime | None = None, company_id: str | None = None) -> dict:
    now = now or utcnow()
    stmt = select(RecomputeJob).where(RecomputeJob.status.in_(("pending", "retrying")), RecomputeJob.next_attempt_at <= now)
    if company_id:
        stmt = stmt.where(RecomputeJob.company_id == company_id)
    done = failed = dead = 0
    backoff = get_config(db, "auditagent.recompute.retry_backoff_minutes", RETRY_BACKOFF_MIN) or RETRY_BACKOFF_MIN
    for job in list(db.scalars(stmt.order_by(RecomputeJob.created_at))):
        try:
            with db.begin_nested():
                evaluate(db, job.company_id, cause=job.cause)
            job.status, job.finished_at = "done", now
            done += 1
        except Exception as exc:  # retry 1m, 5m, 30m, 2h then dead letter with alert
            job.attempts += 1
            job.last_error = type(exc).__name__
            if job.attempts > len(backoff):
                job.status, job.finished_at = "dead_letter", now
                last = latest_result(db, job.company_id)
                if last is not None:
                    last.not_refreshed = True
                record_event(db, event_type="DEAD_LETTER_ALERT", category="system", outcome="failed", company_id=job.company_id, subject_type="recompute_job", subject_id=job.id, details={"attempts": job.attempts})
                dead += 1
            else:
                job.status = "retrying"
                job.next_attempt_at = now + timedelta(minutes=int(backoff[job.attempts - 1]))
                failed += 1
    db.flush()
    return {"done": done, "retrying": failed, "dead_letter": dead}


# --- owner inputs and actions --------------------------------------------------------------------------------


def set_inputs(db: Session, company_id: str, *, actor_name: str, actor_role: str, actor_key: str | None, payload: dict) -> AuditInputs:
    inp = db.get(AuditInputs, company_id)
    if inp is None:
        inp = AuditInputs(company_id=company_id)
        db.add(inp)
    owner_level = actor_role in ("owner", "remote_owner")
    if "tax_group_member" in payload and payload["tax_group_member"] is not None:
        if payload["tax_group_member"] not in TAX_GROUP_VALUES:
            raise ValidationFailed("tax group answer must be yes, no or don't know", reason_code="VALUE_INVALID")
        inp.tax_group_member = payload["tax_group_member"]
        inp.tax_group_state = "self_declared_unverified" if owner_level else "owner_entered_unverified"
    if payload.get("qfzp") is not None:
        if payload["qfzp"] not in QFZP_VALUES:
            raise ValidationFailed("QFZP answer is not valid", reason_code="VALUE_INVALID")
        inp.qfzp, inp.qfzp_state = payload["qfzp"], "self_declared_unverified"
    if payload.get("period_start") and payload.get("period_end"):
        inp.period_start, inp.period_end = date.fromisoformat(str(payload["period_start"])), date.fromisoformat(str(payload["period_end"]))
        inp.period_confirmed = owner_level
    inp.declared_by, inp.declared_by_role, inp.declared_at, inp.updated_at = actor_name, actor_role, utcnow(), utcnow()
    inp.owner_confirmed = owner_level
    if payload.get("revenue_fils") is not None:
        inputs = resolve_inputs(db, company_id)
        ps, pe = inp.period_start or inputs.get("period_start"), inp.period_end or inputs.get("period_end")
        if not ps or not pe:
            raise ValidationFailed("add the tax period first", reason_code="PERIOD_REQUIRED")
        for old in db.scalars(select(AuditRevenueFigure).where(AuditRevenueFigure.company_id == company_id, AuditRevenueFigure.source == "owner_declared", AuditRevenueFigure.is_current.is_(True))):
            old.is_current = False
        db.add(AuditRevenueFigure(company_id=company_id, period_start=ps, period_end=pe, source="owner_declared", amount_fils=int(payload["revenue_fils"]), vat_fils=int(payload.get("vat_fils") or 0), covers_full_period=True, owner_confirmed=owner_level, entered_by=actor_name))
    db.flush()
    record_event(db, event_type="AUDIT_INPUTS_UPDATED", category="config", actor_key=actor_key, actor_role=actor_role, company_id=company_id, details={"fields": sorted(k for k, v in payload.items() if v is not None)})
    request_recompute(db, company_id, "input_changed")
    return inp


def owner_action(db: Session, principal: Any, company_id: str, *, action: str, role: str, reason_code: str | None = None, reason_text: str | None = None) -> dict:
    """Acknowledge, hide the banner, dispute the underlying data, request a human review. Never dismiss or override."""
    if action not in OWNER_ACTIONS:
        record_event(db, event_type="OVERRIDE_REFUSED", category="agent", outcome="refused", reason_code="OWNER_CANNOT_OVERRIDE", actor_key=principal.actor_key, actor_role=role, company_id=company_id, details={"action": action})
        raise ValidationFailed("The result cannot be dismissed or overridden. You can dispute the underlying data or ask for a human review.", reason_code="OWNER_CANNOT_OVERRIDE")
    if role in ("remote_owner",) and action in ("acknowledge", "hide_banner"):
        raise Forbidden("Your role can view this. Ask the owner for access to change it.", reason_code="READ_ONLY_ROLE")
    row = latest_result(db, company_id)
    act = AuditFlagAction(company_id=company_id, result_id=row.id if row else None, action=action, reason_code=reason_code, reason_text=(reason_text or None), by_uuid=principal.identity_uuid, by_name=principal.display_name, by_role=role)
    out: dict[str, Any] = {"action": action}
    if action == "ask_auditor":
        if not get_config(db, "auditagent.ask_auditor_path.enabled", False):
            raise SwitchedOff("this path is switched off in this version", reason_code="FEATURE_SWITCHED_OFF")
        out["text"] = {"next_steps": both("next_steps"), "free_choice": both("free_choice")}
    elif row is None:
        raise ValidationFailed("no result has been computed yet", reason_code="NOT_YET_ASSESSED")
    elif action == "acknowledge":
        row.acknowledged_by, row.acknowledged_at = principal.display_name, utcnow()
    elif action == "hide_banner":
        row.banner_hidden_at = utcnow()
    elif action == "dispute":
        if reason_code not in DISPUTE_CODES:
            raise ValidationFailed("choose what is wrong with the underlying data", reason_code="DISPUTE_CODE_REQUIRED", details={"codes": list(DISPUTE_CODES)})
    elif action == "request_review":
        target = int(get_config(db, "auditagent.human_review.target_working_days", 3) or 3)
        db.add(act)
        db.flush()
        case_id = _open_case(db, company_id, row, "user_requested", principal.actor_key, event_id=f"review-{act.id}", opened_by=role, trigger_source="user_raised")
        act.case_id = case_id
        ref = None
        try:
            from app.modules.escalation.models import EscalationCase

            c = db.get(EscalationCase, case_id) if case_id else None
            ref = getattr(c, "case_reference", None) or getattr(c, "reference", None) or case_id
        except ImportError:  # pragma: no cover
            ref = case_id
        out.update({"case_id": case_id, "case_reference": ref, "target_working_days": target, "target_label": both("review_target", n=target)})
    if act not in db:
        db.add(act)
    db.flush()
    record_event(db, event_type={"dispute": "DISPUTE_OPENED", "acknowledge": "CHANGE_NOTICE_ACKNOWLEDGED"}.get(action, f"AUDIT_FLAG_{action.upper()}"), category="agent", actor_key=principal.actor_key, actor_role=role, company_id=company_id, subject_type="audit_required_result", subject_id=row.id if row else None, details={"reason_code": reason_code, "case_id": act.case_id})
    out["result"] = row.result if row else None
    return out


# --- presentation --------------------------------------------------------------------------------------------


def wording(row: AuditRequiredResult | None) -> dict:
    """Fixed, approved wording keys; 'may', never 'must'; no price, buy button or provider referral."""
    if row is None:
        return {"state": "not_yet_assessed", "keys": ["badge_indicative", "disclaimer"]}
    keys = ["badge_indicative"]
    if row.result == "likely_required":
        keys += ["headline_likely_required", "may_be_required"]
        if "revenue_threshold" in row.reasons:
            keys.append("shown_because_revenue")
        keys += ["next_steps", "free_choice"]
    elif row.result == "likely_not_required":
        keys += ["headline_likely_not_required", "not_indicated_detail"]
    else:
        keys += ["headline_cannot_determine"]
        if row.checklist:
            keys.append("cannot_determine_items")
        if row.near_threshold:
            keys.append("near_threshold_strip")
        if "at_threshold" in row.cannot_determine_reasons:
            keys.append("at_threshold")
    if "revenue_only" in (row.caveats or []):
        keys.append("caveat_revenue_only")
    keys += ["disclaimer_basis", "disclaimer"]
    return {"state": row.result, "keys": keys}


def _text(row: AuditRequiredResult | None, lang: str) -> dict:
    w = wording(row)
    out = {}
    for k in w["keys"]:
        if k == "headline_likely_required" and row is not None:
            reason = " / ".join(s(f"reason_{r}", lang) for r in row.reasons) or s("reason_revenue_threshold", lang)
            out[k] = s(k, lang, reason=reason)
        elif k == "cannot_determine_items" and row is not None:
            out[k] = s(k, lang, items=", ".join(CHECKLIST.get(i, {}).get(lang, i) for i in row.checklist))
        elif k == "disclaimer_basis" and row is not None:
            out[k] = s(k, lang, rule_set=f"criteria {row.criteria_version_id}", date=row.evaluated_at.date().isoformat())
        else:
            out[k] = s(k, lang)
    return out


def result_dict(db: Session, row: AuditRequiredResult | None, *, log_display: bool = False, actor_key: str | None = None, company_id: str | None = None) -> dict:
    if log_display:
        record_event(db, event_type="FLAG_DISPLAYED", category="data_access", actor_key=actor_key, company_id=company_id, subject_type="audit_required_result", subject_id=row.id if row else None, details={"criteria_version": row.criteria_version_id if row else None, "state": row.result if row else "not_yet_assessed"})
    if row is None:
        return {"state": "not_yet_assessed", "wording": wording(None), "text": {"en": _text(None, "en"), "ar": _text(None, "ar")}}
    case = None
    if row.case_id:
        try:
            from app.modules.escalation.models import EscalationCase
            from app.modules.escalation.service import owner_status

            c = db.get(EscalationCase, row.case_id)
            if c is not None:
                case = {"case_id": c.case_id, "status": owner_status(c), "opened_at": c.opened_at.isoformat(), "owning_role": "Licensed auditor firm"}
        except ImportError:  # pragma: no cover
            case = {"case_id": row.case_id}
    history = [{"result": h.result, "evaluated_at": h.evaluated_at.isoformat(), "criteria_version": h.criteria_version_id, "cause": h.change_cause} for h in db.scalars(select(AuditRequiredResult).where(AuditRequiredResult.company_id == row.company_id).order_by(AuditRequiredResult.evaluated_at.desc()).limit(10))]
    return {
        "id": row.id, "state": row.result, "reasons": row.reasons, "cannot_determine_reasons": row.cannot_determine_reasons,
        "checklist": [{"item": i, **CHECKLIST.get(i, {})} for i in row.checklist], "caveats": row.caveats,
        "criteria_version": row.criteria_version_id, "instrument": row.instrument, "confirmation_state": row.confirmation_state,
        "period_start": row.period_start.isoformat() if row.period_start else None, "period_end": row.period_end.isoformat() if row.period_end else None, "period_months": row.period_months,
        "revenue_source": row.revenue_source, "revenue_source_order": ["ledger", "e_invoice", "owner_declared"], "revenue_figures": row.revenue_figures, "governing_revenue_fils": row.governing_revenue_fils,
        "twelve_month_equivalent_fils": row.twelve_month_equivalent_fils, "near_threshold": row.near_threshold, "evaluated_at": row.evaluated_at.isoformat(),
        "previous_result": row.previous_result, "change_cause": row.change_cause, "change_notice": bool(row.previous_result and row.previous_result != row.result and not row.acknowledged_at),
        "acknowledged_by": row.acknowledged_by, "acknowledged_at": row.acknowledged_at.isoformat() if row.acknowledged_at else None, "banner_hidden": row.banner_hidden_at is not None,
        "not_refreshed": row.not_refreshed, "case": case, "is_demo": row.is_demo, "history": history,
        "wording": wording(row), "text": {"en": _text(row, "en"), "ar": _text(row, "ar")},
        "ask_auditor_enabled": False,
    }


def audit_flag_summary(db: Session, company_id: str) -> dict:
    """Dashboard summary (K20 state): state, reason codes, wording keys, evaluated_at."""
    row = latest_result(db, company_id)
    w = wording(row)
    return {"state": row.result if row else "not_yet_assessed", "reason_codes": (row.reasons + row.cannot_determine_reasons) if row else [], "wording_keys": w["keys"], "evaluated_at": row.evaluated_at.isoformat() if row else None, "criteria_version": row.criteria_version_id if row else None, "confirmation_state": row.confirmation_state if row else None, "case_id": row.case_id if row else None, "near_threshold": bool(row and row.near_threshold)}


# --- K20 ---------------------------------------------------------------------------------------------------------


def _suppress(cells: dict[str, int], minimum: int) -> dict[str, dict]:
    out = {k: {"value": v, "suppressed": 0 < v < minimum} for k, v in cells.items()}
    hidden = [k for k, c in out.items() if c["suppressed"]]
    if len(hidden) == 1:  # complementary suppression: hide the next smallest cell too
        rest = sorted((k for k, c in out.items() if not c["suppressed"] and c["value"] > 0), key=lambda k: out[k]["value"])
        if rest:
            out[rest[0]]["suppressed"] = True
    for c in out.values():
        if c["suppressed"]:
            c["value"] = None
    return out


def k20(db: Session) -> dict:
    """Audit-required share of licences; DET view minimum cell 10 with complementary suppression."""
    minimum = int(get_config(db, "auditagent.k20.min_cell_size", 10) or 10)
    try:
        from app.modules.licences.models import Licence

        licences = list(db.scalars(select(Licence).where(Licence.status == "active")))
    except ImportError:  # pragma: no cover
        licences = []
    states = {"likely_required": 0, "likely_not_required": 0, "cannot_determine": 0}
    near = changed = not_evaluated = 0
    for lic in licences:
        row = latest_result(db, lic.company_id)
        if row is None:
            not_evaluated += 1
            continue
        states[row.result] = states.get(row.result, 0) + 1
        near += int(row.near_threshold)
        first = db.scalar(select(AuditRequiredResult).where(AuditRequiredResult.company_id == lic.company_id).order_by(AuditRequiredResult.evaluated_at).limit(1))
        changed += int(first is not None and first.result != row.result)
    denom = sum(states.values())
    cells = _suppress(states, minimum)
    shares = {k: (round(c["value"] / denom, 4) if (c["value"] is not None and denom >= minimum) else None) for k, c in cells.items()}
    return {
        "denominator": denom if denom >= minimum else None, "denominator_suppressed": 0 < denom < minimum, "cells": cells, "shares": shares,
        "near_threshold_overlay": near if near >= minimum else None, "changed_result": changed if changed >= minimum else None,
        "not_yet_evaluated": not_evaluated if (not_evaluated == 0 or not_evaluated >= minimum) else None, "min_cell_size": minimum,
        "note": "Indicator shares, not legal determinations. Cells below the minimum size are hidden with complementary suppression.",
    }
