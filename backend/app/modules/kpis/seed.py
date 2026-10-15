"""E9-S1 seeds: KPI catalogue, SC14 configuration keys, suppression rule, and the synthetic demo fixture.

The fixture (~140 pilot licences, label 'Demo data') lives in its own table, never mixed with real company
rows, and is used only while ``det_dashboard.include_demo_fixture`` is true (default false; the demo seed
switches it on). Sizes are chosen so tiles show values above N while the small wave 1a cohort and the small
licence categories still demonstrate suppression and the 'Other (combined)' line.
"""

from __future__ import annotations

import random
from datetime import date, datetime, time, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.time import dubai_today
from app.modules.config.service import ensure_config, ensure_rule, get_config, set_config
from app.modules.kpis import suppression as sup
from app.modules.kpis.catalogue import DEFAULT_RELEASE_SETTINGS, ensure_catalogue
from app.modules.kpis.models import KpiFixtureLicence

ORDER = 90
PM = "DET pilot manager"


def seed(db: Session) -> None:
    ensure_catalogue(db)
    ensure_config(db, sup.CONFIG_KEY, sup.DEFAULT_N, unit="licences", owner=PM, status="provisional", label="provisional, set by DET; allowed 3-50; DET compliance lead consulted; changes audited", description="Minimum group size N for every DET aggregate (screen, API, export, scheduled report).")
    ensure_rule(db, sup.RULE_ID, "DET aggregate suppression rules (E9-S1 F2)", instrument="design control, not a legal threshold", status="provisional", owner_role=f"{PM} / privacy officer", parameters={k: v for k, v in sup.DEFAULT_RULES.items()})
    ensure_config(db, "det_dashboard.include_demo_fixture", False, owner="Qeonix product owner", status="provisional", label="Demo data fixture; true only in the demo seed; never mixed with real company rows")
    ensure_config(db, "det_dashboard.later_phase_kpis.enabled", False, owner="Qeonix product owner", status="provisional", label="single release setting: K5-K8 switch from 'Not yet available' to live with no layout change")
    ensure_config(db, "det_dashboard.release_settings", DEFAULT_RELEASE_SETTINGS, owner="Qeonix product owner", status="provisional", label="per-tile release state and planned phase label")
    ensure_config(db, "det_dashboard.k7k8_min_measurable_share", 60, unit="%", owner="Pilot team", status="provisional", label="product threshold: rate shown only at or above this measurable share")
    ensure_config(db, "det_dashboard.k7k8_min_returns", 30, unit="returns", owner="Pilot team", status="provisional", label="rate shown only with at least this many measurable returns")
    ensure_config(db, "det_dashboard.k3_payment_term_days", 30, unit="days", owner=PM, status="to_be_confirmed", label="K3 stays provisional while any invoice is within its payment term; term to be set with DET")
    ensure_config(db, "det_dashboard.k3_cancelling_refund_reasons", ["full_credit", "licence_cancelled", "billed_in_error", "charged_in_error", "opt_out"], owner="DET finance", status="to_be_confirmed", label="refunds that cancel the charge reduce the billed denominator; partial and goodwill refunds reduce collected only")
    ensure_config(db, "det_dashboard.k4_counted_refund_reasons", ["opt_out", "complaint", "service_not_used", "charged_in_error"], owner="DET finance", status="to_be_confirmed", label="k4-v1: reasons counted for flag_refunded; other reasons are 'unmapped' and shown as excluded")
    ensure_config(db, "det_dashboard.k4_denominator_rule", "active_at_start_plus_started", unit="enum", owner="Data dictionary", status="provisional", label="k4-v1 rate denominator (Q153); alternatives active_any_time, invoice_month_cohort (Q291 cohort view)")
    ensure_config(db, "det_dashboard.k4_opt_out_headline", "requests", unit="enum", owner="DET", status="to_be_confirmed", label="[OPEN] requests (event time = request received) or det_confirmed if DET approval is required")
    ensure_config(db, "det_dashboard.k6_grace_length_days", None, unit="days", owner="DET", status="to_be_confirmed", label="'unknown' [OPEN]; renewals after expiry are 'renewed late' until DET confirms a grace length")
    ensure_config(db, "det_dashboard.k6_suspended_rule", "exclude", unit="enum", owner="DET", status="provisional", label="conflict Q451 (keep in denominator, blocked count) vs Q268 (exclude via mapping); default per Q268, recorded in the data dictionary")
    ensure_config(db, "det_dashboard.k6_final_after_days", 30, unit="days", owner=PM, status="provisional", label="K6 provisional until month end, final 30 days after")
    ensure_config(db, "det_dashboard.k5_usage_bands", {"none": 0, "light": 1, "regular": 5}, unit="events in 90 days", owner="Product", status="provisional", label="configurable, Phase 3")
    ensure_config(db, "det_dashboard.k19_signature_required", {"audit_file_draft": True, "audit_work_draft": True, "year_end_pack_with_opinion": True, "agreed_upon_procedures_report": True, "management_summary": False}, owner="Licensed auditor lead", status="provisional", label="sig-v1: a type missing from this table counts as signature required (fail closed)")
    ensure_config(db, "det_dashboard.k19_excluded_types", ["tax_return_draft", "compliance_summary"], owner="Licensed auditor lead", status="provisional", label="excluded from K19 (not audit deliverables)")
    ensure_config(db, "det_dashboard.k29_qualifying_events", ["SIGN_IN", "DOCUMENT_DOWNLOADED", "APPROVAL_RECORDED", "CONSENT_GRANTED", "CONSENT_WITHDRAWN", "ESCALATION_OPENED"], owner="Product", status="provisional", label="K29 qualifying events; system-generated events excluded")
    ensure_config(db, "det_dashboard.k29_window_days", 30, unit="days", owner="Product", status="provisional")
    ensure_config(db, "det_dashboard.stale_threshold_daily", 1, unit="missed refreshes", owner="Product", status="provisional", label="fixed by story")
    ensure_config(db, "det_dashboard.stale_threshold_monthly", 1, unit="missed refreshes", owner="Product", status="provisional", label="fixed by story")
    ensure_config(db, "det_dashboard.loading_slow_after_seconds", 10, unit="seconds", owner="UX", status="provisional", label="fixed by story")
    ensure_config(db, "det_dashboard.export_rate_limit", None, owner="Tech Lead", status="to_be_confirmed", label="Q450 open")
    ensure_config(db, "det_dashboard.suppression_mode", "per_query", unit="enum", owner="Tech Lead", status="to_be_confirmed", label="per query vs pre-computed cube: Q450 open")
    ensure_rule(db, "sig-v1", "K19 signature-required table per deliverable type", instrument="Federal Law 12/2014 (licensed auditors; to be confirmed)", status="provisional", owner_role="Licensed auditor lead", parameters={"fail_closed": True, "config_key": "det_dashboard.k19_signature_required"})
    ensure_rule(db, "k7k8-v1", "K7/K8 filing timeliness (owner-reported, not FTA-verified)", instrument="vat-due-v1, ct-due-v1 (rule and calendar reference)", status="provisional", owner_role="Pilot team", parameters={"min_measurable_share": 60, "min_returns": 30, "measurable_due_sources": ["FTA_NOTICE", "FTA_PORTAL_STATUS", "RULE_DERIVED"], "measurable_filed_sources": ["company_reported_receipt", "fta_status"], "roll_rule": "no_roll"})
    ensure_rule(db, "k5-v1", "K5 retention at renewal (creation-stamped cohort)", instrument="product definition", status="provisional", owner_role="Product", parameters={"attribution": "cohort stamped at creation", "usage_window_days": 90})
    ensure_rule(db, "k29-v1", "K29 cohort usage rate", instrument="product definition", status="provisional", owner_role="Product", parameters={"window_days": 30})
    db.flush()


# --- demo fixture ---------------------------------------------------------------------------------------------


def _month_start(d: date, back: int) -> date:
    idx = d.year * 12 + (d.month - 1) - back
    return date(idx // 12, idx % 12 + 1, 1)


def build_fixture(today: date) -> list[dict]:
    """Deterministic synthetic pilot (140 licences). Returns rows for KpiFixtureLicence."""
    rng = random.Random(9014)
    specs = [("PILOT1", "1b", "opt_in", 95), ("PILOT1D", "1b", "default_on_with_opt_out", 37), ("WAVE1A", "1a", "opt_in", 8)]
    categories = ["Commercial"] * 70 + ["Professional"] * 52 + ["Industrial"] * 12 + ["Tourism"] * 6
    rng.shuffle(categories)
    methods = ["DET online payment"] * 110 + ["DET service centre"] * 24 + ["Bank transfer"] * 6
    rng.shuffle(methods)
    offsets = [0] * 22 + [1] * 24 + [2] * 18 + [3] * 16 + [4] * 15 + [5] * 13 + [6] * 12 + [7] * 12
    rng.shuffle(offsets)
    cur_start = _month_start(today, 0)
    rows: list[dict] = []
    i = 0
    for cohort, wave, basis, count in specs:
        for _ in range(count):
            ref = f"FX-{i + 1:03d}"
            back = 0 if cohort == "WAVE1A" else offsets.pop()
            ms = _month_start(today, back)
            max_day = (today - ms).days if back == 0 else 27
            inv = ms + timedelta(days=rng.randint(0, max(0, max_day)))
            gross, net, vat = 63000, 60000, 3000
            r = rng.random()
            held = cohort == "PILOT1" and i % 47 == 5
            line = {"kind": "charge", "date": inv.isoformat(), "date_source": "billing_line_timestamp" if i % 41 == 3 else "invoice_date", "net": net, "vat": None if i % 29 == 7 else vat, "gross": gross, "term_months": 12, "payment_method": methods[i], "collected_final": 0, "collected_platform": 0, "refunded": 0, "refund_cancels_charge": False, "confirmed": True}
            if r < 0.78:
                line.update(payment_status="collected", collected_final=gross)
            elif r < 0.88:
                line.update(payment_status="collected", collected_platform=gross)
            elif r < 0.93:
                line.update(payment_status="partially_collected", collected_final=gross // 2)
            else:
                line.update(payment_status="not_collected")
            sub: dict = {"status": "active", "created_on": (inv - timedelta(days=2)).isoformat(), "active_from": inv.isoformat(), "active_to": (inv + timedelta(days=364)).isoformat(), "unpaid": line["payment_status"] in ("not_collected", "partially_collected"), "invoice_date": inv.isoformat(), "term_months": 12, "lines": [line], "opt_out": None, "refunds": [], "complaints": [], "renewal_due": (inv + timedelta(days=365)).isoformat(), "renewed": False, "cancelled_before_term_end": False, "renewal_choice_marker": None, "events": []}
            if held:
                sub.update(status="held_for_review", active_from=None, active_to=None, lines=[], invoice_date=None, unpaid=False)
            # k4-v1 flags: more frequent in the default-on cohort; events land inside the 90-day window
            flag_p = 0.6 if basis == "default_on_with_opt_out" else 0.15
            if not held and back <= 3 and rng.random() < flag_p:
                ev_day = min(today, max(inv + timedelta(days=rng.randint(3, 40)), cur_start if rng.random() < 0.8 else inv + timedelta(days=3)))
                kind = rng.choice(["opt_out", "opt_out", "opt_out", "refund", "complaint"])
                if kind == "opt_out":
                    sub["opt_out"] = {"at": ev_day.isoformat(), "status": rng.choice(["det_confirmed", "det_confirmed", "pending", "rejected"])}
                    if sub["opt_out"]["status"] == "det_confirmed":
                        sub.update(status="opted_out", active_to=ev_day.isoformat())
                elif kind == "refund":
                    sub["refunds"].append({"at": ev_day.isoformat(), "reason": "opt_out"})
                    sub["opt_out"] = {"at": ev_day.isoformat(), "status": "det_confirmed"}
                    sub.update(status="opted_out", active_to=ev_day.isoformat())
                    line.update(refunded=line["collected_final"] + line["collected_platform"], refund_cancels_charge=True)
                    sub["lines"].append({**line, "kind": "credit_note", "date": ev_day.isoformat(), "net": -net, "vat": -vat if line["vat"] is not None else None, "gross": -gross, "collected_final": 0, "collected_platform": 0, "refunded": 0})
                else:
                    sub["complaints"].append({"at": ev_day.isoformat(), "category": rng.choice(["charge", "charge", "opt_out", "other", "uncategorised"])})
            if not held and i % 53 == 11:
                sub["refunds"].append({"at": min(today, inv + timedelta(days=4)).isoformat(), "reason": "failed_payment"})  # technical: excluded
            if sub["status"] == "active" and rng.random() < 0.58:
                for _ in range(rng.randint(1, 4)):
                    sub["events"].append({"type": rng.choice(["SIGN_IN", "SIGN_IN", "DOCUMENT_DOWNLOADED", "APPROVAL_RECORDED", "CONSENT_GRANTED"]), "at": (today - timedelta(days=rng.randint(0, 29))).isoformat()})
            # K6 renewal facts: previous expiry spread over the last six months and this month
            exp = _month_start(today, rng.randint(0, 5)) + timedelta(days=rng.randint(0, 27))
            exp = min(exp, today + timedelta(days=10))
            rs = rng.random()
            raw, done, block = "RENEWED", None, None
            if rs < 0.62:
                done = datetime.combine(exp - timedelta(days=rng.randint(0, 25)), time(6, 0))  # on time or early (06:00 UTC = 10:00 Dubai)
            elif rs < 0.72:
                done = datetime.combine(exp + timedelta(days=rng.randint(3, 25)), time(6, 0))
            elif rs < 0.80:
                raw = "EXPIRED"
            elif rs < 0.83:
                raw = "CANCELLED"
            elif rs < 0.85:
                raw = "SUSPENDED"
            elif rs < 0.88:
                raw, block = "EXPIRED", "blocked_by_ejari"
            elif rs < 0.89:
                raw = "PENDING_DET_REVIEW"  # unmapped: unknown + alert
            else:
                done = datetime.combine(exp - timedelta(days=1), time(6, 0))
            if done is not None and done.date() > today:
                done = None
                raw = "ACTIVE"
            renewal = {"issuing_authority": "DET", "licence_type": "free_zone" if i % 67 == 9 else "mainland", "prior_expiry": exp.isoformat(), "renewal_completed_at": done.isoformat() if done else None, "raw_status": raw, "block_reason_code": block}
            # K7/K8 return facts (owner-reported): VAT returns due on the 28th of recent months
            returns = []
            for qb in (0, 1, 2):
                due = _month_start(today, qb) + timedelta(days=27)
                rr = rng.random()
                ret = {"tax_type": "vat_return", "statutory_due": due.isoformat(), "due_used": due.isoformat(), "deadline_source": "RULE_DERIVED", "filed_date": None, "filed_source": None, "extension_recorded": False}
                if rr < 0.08:
                    ret.update(deadline_source="OWNER_ENTERED", filed_source="owner_declaration", filed_date=(due - timedelta(days=2)).isoformat())
                elif rr < 0.12:
                    new_due = due + timedelta(days=20)
                    ret.update(deadline_source="FTA_NOTICE", due_used=new_due.isoformat(), extension_recorded=True, filed_source="company_reported_receipt", filed_date=(new_due - timedelta(days=1)).isoformat())
                elif rr < 0.30:
                    pass  # filed date not available
                else:
                    late = rng.random() < 0.09
                    fd = due + timedelta(days=rng.randint(1, 12)) if late else due - timedelta(days=rng.randint(0, 10))
                    if fd > today and not late and rng.random() < 0.6:
                        fd = today - timedelta(days=rng.randint(0, 3))  # early filers for a return not yet due
                    if fd <= today:
                        ret.update(filed_source="company_reported_receipt" if rng.random() < 0.9 else "fta_status", filed_date=fd.isoformat())
                returns.append(ret)
            # K19 deliverables
            deliverables = []
            if i % 4 == 0:
                st = rng.choice(["draft"] * 5 + ["in_review"] * 4 + ["signed"] * 3 + ["rejected"] * 2 + ["issued"] + ["superseded"])
                deliverables.append({"type": "audit_file_draft", "status": st, "signed": st in ("signed", "issued"), "released": st == "issued"})
            if i % 9 == 0:
                deliverables.append({"type": "management_summary", "status": "draft", "signed": False, "released": False})
            if i % 7 == 0:
                deliverables.append({"type": "tax_return_draft", "status": "draft", "signed": False, "released": False})
            # K20 evaluations (latest per licence per period wins)
            evaluations = []
            if i % 2 == 0:
                first = rng.choice(["likely_not_required"] * 6 + ["cannot_determine"] * 3 + ["likely_required"])
                evaluations.append({"period": f"FY{today.year - 1}", "result": first, "evaluated_at": datetime.combine(today - timedelta(days=60), time(8)).isoformat()})
                if i % 10 == 0:
                    evaluations.append({"period": f"FY{today.year - 1}", "result": rng.choice(["likely_required", "likely_not_required"]), "evaluated_at": datetime.combine(today - timedelta(days=10), time(8)).isoformat()})
            rows.append({"fixture_ref": ref, "cohort": cohort, "wave": wave, "enrolment_basis": basis, "licence_category": categories[i], "payment_method": methods[i], "facts": {"subscription": sub, "renewal": renewal, "returns": returns, "deliverables": deliverables, "evaluations": evaluations}})
            i += 1
    return rows


def seed_demo(db: Session) -> None:
    current = get_config(db, "det_dashboard.include_demo_fixture", None)
    if current is False:
        from app.modules.config.service import get_config_entry

        if get_config_entry(db, "det_dashboard.include_demo_fixture").changed_by == "seed":
            set_config(db, "det_dashboard.include_demo_fixture", True, changed_by="demo_seed", change_reason="demo environment shows the synthetic pilot fixture (Demo data)")
    if db.scalar(select(KpiFixtureLicence.id).limit(1)) is not None:
        return
    db.add_all([KpiFixtureLicence(**r) for r in build_fixture(dubai_today())])
    db.flush()
