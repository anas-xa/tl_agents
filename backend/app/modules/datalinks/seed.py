"""Data-link configuration, rule register entries, route-holder register, bank list and demo data. ORDER 35."""

from __future__ import annotations

import calendar
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.time import dubai_today, utcnow
from app.demo import CO_ALNOOR, CO_BLUEDUNE, CO_GULFTECH, PERSONA_UUIDS, demo_ct_year, demo_vat_quarters
from app.modules.access.service import Principal
from app.modules.audit.service import ensure_identity_mapping
from app.modules.config.service import ensure_config, ensure_rule
from app.modules.datalinks import service as svc
from app.modules.datalinks.models import (
    BankConfig,
    BankLink,
    RouteHolderRegister,
    StatementUpload,
    TaxAuthorityLink,
    TaxProfile,
)

ORDER = 35

K27_WINDOWS_V1 = {
    "bank": {"expected_interval_h": 24, "tolerance_h": 6, "stale_after_h": 48, "note": "conflicting estimates recorded: 30 h (Q77), 36 h (Q55), 48 h (Q388); tune in pilot"},
    "det": {"expected_interval_h": 24, "tolerance_h": 6, "stale_after_h": 72},
    "fta": {"expected_interval_h": 24, "tolerance_h": 6, "stale_after_h": 72, "note": "Q77 gives 30 h; excluded from K27 until live"},
    "erp": {"expected_interval_h": 24, "tolerance_h": 6, "stale_after_h": 72, "note": "Q77 gives 48 h for cloud ERP; Phase 1 has no connector"},
    "e_invoice": {"expected_interval_h": 1, "tolerance_h": 1, "stale_after_h": 24, "note": "inactive before 1 Jan 2027 (AED 50m+) / 1 Jul 2027; excluded from K27"},
}
BANKS = [
    ("demo_bank", "Demo Bank (fixture)", "البنك التجريبي (بيانات تجريبية)", True),
    ("enbd", "Emirates NBD", "بنك الإمارات دبي الوطني", False),
    ("adcb", "Abu Dhabi Commercial Bank", "بنك أبوظبي التجاري", False),
    ("fab", "First Abu Dhabi Bank", "بنك أبوظبي الأول", False),
    ("mashreq", "Mashreq", "المشرق", False),
    ("dib", "Dubai Islamic Bank", "بنك دبي الإسلامي", False),
    ("rakbank", "RAKBANK", "بنك رأس الخيمة الوطني", False),
    ("cbd", "Commercial Bank of Dubai", "بنك دبي التجاري", False),
]


def seed(db: Session) -> None:
    eng, prod, dom = "Qeonix engineering lead", "Qeonix product owner", "Qeonix domain data lead"
    ensure_config(db, "datalinks.route_holder", "licensed_provider_partner", owner="Operator / Legal", status="to_be_confirmed", label="start value; CBUAE and law firm confirm; values licensed_provider_partner | own_licence | none")
    ensure_config(db, "datalinks.openfinance.enabled", False, owner=prod, status="to_be_confirmed", label="OFF until the integration checklist row for the licensed Open Finance route (Nebras / Al Tareq) is confirmed live")
    ensure_config(db, "datalinks.bank.consent_max_duration_months", 12, unit="months", owner=prod, status="provisional", label="configurable; route max if shorter")
    ensure_config(db, "datalinks.bank.expiry_notice_offsets_days", [30, 14, 7], unit="days before", owner=prod, status="provisional", label="SC5 renew prompt default 14 days before")
    ensure_config(db, "datalinks.bank.revocation_poll_interval_minutes", 15, unit="minutes", owner=eng, status="provisional")
    ensure_config(db, "datalinks.bank.pull_schedule", {"time": "02:00", "timezone": "Asia/Dubai", "frequency": "daily"}, owner=eng, status="provisional", label="configurable")
    ensure_config(db, "datalinks.bank.pull_retries", {"attempts": 3, "delays_minutes": [1, 5, 15], "jitter": True, "then": "Error"}, owner=eng, status="provisional", label="illustrative")
    ensure_config(db, "datalinks.bank.on_demand_refresh_limit_per_day", 3, unit="pulls per account per day", owner=prod, status="provisional", label="a few pulls/day/account within bank and platform rate limits")
    ensure_config(db, "datalinks.upload.max_size_mb", 20, unit="MB", owner=prod, status="provisional", label="configurable; UI/Q386 cite 10 MB illustrative - conflict noted, 20 MB (Q387) used")
    ensure_config(db, "datalinks.upload.max_rows", 50000, unit="rows", owner=prod, status="provisional", label="configurable")
    ensure_config(db, "datalinks.upload.invalid_row_threshold_percent", 20, unit="%", owner=prod, status="provisional", label="configurable; whole file refused above this")
    ensure_config(db, "datalinks.upload.formats", ["csv", "xlsx", "pdf"], owner=prod, status="provisional", label="CSV, XLSX, text-based PDF; encrypted or image-only PDF refused")
    ensure_config(db, "datalinks.upload.statement_age_amber_days", 35, unit="days after statement end", owner=dom, status="provisional", label="estimate; 'Update due' badge")
    ensure_config(db, "datalinks.upload.retention_after_withdrawal_days", 30, unit="days", owner=prod, status="provisional", label="illustrative; lock then delete; owner may request earlier; production with DET and counsel")
    ensure_config(db, "datalinks.upload.notice_version", "v1", owner="Qeonix product owner / Legal", status="provisional", label="notice-and-consent record wording for uploads (data submission, not consent)")
    ensure_config(db, "datalinks.erp.supported_systems", [], owner="PM with pilot cohort (E2-S5)", status="confirmed", label="pilot: none; connector list is versioned config starting EMPTY (Q64)")
    ensure_config(db, "datalinks.erp.vendor_flags", {"zoho_books": False, "quickbooks": False, "tally": False, "sap": False}, owner="PM / Security", status="to_be_confirmed", label="per-vendor flag, off for production data until DET and DESC confirm outbound calls in writing")
    ensure_config(db, "datalinks.erp.file_upload_enabled", True, owner=prod, status="confirmed", label="ON from wave 1a; decided, not a switch")
    ensure_config(db, "datalinks.erp.vendor_preconditions", ["entered in the residency register", "DET and DESC accept outbound calls if hosted outside the UAE", "company has given the separate ledger and invoice data authorisation"], owner=prod, status="confirmed", label="three preconditions before a vendor is added")
    ensure_config(db, "datalinks.erp.refresh_window_hours", {}, owner=eng, status="to_be_confirmed", label="[OPEN] per system")
    ensure_config(db, "datalinks.erp.debits_equal_credits_tolerance_fils", None, unit="fils", owner="Tech lead", status="to_be_confirmed", label="[OPEN] Q63")
    ensure_config(db, "datalinks.erp.open_items_q63", {"retry_backoff": "open", "idempotency_replace_vs_version": "open", "deleted_at_source": "open", "invoice_match_keys_and_tolerance": "open", "reauth_notification_channel": "open"}, owner="Tech lead", status="to_be_confirmed", label="[OPEN] Q63")
    ensure_config(db, "datalinks.erp.raw_purge_after_withdrawal_days", 30, unit="days", owner=prod, status="provisional", label="~30 provisional")
    ensure_config(db, "datalinks.tax.adapter.enabled", False, owner="PM / E1-S8", status="to_be_confirmed", label="OFF until the E1-S8 FTA row is complete; no machine access assumed")
    ensure_config(db, "datalinks.tax.channel", {"channel": "open", "formats": "open", "auth_method": "open", "legal_basis": "open"}, owner="FTA", status="to_be_confirmed", label="[OPEN]")
    ensure_config(db, "datalinks.tax.stale_threshold_days", 7, unit="days", owner="UX (demo parameter)", status="provisional", label="demo; production set with DET")
    ensure_config(db, "datalinks.tax.poll_boost_before_due", "every 6 h (Q77) / hourly (Q392) in the 7 days before a due date", owner=dom, status="provisional", label="configuration only; estimate")
    ensure_config(db, "datalinks.tax.freshness_placeholder_hours", 24, unit="hours", owner=prod, status="provisional", label="Q70 placeholder for status")
    ensure_config(db, "datalinks.tax.accepted_identity_levels_and_signature_types", [], owner="DET / UAE PASS / FTA", status="to_be_confirmed", label="[OPEN] empty until confirmed")
    ensure_config(db, "datalinks.tax.remote_owner_consent_allowed", False, owner=prod, status="confirmed", label="not allowed in MVP (Q72)")
    ensure_config(db, "datalinks.tax.sbr_period_cutoff", "2026-12-31", unit="date", owner="[REG] confirm", status="to_be_confirmed", label="Small Business Relief covers periods ending on or before 31 Dec 2026 [REG, confirm]; indicator only")
    ensure_config(db, "datalinks.tax.ct_due_rule", "9 months after period end", owner="[REG]", status="to_be_confirmed", label="[REG] rule register ct-due-v1")
    ensure_config(db, "datalinks.tax.vat_due_rule", "28 days after period end", owner="[REG]", status="to_be_confirmed", label="[REG] rule register vat-due-v1")
    ensure_config(db, "datalinks.tax.trn_pattern", r"^100\d{12}$", owner="Tech lead", status="to_be_confirmed", label="[OPEN] Q390 manual field validation; 15 digits starting 100 assumed")
    ensure_config(db, "datalinks.tax.filing_frequencies", ["monthly", "quarterly", "annual"], owner="Tech lead", status="to_be_confirmed", label="[OPEN] Q390 value list")
    ensure_config(db, "datalinks.tax.det_admin_small_group_suppression", 10, unit="count", owner="DET", status="provisional", label="groups < 10 suppressed")
    ensure_config(db, "datalinks.k27.window_calendar_mode", "plain_elapsed", owner=prod, status="confirmed", label="Q78: plain elapsed calendar time; no skipping of weekends, holidays or downtime in Phase 1")
    ensure_config(db, "datalinks.k27.reporting_lines", ["connector", "uploaded"], owner=prod, status="confirmed", label="Q78: two lines; uploaded-data line is the pilot headline")
    ensure_config(db, "datalinks.links.connecting_timeout_minutes", 15, unit="minutes", owner=prod, status="provisional", label="placeholder, versioned: 'Still connecting. If this continues, contact support.'")
    ensure_config(db, "datalinks.links.status_check_delayed_after_hours", 6, unit="hours", owner=eng, status="to_be_confirmed", label="[OPEN] Q402 delayed-detection trigger and N")
    ensure_config(db, "datalinks.links.manual_upload_reminder_days", 35, unit="days", owner=prod, status="provisional", label="fits monthly bookkeeping")
    ensure_config(db, "datalinks.links.loading_slow_threshold_seconds", 10, unit="seconds", owner="Qeonix UX lead", status="provisional")
    ensure_rule(db, "k27-windows-v1", "K27 freshness windows per source (expected interval / tolerance / stale after)", instrument="pilot operating rule", status="provisional", owner_role="Qeonix domain data lead", parameters={"windows": K27_WINDOWS_V1, "mode": "plain_elapsed", "holiday_note": "informational only; no threshold change"})
    ensure_rule(db, "vat-due-v1", "VAT return due date: 28 days after the end of the tax period", instrument="Federal Decree-Law No. 8 of 2017 and Cabinet Decision 52 of 2017 (to be confirmed)", status="to_be_confirmed", owner_role="Tax specialist", parameters={"days_after_period_end": 28})
    ensure_rule(db, "ct-due-v1", "Corporate tax return due date: 9 months after the end of the tax period", instrument="Federal Decree-Law No. 47 of 2022 (to be confirmed)", status="to_be_confirmed", owner_role="Tax specialist", parameters={"months_after_period_end": 9})
    if db.scalar(select(RouteHolderRegister).where(RouteHolderRegister.is_current.is_(True))) is None:
        db.add(RouteHolderRegister(version=1, route_holder="licensed_provider_partner", provider_legal_name=None, cbuae_licence_reference=None, authorised_activities=["account information service"], agreement_signed=False, consent_model={"who_consents": "authorised signatory", "scope": ["accounts", "data types", "purpose", "period"], "revocation": "provider flow; consent identifier mirrored"}, processing_location="to be confirmed (ties to residency register)", revocation_flow="provider revocation flow (to be confirmed)", coverage_confirmed=False, status="to_be_confirmed", label="start value: licensed_provider_partner; coverage unconfirmed; bank link refused until evidence complete", effective_from=dubai_today()))
    for bank_id, en, ar, demo in BANKS:
        if db.get(BankConfig, bank_id) is None:
            db.add(BankConfig(bank_id=bank_id, name_en=en, name_ar=ar, demo=demo, coverage_status="unconfirmed", corporate_account_types_live=[]))
    db.flush()


# Al Noor's demo bank statement covers one calendar month: the latest month that ended at least 35 days before today
# (so the manual-data badge reads 'update due'). Placeholders are filled by alnoor_statement().
ALNOOR_STATEMENT_TEMPLATE = [
    (1, "Opening balance / الرصيد الافتتاحي,,,\"152,340.50\",AED,OB-{mm}01"),
    (2, "Ejari rent Q{q} - Business Bay office / إيجار إيجاري الربع {q_ar},\"42,000.00\",,\"110,340.50\",AED,TRF-88102"),
    (3, "DEWA bill {prev_month} / فاتورة هيئة كهرباء ومياه دبي,\"3,215.75\",,\"107,124.75\",AED,DEWA-{prev_mm}03"),
    (4, "Customer receipt INV-{yyyy}-0142 Al Fajer Trading / تحصيل فاتورة,,\"18,750.00\",\"125,874.75\",AED,RCV-3341"),
    (5, "Supplier payment Gulf Packaging LLC / دفعة للمورد,\"9,870.00\",,\"116,004.75\",AED,TRF-88130"),
    (6, "Bank charges / رسوم مصرفية,105.00,,\"115,899.75\",AED,CHG-{mm}06"),
    (7, "Customer receipt INV-{yyyy}-0143 شركة الواحة للتجارة,,\"27,300.00\",\"143,199.75\",AED,RCV-3342"),
    (10, "Etisalat telecom {month} / اتصالات,842.00,,\"142,357.75\",AED,ETS-{mm}10"),
    (12, "Supplier payment Noor Logistics / نور للخدمات اللوجستية,\"6,450.00\",,\"135,907.75\",AED,TRF-88155"),
    (14, "Customer receipt INV-{yyyy}-0144 Desert Line Co,,\"12,400.00\",\"148,307.75\",AED,RCV-3343"),
    (15, "FTA VAT payment Q{pq} {pq_yyyy} / سداد ضريبة القيمة المضافة,\"21,860.00\",,\"126,447.75\",AED,FTA-VAT-Q{pq}"),
    (18, "Owner drawing - Khalid / مسحوبات المالك,\"15,000.00\",,\"111,447.75\",AED,TRF-88170"),
    (20, "Supplier payment Al Madar Stationery / القرطاسية,\"1,230.50\",,\"110,217.25\",AED,TRF-88181"),
    (22, "Customer receipt INV-{yyyy}-0145 Blue Sky FZE,,\"33,000.00\",\"143,217.25\",AED,RCV-3344"),
    (24, "Refund to customer INV-{yyyy}-0139 / استرداد لعميل,\"2,500.00\",,\"140,717.25\",AED,TRF-88190"),
    (25, "POS settlement - Network International / تسوية نقاط البيع,,\"4,860.30\",\"145,577.55\",AED,POS-{mm}25"),
    (26, "Insurance premium - vehicle / قسط تأمين المركبة,\"3,980.00\",,\"141,597.55\",AED,TRF-88201"),
    (27, "WPS salaries {month} / رواتب نظام حماية الأجور,\"46,500.00\",,\"95,097.55\",AED,WPS-{mm}27"),
    (27, "WPS salaries {month} / رواتب نظام حماية الأجور,\"46,500.00\",,\"48,597.55\",AED,WPS-{mm}27"),
    (28, "Customer receipt INV-{yyyy}-0146 ١٢٣ Trading / تحصيل,,\"9,990.00\",\"58,587.55\",AED,RCV-3345"),
    (29, "Bank charges - international transfer / رسوم تحويل دولي,75.00,,\"58,512.55\",AED,CHG-{mm}29"),
    (30, "Supplier payment Emirates Printing Press,\"4,120.00\",,\"54,392.55\",AED,TRF-88215"),
    (31, "Interest / profit credit / أرباح الوديعة,, 312.40,\"54,704.95\",AED,INT-{mm}31"),
    (31, "Customer receipt INV-{yyyy}-0147 مؤسسة النخيل,,\"16,250.00\",\"70,954.95\",AED,RCV-3346"),
    (31, "Petty cash withdrawal / سحب نثريات,\"2,000.00\",,\"68,954.95\",AED,ATM-{mm}31"),
]
QUARTER_AR = {1: "الأول", 2: "الثاني", 3: "الثالث", 4: "الرابع"}


def statement_month(today: date | None = None) -> tuple[date, date]:
    """First and last day of the latest calendar month that ended at least 35 days before today."""
    anchor = (today or demo_vat_quarters().today) - timedelta(days=35)
    end = anchor if (anchor + timedelta(days=1)).day == 1 else anchor.replace(day=1) - timedelta(days=1)
    return end.replace(day=1), end


def alnoor_statement(today: date | None = None) -> str:
    start, end = statement_month(today)
    prev = start - timedelta(days=1)
    q = (start.month - 1) // 3 + 1
    pq, pq_year = (4, start.year - 1) if q == 1 else (q - 1, start.year)
    values = {"mm": f"{start.month:02d}", "prev_mm": f"{prev.month:02d}", "month": calendar.month_name[start.month], "prev_month": calendar.month_name[prev.month], "yyyy": start.year, "q": q, "q_ar": QUARTER_AR[q], "pq": pq, "pq_yyyy": pq_year}
    lines = ["Date,Description,Debit,Credit,Balance,Currency,Reference"]
    for day, text in ALNOOR_STATEMENT_TEMPLATE:
        lines.append(f"{start.replace(day=min(day, end.day)).isoformat()},{text.format(**values)}")
    return "\n".join(lines) + "\n"


ALNOOR_TRIAL_BALANCE = """Account code,Account name,اسم الحساب,Debit,Credit
1000,Cash at bank,النقد في البنك,"68,954.95",
1100,Accounts receivable,ذمم مدينة,"41,200.00",
2000,Accounts payable,ذمم دائنة,,"22,340.00"
2100,VAT payable,ضريبة القيمة المضافة المستحقة,,"5,980.00"
3000,Owner's equity,حقوق المالك,,"60,000.00"
4000,Sales revenue,إيرادات المبيعات,,"117,690.00"
5000,Cost of sales,تكلفة المبيعات,"52,355.05",
6000,Rent expense,مصروف الإيجار,"42,000.00",
6100,Salaries expense,مصروف الرواتب,"46,500.00",
9999,Suspense,حساب معلق,"-45,000.00",
"""


def _principal(db: Session, persona: str, name: str) -> Principal:
    uuid = PERSONA_UUIDS[persona]
    return Principal(identity_uuid=uuid, actor_key=ensure_identity_mapping(db, uuid), display_name=name, assurance_level="SOP3", profile_type=1, language="en", session_id="seed-demo")


def seed_demo(db: Session) -> None:
    now = utcnow()
    khalid = _principal(db, "khalid", "Khalid Al Mansoori")
    # Al Noor: completed manual statement upload (~25 mixed Arabic/English lines) under its own declaration record
    if db.scalar(select(StatementUpload).where(StatementUpload.company_id == CO_ALNOOR, StatementUpload.is_demo.is_(True))) is None:
        m_start, m_end = statement_month()
        tag = f"{calendar.month_abbr[m_start.month].lower()}-{m_start.year}"
        up = svc.create_upload(db, khalid, CO_ALNOOR, file_name=f"alnoor-demo-bank-statement-{tag}.csv", data=alnoor_statement().encode("utf-8"), kind="bank_statement", bank_id="demo_bank", bank_name="Demo Bank (fixture)", account_ref="AE07DEMO0000000001234", purpose="bookkeeping_classification", notice_acknowledged=True)
        up.is_demo = True
        up.uploaded_at = now - timedelta(days=12)
        tb = svc.create_upload(db, khalid, CO_ALNOOR, file_name=f"alnoor-demo-trial-balance-{tag}.csv", data=ALNOOR_TRIAL_BALANCE.encode("utf-8"), kind="erp_export", export_type="trial_balance", purpose="bookkeeping_classification", notice_acknowledged=True, period_start=m_start, period_end=m_end)
        tb.is_demo = True
        tb.uploaded_at = now - timedelta(days=11)
    # Al Noor: tax profile company_provided (VAT quarterly, entered period = the open demo quarter, TRN 100xxxxxxxxxxxx;
    # CT registered for the financial year running after the demo CT year, SBR unknown)
    if db.scalar(select(TaxProfile).where(TaxProfile.company_id == CO_ALNOOR)) is None:
        open_q = demo_vat_quarters().open
        ct_year = demo_ct_year().end.year + 1
        vat = svc.set_tax_profile(db, khalid, CO_ALNOOR, {"tax_type": "vat", "trn": "100234567890003", "registration_status": "registered", "filing_status": "last return submitted (as provided by the company)", "tax_period_start": open_q.start.isoformat(), "tax_period_end": open_q.end.isoformat(), "filing_frequency": "quarterly", "source": "company_provided"})
        vat.is_demo = True
        ct = svc.set_tax_profile(db, khalid, CO_ALNOOR, {"tax_type": "corporate_tax", "trn": "100234567890004", "registration_status": "registered", "filing_status": "first period not yet due (as provided by the company)", "tax_period_start": f"{ct_year}-01-01", "tax_period_end": f"{ct_year}-12-31", "filing_frequency": "annual", "source": "company_provided", "small_business_relief": [{"period_end": f"{ct_year}-12-31", "indicator": "unknown", "source": "unknown"}]})
        ct.is_demo = True
    # tax links: Al Noor manual/unverified (adapter off), Gulf Tech fixture 'error' state labelled Demo data
    svc.tax_link(db, CO_ALNOOR)
    gt = svc.tax_link(db, CO_GULFTECH)
    if gt.fixture_key is None:
        gt.fixture_key, gt.error_cause, gt.last_good_read_at = "error", "authority_not_responding", now - timedelta(days=2)
    # Blue Dune: demo bank link bound to the withdrawn consent (badge 'Consent withdrawn' overrides technical active)
    if db.scalar(select(BankLink).where(BankLink.company_id == CO_BLUEDUNE)) is None:
        from app.modules.consent.models import Consent

        c = db.scalar(select(Consent).where(Consent.company_id == CO_BLUEDUNE, Consent.consent_type == "bank_data_open_finance"))
        db.add(BankLink(company_id=CO_BLUEDUNE, bank_id="demo_bank", consent_id=c.consent_id if c else None, consent_version=1, external_consent_id="ALT-DEMO-5678", status="consent_withdrawn", accounts=[{"account_ref": "AE12DEMO0000000005678", "masked": "•••• 5678", "holder_name": "Blue Dune Consultancy", "match_result": "automatic"}], last_good_pull_at=now - timedelta(days=4), data_as_of=(now - timedelta(days=4)).date(), accounts_refreshed=1, accounts_total=1, is_demo=True))
    db.add(TaxAuthorityLink(company_id=CO_BLUEDUNE, status="not_available")) if db.scalar(select(TaxAuthorityLink).where(TaxAuthorityLink.company_id == CO_BLUEDUNE)) is None else None
    db.flush()
