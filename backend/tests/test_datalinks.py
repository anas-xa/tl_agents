"""E4-S3..S6: manual uploads, route readiness, ERP register, tax profile and link, freshness and K27 windows."""

from __future__ import annotations

import io
import zipfile
from datetime import timedelta

import pytest
from sqlalchemy import func, select

from app.core.time import utcnow
from app.modules.audit.models import AuditEvent
from app.modules.config.service import set_config
from app.modules.datalinks import parsing
from app.modules.datalinks import service as dsvc
from app.modules.datalinks.models import StatementLine, StatementUpload
from app.modules.datalinks.strings import STRINGS as DL_STRINGS
from tests.conftest import sign_in

ALNOOR = "co_alnoor"


@pytest.fixture(autouse=True)
def _clear_gate_cache():
    from app.modules.consent.service import invalidate_gate

    invalidate_gate()
    yield


CSV = """التاريخ,البيان,المبلغ,الرصيد,العملة
2026-09-01,إيجار المكتب - إيجاري Business Bay,-12000.00,"88,000.00",AED
02/09/2026,DEWA bill / فاتورة ديوا,"-1,250.75",86749.25,AED
2026-09-03,Customer receipt INV-0201 شركة النخيل,"‏١٥٬٠٠٠٫٠٠",101749.25,AED
2026-09-04,Bank charges,-105,101644.25,AED
2026-09-05,WPS salaries / رواتب,-30000,71644.25,AED
"""


def _upload(client, data: bytes, name="statement.csv", **fields):
    form = {"kind": "bank_statement", "bank_id": "demo_bank", "bank_name": "Demo Bank (fixture)", "account_ref": "AE07DEMO0000000001234", "purpose": "bookkeeping_classification", "notice_acknowledged": "true"}
    form.update({k: str(v) for k, v in fields.items()})
    return client.post(f"/api/companies/{ALNOOR}/uploads", files={"file": (name, data, "application/octet-stream")}, data=form)


def _events(db, event_type, reason=None):
    stmt = select(AuditEvent).where(AuditEvent.event_type == event_type)
    if reason:
        stmt = stmt.where(AuditEvent.reason_code == reason)
    return list(db.scalars(stmt))


# --- uploads ------------------------------------------------------------------------------------------------


def test_csv_upload_ready_manual_unverified_with_normalisation(client, db):
    sign_in(client, "khalid")
    r = _upload(client, CSV.encode("utf-8"), name="sept.csv")
    assert r.status_code == 201, r.text
    up = r.json()
    assert up["status"] == "ready" and up["label"] == "manual, unverified" and up["declaration_id"] and up["notice_acknowledged_at"]
    assert up["rows_total"] == 5 and up["rows_accepted"] == 5 and up["rows_rejected"] == 0 and up["encoding_detected"] == "UTF-8"
    assert up["account_masked"] == "•••• 1234" and up["malware_scan_result"] == "clean_stub" and up["authorisation_consent_id"]
    lines = client.get(f"/api/companies/{ALNOOR}/uploads/{up['upload_id']}/lines").json()["lines"]
    assert [ln["amount_fils"] for ln in lines] == [-1200000, -125075, 1500000, -10500, -3000000]
    assert lines[1]["txn_date"] == "2026-09-02" and lines[0]["language_class"] == "mixed" and lines[3]["language_class"] == "latin"
    assert "‏" not in lines[2]["description"] and "١٥" not in str(lines[2]["amount_fils"])
    assert all(ln["label"] == "manual, unverified" for ln in lines)
    row = db.scalar(select(StatementLine).where(StatementLine.upload_id == up["upload_id"], StatementLine.line_no == 4))
    assert row.description_normalised == "Customer receipt INV-0201 شركة النخيل" and row.currency == "AED" and row.balance_fils == 10174925
    assert _events(db, "UPLOAD_STORED")
    listing = client.get(f"/api/companies/{ALNOOR}/uploads").json()
    assert listing["limits"]["max_size_mb"] == 20 and listing["limits"]["max_rows"] == 50000 and listing["limits"]["invalid_row_threshold_percent"] == 20
    assert listing["manual_data_age"]["badge"] in ("neutral", "update_due") and listing["label"].lower() == "manual, unverified"
    assert "verified" not in listing["strings"]["upload.you_uploaded"].replace("unverified", "")


def test_upload_without_notice_record_is_quarantined(client, db):
    sign_in(client, "khalid")
    r = _upload(client, CSV.encode("utf-8"), notice_acknowledged="false")
    assert r.status_code == 201
    up = r.json()
    assert up["status"] == "quarantined" and up["quarantine_reason"] == "no_notice_record" and up["declaration_id"] is None
    assert db.scalar(select(func.count(StatementLine.id)).where(StatementLine.upload_id == up["upload_id"])) == 0
    r2 = _upload(client, CSV.encode("utf-8"), purpose="marketing")
    assert r2.json()["status"] == "quarantined"
    assert _events(db, "UPLOAD_QUARANTINED", "NO_NOTICE_RECORD")


def test_upload_validation_rules(client, db):
    sign_in(client, "khalid")
    assert _upload(client, b"MZ...", name="virus.exe").json()["rejection_cause"] == "wrong_type"
    set_config(db, "datalinks.upload.max_size_mb", 0, changed_by="test")
    db.commit()
    assert _upload(client, CSV.encode(), name="big.csv").json()["rejection_cause"] == "over_size_limit"
    set_config(db, "datalinks.upload.max_size_mb", 20, changed_by="test")
    db.commit()
    assert _upload(client, b"foo,bar\n1,2\n", name="odd.csv").json()["rejection_cause"] == "unknown_header"
    bad = "Date,Description,Amount\n2026-09-01,ok,10\nnot-a-date,x,10\nnot-a-date,y,10\n"
    r = _upload(client, bad.encode(), name="bad.csv").json()
    assert r["status"] == "rejected" and r["rejection_cause"] == "too_many_invalid_rows" and r["rows_rejected"] == 2
    assert r["rejection_report"][0]["message_ar"] and any(x.get("line_no") == 3 for x in r["rejection_report"])
    assert db.scalar(select(func.count(StatementLine.id)).where(StatementLine.upload_id == r["upload_id"])) == 0
    eicar = b"X5O!P%@AP[4\\PZX54(P^)7CC)7}$EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*"
    q = _upload(client, b"Date,Description,Amount\n" + eicar, name="scan.csv").json()
    assert q["status"] == "quarantined" and q["quarantine_reason"] == "failed_security_check"
    enc = b"%PDF-1.7\n1 0 obj << /Encrypt 2 0 R >> endobj\n"
    assert _upload(client, enc, name="locked.pdf").json()["rejection_cause"] == "password_protected"
    img = b"%PDF-1.7\n1 0 obj << /Type /XObject /Subtype /Image >> endobj\n"
    assert _upload(client, img, name="scan.pdf").json()["rejection_cause"] == "image_only"
    set_config(db, "datalinks.upload.max_rows", 2, changed_by="test")
    db.commit()
    assert _upload(client, CSV.encode(), name="rows.csv").json()["rejection_cause"] == "too_many_rows"
    assert _events(db, "UPLOAD_REJECTED", "WRONG_TYPE")


def test_duplicate_rows_skipped_on_re_upload(client, db):
    sign_in(client, "khalid")
    first = _upload(client, CSV.encode(), name="a.csv").json()
    second = _upload(client, CSV.encode(), name="b.csv").json()
    assert first["rows_accepted"] == 5 and second["status"] == "ready" and second["rows_accepted"] == 0 and second["rows_skipped_duplicate"] == 5
    # same key with a second occurrence index is kept (two identical salary lines are both real)
    twice = "Date,Description,Amount\n2026-09-05,WPS salaries / رواتب,-30000\n2026-09-05,WPS salaries / رواتب,-30000\n"
    third = _upload(client, twice.encode(), name="c.csv").json()
    assert third["rows_accepted"] == 1 and third["rows_skipped_duplicate"] == 1


def test_xlsx_upload_parsed_without_dependencies(client):
    sign_in(client, "khalid")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("[Content_Types].xml", "<Types/>")
        zf.writestr("xl/sharedStrings.xml", '<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><si><t>Date</t></si><si><t>Description</t></si><si><t>Amount</t></si><si><t>DEWA / ديوا</t></si></sst>')
        zf.writestr("xl/worksheets/sheet1.xml", '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData><row r="1"><c r="A1" t="s"><v>0</v></c><c r="B1" t="s"><v>1</v></c><c r="C1" t="s"><v>2</v></c></row><row r="2"><c r="A2"><v>46235</v></c><c r="B2" t="s"><v>3</v></c><c r="C2"><v>-99.5</v></c></row><row r="3"><c r="A3" t="inlineStr"><is><t>2026-08-02</t></is></c><c r="B3" t="inlineStr"><is><t>Rent</t></is></c><c r="C3"><v>1200</v></c></row></sheetData></worksheet>')
    r = _upload(client, buf.getvalue(), name="book.xlsx")
    assert r.status_code == 201, r.text
    up = r.json()
    assert up["status"] == "ready" and up["rows_accepted"] == 2 and up["file_type"] == "xlsx"
    lines = client.get(f"/api/companies/{ALNOOR}/uploads/{up['upload_id']}/lines").json()["lines"]
    assert lines[0]["txn_date"] == "2026-08-01" and lines[0]["amount_fils"] == -9950 and lines[1]["amount_fils"] == 120000


def test_delegate_upload_rights_and_owner_only_delete(client, db):
    sign_in(client, "omar")
    r = _upload(client, CSV.encode(), name="omar.csv")
    assert r.status_code == 201 and r.json()["status"] == "ready" and r.json()["uploader_role"] == "delegate"
    gt = client.post("/api/companies/co_gulftech/uploads", files={"file": ("x.csv", CSV.encode(), "text/csv")}, data={"purpose": "bookkeeping_classification", "notice_acknowledged": "true"})
    assert gt.status_code == 403 and gt.json()["error"] == "DELEGATE_FUNCTION_NOT_ASSIGNED"
    assert client.delete(f"/api/companies/{ALNOOR}/uploads/{r.json()['upload_id']}").status_code == 403
    sign_in(client, "khalid")
    d = client.delete(f"/api/companies/{ALNOOR}/uploads/{r.json()['upload_id']}")
    assert d.status_code == 200 and d.json()["status"] == "deleted"
    assert db.scalar(select(func.count(StatementLine.id)).where(StatementLine.upload_id == r.json()["upload_id"])) == 0
    assert _events(db, "UPLOAD_BATCH_DELETED")
    sign_in(client, "layla")
    assert client.get(f"/api/companies/{ALNOOR}/uploads").status_code == 403


def test_statement_lines_readable_by_tax_module_from_demo(db):
    rows = list(db.scalars(select(StatementLine).where(StatementLine.company_id == ALNOOR)))
    assert len(rows) >= 24 and {r.language_class for r in rows} >= {"mixed"}
    assert all(isinstance(r.amount_fils, int) and r.dedupe_key and r.data_use_flag == "active" for r in rows)
    up = db.scalar(select(StatementUpload).where(StatementUpload.company_id == ALNOOR, StatementUpload.kind == "bank_statement", StatementUpload.is_demo.is_(True)))
    assert up.status == "ready" and up.label == "manual, unverified" and up.declaration_id and up.authorisation_consent_id
    assert dsvc.manual_data_age(db, ALNOOR)["badge"] == "update_due"


# --- bank route (E4-S3) and ERP register (E4-S4) ------------------------------------------------------------


def test_bank_route_not_live_refuses_link_and_pulls(client, db):
    sign_in(client, "khalid")
    links = client.get(f"/api/companies/{ALNOOR}/links").json()
    assert links["route"]["route_holder"] == "licensed_provider_partner" and links["route"]["coverage_confirmed"] is False and links["route"]["bank_link_allowed"] is False
    assert all(b["availability"] == "not_yet_available" for b in links["banks"]) and any(b["demo"] for b in links["banks"])
    r = client.post(f"/api/companies/{ALNOOR}/links/bank", json={"bank_id": "demo_bank"})
    assert r.status_code == 403 and r.json()["error"] == "NO_LICENSED_BANK_ROUTE" and r.json()["details"]["upload_instead"]
    assert _events(db, "BANK_LINK_REFUSED")
    sched = client.post(f"/api/companies/{ALNOOR}/links/pulls/schedule")
    assert sched.status_code == 403 and sched.json()["error"] == "FEATURE_SWITCHED_OFF"
    assert client.post(f"/api/companies/{ALNOOR}/links/x/refresh").json()["error"] == "FEATURE_SWITCHED_OFF"
    nm = client.post(f"/api/companies/{ALNOOR}/links/bank/enbd/notify-me")
    assert nm.status_code == 200 and nm.json()["note"] == "preference, not consent"
    # switch on with evidence still incomplete: still refused (fail closed on the register, not just the switch)
    set_config(db, "datalinks.openfinance.enabled", True, changed_by="test")
    db.commit()
    assert client.post(f"/api/companies/{ALNOOR}/links/bank", json={"bank_id": "demo_bank"}).json()["error"] == "NO_LICENSED_BANK_ROUTE"


def test_erp_register_empty_connect_refused_file_route_on(client, db):
    sign_in(client, "khalid")
    erp = client.get(f"/api/companies/{ALNOOR}/links/erp").json()
    reg = erp["register"]
    assert reg["supported_systems"] == [] and reg["file_upload_enabled"] is True and len(reg["preconditions"]) == 3
    assert all(v is False for v in reg["vendor_flags"].values()) and reg["remote_owner_can_connect"] is False
    r = client.post(f"/api/companies/{ALNOOR}/links/erp", json={"system_type": "zoho_books"})
    assert r.status_code == 403 and r.json()["error"] == "CONNECTOR_NOT_AVAILABLE"
    set_config(db, "datalinks.erp.supported_systems", ["zoho_books"], changed_by="test")
    db.commit()
    assert client.post(f"/api/companies/{ALNOOR}/links/erp", json={"system_type": "zoho_books"}).json()["error"] == "FEATURE_SWITCHED_OFF"
    tb = "Account code,Account name,Debit,Credit\n1000,Cash,100.00,\n4000,Sales,,100.00\n7777,Unknown thing,5.00,\n"
    up = client.post(f"/api/companies/{ALNOOR}/uploads", files={"file": ("tb.csv", tb.encode(), "text/csv")}, data={"kind": "erp_export", "export_type": "trial_balance", "purpose": "bookkeeping_classification", "notice_acknowledged": "true", "period_start": "2026-07-01", "period_end": "2026-09-30"}).json()
    assert up["status"] == "ready" and up["kind"] == "erp_export" and up["rows_accepted"] == 3
    erp = client.get(f"/api/companies/{ALNOOR}/links/erp").json()
    link = next(ln for ln in erp["links"] if ln["link_type"] == "manual upload")
    run = link["runs"][0]
    assert run["result"] == "partial" and "7777" in run["needs_mapping"] and run["validation_findings"][0]["check"] == "debits_equal_credits"
    assert run["validation_findings"][0]["status"] == "open_q63" and link["refresh_window_hours"] is None
    sign_in(client, "priya")
    assert client.post("/api/companies/co_bluedune/links/erp", json={"system_type": "zoho_books"}).status_code == 403


# --- tax profile and link (E4-S5) -------------------------------------------------------------------------------


def test_tax_profile_source_flags_due_dates_and_validation(client, db):
    sign_in(client, "khalid")
    body = {"tax_type": "vat", "trn": "100123456789012", "registration_status": "registered", "tax_period_start": "2026-07-01", "tax_period_end": "2026-09-30", "filing_frequency": "quarterly"}
    r = client.put(f"/api/companies/{ALNOOR}/tax-profile", json=body)
    assert r.status_code == 200, r.text
    p = r.json()
    assert p["source"] == "company_provided" and p["verification_tag"] == "unverified" and p["not_confirmed_by_authority"] and p["source_label"] == "Entered by hand"
    assert p["due_dates"][0] == {"period_end": "2026-09-30", "due_date": "2026-10-28", "source": "computed", "rule": "vat-due-v1"} and p["due_date_source"] == "computed"
    assert p["entered_by"] == "Khalid Al Mansoori" and p["as_of"] and p["k7k8_measurable"] is False and p["version"] >= 2
    assert client.put(f"/api/companies/{ALNOOR}/tax-profile", json={**body, "trn": "12345"}).status_code == 422
    assert client.put(f"/api/companies/{ALNOOR}/tax-profile", json={**body, "filing_frequency": "weekly"}).status_code == 422
    assert client.put(f"/api/companies/{ALNOOR}/tax-profile", json={**body, "tax_period_end": "2026-01-01"}).status_code == 422
    assert client.put(f"/api/companies/{ALNOOR}/tax-profile", json={**body, "source": "document_confirmed"}).status_code == 422
    assert client.put(f"/api/companies/{ALNOOR}/tax-profile", json={**body, "source": "fta_live"}).status_code == 422
    assert client.put(f"/api/companies/{ALNOOR}/tax-profile", json={**body, "small_business_relief": [{"period_end": "2026-12-31", "indicator": "claimed", "source": "fta_confirmed"}]}).status_code == 422
    ok = client.put(f"/api/companies/{ALNOOR}/tax-profile", json={**body, "source": "document_confirmed", "receipt_upload_ref": "doc_emaratax_ack_1", "filed_date": "2026-10-20", "filing_status": "submitted (as provided by the company)"}).json()
    assert ok["k7k8_measurable"] is True and ok["source_label"].endswith("(manual evidence)")
    ct = client.put(f"/api/companies/{ALNOOR}/tax-profile", json={"tax_type": "corporate_tax", "trn": "100123456789013", "tax_period_end": "2026-12-31", "small_business_relief": [{"period_end": "2026-12-31", "indicator": "unknown", "source": "owner_declared"}]}).json()
    assert ct["due_dates"][0]["due_date"] == "2027-09-28" and ct["small_business_relief"][0]["source"] == "owner_declared"
    prof = client.get(f"/api/companies/{ALNOOR}/tax-profile").json()
    assert {p["tax_type"] for p in prof["profiles"]} == {"vat", "corporate_tax"} and prof["rules"]["sbr_period_cutoff"] == "2026-12-31"
    assert _events(db, "TAX_PROFILE_ENTERED")
    # duplicate TRN on another company is held, not accepted
    assert client.put("/api/companies/co_safwa/tax-profile", json={"tax_type": "vat", "trn": "100123456789012"}).status_code == 409


def test_remote_owner_enters_company_provided_data_but_no_consent_control(client):
    sign_in(client, "priya")
    r = client.put("/api/companies/co_bluedune/tax-profile", json={"tax_type": "vat", "trn": "100999999999999", "tax_period_end": "2026-09-30", "filing_frequency": "quarterly"})
    assert r.status_code == 200 and r.json()["source"] == "company_provided" and r.json()["entered_by_role"] == "remote_owner"
    tl = client.get("/api/companies/co_bluedune/tax-link").json()
    assert tl["remote_owner"] is True and tl["remote_owner_consent_online"] is False and tl["remote_owner_status_text"] == "company-provided data only; no live FTA link"
    assert tl["status"] == "manual_unverified" and tl["switch_on"] is False
    assert client.post("/api/companies/co_bluedune/links/bank", json={"bank_id": "demo_bank"}).status_code == 403, "owner abroad: read-only link status"


def test_tax_link_states_adapter_off_and_fixtures(client, db):
    sign_in(client, "khalid")
    tl = client.get(f"/api/companies/{ALNOOR}/tax-link").json()
    assert tl["status"] == "manual_unverified" and tl["switch_on"] is False and len(tl["profiles"]) == 2
    assert tl["strings"]["not_available"].startswith("We cannot read your tax record") and tl["credential_policy"].startswith("The platform never holds EmaraTax credentials")
    assert tl["strings"]["cause"]["authority_not_responding"] == "The authority service is not responding"
    r = client.post(f"/api/companies/{ALNOOR}/tax-link/start", json={})
    assert r.status_code == 403 and r.json()["error"] == "FEATURE_SWITCHED_OFF" and _events(db, "TAX_LINK_REFUSED")
    sign_in(client, "omar")
    gt = client.get("/api/companies/co_gulftech/tax-link").json()
    assert gt["status"] == "error" and gt["demo_data"] is True and gt["error_cause"] == "authority_not_responding" and gt["last_good_read_at"]
    assert client.put("/api/companies/co_gulftech/tax-profile", json={"tax_type": "vat", "trn": "100111111111111"}).json()["error"] == "DELEGATE_FUNCTION_NOT_ASSIGNED"
    assert client.put(f"/api/companies/{ALNOOR}/tax-profile", json={"tax_type": "vat", "trn": "100111111111111"}).status_code == 200


# --- freshness, badges and K27 (E4-S6) ------------------------------------------------------------------------


def test_k27_windows_seeded_per_source(db):
    w = dsvc.k27_windows(db)
    assert (w["bank"]["expected_interval_h"], w["bank"]["tolerance_h"], w["bank"]["stale_after_h"]) == (24, 6, 48)
    for src in ("det", "fta", "erp"):
        assert (w[src]["expected_interval_h"], w[src]["tolerance_h"], w[src]["stale_after_h"]) == (24, 6, 72)
    assert (w["e_invoice"]["expected_interval_h"], w["e_invoice"]["tolerance_h"], w["e_invoice"]["stale_after_h"]) == (1, 1, 24)


def test_freshness_state_and_badge_precedence():
    now = utcnow()
    win = {"expected_interval_h": 24, "tolerance_h": 6, "stale_after_h": 30}
    assert dsvc.freshness_state(now - timedelta(hours=20), win, now=now)["state"] == "fresh"
    assert dsvc.freshness_state(now - timedelta(hours=28), win, now=now)["state"] == "fresh", "within expected + tolerance"
    assert dsvc.freshness_state(now - timedelta(hours=31), win, now=now)["state"] == "stale"
    assert dsvc.freshness_state(now - timedelta(hours=40), {**win, "stale_after_h": 48}, now=now)["state"] == "late"
    assert dsvc.freshness_state(now - timedelta(hours=1), win, now=now, consent_ok=False) == {"state": "no_consent", "age_hours": None, "reason": "consent"}
    assert dsvc.freshness_state(None, win, now=now)["reason"] == "never_refreshed"
    # a weekend or Eid window counts as plain elapsed time (Q78)
    assert dsvc.freshness_state(now - timedelta(days=3), win, now=now)["state"] == "stale"
    kw = dict(connecting_since=None, last_check_at=None, accounts_refreshed=None, accounts_total=None, now=now)
    assert dsvc.resolve_badge(link_status="active", consent_status="withdrawn_on_platform", freshness="fresh", **kw) == "consent_withdrawn"
    assert dsvc.resolve_badge(link_status="active", consent_status="expired", freshness="fresh", **kw) == "consent_expired"
    assert dsvc.resolve_badge(link_status="error", consent_status="active", freshness="fresh", **kw) == "failed"
    assert dsvc.resolve_badge(link_status="active", consent_status="active", freshness="stale", **kw) == "stale"
    assert dsvc.resolve_badge(link_status="active", consent_status="active", freshness="fresh", **{**kw, "last_check_at": now - timedelta(hours=7)}) == "status_check_delayed"
    assert dsvc.resolve_badge(link_status="active", consent_status="active", freshness="fresh", **{**kw, "accounts_refreshed": 1, "accounts_total": 2}) == "partial"
    assert dsvc.resolve_badge(link_status="connecting", consent_status="active", freshness="fresh", **kw) == "connecting"
    assert dsvc.resolve_badge(link_status="not_yet_available", consent_status=None, freshness="no_consent", **kw) == "not_available_yet"
    assert dsvc.resolve_badge(link_status="active", consent_status="active", freshness="late", **kw) == "active"
    assert dsvc.BADGE_ORDER == ["failed", "consent_expired", "consent_withdrawn", "stale", "status_check_delayed", "partial", "connecting", "not_available_yet", "active"]


def test_links_view_sorted_worst_first_with_manual_line_and_masked_accounts(client, db):
    sign_in(client, "khalid")
    out = client.get(f"/api/companies/{ALNOOR}/links").json()
    badges = [r["badge"] for r in out["rows"]]
    assert badges == sorted(badges, key=dsvc.BADGE_ORDER.index)
    bank = next(r for r in out["rows"] if r["source_type"] == "bank")
    assert bank["badge"] == "connecting" and bank["masked_account"] == "•••• 1234" and bank["excluded_from_k27"]
    assert bank["still_connecting"] is True and out["connecting_timeout_minutes"] == 15
    tax = next(r for r in out["rows"] if r["source_type"] == "tax_authority")
    assert tax["badge"] == "not_available_yet" and tax["next_step"] == "enter_manually" and len(tax["manual_entries"]) == 2
    det = next(r for r in out["rows"] if r["source_type"] == "det")
    assert det["badge"] == "active" and det["freshness"]["state"] == "fresh"
    ml = out["manual_uploads_line"]
    assert ml["label"] == "manual, unverified" and ml["badge"] == "update_due" and ml["state"] == "stale" and ml["count"] >= 2
    assert out["k27"]["connector_line"]["denominator"] >= 1 and out["k27"]["uploaded_line"] == {"numerator": 0, "denominator": 1}
    assert out["k27"]["window_calendar_mode"] == "plain_elapsed" and out["remote_owner_read_only"] is False
    assert _events(db, "LINK_STATUS_VIEWED")
    # Arabic names for the sources
    ar = client.get(f"/api/companies/{ALNOOR}/links?lang=ar").json()
    assert any("الهيئة" in r["source_name"] for r in ar["rows"])


def test_blue_dune_withdrawn_consent_overrides_active_link(client, db):
    sign_in(client, "priya")
    out = client.get("/api/companies/co_bluedune/links").json()
    bank = next(r for r in out["rows"] if r["source_type"] == "bank")
    assert bank["badge"] == "consent_withdrawn" and bank["reason_line"] == "no_data_is_being_read" and bank["next_step"] == "open_consent_centre" and bank["is_demo"]
    assert out["rows"][0]["source_type"] == "bank", "worst first"
    assert out["remote_owner_read_only"] is True and bank["link_id"] in out["needs_attention"]
    assert out["k27"]["excluded_counts"]["consent_withdrawn"] == 1


def test_staff_technical_detail_logged_and_aggregates(client, db):
    sign_in(client, "yusuf")
    r = client.get(f"/api/companies/{ALNOOR}/links/bank-route/technical-detail")
    assert r.status_code == 200 and _events(db, "LINK_TECHNICAL_DETAIL_OPENED")
    sign_in(client, "khalid")
    assert client.get(f"/api/companies/{ALNOOR}/links/bank-route/technical-detail").status_code == 403
    sign_in(client, "sara")
    agg = client.get("/api/datalinks/k27").json()
    assert agg["companies"] == 4 and agg["k11_headline"] == "Not yet measurable: bank route not available" and agg["manual_statement_on_file"] >= 1
    sign_in(client, "lina")
    reg = client.get("/api/datalinks/route-register").json()
    assert reg["register"]["route_holder"] == "licensed_provider_partner" and reg["register"]["coverage_confirmed"] is False


def test_parsing_helpers_and_strings():
    assert parsing.parse_amount("(1,234.56)") == -123456 and parsing.parse_amount("١٬٢٣٤٫٥٠") == 123450 and parsing.parse_amount("1.234,56") == 123456
    assert parsing.parse_amount("abc") is None and parsing.parse_amount("") is None
    assert parsing.normalise_text("‏تاريخ ١٢") == "تاريخ 12" and parsing.language_class("DEWA / ديوا") == "mixed"
    assert parsing.parse_date("15/03/2027").isoformat() == "2027-03-15" and parsing.parse_date("15 Mar 2027").isoformat() == "2027-03-15"
    for key, item in DL_STRINGS.items():
        assert item["en"].strip() and item["ar"].strip(), key
        assert "verified by the fta" not in item["en"].lower() and "live fta status" not in item["en"].lower() and "tax agent" not in item["en"].lower()
    assert DL_STRINGS["upload.label"]["ar"] == "يدوي، غير موثّق"
