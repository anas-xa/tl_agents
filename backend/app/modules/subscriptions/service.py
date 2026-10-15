"""Subscription creation, fee schedule, lifecycle, billing hook, payment allocation, opt-out/refund cases,
complaints and first-run welcome (E2-S2, E2-S3, E2-S4).

This module consumes the licence-event outbox; it never imports the licence-event handler module and is
never called from it (contract test).
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import Conflict, Forbidden, NotFound, SwitchedOff, ValidationFailed
from app.core.ids import reference_code
from app.core.time import DUBAI, dubai_date, dubai_today, utcnow
from app.modules.audit.service import record_event
from app.modules.config.service import get_config
from app.modules.licences.models import Licence, LicenceEvent, LicenceEventOutbox
from app.modules.licences.outbox import register_consumer
from app.modules.subscriptions.models import (
    CASE_TERMINAL,
    COMPLAINT_STATUSES,
    TRANSITIONS,
    BillingAdjustmentProposal,
    BillingRequest,
    Case,
    Complaint,
    PaymentAllocation,
    PaymentEvent,
    ReconciliationItem,
    Subscription,
    SubscriptionStateHistory,
    WelcomeRun,
)

# --- switches and configuration ------------------------------------------------------------------------


def switch(db: Session, name: str, default: bool = False) -> bool:
    return bool(get_config(db, f"subscription.{name}.enabled", default))


def require_switch(db: Session, name: str, default: bool = False) -> None:
    if not switch(db, name, default):
        raise SwitchedOff(f"subscription increment '{name}' is switched off", reason_code="FEATURE_SWITCHED_OFF", details={"switch": f"subscription.{name}.enabled"})


def fee_schedules(db: Session) -> list[dict]:
    return list(get_config(db, "fee_schedule.schedules", []) or [])


def schedule_in_force(db: Session, on: date) -> dict:
    """The schedule version effective on the event date; later versions never alter existing subscriptions."""
    rows = sorted(fee_schedules(db), key=lambda s: s.get("effective_date", ""))
    chosen = None
    for s in rows:
        if date.fromisoformat(s["effective_date"]) <= on:
            chosen = s
    if chosen is None and rows:
        chosen = rows[0]
    if chosen is None:
        raise NotFound("no fee schedule configured", reason_code="FEE_SCHEDULE_MISSING")
    return chosen


def opt_out_config(db: Session) -> dict:
    return dict(get_config(db, "opt_out.config", {}) or {})


def tbc_labels(db: Session) -> dict:
    """Every parameter still to be confirmed with DET, so screens show 'to be confirmed with DET', never a number."""
    cfg = opt_out_config(db)
    out = {}
    for key in ("opt_out_window_days", "refund_window_days", "cancel_effective", "refund_mode", "pro_rata_refund", "notice_period", "complaint_reply_period_working_days", "refund_response_time_working_days", "post_opt_out_data_retention_days"):
        item = cfg.get(key) or {}
        out[key] = {"value": item.get("value"), "status": item.get("status", "example"), "confirmed": item.get("status") == "confirmed", "label": item.get("label", "to be confirmed with DET")}
    return out


# --- fee arithmetic (pure) -------------------------------------------------------------------------------


def round_half_up_div(numerator: int, denominator: int) -> int:
    """Integer half-up division, once per line, in fils."""
    return (numerator * 2 + denominator) // (denominator * 2)


def whole_months_between(start: date, end_inclusive: date) -> int | None:
    """Number of whole months if end+1 day is exactly start plus n months, else None."""
    nxt = end_inclusive + timedelta(days=1)
    months = (nxt.year - start.year) * 12 + (nxt.month - start.month)
    if months <= 0:
        return None
    y, m = start.year + (start.month - 1 + months) // 12, (start.month - 1 + months) % 12 + 1
    try:
        candidate = start.replace(year=y, month=m)
    except ValueError:
        return None
    return months if candidate == nxt else None


def compute_fee(base_annual_fils: int, start: date, end_inclusive: date, *, vat_rate_bp: int = 500, proration: str = "days", vat_split: bool = True) -> dict:
    """Fee from the versioned schedule: whole months -> base x months / 12; otherwise base x days / 365
    (leap years not special-cased); VAT half-up once per line; gross = net + VAT. Rounding once per line."""
    term_days = (end_inclusive - start).days + 1
    if term_days <= 0:
        raise ValidationFailed("term end must not precede term start", reason_code="TERM_INVALID")
    months = whole_months_between(start, end_inclusive)
    if proration == "none":
        net, term_type = base_annual_fils, "whole_months"
        months = months if months else None
    elif months is not None:
        net, term_type = round_half_up_div(base_annual_fils * months, 12), "whole_months"
    else:
        net, term_type = round_half_up_div(base_annual_fils * term_days, 365), "part_term"
    vat = round_half_up_div(net * vat_rate_bp, 10000) if vat_split else 0
    return {"net_fils": net, "vat_fils": vat, "gross_fils": net + vat, "term_days": term_days, "term_months": months, "term_type": term_type, "vat_rate_bp": vat_rate_bp if vat_split else 0}


def distribute(amount_fils: int, months: int) -> list[int]:
    """Recognition split: equal integer parts, the last month takes the remainder (100/3 -> 33, 33, 34)."""
    if months <= 0:
        return []
    base, rem = divmod(amount_fils, months)
    return [base] * (months - 1) + [base + rem]


def cohort_month(invoice_at_utc: datetime) -> str:
    """Invoice month after converting UTC -> Asia/Dubai (31 Mar 23:59 GST -> 2027-03; 1 Apr 00:00 GST -> 2027-04)."""
    local = invoice_at_utc.replace(tzinfo=UTC).astimezone(DUBAI)
    return f"{local.year:04d}-{local.month:02d}"


def allocate_platform_derived(payment_fils: int, lines: list[dict]) -> list[dict]:
    """alloc-v1 (c): pro-rata by gross line amount, half-up once per line in line order; the residual fil
    goes to the largest line (the licence fee), never the subscription line."""
    total = sum(int(line["gross_fils"]) for line in lines)
    if total <= 0:
        return []
    out = []
    for line in lines:
        out.append({"line_id": line["line_id"], "line_type": line.get("line_type"), "amount_fils": round_half_up_div(payment_fils * int(line["gross_fils"]), total)})
    residual = payment_fils - sum(o["amount_fils"] for o in out)
    if residual:
        # the residual fil (positive or negative) never lands on the subscription line
        candidates = [i for i in range(len(lines)) if lines[i].get("line_type") != "smart_services_subscription"] or list(range(len(lines)))
        largest = max(candidates, key=lambda i: int(lines[i]["gross_fils"]))
        out[largest]["amount_fils"] += residual
    return out


# --- state machine ---------------------------------------------------------------------------------------


def transition(db: Session, sub: Subscription, to: str, *, actor_key: str | None, reason_code: str | None) -> Subscription:
    allowed = TRANSITIONS.get(sub.status, set())
    if to not in allowed:
        record_event(db, event_type="SUBSCRIPTION_TRANSITION_REJECTED", category="billing", outcome="refused", reason_code="TRANSITION_NOT_ALLOWED", actor_key=actor_key, company_id=sub.company_id, subject_type="subscription", subject_id=sub.id, details={"from": sub.status, "to": to})
        raise Conflict(f"transition {sub.status} -> {to} is not allowed", reason_code="TRANSITION_NOT_ALLOWED", details={"from": sub.status, "to": to})
    db.add(SubscriptionStateHistory(subscription_id=sub.id, from_status=sub.status, to_status=to, actor_key=actor_key, reason_code=reason_code))
    record_event(db, event_type="SUBSCRIPTION_STATE_CHANGED", category="billing", actor_key=actor_key, company_id=sub.company_id, licence_number=sub.licence_number, subject_type="subscription", subject_id=sub.id, reason_code=reason_code, details={"from": sub.status, "to": to})
    sub.status = to
    if to == "ended":
        sub.ended_on = sub.ended_on or dubai_today()
    return sub


# --- creation from licence events (outbox consumer) ----------------------------------------------------


def _raise_held(db: Session, sub: Subscription | None, reason: str, licence_number: str, company_id: str | None, rtype: str = "conflict", note: str | None = None) -> None:
    db.add(ReconciliationItem(type=rtype, subscription_id=sub.id if sub else None, licence_number=licence_number, note=note or reason))
    record_event(db, event_type="SUBSCRIPTION_HELD_FOR_REVIEW", category="billing", outcome="held", reason_code=reason, company_id=company_id, licence_number=licence_number, subject_type="subscription", subject_id=sub.id if sub else None, details={"reason": reason})


def create_subscription_for_event(db: Session, ev: LicenceEvent) -> tuple[Subscription | None, str]:
    """Create (or version) the subscription for a completed issuance/renewal. Returns (subscription, note)."""
    if not switch(db, "records", True):
        return None, "subscription_records switched off"
    if ev.status != "processed" or ev.event_type not in ("issued", "renewed"):
        return None, f"event {ev.event_type}/{ev.status} is not a subscription trigger"
    lic = db.scalar(select(Licence).where(Licence.licence_number == ev.licence_number))
    if lic is None or lic.scope != "in_scope" or lic.held_for_review or lic.status in ("unknown", "cancelled"):
        return None, "licence not in scope, held, unknown or cancelled: never billed"
    if not lic.company_id:
        return None, "licence not linked to a company yet"
    effective = ev.effective_date or dubai_today()
    # Cohort state at the event's effective date (point-in-time); late processing does not change it.
    try:
        from app.modules.cohorts.service import mark_active, membership_at

        membership = membership_at(db, lic.licence_number, datetime.combine(effective, datetime.max.time()))
    except ImportError:  # pragma: no cover - cohorts module absent
        membership, mark_active = None, None  # type: ignore[assignment]
    if membership is None:
        record_event(db, event_type="SUBSCRIPTION_NOT_CREATED", category="billing", outcome="skipped", reason_code="NOT_IN_COHORT_AT_EFFECTIVE_DATE", company_id=lic.company_id, licence_number=lic.licence_number, subject_type="licence_event", subject_id=ev.event_id)
        return None, "licence not in the pilot cohort at the event's effective date"
    # Enrolment basis is fixed at creation and the build works for either setting.
    if membership["enrolment_mode"] == "default_on_with_opt_out":
        basis = "default_on"
    else:
        if membership.get("owner_opted_in_at") is None:
            record_event(db, event_type="SUBSCRIPTION_NOT_CREATED", category="billing", outcome="skipped", reason_code="AWAITING_OWNER_OPT_IN", company_id=lic.company_id, licence_number=lic.licence_number, subject_type="licence_event", subject_id=ev.event_id)
            return None, "opt-in cohort: no owner opt-in recorded"
        basis = "opted_in"
    # An earlier opt-out is never silently re-enrolled: the renewal asks again (SC2) or leaves it off.
    if db.scalar(select(Subscription).where(Subscription.licence_number == lic.licence_number, Subscription.status.in_(("opted_out", "cancelled_by_opt_out")))) is not None:
        record_event(db, event_type="SUBSCRIPTION_NOT_CREATED", category="billing", outcome="skipped", reason_code="PRIOR_OPT_OUT", company_id=lic.company_id, licence_number=lic.licence_number, subject_type="licence_event", subject_id=ev.event_id)
        return None, "prior opt-out on this licence: not re-enrolled"
    start = ev.new_term_start_date or effective
    schedule = schedule_in_force(db, effective)
    proration = str(get_config(db, "fee_schedule.proration", "days"))
    if proration == "none" or not lic.expiry_date or lic.expiry_date < start:
        end = _add_months(start, 12) - timedelta(days=1)
    else:
        end = lic.expiry_date
    # One subscription per licence per term; an overlapping term is versioned (pending_billing) or held.
    existing = db.scalar(select(Subscription).where(Subscription.licence_number == lic.licence_number, Subscription.start_date == start))
    if existing is not None:
        record_event(db, event_type="SUBSCRIPTION_DUPLICATE_IGNORED", category="billing", outcome="ignored", reason_code="SAME_TERM", company_id=lic.company_id, licence_number=lic.licence_number, subject_type="subscription", subject_id=existing.id, details={"event_id": ev.event_id})
        return existing, "subscription for this term already exists; unchanged"
    overlap = db.scalar(select(Subscription).where(Subscription.licence_number == lic.licence_number, Subscription.status.notin_(("ended", "cancelled", "opted_out", "cancelled_by_opt_out")), Subscription.start_date <= end, Subscription.end_date >= start))
    if overlap is not None:
        if overlap.status == "pending_billing":
            return _new_version(db, overlap, start, end, schedule, ev), "new version while pending_billing"
        _raise_held(db, overlap, "OVERLAPPING_TERM", lic.licence_number, lic.company_id, "overlap", note=f"event {ev.event_id} overlaps term {overlap.start_date}..{overlap.end_date}")
        if overlap.status in TRANSITIONS and "held_for_review" in TRANSITIONS[overlap.status]:
            transition(db, overlap, "held_for_review", actor_key=None, reason_code="OVERLAPPING_TERM")
            overlap.held_reason = "overlapping_term"
        return overlap, "overlap held for review; amounts and dates unchanged"
    # A company already holding a default-on subscription never gets a second one.
    if basis == "default_on" and db.scalar(select(Subscription).where(Subscription.company_id == lic.company_id, Subscription.enrolment_basis == "default_on", Subscription.status.notin_(("ended", "cancelled", "opted_out", "cancelled_by_opt_out")))) is not None:
        record_event(db, event_type="SUBSCRIPTION_NOT_CREATED", category="billing", outcome="skipped", reason_code="DEFAULT_ON_ALREADY_HELD", company_id=lic.company_id, licence_number=lic.licence_number)
        return None, "company already holds a default-on subscription"
    fee = compute_fee(int(schedule["base_annual_fils"]), start, end, vat_rate_bp=int(schedule.get("vat_rate_bp", 500)), proration=proration, vat_split=bool(get_config(db, "billing.vat_split_switch", True)))
    cohort_stamp = f"{membership['cohort_code']}-{cohort_month(utcnow())}"
    sub = Subscription(
        licence_number=lic.licence_number, licence_id=lic.id, company_id=lic.company_id, enrolment_basis=basis, cohort_id=cohort_stamp, cohort_register_id=membership["cohort_id"], cohort_version=membership["cohort_version"], wave=membership["wave"],
        start_date=start, end_date=end, term_days=fee["term_days"], term_months=fee["term_months"], term_type=fee["term_type"], base_annual_fils=int(schedule["base_annual_fils"]), fee_schedule_version=schedule["version"], fee_schedule_status=schedule.get("status", "example"),
        opt_out_refund_config_version=opt_out_config(db).get("version"), net_amount_fils=fee["net_fils"], vat_rate_bp=fee["vat_rate_bp"], vat_fils=fee["vat_fils"], gross_fils=fee["gross_fils"], amount_basis=schedule.get("amount_basis", "net"), proration_rule=proration,
        det_event_reference=ev.det_reference, source_event_id=ev.event_id, renewal_due_at=end + timedelta(days=1), status="created",
    )
    db.add(sub)
    db.flush()
    db.add(SubscriptionStateHistory(subscription_id=sub.id, from_status=None, to_status="created", reason_code=f"licence_event:{ev.event_type}"))
    record_event(db, event_type="SUBSCRIPTION_CREATED", category="billing", company_id=sub.company_id, licence_number=sub.licence_number, subject_type="subscription", subject_id=sub.id, config_version=f"fee_schedule@{schedule['version']}", details={"enrolment_basis": basis, "cohort_id": cohort_stamp, "term_days": sub.term_days, "event_id": ev.event_id, "fee_schedule_status": sub.fee_schedule_status})
    transition(db, sub, "pending_billing", actor_key=None, reason_code="created")
    sub.pending_billing_reason = _pending_reason(db, sub, schedule)
    if membership.get("billing_allowed") is False:
        sub.pending_billing_reason = sub.pending_billing_reason or "billing_live_off"
    if mark_active:
        mark_active(db, membership["membership_id"])
    # Successor link for K5 (renewed = successor from a DET renewal event).
    prev = db.scalar(select(Subscription).where(Subscription.licence_number == lic.licence_number, Subscription.id != sub.id, Subscription.end_date < start).order_by(Subscription.end_date.desc()).limit(1))
    if prev is not None and ev.event_type == "renewed":
        prev.renewed_subscription_id = sub.id
    return sub, "created"


def _pending_reason(db: Session, sub: Subscription, schedule: dict) -> str | None:
    if schedule.get("status") != "confirmed":
        return "fee_schedule_not_confirmed"
    if sub.enrolment_basis == "default_on" and not switch(db, "default_on_billing"):
        return "default_on_hold"
    if not switch(db, "billing_live"):
        return "billing_live_off"
    return None


def _add_months(d: date, months: int) -> date:
    y, m = d.year + (d.month - 1 + months) // 12, (d.month - 1 + months) % 12 + 1
    last = (date(y + (m // 12), m % 12 + 1, 1) - timedelta(days=1)).day
    return d.replace(year=y, month=m, day=min(d.day, last))


def _new_version(db: Session, sub: Subscription, start: date, end: date, schedule: dict, ev: LicenceEvent) -> Subscription:
    fee = compute_fee(sub.base_annual_fils, start, end, vat_rate_bp=sub.vat_rate_bp or 500, proration=sub.proration_rule or "days", vat_split=sub.vat_rate_bp != 0)
    history = list(sub.version_history or [])
    history.append({"version": sub.version, "start_date": sub.start_date.isoformat(), "end_date": sub.end_date.isoformat(), "net_fils": sub.net_amount_fils, "vat_fils": sub.vat_fils, "gross_fils": sub.gross_fils, "term_days": sub.term_days, "det_event_reference": sub.det_event_reference, "replaced_at": utcnow().isoformat()})
    sub.version_history = history
    sub.version += 1
    sub.start_date, sub.end_date, sub.term_days, sub.term_months, sub.term_type = start, end, fee["term_days"], fee["term_months"], fee["term_type"]
    sub.net_amount_fils, sub.vat_fils, sub.gross_fils = fee["net_fils"], fee["vat_fils"], fee["gross_fils"]
    sub.det_event_reference, sub.source_event_id, sub.renewal_due_at = ev.det_reference, ev.event_id, end + timedelta(days=1)
    record_event(db, event_type="SUBSCRIPTION_VERSIONED", category="billing", company_id=sub.company_id, licence_number=sub.licence_number, subject_type="subscription", subject_id=sub.id, details={"version": sub.version, "event_id": ev.event_id})
    return sub


def end_subscription_for_licence_change(db: Session, ev: LicenceEvent) -> int:
    """Licence cancelled/suspended/expired/out of scope: end date set, no new term, audited; if already billed a
    draft billing adjustment proposal is created for a DET administrator (never an automatic refund)."""
    n = 0
    for sub in db.scalars(select(Subscription).where(Subscription.licence_number == ev.licence_number, Subscription.status.notin_(("ended", "cancelled", "opted_out", "cancelled_by_opt_out")))):
        cause = {"cancelled": "licence_cancelled", "suspended": "licence_suspended", "expired": "licence_not_renewed", "transferred": "licence_transferred"}.get(ev.event_type or "", "licence_change")
        if ev.event_type == "expired":
            continue  # expired-in-grace: the subscription runs to its term end; non-renewal is derived at renewal_due_at
        sub.end_date = min(sub.end_date, ev.effective_date or dubai_today())
        sub.ended_cause, sub.ended_on = cause, ev.effective_date or dubai_today()
        if sub.status in ("billed", "collected", "active", "paused", "pending_billing", "billing_requested", "held_for_review"):
            if "ended" in TRANSITIONS[sub.status]:
                transition(db, sub, "ended", actor_key=None, reason_code=cause)
            if sub.status != "pending_billing":
                db.add(BillingAdjustmentProposal(subscription_id=sub.id, reason=cause))
                record_event(db, event_type="BILLING_ADJUSTMENT_PROPOSED", category="billing", company_id=sub.company_id, subject_type="subscription", subject_id=sub.id, reason_code=cause, details={"status": "draft", "sent_automatically": False})
        n += 1
    return n


@register_consumer
def consume_outbox(db: Session) -> int:
    """Outbox consumer with a retry queue: 1, 5, 15 min (config), 5 attempts, then dead-letter + alert."""
    max_attempts = int(get_config(db, "subscription.retry_max_attempts", 5) or 5)
    n = 0
    for row in list(db.scalars(select(LicenceEventOutbox).where(LicenceEventOutbox.consumed_at.is_(None), LicenceEventOutbox.dead_letter.is_(False)).order_by(LicenceEventOutbox.id))):
        ev = db.scalar(select(LicenceEvent).where(LicenceEvent.event_id == row.event_id))
        try:
            if ev is None:
                raise NotFound("event missing", reason_code="EVENT_MISSING")
            if ev.event_type in ("issued", "renewed"):
                create_subscription_for_event(db, ev)
            elif ev.event_type in ("cancelled", "suspended", "transferred", "expired"):
                end_subscription_for_licence_change(db, ev)
            row.consumed_at = utcnow()
            db.commit()
            n += 1
        except Exception as exc:
            db.rollback()
            row = db.get(LicenceEventOutbox, row.id)
            row.attempts += 1
            row.last_error = str(exc)[:255]
            if row.attempts >= max_attempts:
                row.dead_letter = True
                record_event(db, event_type="SUBSCRIPTION_QUEUE_DEAD_LETTER", category="system", outcome="failed", reason_code="RETRY_EXHAUSTED", licence_number=row.licence_number, subject_type="licence_event", subject_id=row.event_id, details={"attempts": row.attempts, "alert": True})
            db.commit()
    return n


# --- billing hook (E2-S3) --------------------------------------------------------------------------------


def request_billing(db: Session, sub: Subscription, *, actor_key: str | None, adapter: str | None = None) -> BillingRequest:
    """Request the subscription line as a *separate* line on the licence billing record."""
    require_switch(db, "billing_live")
    schedule = next((s for s in fee_schedules(db) if s["version"] == sub.fee_schedule_version), None)
    if not schedule or schedule.get("status") != "confirmed":
        raise SwitchedOff("no billing request while the fee schedule is not marked confirmed", reason_code="FEE_SCHEDULE_NOT_CONFIRMED")
    if sub.enrolment_basis == "default_on" and not switch(db, "default_on_billing"):
        raise SwitchedOff("default-on billing stays on hold until the signed DET-Qeonix agreement", reason_code="DEFAULT_ON_HOLD")
    if switch(db, "consent_required_before_billing", True) and sub.enrolment_basis == "default_on" and not sub.notice_version_shown:
        raise SwitchedOff("the bilingual notice must be shown and recorded before a default-on line is requested", reason_code="CONSENT_REQUIRED_BEFORE_BILLING")
    if sub.status not in ("pending_billing",):
        raise Conflict("billing can only be requested from pending_billing", reason_code="TRANSITION_NOT_ALLOWED", details={"status": sub.status})
    period = f"{sub.start_date.isoformat()}|{sub.end_date.isoformat()}"
    key = f"{sub.licence_number}+{sub.id}+{period}"
    existing = db.scalar(select(BillingRequest).where(BillingRequest.idempotency_key == key))
    if existing is not None:
        if existing.amount_snapshot_fils != sub.net_amount_fils:
            db.add(ReconciliationItem(type="conflict", subscription_id=sub.id, billing_request_id=existing.id, licence_number=sub.licence_number, period=period, sent_fils=existing.amount_snapshot_fils, readback_fils=sub.net_amount_fils, note="same key, different amount: not sent; original stands"))
            record_event(db, event_type="BILLING_REQUEST_CONFLICT", category="billing", outcome="refused", reason_code="AMOUNT_CONFLICT", actor_key=actor_key, company_id=sub.company_id, subject_type="billing_request", subject_id=existing.id)
            raise Conflict("same idempotency key with a different amount: not sent, original stands", reason_code="BILLING_AMOUNT_CONFLICT")
        return existing
    req = BillingRequest(subscription_id=sub.id, licence_number=sub.licence_number, billing_period=period, idempotency_key=key, amount_snapshot_fils=sub.net_amount_fils, net_fils=sub.net_amount_fils, vat_fils=sub.vat_fils, gross_fils=sub.gross_fils, reference_field=key, adapter=adapter or str(get_config(db, "billing.hook_interface", "manual")), sent_at=utcnow(), outstanding_fils=sub.gross_fils)
    db.add(req)
    db.flush()
    transition(db, sub, "billing_requested", actor_key=actor_key, reason_code="billing_line_requested")
    sub.pending_billing_reason = None
    record_event(db, event_type="BILLING_LINE_REQUESTED", category="billing", actor_key=actor_key, company_id=sub.company_id, licence_number=sub.licence_number, subject_type="billing_request", subject_id=req.id, details={"idempotency_key": key, "adapter": req.adapter, "separate_line": True})
    return req


def read_back(db: Session, req: BillingRequest, det_record: dict | None, *, actor_key: str | None) -> BillingRequest:
    """Confirm from the DET billing record only. Empty read = pending confirmation; exact fils match = billed;
    right amount on a different invoice/period or any difference = mismatch."""
    sub = db.get(Subscription, req.subscription_id)
    req.read_attempts += 1
    req.last_read_at = utcnow()
    req.last_readback = det_record
    max_attempts = int(get_config(db, "readback.max_attempts", 8) or 8)
    if req.status == "cancelled":
        return req
    if not det_record or not det_record.get("lines"):
        if req.status == "requested":
            req.status = "pending_confirmation"
            if sub.status == "billing_requested":
                transition(db, sub, "pending_confirmation", actor_key=actor_key, reason_code="empty_readback")
        if req.read_attempts >= max_attempts:
            db.add(ReconciliationItem(type="aged_pending_confirmation", subscription_id=sub.id, billing_request_id=req.id, licence_number=req.licence_number, period=req.billing_period, sent_fils=req.net_fils, note="max read attempts reached; stays pending confirmation, excluded from K2/K3 headlines"))
        record_event(db, event_type="BILLING_READBACK", category="billing", outcome="pending", reason_code="EMPTY_READ", actor_key=actor_key, company_id=sub.company_id, subject_type="billing_request", subject_id=req.id, details={"attempt": req.read_attempts})
        return req
    lines = det_record["lines"]
    matches = [ln for ln in lines if ln.get("reference") == req.reference_field]
    if not matches:  # secondary match: licence number + period + line type + net fils
        matches = [ln for ln in lines if ln.get("licence_number") == req.licence_number and ln.get("period") == req.billing_period and ln.get("line_type", req.line_type) == req.line_type and int(ln.get("net_fils", -1)) == req.net_fils]
    if len(matches) >= 2:
        req.status = "held"
        req.hold_reason = "Awaiting DET review"
        db.add(ReconciliationItem(type="duplicate_lines", subscription_id=sub.id, billing_request_id=req.id, licence_number=req.licence_number, period=req.billing_period, sent_fils=req.net_fils, note="two lines for one key"))
        if "held_for_review" in TRANSITIONS[sub.status]:
            transition(db, sub, "held_for_review", actor_key=actor_key, reason_code="DUPLICATE_LINES")
        return req
    if not matches:
        if req.status == "billed":
            req.status = "mismatch"
            db.add(ReconciliationItem(type="billed_line_disappeared", subscription_id=sub.id, billing_request_id=req.id, licence_number=req.licence_number, period=req.billing_period, sent_fils=req.net_fils, note="previously billed line no longer on the record; nothing reverted"))
        elif req.status == "requested":
            req.status = "pending_confirmation"
            if sub.status == "billing_requested":
                transition(db, sub, "pending_confirmation", actor_key=actor_key, reason_code="no_matching_line")
        return req
    line = matches[0]
    ok = int(line.get("net_fils", -1)) == req.net_fils and line.get("licence_number") == req.licence_number and line.get("period", req.billing_period) == req.billing_period and (det_record.get("invoice_id") is None or req.invoice_id in (None, det_record.get("invoice_id")))
    if not ok:
        req.status = "mismatch"
        db.add(ReconciliationItem(type="mismatch", subscription_id=sub.id, billing_request_id=req.id, licence_number=req.licence_number, period=req.billing_period, sent_fils=req.net_fils, readback_fils=int(line.get("net_fils", 0)), note="exact fils equality required; no tolerance"))
        record_event(db, event_type="BILLING_READBACK", category="billing", outcome="mismatch", reason_code="AMOUNT_OR_PERIOD_MISMATCH", actor_key=actor_key, company_id=sub.company_id, subject_type="billing_request", subject_id=req.id)
        return req
    req.status = "billed"
    req.billing_line_id = line.get("billing_line_id")
    req.invoice_id = det_record.get("invoice_id")
    if det_record.get("invoice_date"):
        req.invoice_date, req.invoice_date_source = date.fromisoformat(det_record["invoice_date"][:10]), "invoice_date"
    elif line.get("timestamp"):
        req.billing_line_timestamp = datetime.fromisoformat(line["timestamp"].replace("Z", "+00:00")).astimezone(UTC).replace(tzinfo=None)
        req.invoice_date, req.invoice_date_source = req.billing_line_timestamp.date(), "billing_line_timestamp"
    sub.billing_line_id, sub.invoice_id = req.billing_line_id, req.invoice_id
    if sub.status in ("billing_requested", "pending_confirmation"):
        transition(db, sub, "billed", actor_key=actor_key, reason_code="readback_confirmed")
    record_event(db, event_type="BILLING_READBACK", category="billing", outcome="billed", actor_key=actor_key, company_id=sub.company_id, licence_number=sub.licence_number, subject_type="billing_request", subject_id=req.id, details={"billing_line_id": req.billing_line_id, "invoice_date_source": req.invoice_date_source})
    return req


def record_payment(db: Session, payload: dict, *, actor_key: str | None) -> PaymentEvent:
    """Payment/refund/failure event from the payment channel: deduped on payment_transaction_id, allocated
    with alloc-v1, collection status derived only from source records."""
    txid = str(payload.get("payment_transaction_id") or "").strip()
    if not txid:
        raise ValidationFailed("payment_transaction_id is required", reason_code="PAYMENT_ID_REQUIRED")
    existing = db.scalar(select(PaymentEvent).where(PaymentEvent.payment_transaction_id == txid))
    if existing is not None:
        record_event(db, event_type="PAYMENT_DUPLICATE_IGNORED", category="billing", outcome="ignored", actor_key=actor_key, subject_type="payment", subject_id=existing.id)
        return existing
    ts = payload.get("source_timestamp")
    pe = PaymentEvent(payment_transaction_id=txid, payment_idempotency_key=payload.get("payment_idempotency_key"), source_timestamp=datetime.fromisoformat(str(ts).replace("Z", "+00:00")).astimezone(UTC).replace(tzinfo=None) if ts else None, amount_fils=int(payload.get("amount_fils", 0)), type=payload.get("type", "payment"), billing_line_id=payload.get("billing_line_id"), invoice_id=payload.get("invoice_id"), invoice_lines=payload.get("invoice_lines"), refund_reason=payload.get("refund_reason"), channel=payload.get("channel"))
    db.add(pe)
    db.flush()
    if pe.type == "failure":
        pe.allocation_status = "no_allocation_failed"
        req = _request_for(db, pe)
        if req is not None:
            req.collection_status = "failed"
            req.receipt_reference = payload.get("reference")
        record_event(db, event_type="PAYMENT_FAILED", category="billing", outcome="failed", actor_key=actor_key, subject_type="payment", subject_id=pe.id, details={"licence_not_affected": True})
        return pe
    _allocate(db, pe, payload.get("reference"), actor_key)
    return pe


def _request_for(db: Session, pe: PaymentEvent) -> BillingRequest | None:
    if pe.billing_line_id:
        return db.scalar(select(BillingRequest).where(BillingRequest.billing_line_id == pe.billing_line_id))
    if pe.invoice_id:
        rows = list(db.scalars(select(BillingRequest).where(BillingRequest.invoice_id == pe.invoice_id)))
        return rows[0] if len(rows) == 1 else None
    return None


def _allocate(db: Session, pe: PaymentEvent, reference: str | None, actor_key: str | None) -> None:
    sign = -1 if pe.type == "refund" else 1
    req: BillingRequest | None = None
    basis: str | None = None
    amount = pe.amount_fils
    provisional = False
    if pe.billing_line_id:  # (a) billing-line: exact, final
        req, basis = _request_for(db, pe), "billing-line"
    elif pe.invoice_id:
        lines = pe.invoice_lines or []
        sub_lines = [ln for ln in lines if ln.get("line_type") == "smart_services_subscription"]
        if lines and len(lines) == 1 and sub_lines:  # (b) invoice-single-line: full payment, final
            req, basis = db.scalar(select(BillingRequest).where(BillingRequest.billing_line_id == sub_lines[0]["line_id"])), "invoice-single-line"
        elif lines and sub_lines and bool(get_config(db, "billing.platform_derived_allocation.enabled", True)):  # (c) pro-rata by gross
            split = allocate_platform_derived(pe.amount_fils, lines)
            share = next((s for s in split if s["line_id"] == sub_lines[0]["line_id"]), None)
            req = db.scalar(select(BillingRequest).where(BillingRequest.billing_line_id == sub_lines[0]["line_id"]))
            if share and req is not None:
                basis, amount, provisional = "platform-derived", share["amount_fils"], True
    if req is None or basis is None:
        pe.allocation_status = "received_unallocated"  # shown as received, no allocation in the PoC
        record_event(db, event_type="PAYMENT_RECEIVED_UNALLOCATED", category="billing", outcome="held", actor_key=actor_key, subject_type="payment", subject_id=pe.id, details={"type": pe.type, "has_invoice": bool(pe.invoice_id)})
        if pe.invoice_id:
            for r in db.scalars(select(BillingRequest).where(BillingRequest.invoice_id == pe.invoice_id)):
                if r.collection_status == "not_collected":
                    r.collection_status = "received_unallocated"
                    r.receipt_reference = r.receipt_reference or reference
        return
    if pe.type == "refund":
        collected = req.collected_fils
        if pe.refund_reason == "opt-out":
            amount = min(amount, collected)
        if amount > collected:  # cap: attributed refund never exceeds the line allocation
            db.add(ReconciliationItem(type="unattributed_refund_excess", subscription_id=req.subscription_id, billing_request_id=req.id, licence_number=req.licence_number, period=req.billing_period, sent_fils=amount, readback_fils=collected, note="refund above allocation; excess unattributed"))
            amount = collected
    db.add(PaymentAllocation(supersedes_allocation_id=None, allocation_basis=basis, payment_transaction_id=pe.payment_transaction_id, billing_request_id=req.id, billing_line_id=req.billing_line_id, amount_fils=amount * sign, provisional=provisional, kind="refund" if pe.type == "refund" else "payment"))
    pe.allocation_status = "allocated"
    if pe.type == "refund":
        req.refunded_fils += amount
    else:
        req.collected_fils += amount
    req.provisional = provisional or req.provisional
    req.receipt_reference = req.receipt_reference or reference
    net_collected = req.collected_fils - req.refunded_fils
    req.outstanding_fils = max(0, req.gross_fils - req.collected_fils)
    if req.refunded_fils and req.refunded_fils >= req.collected_fils:
        req.collection_status = "refunded"
    elif req.refunded_fils:
        req.collection_status = "partially_refunded"
    elif net_collected >= req.gross_fils:
        req.collection_status = "collected"
    elif net_collected > 0:
        req.collection_status = "partially_collected"
    sub = db.get(Subscription, req.subscription_id)
    if sub and sub.status == "billed" and req.collection_status == "collected":
        transition(db, sub, "collected", actor_key=actor_key, reason_code="payment_read_back")
        transition(db, sub, "active", actor_key=actor_key, reason_code="collection_confirmed")
        sub.allocation_basis_flag = basis
        sub.service_mode, sub.grace_until = "full", None
    record_event(db, event_type="PAYMENT_ALLOCATED", category="billing", actor_key=actor_key, company_id=sub.company_id if sub else None, subject_type="payment", subject_id=pe.id, details={"basis": basis, "rule_version": "alloc-v1", "provisional": provisional, "collection_status": req.collection_status})


def apply_unpaid_grace(db: Session, sub: Subscription, req: BillingRequest | None, today: date | None = None) -> None:
    """Unpaid after notice + grace (provisional 30 days): smart services read-only; the licence is never affected."""
    today = today or dubai_today()
    grace_days = int(get_config(db, "unpaid.grace_period_days", 30) or 30)
    if req is not None and req.status == "billed" and req.collection_status in ("not_collected", "failed", "partially_collected") and req.invoice_date:
        sub.grace_until = req.invoice_date + timedelta(days=grace_days)
        sub.service_mode = "read_only" if today > sub.grace_until else "full"


# --- opt-out state and cases (E2-S4) -------------------------------------------------------------------


def get_opt_out_state(db: Session, subscription_id: str) -> str:
    """Contract with E2-S2: none | window_open | opted_out. Window length unconfirmed -> window_open."""
    sub = db.get(Subscription, subscription_id)
    if sub is None:
        return "none"
    if sub.status in ("opted_out", "cancelled_by_opt_out"):
        return "opted_out"
    if db.scalar(select(Case).where(Case.subscription_id == subscription_id, Case.action_family == "opt_out", Case.state == "applied")) is not None:
        return "opted_out"
    window = (opt_out_config(db).get("opt_out_window_days") or {})
    if window.get("status") == "confirmed" and window.get("value") is not None and (dubai_today() - sub.start_date).days > int(window["value"]):
        return "none"
    return "window_open"


def open_case(db: Session, sub: Subscription, *, action: str, request_id: str, reason_code: str, actor_key: str, actor_role: str, language: str | None, assurance_level: str | None, free_text: str | None = None) -> tuple[Case, bool]:
    """Opt-out or refund request. Dedupe by subscription + action family: an open or applied case is returned
    unchanged with 'already requested' (HTTP 200), never a second DET instruction. Returns (case, created)."""
    if action not in ("opt_out", "refund"):
        raise ValidationFailed("action must be opt_out or refund", reason_code="CASE_ACTION_INVALID")
    cfg = opt_out_config(db)
    if action == "opt_out" and not bool((cfg.get("opt_out_allowed") or {}).get("value", True)):
        raise Forbidden("opt-out cannot be disabled without a recorded DET + counsel decision", reason_code="OPT_OUT_ALWAYS_ALLOWED")
    reasons = get_config(db, "reasons.lists", {}) or {}
    valid = {r["code"] for r in reasons.get(action, [])}
    if valid and reason_code not in valid:
        raise ValidationFailed("reason code not in the configured list", reason_code="REASON_CODE_INVALID", details={"allowed": sorted(valid)})
    existing = db.scalar(select(Case).where(Case.subscription_id == sub.id, Case.action_family == action, Case.state.in_(("requested", "pending_DET", "needs_DET_action", "applied"))))
    if existing is not None:
        record_event(db, event_type="CASE_DUPLICATE_RETURNED", category="consent", outcome="ignored", reason_code="already_requested", actor_key=actor_key, company_id=sub.company_id, subject_type="case", subject_id=existing.id)
        return existing, False
    if action == "opt_out" and sub.status in ("opted_out", "cancelled_by_opt_out"):
        raise Conflict("Smart services are already stopped for this licence.", reason_code="ALREADY_STOPPED")
    terms_version = str(get_config(db, "subscription.terms.version", "terms-v1"))
    case = Case(subscription_id=sub.id, company_id=sub.company_id, action=action, action_family=action, terms_version=terms_version, request_id=request_id, idempotency_key="pending", reason_code=reason_code, reason_config_version=str(reasons.get("version", "reasons-v1")), free_text=free_text, state="requested", actor_key=actor_key, actor_role=actor_role, language_shown=language, notice_version_shown=str(get_config(db, "subscription.notice.version", "notice-v1")), identity_assurance_level=assurance_level, reference_code=reference_code())
    db.add(case)
    db.flush()
    case.idempotency_key = f"{sub.id}+{action}+{terms_version}+{case.id}"
    # One instruction per action: sent to the (simulated) DET hook and read back; never confirmed by assumption.
    case.det_instruction_state, case.det_instruction_sent_at, case.state = "sent", utcnow(), "pending_DET"
    record_event(db, event_type=f"CASE_{action.upper()}_REQUESTED", category="consent", actor_key=actor_key, actor_role=actor_role, company_id=sub.company_id, licence_number=sub.licence_number, subject_type="case", subject_id=case.id, language=language, config_version=f"reasons@{case.reason_config_version}", details={"reason_code": reason_code, "terms_version": terms_version, "assurance_level": assurance_level, "state": case.state})
    return case, True


def cancel_case(db: Session, case: Case, *, actor_key: str) -> Case:
    if case.state in CASE_TERMINAL:
        raise Conflict("this request is already closed", reason_code="CASE_CLOSED")
    case.state, case.decided_at = "cancelled", utcnow()
    record_event(db, event_type="CASE_CANCELLED_BY_OWNER", category="consent", actor_key=actor_key, company_id=case.company_id, subject_type="case", subject_id=case.id)
    return case


def det_case_decision(db: Session, case: Case, *, decision: str, actor_key: str, reason: str | None, effective_at: date | None) -> Case:
    """DET confirms or refuses; a late answer after needs_DET_action closes the alert and is audited."""
    if case.state in CASE_TERMINAL:
        record_event(db, event_type="CASE_DUPLICATE_IGNORED", category="consent", outcome="ignored", reason_code="duplicate_ignored", actor_key=actor_key, company_id=case.company_id, subject_type="case", subject_id=case.id)
        return case
    late = case.state == "needs_DET_action"
    sub = db.get(Subscription, case.subscription_id)
    if decision == "confirm":
        case.state, case.det_instruction_state, case.effective_at = "applied", "confirmed", effective_at or dubai_today()
        if case.action == "opt_out" and sub is not None:
            if sub.status in ("pending_billing", "billing_requested"):
                transition(db, sub, "cancelled_by_opt_out", actor_key=actor_key, reason_code="opt_out_confirmed")
                for req in db.scalars(select(BillingRequest).where(BillingRequest.subscription_id == sub.id, BillingRequest.status.in_(("requested", "pending_confirmation")))):
                    req.status, req.hold_reason = "cancelled", "Opt-out request received"
            elif sub.status in ("billed", "active"):
                transition(db, sub, "opted_out", actor_key=actor_key, reason_code="opt_out_confirmed")
                sub.ended_on = case.effective_at
    elif decision == "reject":
        case.state, case.det_instruction_state = "rejected", "confirmed"
    else:
        raise ValidationFailed("decision must be confirm or reject", reason_code="DECISION_INVALID")
    case.decided_at, case.decision_reason = utcnow(), reason
    if late:
        record_event(db, event_type="CASE_LATE_CONFIRMED" if decision == "confirm" else "CASE_LATE_REJECTED", category="consent", actor_key=actor_key, company_id=case.company_id, subject_type="case", subject_id=case.id, reason_code="late_confirmation")
        record_event(db, event_type="CASE_ALERT_CLOSED", category="consent", actor_key=actor_key, company_id=case.company_id, subject_type="case", subject_id=case.id, reason_code="late confirmation", details={"alert_id": case.alert_id})
    record_event(db, event_type="CASE_DET_DECISION", category="consent", actor_key=actor_key, company_id=case.company_id, subject_type="case", subject_id=case.id, reason_code=decision, details={"action": case.action, "state": case.state})
    return case


def mark_needs_det_action(db: Session, case: Case) -> Case:
    if case.state == "pending_DET":
        case.state, case.det_instruction_state, case.alert_id = "needs_DET_action", "needs_DET_action", case.alert_id or f"alert_{case.id}"
        record_event(db, event_type="CASE_NEEDS_DET_ACTION", category="escalation", outcome="alert", company_id=case.company_id, subject_type="case", subject_id=case.id, details={"alert_role": get_config(db, "det_hook.alert_role", "det_admin")})
    return case


# --- complaints ------------------------------------------------------------------------------------------


def add_working_days(start: date, days: int) -> date:
    d = start
    while days > 0:
        d += timedelta(days=1)
        if d.weekday() < 5:  # UAE working week Mon-Fri
            days -= 1
    return d


def open_complaint(db: Session, *, company_id: str, licence_number: str | None, subscription_id: str | None, category: str, description: str, preferred_language: str, contact_channel: str | None, actor_key: str, actor_role: str, related_module: str | None = None, related_date: date | None = None) -> Complaint:
    categories = get_config(db, "complaint.categories", []) or []
    codes = {c["code"] for c in categories}
    if codes and category not in codes:
        raise ValidationFailed("category not in the configured list", reason_code="COMPLAINT_CATEGORY_INVALID", details={"allowed": sorted(codes)})
    max_len = int(get_config(db, "complaint.description_max_length", 2000) or 2000)
    if not description.strip() or len(description) > max_len:
        raise ValidationFailed("description is required and length-limited", reason_code="COMPLAINT_DESCRIPTION_INVALID", details={"max_length": max_len})
    sla = int(get_config(db, "complaint.reply_period_working_days", 5) or 5)
    received = utcnow()
    k4 = next((bool(c.get("k4")) for c in categories if c["code"] == category), True)
    row = Complaint(reference=reference_code(), company_id=company_id, licence_number=licence_number, subscription_id=subscription_id, category=category, description=description.strip(), preferred_language=preferred_language, contact_channel=contact_channel, related_module=related_module, related_date=related_date, received_at=received, reply_by=add_working_days(dubai_date(received), sla), filed_by_key=actor_key, filed_by_role=actor_role, filed_for_owner=actor_role == "delegate", escalation_flag=any(k in description.lower() for k in ("bank", "consent", "approval", "identity", "emirates id")), k4_eligible=k4, sla_working_days=sla)
    db.add(row)
    db.flush()
    record_event(db, event_type="COMPLAINT_RECEIVED", category="escalation", actor_key=actor_key, actor_role=actor_role, company_id=company_id, licence_number=licence_number, subject_type="complaint", subject_id=row.id, details={"category": category, "reply_by": row.reply_by.isoformat(), "sla_working_days": sla, "escalation_flag": row.escalation_flag})
    return row


def set_complaint_status(db: Session, row: Complaint, *, status: str, reason_code: str, actor_key: str, interim_due_date: date | None = None) -> Complaint:
    if status not in COMPLAINT_STATUSES:
        raise ValidationFailed("status invalid", reason_code="COMPLAINT_STATUS_INVALID")
    if not reason_code:
        raise ValidationFailed("a reason code is required", reason_code="REASON_CODE_REQUIRED")
    prev = row.status
    row.status, row.status_reason_code = status, reason_code
    if interim_due_date:
        row.interim_due_date = interim_due_date  # original reply_by kept for breach measurement
    record_event(db, event_type="COMPLAINT_STATUS_CHANGED", category="escalation", actor_key=actor_key, actor_role="det_complaint_handler", company_id=row.company_id, subject_type="complaint", subject_id=row.id, reason_code=reason_code, details={"from": prev, "to": status})
    return row


def complaint_dict(c: Complaint, *, handler: bool = False) -> dict:
    d = {"id": c.id, "reference": c.reference, "licence_number": c.licence_number, "category": c.category, "preferred_language": c.preferred_language, "contact_channel": c.contact_channel, "received_at": c.received_at.isoformat(), "reply_by": c.reply_by.isoformat(), "interim_due_date": c.interim_due_date.isoformat() if c.interim_due_date else None, "status": c.status, "status_reason_code": c.status_reason_code, "filed_for_owner": c.filed_for_owner, "sla_working_days": c.sla_working_days, "related_module": c.related_module}
    if handler:
        d.update({"company_id": c.company_id, "description": c.description, "escalation_flag": c.escalation_flag, "k4_eligible": c.k4_eligible, "subscription_id": c.subscription_id})
    else:
        d["description"] = c.description
    return d


# --- views -----------------------------------------------------------------------------------------------

BADGE_KEYS = {"created": "pending_billing", "pending_billing": "pending_billing", "billing_requested": "billing_requested", "pending_confirmation": "awaiting_det_confirmation", "billed": "billed", "collected": "active", "active": "active", "held_for_review": "held_for_review", "cancelled_by_opt_out": "cancelled", "opted_out": "opted_out", "cancelled": "cancelled", "paused": "paused", "ended": "ended"}


def case_dict(c: Case) -> dict:
    chip = {"requested": "received", "pending_DET": "pending", "needs_DET_action": "with_det", "applied": "applied", "rejected": "refused", "cancelled": "cancelled", "draft": "draft"}[c.state]
    return {"id": c.id, "action": c.action, "state": c.state, "chip": chip, "status_text": "request received, DET decides" if c.state in ("requested", "pending_DET", "needs_DET_action") else c.state, "reason_code": c.reason_code, "reference_code": c.reference_code, "received_at": c.received_at.isoformat(), "effective_at": c.effective_at.isoformat() if c.effective_at else None, "terms_version": c.terms_version, "det_instruction_state": c.det_instruction_state, "can_cancel": c.state in ("requested", "pending_DET", "needs_DET_action")}


def billing_dict(req: BillingRequest | None, *, show_amounts: bool) -> dict | None:
    if req is None:
        return None
    d = {"id": req.id, "status": req.status, "hold_reason": req.hold_reason, "collection_status": req.collection_status, "payment_reference": req.receipt_reference, "invoice_date": req.invoice_date.isoformat() if req.invoice_date else None, "invoice_date_source": req.invoice_date_source, "billing_period": req.billing_period, "provisional": req.provisional, "read_attempts": req.read_attempts, "last_read_at": req.last_read_at.isoformat() if req.last_read_at else None, "adapter": req.adapter, "separate_line": True}
    if show_amounts:
        d.update({"net_fils": req.net_fils, "vat_fils": req.vat_fils, "gross_fils": req.gross_fils, "collected_fils": req.collected_fils, "outstanding_fils": req.outstanding_fils, "refunded_fils": req.refunded_fils, "amounts_label": "indicative"})
    return d


def subscription_dict(db: Session, sub: Subscription, *, show_amounts: bool = True) -> dict:
    req = db.scalar(select(BillingRequest).where(BillingRequest.subscription_id == sub.id).order_by(BillingRequest.created_at.desc()).limit(1))
    apply_unpaid_grace(db, sub, req)
    payments = []
    if req is not None:
        for a in db.scalars(select(PaymentAllocation).where(PaymentAllocation.billing_request_id == req.id).order_by(PaymentAllocation.allocated_at)):
            payments.append({"allocation_id": a.id, "basis": a.allocation_basis, "rule_version": a.rule_version, "amount_fils": a.amount_fils if show_amounts else None, "provisional": a.provisional, "kind": a.kind, "allocated_at": a.allocated_at.isoformat(), "supersedes_allocation_id": a.supersedes_allocation_id})
        for p in db.scalars(select(PaymentEvent).where(PaymentEvent.invoice_id == req.invoice_id, PaymentEvent.allocation_status == "received_unallocated")) if req.invoice_id else []:
            payments.append({"allocation_id": None, "basis": None, "rule_version": "alloc-v1", "amount_fils": p.amount_fils if show_amounts else None, "provisional": True, "kind": p.type, "allocated_at": p.received_at.isoformat(), "status": "received_unallocated"})
    example_mode = sub.fee_schedule_status != "confirmed"
    amounts_allowed = show_amounts and sub.status not in ("held_for_review", "cancelled", "opted_out", "cancelled_by_opt_out")
    d = {
        "id": sub.id, "licence_number": sub.licence_number, "company_id": sub.company_id, "enrolment_basis": sub.enrolment_basis, "cohort_id": sub.cohort_id, "wave": sub.wave, "cohort_version": sub.cohort_version,
        "start_date": sub.start_date.isoformat(), "end_date": sub.end_date.isoformat(), "term_days": sub.term_days, "term_months": sub.term_months, "term_type": sub.term_type,
        "status": sub.status, "badge": BADGE_KEYS[sub.status], "pending_billing_reason": sub.pending_billing_reason, "held_reason": sub.held_reason, "service_mode": sub.service_mode, "grace_until": sub.grace_until.isoformat() if sub.grace_until else None,
        "fee_schedule_version": sub.fee_schedule_version, "fee_schedule_status": sub.fee_schedule_status, "example_mode": example_mode, "opt_out_refund_config_version": sub.opt_out_refund_config_version, "proration_rule": sub.proration_rule,
        "renewal_due_at": sub.renewal_due_at.isoformat() if sub.renewal_due_at else None, "renewed_subscription_id": sub.renewed_subscription_id, "ended_on": sub.ended_on.isoformat() if sub.ended_on else None, "ended_cause": sub.ended_cause,
        "removed_from_cohort": sub.removed_from_cohort, "paused": sub.paused, "version": sub.version, "is_demo": sub.is_demo, "opt_out_state": get_opt_out_state(db, sub.id),
        "fee": {"base_annual_fils": sub.base_annual_fils, "net_fils": sub.net_amount_fils, "vat_rate_bp": sub.vat_rate_bp, "vat_fils": sub.vat_fils, "gross_fils": sub.gross_fils, "amount_basis": sub.amount_basis, "label": "example" if example_mode else "confirmed", "vat_label": "VAT treatment to be confirmed", "monthly_display_fils": int(get_config(db, "fee_schedule.monthly_display_fils", 5000) or 5000), "monthly_display_only": True} if amounts_allowed else None,
        "billing": billing_dict(req, show_amounts=amounts_allowed), "payments": payments,
        "cases": [case_dict(c) for c in db.scalars(select(Case).where(Case.subscription_id == sub.id).order_by(Case.received_at.desc()))],
        "history": [{"from": h.from_status, "to": h.to_status, "at": h.event_at.isoformat(), "reason_code": h.reason_code} for h in db.scalars(select(SubscriptionStateHistory).where(SubscriptionStateHistory.subscription_id == sub.id).order_by(SubscriptionStateHistory.id))],
        "version_history": sub.version_history or [],
    }
    return d


def company_subscription_view(db: Session, company_id: str, *, can_change: bool, role: str) -> dict:
    """Owner Subscription screen data (SC2/SC11). Delegates and remote owners read the same card read-only."""
    subs = list(db.scalars(select(Subscription).where(Subscription.company_id == company_id).order_by(Subscription.start_date.desc())))
    try:
        from app.modules.cohorts.service import company_cohort_view

        cohort_rows = {r["licence_number"]: r for r in company_cohort_view(db, company_id)}
    except ImportError:  # pragma: no cover
        cohort_rows = {}
    licences = list(db.scalars(select(Licence).where(Licence.company_id == company_id, Licence.scope != "out_of_scope")))
    by_licence = []
    for lic in licences:
        mine = [s for s in subs if s.licence_number == lic.licence_number]
        current = next((s for s in mine if s.status not in ("ended", "cancelled")), mine[0] if mine else None)
        c = cohort_rows.get(lic.licence_number, {})
        if current is None:
            empty = "opted_out" if any(s.status in ("opted_out", "cancelled_by_opt_out") for s in mine) else ("in_cohort_no_event" if c.get("pilot_status") in ("enrolled_starts_next_event", "active") else "not_in_pilot")
        else:
            empty = None
        by_licence.append({"licence_number": lic.licence_number, "licence_status": lic.status, "licence_expiry": lic.expiry_date.isoformat() if lic.expiry_date else None, "pilot": c, "empty_state": empty, "subscription": subscription_dict(db, current) if current else None, "past": [subscription_dict(db, s) for s in mine if s is not current]})
    complaints = [complaint_dict(x) for x in db.scalars(select(Complaint).where(Complaint.company_id == company_id).order_by(Complaint.received_at.desc()))]
    return {
        "company_id": company_id,
        "role": role,
        "can_change": can_change,
        "read_only_note": None if can_change else "only_owner_can_change",
        "licences": by_licence,
        "complaints": complaints,
        "terms_version": get_config(db, "subscription.terms.version", "terms-v1"),
        "notice_version": get_config(db, "subscription.notice.version", "notice-v1"),
        "switches": {k: switch(db, k, d) for k, d in (("records", True), ("fee_schedule_calc", True), ("billing_live", False), ("views", True), ("default_on_billing", False), ("consent_required_before_billing", True))},
        "parameters": tbc_labels(db),
        "reasons": get_config(db, "reasons.lists", {}),
        "complaint_categories": get_config(db, "complaint.categories", []),
        "complaint_reply_period_working_days": get_config(db, "complaint.reply_period_working_days", 5),
        "refund_response_time_working_days": get_config(db, "refund.response_time_working_days", 10),
        "unpaid_grace_period_days": get_config(db, "unpaid.grace_period_days", 30),
        "proposed_wording": True,
        "included": get_config(db, "subscription.included_modules", []),
        "not_included": get_config(db, "subscription.not_included", []),
    }


def det_status_for_licence(db: Session, licence_number: str) -> dict:
    """DET-admin allowed fields only: states, basis, period. Never amounts or company financial data."""
    sub = db.scalar(select(Subscription).where(Subscription.licence_number == licence_number).order_by(Subscription.start_date.desc()).limit(1))
    if sub is None:
        return {"subscription_status": None, "billing_status": None, "collection_status": None, "enrolment_basis": None}
    req = db.scalar(select(BillingRequest).where(BillingRequest.subscription_id == sub.id).order_by(BillingRequest.created_at.desc()).limit(1))
    return {"subscription_status": sub.status, "subscription_badge": BADGE_KEYS[sub.status], "billing_status": req.status if req else None, "collection_status": req.collection_status if req else None, "enrolment_basis": sub.enrolment_basis, "term": f"{sub.start_date.isoformat()}|{sub.end_date.isoformat()}", "fee_schedule_version": sub.fee_schedule_version, "cohort_stamp": sub.cohort_id, "open_cases": len(list(db.scalars(select(Case).where(Case.subscription_id == sub.id, Case.state.in_(("requested", "pending_DET", "needs_DET_action"))))))}


def det_aggregates(db: Session, *, actor_key: str) -> dict:
    """SC14 aggregates: confirmed-only money tiles (billed lines from read-back), counts for pending/mismatch,
    provisional (platform-derived) kept separate, K4 flags with suppression."""
    try:
        from app.modules.cohorts.service import suppress_breakdown, suppress_cell, suppression_n

        n = suppression_n(db)
    except ImportError:  # pragma: no cover
        n = 10
        suppress_cell = lambda v, n: {"value": v, "suppressed": False}  # noqa: E731
        suppress_breakdown = lambda cells, n: {k: {"value": v, "suppressed": False} for k, v in cells.items()}  # noqa: E731
    subs = list(db.scalars(select(Subscription)))
    reqs = list(db.scalars(select(BillingRequest)))
    by_status: dict[str, int] = {}
    for s in subs:
        by_status[s.status] = by_status.get(s.status, 0) + 1
    billed = [r for r in reqs if r.status == "billed"]
    final = [r for r in billed if r.collection_status in ("collected", "partially_collected", "refunded", "partially_refunded") and not r.provisional]
    prov = [r for r in billed if r.provisional]
    k2_net = sum(r.net_fils for r in billed if r.vat_fils)  # net of VAT only when VAT populated
    k2_unconfirmed_vat = sum(r.net_fils for r in billed if not r.vat_fils)
    collected = sum(r.collected_fils for r in final)
    refunded = sum(r.refunded_fils for r in final)
    cases = list(db.scalars(select(Case)))
    complaints = list(db.scalars(select(Complaint)))
    k4 = {
        "rule_version": get_config(db, "k4.rule_version", "k4-v1"),
        "observation_window_days": get_config(db, "k4.observation_window_days", 90),
        "flag_opted_out": suppress_breakdown({"confirmed": sum(1 for c in cases if c.action == "opt_out" and c.state == "applied"), "pending": sum(1 for c in cases if c.action == "opt_out" and c.state in ("requested", "pending_DET", "needs_DET_action")), "rejected": sum(1 for c in cases if c.action == "opt_out" and c.state == "rejected")}, n),
        "flag_refunded": suppress_cell(sum(1 for r in reqs if r.refunded_fils > 0), n),
        "flag_complained": suppress_breakdown({c["code"]: sum(1 for x in complaints if x.category == c["code"]) for c in (get_config(db, "complaint.categories", []) or [])}, n),
        "complaints_uncategorised": suppress_cell(sum(1 for x in complaints if not x.k4_eligible), n),
    }
    record_event(db, event_type="DET_AGGREGATE_QUERIED", category="data_access", actor_key=actor_key, details={"view": "subscriptions", "suppression_n": n})
    return {
        "subscriptions_by_status": suppress_breakdown(by_status, n),
        "total_subscriptions": suppress_cell(len(subs), n),
        "money_confirmed_fils": {"billed_net": k2_net, "billed_net_vat_unconfirmed": k2_unconfirmed_vat, "collected": collected, "refunded": refunded, "net_collected": collected - refunded, "label": "confirmed billed lines only; K2 net of VAT; amounts are examples until DET confirms the fee model"},
        "counts": {"pending_confirmation": sum(1 for r in reqs if r.status == "pending_confirmation"), "mismatch": sum(1 for r in reqs if r.status == "mismatch"), "held": sum(1 for r in reqs if r.status == "held"), "requested": sum(1 for r in reqs if r.status == "requested"), "failed": sum(1 for r in reqs if r.collection_status == "failed"), "partly_collected": sum(1 for r in reqs if r.collection_status == "partially_collected"), "received_unallocated": sum(1 for r in reqs if r.collection_status == "received_unallocated")},
        "provisional_fils": {"platform_derived_collected": sum(r.collected_fils for r in prov), "label": "Estimated by the platform (provisional); never added to confirmed totals"},
        "reconciliation_open": len(list(db.scalars(select(ReconciliationItem).where(ReconciliationItem.status == "open")))),
        "adjustment_proposals_draft": len(list(db.scalars(select(BillingAdjustmentProposal).where(BillingAdjustmentProposal.status == "draft")))),
        "k2_basis": get_config(db, "k2.basis", {}),
        "k3": {"final_bases": ["billing-line", "invoice-single-line"], "provisional_cutoff": get_config(db, "k3.provisional_cutoff_days", None)},
        "k4": k4,
        "suppression_n": n,
        "switches": {k: switch(db, k, d) for k, d in (("billing_live", False), ("default_on_billing", False), ("consent_required_before_billing", True))},
        "fee_schedule": [{"version": s["version"], "status": s.get("status"), "effective_date": s.get("effective_date")} for s in fee_schedules(db)],
    }


# --- first-run welcome (SC2) -----------------------------------------------------------------------------


def welcome_view(db: Session, *, company_id: str, actor_key: str, language: str, assurance_level: str, can_change: bool, role: str) -> dict:
    run = db.scalar(select(WelcomeRun).where(WelcomeRun.company_id == company_id, WelcomeRun.actor_key == actor_key))
    terms_version = str(get_config(db, "subscription.terms.version", "terms-v1"))
    notice_version = str(get_config(db, "subscription.notice.version", "notice-v1"))
    if run is None:
        run = WelcomeRun(company_id=company_id, actor_key=actor_key, terms_version_shown=terms_version, notice_version_shown=notice_version, language_shown=language, identity_assurance_level=assurance_level)
        db.add(run)
        db.flush()
        record_event(db, event_type="WELCOME_SHOWN", category="consent", actor_key=actor_key, actor_role=role, company_id=company_id, language=language, config_version=f"terms@{terms_version}", details={"notice_version": notice_version, "assurance_level": assurance_level})
        for sub in db.scalars(select(Subscription).where(Subscription.company_id == company_id, Subscription.notice_version_shown.is_(None))):
            sub.notice_version_shown, sub.language_shown = notice_version, language
    view = company_subscription_view(db, company_id, can_change=can_change, role=role)
    return {"welcome": {"status": run.status, "language_choice": run.language_choice, "reminder_channel": run.reminder_channel, "terms_version_shown": run.terms_version_shown, "notice_version_shown": run.notice_version_shown, "first_seen_at": run.first_seen_at.isoformat(), "completed_at": run.completed_at.isoformat() if run.completed_at else None}, "reminder_channels": get_config(db, "notifications.channels", {}), "subscription": view}


def welcome_record(db: Session, *, company_id: str, actor_key: str, action: str, language_choice: str | None, reminder_channel: str | None) -> WelcomeRun:
    run = db.scalar(select(WelcomeRun).where(WelcomeRun.company_id == company_id, WelcomeRun.actor_key == actor_key))
    if run is None:
        raise NotFound("welcome not started", reason_code="WELCOME_NOT_STARTED")
    if action not in ("done", "later"):
        raise ValidationFailed("action must be done or later", reason_code="WELCOME_ACTION_INVALID")
    run.status = action
    run.language_choice = language_choice or run.language_choice
    run.reminder_channel = reminder_channel or run.reminder_channel
    if action == "done":
        run.completed_at = utcnow()
    record_event(db, event_type="WELCOME_COMPLETED" if action == "done" else "WELCOME_DEFERRED", category="consent", actor_key=actor_key, company_id=company_id, details={"language_choice": run.language_choice, "reminder_channel": run.reminder_channel})
    return run


def terms_view(db: Session, language: str) -> dict:
    from app.modules.subscriptions.strings import TERMS_SECTIONS

    version = str(get_config(db, "subscription.terms.version", "terms-v1"))
    return {"version": version, "label": "Proposed wording - pending confirmation", "sections": [{"key": k, "en": v["en"], "ar": v["ar"]} for k, v in TERMS_SECTIONS.items()], "language": language}


def admin_reread_allowed(db: Session, req: BillingRequest, actor_key: str) -> None:
    """Rate limits for admin re-reads: 1 per subscription per 5 min; 10 per admin per hour (config)."""
    limits = get_config(db, "admin.reread_rate", {"per_subscription_minutes": 5, "per_admin_per_hour": 10}) or {}
    now = utcnow()
    if req.last_read_at and now - req.last_read_at < timedelta(minutes=int(limits.get("per_subscription_minutes", 5))):
        raise Conflict("a re-read for this subscription was made less than 5 minutes ago", reason_code="REREAD_RATE_LIMIT")
    from app.modules.audit.models import AuditEvent

    recent = list(db.scalars(select(AuditEvent).where(AuditEvent.event_type == "BILLING_ADMIN_REREAD", AuditEvent.actor_key == actor_key, AuditEvent.occurred_at >= now - timedelta(hours=1))))
    if len(recent) >= int(limits.get("per_admin_per_hour", 10)):
        raise Conflict("hourly re-read limit reached", reason_code="REREAD_RATE_LIMIT")


def reconciliation_list(db: Session) -> list[dict]:
    return [{"id": r.id, "type": r.type, "licence_number": r.licence_number, "period": r.period, "sent_fils": r.sent_fils, "readback_fils": r.readback_fils, "status": r.status, "age_days": (utcnow() - r.raised_at).days, "raised_at": r.raised_at.isoformat(), "resolution_reason": r.resolution_reason} for r in db.scalars(select(ReconciliationItem).order_by(ReconciliationItem.raised_at.desc()).limit(200))]


def resolve_reconciliation(db: Session, item: ReconciliationItem, *, actor_key: str, reason_code: str) -> ReconciliationItem:
    if not reason_code:
        raise ValidationFailed("a reason code is required", reason_code="REASON_CODE_REQUIRED")
    item.status, item.resolution_reason, item.resolved_by_key, item.resolved_at = "resolved", reason_code, actor_key, utcnow()
    record_event(db, event_type="BILLING_RECONCILIATION_RESOLVED", category="billing", actor_key=actor_key, subject_type="reconciliation_item", subject_id=item.id, reason_code=reason_code)
    return item

