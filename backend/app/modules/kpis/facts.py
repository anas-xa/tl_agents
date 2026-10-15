"""Normalised KPI facts from either the platform modules or the synthetic demo fixture (never both).

Subscription fact (K1-K5, K29)::

    key, cohort, wave, enrolment_basis (opt_in | default_on_with_opt_out), licence_category, payment_method,
    status, created_on, active_from, active_to, unpaid, invoice_date, term_months,
    lines: [{kind (charge | credit_note), date, date_source, net, vat (None = unconfirmed), gross, term_months,
             payment_status, payment_method, collected_final, collected_platform, refunded,
             refund_cancels_charge, confirmed}],
    opt_out: {at, status (det_confirmed | pending | rejected)} | None, refunds: [{at, reason}],
    complaints: [{at, category}], renewal_due, renewed, cancelled_before_term_end, renewal_choice_marker,
    events: [{type, at}]

Renewal fact (K6): key, dims, issuing_authority, licence_type, prior_expiry, renewal_completed_at (UTC), raw_status,
block_reason_code. Return fact (K7/K8): key, dims, tax_type, statutory_due, due_used, deadline_source, filed_date,
filed_source, extension_recorded. Deliverable fact (K19): key, dims, type, status, signed, released.
Evaluation fact (K20): licence_key, dims, period, result, evaluated_at.

Facts carry internal keys only for counting; keys, licence numbers and company ids never reach any output.
Company financial detail is never read: only billing-line totals the DET billing record carries for the
subscription line, and statuses.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.time import to_dubai

DIMS = ("cohort", "wave", "enrolment_basis", "licence_category")
BASIS_MAP = {"opted_in": "opt_in", "default_on": "default_on_with_opt_out", "opt_in": "opt_in", "default_on_with_opt_out": "default_on_with_opt_out"}
FINAL_BASES = ("billing-line", "invoice-single-line")


def _d(v: Any) -> date | None:
    if v is None or isinstance(v, date) and not isinstance(v, datetime):
        return v
    if isinstance(v, datetime):
        return to_dubai(v).date()
    return date.fromisoformat(str(v)[:10])


def _dt(v: Any) -> datetime | None:
    if v is None or isinstance(v, datetime):
        return v
    return datetime.fromisoformat(str(v))


def data_version(obj: Any) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, default=str).encode()).hexdigest()[:12]


# --- demo fixture ------------------------------------------------------------------------------------------


def fixture_facts(db: Session) -> dict:
    from app.modules.kpis.models import KpiFixtureLicence

    subs, renewals, returns, deliverables, evaluations = [], [], [], [], []
    for row in db.scalars(select(KpiFixtureLicence).order_by(KpiFixtureLicence.fixture_ref)):
        dims = {"cohort": row.cohort, "wave": row.wave, "enrolment_basis": row.enrolment_basis, "licence_category": row.licence_category}
        f = row.facts or {}
        s = dict(f.get("subscription") or {})
        if s:
            s.update(dims, key=row.fixture_ref, licence_key=row.fixture_ref, payment_method=row.payment_method)
            for k in ("created_on", "active_from", "active_to", "invoice_date", "renewal_due"):
                s[k] = _d(s.get(k))
            s["lines"] = [{**ln, "date": _d(ln["date"])} for ln in s.get("lines") or []]
            if s.get("opt_out"):
                s["opt_out"] = {**s["opt_out"], "at": _d(s["opt_out"]["at"])}
            s["refunds"] = [{**r, "at": _d(r["at"])} for r in s.get("refunds") or []]
            s["complaints"] = [{**c, "at": _d(c["at"])} for c in s.get("complaints") or []]
            s["events"] = [{**e, "at": _d(e["at"])} for e in s.get("events") or []]
            subs.append(s)
        if f.get("renewal"):
            r = dict(f["renewal"])
            r.update(dims, key=row.fixture_ref, prior_expiry=_d(r.get("prior_expiry")), renewal_completed_at=_dt(r.get("renewal_completed_at")))
            renewals.append(r)
        for i, rt in enumerate(f.get("returns") or []):
            returns.append({**rt, **dims, "key": f"{row.fixture_ref}-r{i}", "statutory_due": _d(rt.get("statutory_due")), "due_used": _d(rt.get("due_used")), "filed_date": _d(rt.get("filed_date"))})
        for i, dl in enumerate(f.get("deliverables") or []):
            deliverables.append({**dl, **dims, "key": f"{row.fixture_ref}-d{i}"})
        for ev in f.get("evaluations") or []:
            evaluations.append({**ev, **dims, "licence_key": row.fixture_ref, "evaluated_at": _dt(ev["evaluated_at"])})
    all_sources = {"subscriptions": True, "renewals": True, "returns": True, "deliverables": True, "evaluations": True, "usage": True}
    return {"source": "demo_fixture", "subs": subs, "renewals": renewals, "returns": returns, "deliverables": deliverables, "evaluations": evaluations, "sources": all_sources, "missing": {}}


# --- platform modules ----------------------------------------------------------------------------------------


def _subscription_facts(db: Session, cfg: dict) -> tuple[list[dict], dict[str, dict]]:
    """Subscription facts from E2 (subscriptions, billing read-back, allocations, cases, complaints)."""
    from app.modules.licences.models import Licence
    from app.modules.subscriptions.models import (
        BillingRequest,
        Case,
        Complaint,
        PaymentAllocation,
        PaymentEvent,
        Subscription,
        SubscriptionStateHistory,
    )

    categories = {lic.licence_number: (lic.category or "unknown") for lic in db.scalars(select(Licence))}
    allocs = list(db.scalars(select(PaymentAllocation)))
    superseded = {a.supersedes_allocation_id for a in allocs if a.supersedes_allocation_id}
    payments = {p.payment_transaction_id: p for p in db.scalars(select(PaymentEvent))}
    cancel_reasons = set(cfg.get("cancelling_refund_reasons") or [])
    k4_categories = cfg.get("complaint_categories") or []
    qualifying = set(cfg.get("qualifying_events") or [])
    events_by_company: dict[str, list[dict]] = {}
    if qualifying:
        from app.modules.audit.models import AuditEvent

        for ev in db.scalars(select(AuditEvent).where(AuditEvent.event_type.in_(qualifying), AuditEvent.company_id.is_not(None))):
            events_by_company.setdefault(ev.company_id, []).append({"type": ev.event_type, "at": _d(ev.occurred_at)})
    out: list[dict] = []
    company_dims: dict[str, dict] = {}
    for sub in db.scalars(select(Subscription).order_by(Subscription.start_date)):
        hist = list(db.scalars(select(SubscriptionStateHistory).where(SubscriptionStateHistory.subscription_id == sub.id).order_by(SubscriptionStateHistory.event_at)))
        active_from = active_to = None
        for h in hist:
            if h.to_status == "active" and active_from is None:
                active_from = _d(h.event_at)
            elif active_from is not None and h.from_status == "active" and h.to_status != "active":
                active_to = _d(h.event_at)
        if active_from is None and sub.status == "active":
            active_from = sub.start_date
        if active_from is not None:
            active_to = min(active_to or sub.end_date, sub.ended_on or sub.end_date)
        reqs = list(db.scalars(select(BillingRequest).where(BillingRequest.subscription_id == sub.id)))
        lines = []
        unpaid = False
        methods: set[str] = set()
        refunds: list[dict] = []
        for req in reqs:
            line_allocs = [a for a in allocs if a.billing_request_id == req.id and a.id not in superseded]
            col_final = sum(a.amount_fils for a in line_allocs if a.kind == "payment" and a.allocation_basis in FINAL_BASES)
            col_platform = sum(a.amount_fils for a in line_allocs if a.kind == "payment" and a.allocation_basis == "platform-derived")
            for a in line_allocs:
                p = payments.get(a.payment_transaction_id)
                if p is not None and p.channel:
                    methods.add(p.channel)
            reasons = [p.refund_reason for p in payments.values() if p.type == "refund" and ((req.billing_line_id and p.billing_line_id == req.billing_line_id) or (req.invoice_id and p.invoice_id == req.invoice_id))]
            for p in payments.values():
                if p.type == "refund" and ((req.billing_line_id and p.billing_line_id == req.billing_line_id) or (req.invoice_id and p.invoice_id == req.invoice_id)):
                    refunds.append({"at": _d(p.received_at), "reason": p.refund_reason})
            when = req.invoice_date or (req.billing_line_timestamp and _d(req.billing_line_timestamp)) or _d(req.created_at)
            if req.status in ("billed", "pending_confirmation"):
                lines.append({
                    "kind": "charge", "date": when, "date_source": "invoice_date" if req.invoice_date else "billing_line_timestamp",
                    "net": req.net_fils, "vat": req.vat_fils if req.vat_fils else None, "gross": req.gross_fils, "term_months": sub.term_months or max(1, round(sub.term_days / 30.4)),
                    "payment_status": req.collection_status, "payment_method": None, "collected_final": col_final, "collected_platform": col_platform,
                    "refunded": req.refunded_fils, "refund_cancels_charge": any(r in cancel_reasons for r in reasons), "confirmed": req.status == "billed",
                })
            if req.status == "billed" and req.collection_status in ("not_collected", "failed", "partially_collected", "received_unallocated"):
                unpaid = True
        method = sorted(methods)[0] if methods else "unknown"
        for ln in lines:
            ln["payment_method"] = method
        opt = None
        for c in db.scalars(select(Case).where(Case.subscription_id == sub.id, Case.action == "opt_out").order_by(Case.received_at)):
            st = {"applied": "det_confirmed", "rejected": "rejected", "requested": "pending", "pending_DET": "pending", "needs_DET_action": "pending"}.get(c.state)
            if st:
                opt = {"at": _d(c.received_at), "status": st}
        complaints = []
        for c in db.scalars(select(Complaint).where(Complaint.subscription_id == sub.id)):
            cat = c.category if any(x.get("code") == c.category for x in k4_categories) else "uncategorised"
            complaints.append({"at": _d(c.received_at), "category": cat})
        status = {"cancelled_by_opt_out": "opted_out"}.get(sub.status, sub.status)
        dims = {"cohort": (sub.cohort_id or "unknown").split("-")[0], "wave": sub.wave or "unknown", "enrolment_basis": BASIS_MAP.get(sub.enrolment_basis, sub.enrolment_basis), "licence_category": categories.get(sub.licence_number, "unknown")}
        company_dims[sub.company_id] = dims
        invoice = min((ln["date"] for ln in lines if ln["confirmed"]), default=None)
        out.append({
            "key": sub.id, "licence_key": sub.company_id, **dims, "payment_method": method, "status": status, "created_on": _d(sub.created_at), "active_from": active_from, "active_to": active_to, "unpaid": unpaid,
            "invoice_date": invoice, "term_months": sub.term_months, "lines": lines, "opt_out": opt, "refunds": refunds, "complaints": complaints,
            "renewal_due": sub.renewal_due_at or sub.end_date, "renewed": bool(sub.renewed_subscription_id), "cancelled_before_term_end": bool(sub.ended_on and sub.ended_on < sub.end_date and (sub.ended_cause or "").startswith("licence_cancel")),
            "renewal_choice_marker": None, "events": events_by_company.get(sub.company_id, []),
        })
    return out, company_dims


def _renewal_facts(db: Session, company_dims: dict[str, dict]) -> list[dict]:
    from app.modules.licences.models import Licence, LicenceEvent

    out = []
    covered: set[tuple[str, date]] = set()
    lic_by_number = {lic.licence_number: lic for lic in db.scalars(select(Licence))}
    for ev in db.scalars(select(LicenceEvent).where(LicenceEvent.event_type == "renewed", LicenceEvent.previous_expiry_date.is_not(None))):
        lic = lic_by_number.get(ev.licence_number)
        if lic is None:
            continue
        dims = company_dims.get(lic.company_id or "", {}) or {"licence_category": lic.category or "unknown"}
        out.append({"key": f"ren-{ev.id}", **dims, "issuing_authority": lic.issuing_authority, "licence_type": lic.licence_type, "prior_expiry": ev.previous_expiry_date, "renewal_completed_at": ev.renewal_completed_at, "raw_status": ev.raw_status or "RENEWED", "block_reason_code": None})
        covered.add((lic.licence_number, ev.previous_expiry_date))
    for lic in lic_by_number.values():
        if lic.expiry_date and (lic.licence_number, lic.expiry_date) not in covered and lic.expiry_date <= date.today():
            dims = company_dims.get(lic.company_id or "", {}) or {"licence_category": lic.category or "unknown"}
            out.append({"key": f"exp-{lic.id}", **dims, "issuing_authority": lic.issuing_authority, "licence_type": lic.licence_type, "prior_expiry": lic.expiry_date, "renewal_completed_at": None, "raw_status": lic.raw_status or "", "block_reason_code": None})
    return out


def _return_facts(db: Session, company_dims: dict[str, dict]) -> list[dict] | None:
    try:
        from app.modules.deadlines.models import FiledEvidence, Obligation
    except ImportError:
        return None
    evidence = {}
    for fe in db.scalars(select(FiledEvidence)):
        evidence[(fe.company_id, fe.obligation_key)] = fe
    out = []
    for ob in db.scalars(select(Obligation).where(Obligation.obligation_type.in_(("vat_return", "ct_return")), Obligation.superseded.is_(False))):
        fe = evidence.get((ob.company_id, ob.obligation_key))
        filed_source = {"fta_status": "fta_status", "receipt": "company_reported_receipt", "owner_declaration": "owner_declaration"}.get(fe.source) if fe else None
        out.append({"key": ob.obligation_id, **company_dims.get(ob.company_id, {}), "tax_type": ob.obligation_type, "statutory_due": ob.statutory_date, "due_used": ob.due_date_used, "deadline_source": ob.deadline_source, "filed_date": fe.filed_date if fe else None, "filed_source": filed_source, "extension_recorded": ob.due_date_source == "fta_extension"})
    return out


def _deliverable_facts(db: Session, company_dims: dict[str, dict]) -> list[dict] | None:
    try:
        from app.modules.auditagent.models import AuditWorkingFile
    except ImportError:
        return None
    status_map = {"under_review": "in_review"}
    return [
        {"key": f.id, **company_dims.get(f.company_id, {}), "type": f.deliverable_type, "status": status_map.get(f.status, f.status), "signed": f.status == "signed" and not f.signature_void, "released": False}
        for f in db.scalars(select(AuditWorkingFile).where(AuditWorkingFile.is_current.is_(True)))
    ]


def _evaluation_facts(db: Session, company_dims: dict[str, dict]) -> list[dict] | None:
    try:
        from app.modules.auditagent.models import AuditRequiredResult
    except ImportError:
        return None
    return [
        {"licence_key": r.company_id, **company_dims.get(r.company_id, {}), "period": f"FY{r.period_end.year}" if r.period_end else "unknown", "result": r.result, "evaluated_at": r.evaluated_at}
        for r in db.scalars(select(AuditRequiredResult))
    ]


def platform_facts(db: Session, cfg: dict) -> dict:
    subs, company_dims = _subscription_facts(db, cfg)
    renewals = _renewal_facts(db, company_dims)
    sources = {"subscriptions": True, "renewals": True, "usage": True}
    missing: dict[str, list[str]] = {}
    out: dict[str, Any] = {"source": "platform", "subs": subs, "renewals": renewals}
    for name, fn, kpis in (("returns", _return_facts, ("K7", "K8")), ("deliverables", _deliverable_facts, ("K19",)), ("evaluations", _evaluation_facts, ("K20",))):
        try:
            rows = fn(db, company_dims)
        except Exception:  # noqa: BLE001 - a module built in parallel may not have its tables yet
            db.rollback()
            rows = None
        sources[name] = rows is not None
        out[name] = rows or []
        if rows is None:
            for k in kpis:
                missing.setdefault(k, []).append(name)
    # K19 counts issued audit reports from the documents register (E7-S5); until it exists the figure is partial.
    try:
        import app.modules.documents.models  # noqa: F401
    except ImportError:
        missing.setdefault("K19", []).append("documents")
    out["sources"] = sources
    out["missing"] = missing
    return out


def licence_facts_active_keys(subs: list[dict], as_of: date) -> set[str]:
    from app.modules.kpis.calculators import active_at

    return {s.get("licence_key") or s["key"] for s in subs if active_at(s, as_of)}
