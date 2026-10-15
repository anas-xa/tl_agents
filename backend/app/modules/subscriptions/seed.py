"""E2-S2/S3/S4 configuration (switches, fee schedule, billing hook, opt-out/refund, complaints, K2-K4) and
demo subscriptions for the demo companies."""

from __future__ import annotations

from datetime import date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.time import dubai_date, dubai_today, utcnow
from app.modules.config.service import ensure_config, ensure_rule
from app.modules.subscriptions.models import (
    BillingRequest,
    Case,
    Complaint,
    PaymentAllocation,
    PaymentEvent,
    Subscription,
    SubscriptionStateHistory,
)
from app.modules.subscriptions.service import add_working_days, compute_fee

ORDER = 20
PM = "DET pilot manager"
PO = "Qeonix product owner"


def seed(db: Session) -> None:
    # Increment switches. Records and fee calculation carry their gate evidence in tests/test_subscriptions.py
    # (replay creates no duplicate; fee table passes); billing_live stays off until the schedule is confirmed.
    ensure_config(db, "subscription.records.enabled", True, owner=PO, status="provisional", label="increment 1 gate: one record per licence per term, replay creates no duplicate (test evidence); billing off; example fee data only")
    ensure_config(db, "subscription.fee_schedule_calc.enabled", True, owner=PO, status="provisional", label="increment 2 gate: fee from schedule version in force on event date; fils rounding test passes")
    ensure_config(db, "subscription.billing_live.enabled", False, owner=PM, status="to_be_confirmed", label="off until the fee schedule is marked confirmed and, for default-on, the signed DET-Qeonix agreement")
    ensure_config(db, "subscription.views.enabled", True, owner=PO, status="provisional", label="increment 4: owner, delegate and reviewer views AR/EN RTL")
    ensure_config(db, "subscription.default_on_billing.enabled", False, owner=PM, status="to_be_confirmed", label="default-on billing never goes live before the signed DET-Qeonix agreement")
    ensure_config(db, "subscription.consent_required_before_billing.enabled", True, owner=PM, status="provisional", label="the bilingual notice must be shown and recorded before any default-on line is requested")
    ensure_config(db, "enrolment.default_on", "opt_in", unit="enum", owner=PM, status="to_be_confirmed", label="[OPEN] legal: default_on vs opt_in; pilot default opt_in until agreement signed")
    ensure_config(db, "fee_schedule.schedules", [{"version": "fee-v1", "effective_date": "2025-01-01", "status": "example", "base_annual_fils": 60000, "term_unit": "month", "term_months": 12, "vat_treatment": "net; VAT separate line", "vat_rate_bp": 500, "amount_basis": "net", "pro_rata_basis": "days", "late_renewal_start": "new_start", "enrolment_mode": "opt_in", "refund_or_cancellation_rule": "to be confirmed", "label": "example, not a confirmed price"}], owner=PM, status="to_be_confirmed", label="versioned fee schedule; example until DET confirms the fee model")
    ensure_config(db, "fee_schedule.base_annual_fils", 60000, unit="fils", owner=PM, status="to_be_confirmed", label="example, not confirmed (AED 600)")
    ensure_config(db, "fee_schedule.monthly_display_fils", 5000, unit="fils", owner=PM, status="to_be_confirmed", label="display only ('about AED 50 a month'); never a billing cycle")
    ensure_config(db, "fee_schedule.vat_rate_bp", 500, unit="bp", owner=PM, status="to_be_confirmed", label="working assumption 5%; FTA to confirm")
    ensure_config(db, "fee_schedule.amount_basis", "net", unit="enum", owner=PM, status="to_be_confirmed", label="VAT treatment to be confirmed; versioned")
    ensure_config(db, "fee_schedule.pro_rata_basis", "days", unit="enum", owner=PM, status="provisional", label="whole months -> months/12, else days/365")
    ensure_config(db, "fee_schedule.late_renewal_start", "new_start", unit="enum", owner=PM, status="to_be_confirmed", label="[OPEN] grace period; no back-billing")
    ensure_config(db, "fee_schedule.proration", "days", unit="enum", owner=PM, status="provisional", label="daily proration for non-12-month terms; PM pilot alternative 'none' (one full annual charge per event, term from effective date) held as the other value")
    ensure_config(db, "fee_schedule.rounding", {"mode": "half_up", "per": "line", "on": "net", "unit": "fils", "integer_formula": "(base x days x 2 + 365) div (365 x 2)"}, owner=PO, status="provisional", label="assumption")
    ensure_config(db, "subscription.retry_schedule_minutes", [1, 5, 15], unit="minutes", owner=PO, status="provisional", label="configurable, for production; then dead-letter + alert")
    ensure_config(db, "subscription.retry_max_attempts", 5, unit="count", owner=PO, status="provisional")
    ensure_config(db, "billing.retry_schedule", ["5m", "15m", "1h", "4h", "12h"], owner=PO, status="provisional", label="same key; after last retry or 48 h -> held_for_review + alert")
    ensure_config(db, "reconciliation.daily_pending_hours", 24, unit="hours", owner=PO, status="provisional", label="list pending_billing / billing_requested older than 24 h")
    ensure_config(db, "subscription.cohort_stamping", {"rule": "invoice date converted UTC -> Asia/Dubai before taking the month", "format": "{cohort_code}-{YYYY-MM}"}, owner=PO, status="provisional")
    ensure_config(db, "k2.basis", {"version": "k2-v1", "timing": "invoice date of the DET billing line; period = invoice-date month", "fallback": "billing-line timestamp (labelled)", "amount": "net of VAT only when vat_amount populated, else 'VAT treatment unconfirmed'", "recognised_view": "by subscription period; normalised annual = billed net / term_months x 12", "credit_notes": "separate negative line in a later month; original cohort not restated"}, owner="DET finance", status="provisional", label="versioned; DET finance may switch")
    ensure_config(db, "k3.provisional_cutoff_days", 30, unit="days", owner=PM, status="provisional", label="period provisional until the cut-off after period end")
    ensure_config(db, "sc2.loading_slow_seconds", 10, unit="seconds", owner=PO, status="provisional", label="then 'Still loading...'")
    ensure_config(db, "sc2.auto_retry", {"auto_after_seconds": 5, "manual_tries_before_support": 3}, owner=PO, status="provisional")
    # Billing hook (E2-S3)
    ensure_config(db, "billing.hook_interface", "manual", unit="enum", owner=PM, status="to_be_confirmed", label="[OPEN] DET billing hook interface; manual DET adapter is the Phase 1A fallback")
    ensure_config(db, "billing.payment_channel", None, owner=PM, status="to_be_confirmed", label="[OPEN] DET online payment, Dubai Pay or gateway; collection point is configuration")
    ensure_config(db, "readback.wait_before_alert_minutes", 60, unit="minutes", owner=PM, status="provisional", label="configurable, for production")
    ensure_config(db, "readback.schedule", ["5m", "15m", "60m", "then every 4h"], owner=PM, status="provisional")
    ensure_config(db, "readback.max_attempts", 8, unit="count", owner=PM, status="provisional")
    ensure_config(db, "readback.timeout_seconds", 10, unit="seconds", owner=PM, status="provisional", label="timeout = empty read")
    ensure_config(db, "readback.alt", ["1m", "5m", "15m", "60m", "wait 4h", "payment status every 4h + nightly"], owner=PM, status="provisional", label="superseded by readback.schedule; kept as reference (Q25)")
    ensure_config(db, "readback.test_latencies", ["0s", "90s", "5h"], owner=PO, status="provisional", label="stub parameter")
    ensure_config(db, "admin.reread_rate", {"per_subscription_minutes": 5, "per_admin_per_hour": 10, "reason_code_required": True}, owner=PM, status="provisional")
    ensure_config(db, "alert.recipients", {"det_admin": "reconciliation queue (portal)", "qeonix_ops": "operations queue (email)"}, owner=PM, status="provisional")
    ensure_config(db, "amount.compare", "exact equality in fils, no tolerance", owner=PO, status="provisional", label="rule")
    ensure_config(db, "billing.rounding", {"mode": "half_up", "scope": "presentation and invoicing only", "authority": "DET billing line; differences flagged as reconciliation exception"}, owner=PM, status="to_be_confirmed", label="[OPEN] DET rounding")
    ensure_config(db, "alloc.rule_version", "alloc-v1", owner=PO, status="provisional", label="design rule, not official; alloc-v2 ('subscription paid last') comparison only")
    ensure_config(db, "billing.vat_split_switch", True, owner=PM, status="to_be_confirmed", label="VAT treatment to be confirmed (on = taxable supply, off = outside VAT)")
    ensure_config(db, "billing.platform_derived_allocation.enabled", True, owner=PO, status="provisional", label="alloc-v1 (c) pro-rata by gross; flagged provisional; a payment with no invoice lines stays received_unallocated")
    ensure_config(db, "partial_allocation.order", {"rule": "licence fee first; subscription never paid from the licence fee amount; shortfall leaves the subscription unpaid"}, owner="DET finance", status="to_be_confirmed", label="unconfirmed DET collection-order assumption (Q26); alloc-v1 is the K3 attribution rule")
    ensure_config(db, "refund.window_days", 14, unit="days", owner=PM, status="provisional", label="placeholder, from payment; provisional")
    ensure_config(db, "unpaid.grace_period_days", 30, unit="days", owner=PM, status="provisional", label="provisional; then read-only smart services; the licence is never affected")
    ensure_config(db, "partial_payment.estimate", "5-15% of invoices, peaking at renewal clusters", owner=PO, status="provisional", label="estimate")
    # Opt-out, refund, complaints (E2-S4): each parameter with status; non-confirmed never shown as a number.
    ensure_config(db, "opt_out.config", {
        "version": "optout-v1",
        "enrolment": {"value": "opt_in", "status": "proposed", "label": "to be confirmed with DET", "approver": None, "effective_date": None},
        "opt_out_allowed": {"value": True, "status": "confirmed", "label": "owner opt-out can never be disabled without a recorded DET + counsel decision"},
        "opt_out_window_days": {"value": 30, "status": "example", "label": "to be confirmed with DET; illustrative 30 days from issuance or renewal; never shown as a number until confirmed"},
        "cancel_effective": {"value": None, "status": "example", "label": "to be confirmed with DET (immediate or end of billing period)"},
        "refund_window_days": {"value": 14, "status": "example", "label": "to be confirmed with DET; 14 days from payment is a placeholder"},
        "refund_mode": {"value": None, "status": "example", "label": "[OPEN] to be confirmed with DET"},
        "pro_rata_refund": {"value": None, "status": "example", "label": "[OPEN] to be confirmed with DET"},
        "notice_period": {"value": None, "status": "example", "label": "to be confirmed with DET"},
        "who_may_opt_out": {"value": "owner or authorised signatory; never a delegate", "status": "proposed", "label": "proposed"},
        "complaint_reply_period_working_days": {"value": 5, "status": "proposed", "label": "5 UAE working days (Mon-Fri), configurable; DET owns the SLA"},
        "refund_response_time_working_days": {"value": 10, "status": "example", "label": "illustrative, to be confirmed with DET"},
        "post_opt_out_data_retention_days": {"value": 90, "status": "example", "label": "illustrative, for production"},
    }, owner=PM, status="to_be_confirmed", label="versioned; changes never alter decided cases")
    ensure_config(db, "opt_out.trigger_events", ["issuance", "every renewal before payment", "any time after from the Subscription screen"], owner=PM, status="provisional")
    ensure_config(db, "refund.response_time_working_days", 10, unit="working days", owner=PM, status="provisional", label="illustrative, to be confirmed with DET")
    ensure_config(db, "complaint.reply_period_working_days", 5, unit="working days", owner=PM, status="provisional", label="5 UAE working days (Mon-Fri), configurable; charge/refund complaints inside the 14-day window decided within the same 5 days")
    ensure_config(db, "complaint.categories", [{"code": "charge", "en": "A charge", "ar": "رسوم", "k4": True}, {"code": "opt_out", "en": "Opting out", "ar": "إلغاء الاشتراك", "k4": True}, {"code": "service_quality", "en": "Service quality", "ar": "جودة الخدمة", "k4": True}, {"code": "other", "en": "Other", "ar": "أخرى", "k4": False}], owner=PM, status="provisional", label="K4 counts subscription/billing categories; uncategorised shown separately")
    ensure_config(db, "complaint.description_max_length", 2000, unit="characters", owner=PO, status="provisional")
    ensure_config(db, "needs_det_action.wait_working_days", 2, unit="working days", owner=PM, status="provisional", label="settled 2 working days (Q290/Q355); Q34 earlier said 24 h")
    ensure_config(db, "needs_det_action.reply_time_working_days", 5, unit="working days", owner=PM, status="provisional", label="illustrative, shown to the owner as configured response time")
    ensure_config(db, "det_hook.retry", {"tries": 3, "schedule_minutes": [1, 5, 30]}, owner=PO, status="provisional", label="configurable, for production")
    ensure_config(db, "det_hook.call_timeout_seconds", 30, unit="seconds", owner=PO, status="provisional")
    ensure_config(db, "det_hook.readback_poll", ["1m", "5m", "30m", "then hourly"], owner=PO, status="provisional")
    ensure_config(db, "det_hook.reconciliation_readback_hours", 4, unit="hours", owner=PO, status="provisional")
    ensure_config(db, "det_hook.alert_role", "det_admin", owner=PM, status="provisional", label="DET administrator queue (Q290); DET billing operations per Q34")
    ensure_config(db, "post_opt_out.data_retention_days", 90, unit="days", owner=PM, status="provisional", label="illustrative, for production")
    ensure_config(db, "retention.case_records_years", 5, unit="years", owner="DET + counsel", status="to_be_confirmed", label="after case close or licence cancellation, whichever later; working rule")
    ensure_config(db, "retention.attachments_years", 2, unit="years", owner="DET + counsel", status="to_be_confirmed", label="after case closure, deletion noted; working rule")
    ensure_config(db, "attachments.limits", {"types": ["PDF", "JPG", "PNG"], "by_signature": True, "max_files": 5, "max_mb_each": 5, "max_mb_total": 15, "phase": "1B"}, owner=PO, status="provisional", label="versioned; attachments are Phase 1B")
    ensure_config(db, "k4.rule_version", "k4-v1", owner=PM, status="provisional")
    ensure_config(db, "k4.observation_window_days", 90, unit="days", owner=PM, status="provisional", label="illustrative; options 30/60/90")
    # superseded by det_dashboard.min_group_size (one platform-wide N, kpis.suppression)
    # ensure_config(db, "k4.suppression_N", 10, unit="licences", owner=PM, status="provisional", label="'<10' with complementary suppression")
    ensure_config(db, "k4.refund_reason_mapping", {"excluded": ["failed_payment", "duplicate_payment", "technical_error"]}, owner="DET finance", status="to_be_confirmed", label="placeholder table, to be confirmed with DET finance")
    ensure_config(db, "reasons.lists", {"version": "reasons-v1", "opt_out": [{"code": "cost", "en": "Cost", "ar": "التكلفة"}, {"code": "not_needed", "en": "I do not need it", "ar": "لا أحتاجه"}, {"code": "prefer_not_to_say", "en": "Prefer not to say", "ar": "أفضّل عدم الإفصاح"}, {"code": "other", "en": "Other", "ar": "أخرى"}], "refund": [{"code": "charged_in_error", "en": "Charged in error", "ar": "تم التحصيل بالخطأ"}, {"code": "service_not_used", "en": "Service not used", "ar": "لم تُستخدم الخدمة"}, {"code": "other", "en": "Other", "ar": "أخرى"}], "complaint": [{"code": "charge", "en": "A charge", "ar": "رسوم"}, {"code": "opt_out", "en": "Opting out", "ar": "إلغاء الاشتراك"}, {"code": "service_quality", "en": "Service quality", "ar": "جودة الخدمة"}, {"code": "other", "en": "Other", "ar": "أخرى"}]}, owner=PO, status="provisional", label="stable codes with EN/AR labels; fixed 'other' code")
    ensure_config(db, "notifications.email_rule", "only if the owner opted in; status + sign-in link, never complaint text", owner=PO, status="provisional")
    ensure_config(db, "subscription.terms.version", "terms-v1", owner="DET licensing/legal affairs", status="to_be_confirmed", label="Proposed wording - pending confirmation; AR/EN legal review by a licensed UAE law firm")
    ensure_config(db, "subscription.notice.version", "notice-v1", owner="DET licensing/legal affairs", status="to_be_confirmed", label="pre-payment bilingual notice; version seen and time recorded per licence")
    ensure_config(db, "subscription.included_modules", [{"code": "tax", "en": "Tax calculation and filing-ready preparation", "ar": "احتساب الضريبة والإعداد الجاهز للتقديم"}, {"code": "reminders", "en": "Reminders", "ar": "التذكيرات"}, {"code": "audit_preparation", "en": "Draft audit working files", "ar": "مسودات ملفات عمل التدقيق"}, {"code": "compliance", "en": "Compliance deadline tracking", "ar": "متابعة مواعيد الامتثال"}, {"code": "escalation", "en": "Escalation to a human", "ar": "التصعيد إلى شخص مختص"}], owner=PO, status="provisional", label="Phase 1 modules only")
    ensure_config(db, "subscription.not_included", [{"code": "signed_audit", "en": "Signed audit reports (only a licensed auditor signs; engagement separate)", "ar": "تقارير التدقيق الموقّعة (يوقّعها مدقق مرخّص فقط؛ التكليف منفصل)"}, {"code": "legal_advice", "en": "Individual legal advice (information, not advice)", "ar": "استشارة قانونية فردية (معلومات، وليست استشارة)"}, {"code": "aml", "en": "AML alerts", "ar": "تنبيهات مكافحة غسل الأموال"}, {"code": "auto_filing", "en": "Automatic filing (the owner approves every submission)", "ar": "التقديم التلقائي (يعتمد المالك كل تقديم)"}, {"code": "free_zone", "en": "Free-zone companies", "ar": "شركات المناطق الحرة"}], owner=PO, status="provisional")
    ensure_rule(db, "fee-v1", "Subscription fee schedule (example)", instrument="DET-Qeonix fee model (to be confirmed)", status="to_be_confirmed", owner_role=PM, parameters={"version": "fee-v1", "base_annual_fils": 60000, "vat_rate_bp": 500, "amount_basis": "net", "status": "example", "label": "example, not a confirmed price"})
    ensure_rule(db, "alloc-v1", "Payment allocation rule (pro-rata by gross line amount)", instrument="design rule, not official", status="provisional", owner_role=PO, parameters={"version": "alloc-v1", "bases": ["billing-line", "invoice-single-line", "platform-derived"], "residual_fil": "largest line (licence fee), never the subscription line"})
    ensure_rule(db, "k2-v1", "K2 subscription revenue billed", instrument="DET billing read-back", status="provisional", owner_role="DET finance", parameters={"counts": "confirmed billed lines only", "net_of_vat": True})
    ensure_rule(db, "k3-v1", "K3 subscription collection rate", instrument="payment channel + DET billing record", status="provisional", owner_role=PM, parameters={"final_bases": ["billing-line", "invoice-single-line"], "provisional_basis": "platform-derived"})
    ensure_rule(db, "k4-v1", "K4 opt-out and complaint rate", instrument="platform complaint log and case log", status="provisional", owner_role=PM, parameters={"observation_window_days": 90, "suppression_n": 10, "flags": ["flag_opted_out", "flag_refunded", "flag_complained"]})
    ensure_rule(db, "reasons-v1", "Opt-out, refund and complaint reason lists", status="provisional", owner_role=PO, parameters={"version": "reasons-v1"})
    ensure_rule(db, "terms-v1", "Proposed subscription terms (bilingual)", instrument="Proposed wording - pending confirmation", status="to_be_confirmed", owner_role="DET licensing/legal affairs", parameters={"version": "terms-v1", "legal_review": "licensed UAE law firm (AR/EN) pending"})


def _history(db: Session, sub_id: str, path: list[str], at: datetime) -> None:
    prev = None
    for i, st in enumerate(path):
        db.add(SubscriptionStateHistory(subscription_id=sub_id, from_status=prev, to_status=st, event_at=at + timedelta(minutes=i), reason_code="demo fixture"))
        prev = st


def seed_demo(db: Session) -> None:
    from app.demo import CO_ALNOOR, CO_BLUEDUNE, CO_SAFWA

    if db.scalar(select(Subscription).where(Subscription.id == "sub_alnoor")) is not None:
        return
    today = dubai_today()
    now = utcnow()

    def make(sid: str, licence: str, lic_id: str, company: str, basis: str, cohort_reg: str, cohort_code: str, start: date, end: date, status: str, event_id: str, ref: str, **extra) -> Subscription:
        fee = compute_fee(60000, start, end, vat_rate_bp=500, proration="days", vat_split=True)
        sub = Subscription(id=sid, licence_number=licence, licence_id=lic_id, company_id=company, enrolment_basis=basis, cohort_id=f"{cohort_code}-{start.year:04d}-{start.month:02d}", cohort_register_id=cohort_reg, cohort_version=1, wave="1b", start_date=start, end_date=end, term_days=fee["term_days"], term_months=fee["term_months"], term_type=fee["term_type"], base_annual_fils=60000, fee_schedule_version="fee-v1", fee_schedule_status="example", opt_out_refund_config_version="optout-v1", net_amount_fils=fee["net_fils"], vat_rate_bp=500, vat_fils=fee["vat_fils"], gross_fils=fee["gross_fils"], amount_basis="net", proration_rule="days", det_event_reference=ref, source_event_id=event_id, status=status, renewal_due_at=end + timedelta(days=1), notice_version_shown="notice-v1", language_shown="en", is_demo=True, **extra)
        db.add(sub)
        return sub

    # Al Noor: opted in, billed, collected, active (Demo data).
    an_start, an_end = today - timedelta(days=319), today + timedelta(days=45)
    an = make("sub_alnoor", "DET-1023456", "lic_alnoor", CO_ALNOOR, "opted_in", "coh_pilot1", "PILOT1", an_start, an_end, "active", "DEMO-EV-ALNOOR-REN-1", "REF-AN-R1", billing_line_id="DETBL-AN-0001", invoice_id="DETINV-AN-2025-0001", allocation_basis_flag="billing-line")
    an.created_at = datetime.combine(an_start - timedelta(days=1), datetime.min.time())
    _history(db, an.id, ["created", "pending_billing", "billing_requested", "billed", "collected", "active"], an.created_at)
    an_req = BillingRequest(id="br_alnoor", subscription_id=an.id, licence_number=an.licence_number, billing_period=f"{an_start.isoformat()}|{an_end.isoformat()}", idempotency_key=f"DET-1023456+{an.id}+{an_start.isoformat()}|{an_end.isoformat()}", amount_snapshot_fils=an.net_amount_fils, net_fils=an.net_amount_fils, vat_fils=an.vat_fils, gross_fils=an.gross_fils, reference_field=f"DET-1023456+{an.id}+{an_start.isoformat()}|{an_end.isoformat()}", status="billed", collection_status="collected", collected_fils=an.gross_fils, outstanding_fils=0, receipt_reference="DETPAY-AN-77812", billing_line_id="DETBL-AN-0001", invoice_id="DETINV-AN-2025-0001", invoice_date=an_start - timedelta(days=2), invoice_date_source="invoice_date", adapter="manual", sent_at=an.created_at, read_attempts=1, last_read_at=an.created_at + timedelta(hours=1))
    db.add(an_req)
    db.add(PaymentEvent(id="pay_alnoor", payment_transaction_id="PTX-AN-0001", amount_fils=an.gross_fils, type="payment", billing_line_id="DETBL-AN-0001", invoice_id="DETINV-AN-2025-0001", allocation_status="allocated", channel="DET online payment (stub)", source_timestamp=an.created_at + timedelta(hours=2), received_at=an.created_at + timedelta(hours=2)))
    db.add(PaymentAllocation(allocation_basis="billing-line", payment_transaction_id="PTX-AN-0001", billing_request_id="br_alnoor", billing_line_id="DETBL-AN-0001", amount_fils=an.gross_fils, provisional=False, allocated_at=an.created_at + timedelta(hours=2)))

    # Blue Dune: default-on (fixture-only cohort), billed, payment received but not allocated (Demo data).
    bd_start, bd_end = today - timedelta(days=164), today + timedelta(days=200)
    bd = make("sub_bluedune", "DET-2045678", "lic_bluedune", CO_BLUEDUNE, "default_on", "coh_pilot1_do", "PILOT1D", bd_start, bd_end, "active", "DEMO-EV-BLUEDUNE-REN-1", "REF-BD-R1", billing_line_id="DETBL-BD-0001", invoice_id="DETINV-BD-2025-0007")
    bd.created_at = datetime.combine(bd_start - timedelta(days=1), datetime.min.time())
    _history(db, bd.id, ["created", "pending_billing", "billing_requested", "billed", "active"], bd.created_at)
    db.add(BillingRequest(id="br_bluedune", subscription_id=bd.id, licence_number=bd.licence_number, billing_period=f"{bd_start.isoformat()}|{bd_end.isoformat()}", idempotency_key=f"DET-2045678+{bd.id}+{bd_start.isoformat()}|{bd_end.isoformat()}", amount_snapshot_fils=bd.net_amount_fils, net_fils=bd.net_amount_fils, vat_fils=bd.vat_fils, gross_fils=bd.gross_fils, reference_field=f"DET-2045678+{bd.id}+{bd_start.isoformat()}|{bd_end.isoformat()}", status="billed", collection_status="received_unallocated", collected_fils=0, outstanding_fils=bd.gross_fils, receipt_reference="DETPAY-BD-91022", billing_line_id="DETBL-BD-0001", invoice_id="DETINV-BD-2025-0007", invoice_date=bd_start - timedelta(days=3), invoice_date_source="invoice_date", adapter="manual", sent_at=bd.created_at, read_attempts=2, last_read_at=bd.created_at + timedelta(hours=5)))
    db.add(PaymentEvent(id="pay_bluedune", payment_transaction_id="PTX-BD-0001", amount_fils=bd.gross_fils + 1000000, type="payment", invoice_id="DETINV-BD-2025-0007", allocation_status="received_unallocated", channel="DET online payment (stub)", source_timestamp=bd.created_at + timedelta(days=2), received_at=bd.created_at + timedelta(days=2)))

    # Safwa: licence expired; subscription billed but not collected, past the grace period -> read-only (Demo data).
    sf_start, sf_end = today - timedelta(days=374), today - timedelta(days=10)
    sf = make("sub_safwa", "DET-3067890", "lic_safwa", CO_SAFWA, "opted_in", "coh_pilot1", "PILOT1", sf_start, sf_end, "billed", "DEMO-EV-SAFWA-REN-1", "REF-SF-R1", billing_line_id="DETBL-SF-0001", invoice_id="DETINV-SF-2024-0042", service_mode="read_only", grace_until=sf_start - timedelta(days=2) + timedelta(days=30))
    sf.created_at = datetime.combine(sf_start - timedelta(days=1), datetime.min.time())
    _history(db, sf.id, ["created", "pending_billing", "billing_requested", "billed"], sf.created_at)
    db.add(BillingRequest(id="br_safwa", subscription_id=sf.id, licence_number=sf.licence_number, billing_period=f"{sf_start.isoformat()}|{sf_end.isoformat()}", idempotency_key=f"DET-3067890+{sf.id}+{sf_start.isoformat()}|{sf_end.isoformat()}", amount_snapshot_fils=sf.net_amount_fils, net_fils=sf.net_amount_fils, vat_fils=sf.vat_fils, gross_fils=sf.gross_fils, reference_field=f"DET-3067890+{sf.id}+{sf_start.isoformat()}|{sf_end.isoformat()}", status="billed", collection_status="failed", collected_fils=0, outstanding_fils=sf.gross_fils, billing_line_id="DETBL-SF-0001", invoice_id="DETINV-SF-2024-0042", invoice_date=sf_start - timedelta(days=2), invoice_date_source="invoice_date", adapter="manual", sent_at=sf.created_at, read_attempts=3, last_read_at=sf.created_at + timedelta(days=1)))
    db.add(PaymentEvent(id="pay_safwa_fail", payment_transaction_id="PTX-SF-FAIL-0001", amount_fils=sf.gross_fils, type="failure", billing_line_id="DETBL-SF-0001", invoice_id="DETINV-SF-2024-0042", allocation_status="no_allocation_failed", channel="DET online payment (stub)", source_timestamp=sf.created_at + timedelta(days=3), received_at=sf.created_at + timedelta(days=3)))
    db.add(Case(id="case_safwa_refund", subscription_id=sf.id, company_id=CO_SAFWA, action="refund", action_family="refund", terms_version="terms-v1", request_id="demo-req-sf-1", idempotency_key=f"{sf.id}+refund+terms-v1+case_safwa_refund", reason_code="charged_in_error", reason_config_version="reasons-v1", state="pending_DET", received_at=now - timedelta(days=4), actor_key="demo-owner-safwa", actor_role="owner", language_shown="ar", notice_version_shown="notice-v1", identity_assurance_level="SOP3", reference_code="DEMO4R7K", det_instruction_state="sent", det_instruction_sent_at=now - timedelta(days=4)))
    received = now - timedelta(days=2)
    db.add(Complaint(id="cmp_alnoor_1", reference="DEMOC2X9", company_id=CO_ALNOOR, licence_number="DET-1023456", subscription_id="sub_alnoor", category="charge", description="Demo data: the subscription line appeared on my invoice before I expected it.", preferred_language="ar", contact_channel="portal", received_at=received, reply_by=add_working_days(dubai_date(received), 5), status="in_review", status_reason_code="under_review", filed_by_key="demo-owner-alnoor", filed_by_role="owner", k4_eligible=True, sla_working_days=5))
    db.flush()
