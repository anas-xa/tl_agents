"""Tax seeds (ORDER 55): rule set v1 in the rule register, vat-tp-v1, escalation triggers, config; demo profiles."""

from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.time import utcnow
from app.demo import CO_ALNOOR, CO_BLUEDUNE, CO_GULFTECH, CO_SAFWA, demo_ct_year, demo_vat_quarters
from app.modules.config.models import RuleRegisterEntry
from app.modules.config.service import ensure_config, ensure_rule
from app.modules.tax import service as svc
from app.modules.tax.models import TaxEntityProfile, TaxPeriodRevenue

ORDER = 55

AED = 100  # fils per dirham


def _ensure_version(db: Session, rule_id: str, version: str, title: str, **kw) -> None:
    if db.scalar(select(RuleRegisterEntry).where(RuleRegisterEntry.rule_id == rule_id, RuleRegisterEntry.version == version)) is None:
        db.add(RuleRegisterEntry(rule_id=rule_id, version=version, title=title, **kw))
        db.flush()


def seed(db: Session) -> None:
    owner = "tax expert confirms before loading (E3-S2 release flow)"
    ensure_rule(db, "ct-rate-v1", "Corporate tax rate and threshold", version="v1", instrument="Federal Decree-Law 47/2022 and implementing Cabinet decision, number to be confirmed by the FTA", source="[REG]", effective_from=date(2023, 6, 1), status="to_be_confirmed", owner_role=owner, parameters={"rate_percent": 9, "threshold_fils": 375_000 * AED, "applies_from": "2023-06-01", "applicability_basis": "financial years starting on or after 1 June 2023; version effective at period end applies to the whole period", "label": "test data, not confirmed"})
    ensure_rule(db, "vat-rate-v1", "VAT standard rate", version="v1", instrument="Federal Decree-Law 8/2017; Executive Regulations Cabinet Decision 52/2017 (confirm)", source="[REG]", effective_from=date(2018, 1, 1), status="to_be_confirmed", owner_role=owner, parameters={"rate_percent": 5, "label": "test data, not confirmed"})
    ensure_rule(db, "vat-registration-v1", "VAT registration thresholds", version="v1", instrument="Federal Decree-Law 8/2017 (confirm)", source="[REG]", effective_from=date(2018, 1, 1), status="to_be_confirmed", owner_role=owner, parameters={"mandatory_fils": 375_000 * AED, "voluntary_fils": 187_500 * AED})
    ensure_rule(db, "vat-return-due-v1", "VAT return due date", version="v1", instrument="Federal Decree-Law 8/2017 (confirm); E3-S2 precedence applies", source="[REG]", effective_from=date(2018, 1, 1), status="to_be_confirmed", owner_role=owner, parameters={"days_after_period_end": 28})
    ensure_rule(db, "ct-return-due-v1", "Corporate tax return due date", version="v1", instrument="Federal Decree-Law 47/2022 (confirm)", source="[REG]", effective_from=date(2023, 6, 1), status="to_be_confirmed", owner_role=owner, parameters={"months_after_period_end": 9})
    ensure_rule(db, "sbr-v1", "Small Business Relief (eligibility indicator only)", version="v1", instrument="Ministerial Decision 73/2023", source="[REG]", effective_from=date(2023, 6, 1), effective_to=date(2026, 12, 31), status="to_be_confirmed", owner_role=owner, parameters={"revenue_limit_fils": 3_000_000 * AED, "pro_rate": False, "exclusions": ["qfzp", "mne_group_eur_750m"], "first_period_on_or_after": "2023-06-01", "block_reason_after_end": "period ends after 31 Dec 2026", "label": "assumption, confirm"})
    _ensure_version(db, "sbr-v2", "v2", "Small Business Relief extension (reported, to be confirmed)", instrument="reported extension of the relief end date to 31 Dec 2029; official instrument to be confirmed before loading", source="not loaded", effective_from=None, effective_to=date(2029, 12, 31), status="to_be_confirmed", owner_role=owner, is_current=False, parameters={"applicable": False, "revenue_limit_fils": 3_000_000 * AED, "note": "to be confirmed; not applied. Until loaded, periods ending after 31 Dec 2026 show the normal 9% calculation."})
    ensure_rule(db, "ct-audit-required-v1", "Audited financial statements required", version="v1", instrument="Ministerial Decision 84/2025 (replaced 82/2023 for financial years starting on or after 1 Jan 2025)", source="[REG]", effective_from=date(2025, 1, 1), status="to_be_confirmed", owner_role=owner, parameters={"revenue_fils": 50_000_000 * AED, "qfzp": True, "tax_group": True})
    ensure_rule(db, "ct-loss-cf-v1", "Loss carry-forward cap", version="v1", instrument="Federal Decree-Law 47/2022 (confirm)", effective_from=date(2023, 6, 1), status="to_be_confirmed", owner_role=owner, parameters={"cap_percent": 75, "continuity_of_ownership": "confirm"})
    ensure_rule(db, "ct-interest-limit-v1", "General interest deduction limitation", version="v1", instrument="Federal Decree-Law 47/2022 (confirm)", effective_from=date(2023, 6, 1), status="to_be_confirmed", owner_role=owner, parameters={"net_interest_fils": 12_000_000 * AED, "ebitda_percent": 30, "note": "computed indicator only once inputs exist"})
    ensure_rule(db, "einvoicing-v1", "E-invoicing go-live (date flag only)", version="v1", instrument="Ministerial Decisions 243 and 244 of 2025", effective_from=date(2025, 1, 1), status="to_be_confirmed", owner_role=owner, parameters={"date_flag_only": True, "go_live": None})
    ensure_rule(db, "vat-tp-v1", "VAT time-of-supply, source precedence, FX and credit-note rules (vat-tp-v1)", version="v1", instrument="configuration, not official (Q430); confirm with the FTA", effective_from=date(2018, 1, 1), status="provisional", owner_role=owner, parameters={"time_of_supply": "earliest of date of supply, tax invoice issue date, payment received date", "instalments": "earlier of invoice date, payment due date or payment date per instalment", "invoice_14_day_rule": "invoice date usable if issued within 14 days after supply and no earlier payment (confirm wording)", "deposits": "tax point for the amount received", "human_review": ["reverse charge", "imports", "deemed supplies", "real estate", "financial services"], "date_fields": {"einvoice": "IssueDate (+ delivery/supply date if carried)", "erp": "invoice date + supply/delivery date; payment date from allocation; never the posting date", "bank": "booking date; value date fallback only"}, "dedup_key": ["counterparty", "amount", "currency", "invoice_number"], "bank_to_invoice_date_tolerance_days": None, "precedence": ["einvoice", "erp", "bank"], "fx": "AED VAT stated on invoice governs; else CBUAE rate on the tax-point date; missing rate blocks", "credit_notes": "tax point = issue date; reported in the period issued; original period never reopened"})
    ensure_rule(db, "ct-escalation-v1", "Escalation triggers 1-5 (provisional)", version="v1", instrument="pilot tax specialist team lead sets and signs; DET pilot manager records in the register", effective_from=date(2025, 1, 1), status="provisional", owner_role="pilot tax specialist team lead", parameters={"t1": "any flagged item escalates regardless of amount", "t2_pct_of_profit": 5, "t2_abs_fils": 50_000 * AED, "t2_lines_fils": [375_000 * AED, 3_000_000 * AED], "t3_abs_fils": 10_000 * AED, "t3_pct": 10, "t4_band_fils": [45_000_000 * AED, 55_000_000 * AED], "t5_mismatch_tolerance_pct": 2, "labels": {"t2": "placeholder", "t3": "placeholder", "t4": "provisional", "t5": "provisional (tolerance value not given; 2% placeholder)"}})
    ensure_config(db, "tax.rounding.display_decimals", 2, owner="Qeonix product owner", status="provisional", label="AED 2 decimals as display default only; rounding rule from VAT Executive Regulations, unconfirmed")
    ensure_config(db, "tax.sbr.pro_rate", False, owner="Qeonix product owner", status="to_be_confirmed", label="default: no pro-rating; configurable, to be confirmed")
    ensure_config(db, "tax.escalation.expected_response_hours", 48, unit="hours", owner="pilot tax specialist team lead", status="provisional", label="expected specialist response time shown with escalations")
    ensure_config(db, "tax.ct.supported_scope", "standalone_det_mainland", owner="Qeonix product owner", status="confirmed", label="Q96: tax groups, QFZPs and unclear status block the corporate-tax calculation")
    ensure_config(db, "tax.fx.source", "CBUAE rate on the tax-point date", owner="Qeonix product owner", status="to_be_confirmed", label="not certain it is the only accepted source")
    ensure_config(db, "tax.stale_detection.method", "hash of confirmed transactions", owner="Tech Lead", status="to_be_confirmed", label="Open (Q95, Q429, Q432): triggering events, timing, concurrency, run time")
    ensure_config(db, "tax.penalties.loaded", False, owner="Qeonix product owner", status="confirmed", label="penalty amounts are never loaded or shown")
    ensure_config(db, "tax.naming.product_title", "Tax preparation assistant", owner="Qeonix product owner", status="confirmed", label="'Tax Agent' is not a product name (Q93, Q99, Q100, Q430)")


def seed_demo(db: Session) -> None:
    if db.get(TaxEntityProfile, CO_ALNOOR) is not None:
        return
    quarters, ct = demo_vat_quarters(), demo_ct_year()
    earlier_fy = date(ct.start.year - 1, 1, 1)  # first CT period: the financial year before the demo CT year
    db.add_all([
        TaxEntityProfile(company_id=CO_ALNOOR, trn="100123456700003", vat_registered=True, vat_period_type="quarterly", ct_status="standalone_mainland", ct_status_source="self-declared, unverified (Demo data)", first_ct_period_start=earlier_fy, sbr_election="undecided", revenue_fils=2_800_000 * AED, revenue_source="books (IFRS for SMEs), owner to confirm (Demo data)", revenue_confirmed_by="Khalid Al Mansoori", revenue_confirmed_at=utcnow() - timedelta(days=3)),
        TaxEntityProfile(company_id=CO_BLUEDUNE, trn=None, vat_registered=False, vat_period_type="quarterly", ct_status="standalone_mainland", ct_status_source="self-declared, unverified (Demo data)", first_ct_period_start=ct.start, sbr_election="undecided"),
        TaxEntityProfile(company_id=CO_SAFWA, trn="100987654300003", vat_registered=True, vat_period_type="quarterly", ct_status="tax_group", ct_status_source="self-declared: member of a tax group (Demo data)", first_ct_period_start=earlier_fy),
        TaxEntityProfile(company_id=CO_GULFTECH, trn="100555555500003", vat_registered=True, vat_period_type="monthly", ct_status="unclear", ct_status_source="self-declared, unverified (Demo data)"),
        TaxPeriodRevenue(company_id=CO_ALNOOR, period_start=earlier_fy, period_end=date(earlier_fy.year, 12, 31), revenue_fils=2_450_000 * AED, source="books, owner confirmed (Demo data)", confirmed_by="Khalid Al Mansoori"),
    ])
    db.flush()
    # Demo calculations: Al Noor VAT for the previous and open quarters and CT for the demo year (SBR 'may be
    # eligible'); Safwa blocked CT.
    svc.calculate_vat(db, CO_ALNOOR, quarters.previous.period_id)
    svc.calculate_vat(db, CO_ALNOOR, quarters.open.period_id)
    svc.calculate_ct(db, CO_ALNOOR, ct.period_id, accounting_profit_fils=500_000 * AED, revenue_fils=2_800_000 * AED, revenue_source="books (IFRS for SMEs), owner to confirm (Demo data)")
    svc.calculate_ct(db, CO_SAFWA, ct.period_id)
    db.flush()
