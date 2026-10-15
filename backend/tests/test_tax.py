"""E5-S2 tax: SBR fixtures A-F, VAT fixture, blocked CT states, no-rule stop, stale, escalation triggers, vat-tp-v1."""

from __future__ import annotations

import json
from datetime import date

from sqlalchemy import select

from app.demo import CO_ALNOOR, CO_BLUEDUNE, CO_GULFTECH, CO_SAFWA, PERSONA_UUIDS
from app.modules.audit.models import AuditEvent
from app.modules.bookkeeping import service as bk
from app.modules.companies.models import CompanyRole as Role
from app.modules.tax import service as svc
from app.modules.tax.models import ESCALATED_STATUS, SCOPE_BLOCK_WORDING, EscalationRecord
from tests.conftest import sign_in

AED = 100


class FakePrincipal:
    def __init__(self, uuid, name, role, company_id, functions):
        self.identity_uuid, self.display_name, self.session_id, self.actor_key, self.staff_roles = uuid, name, "s1", "k-" + uuid, []
        self._roles = [Role(identity_uuid=uuid, company_id=company_id, role=role, functions=functions)]

    def roles_for(self, company_id):
        return self._roles

    def primary_role(self):
        return self._roles[0].role


def _ct(db, period, **kw):
    kw.setdefault("prior_revenues", [])
    calc = svc.calculate_ct(db, CO_ALNOOR, period, **kw)
    assert calc.state in ("current", "incomplete"), calc.state_reason
    return calc.outputs




def test_sbr_fixture_a(db):
    o = _ct(db, "2025-01-01_2025-12-31", accounting_profit_fils=500_000 * AED, revenue_fils=2_800_000 * AED, sbr_election="elected")
    assert o["sbr"]["indicator"] == "may be eligible" and o["sbr"]["text"] == "eligible, election needed" and o["tax_fils"] == 0
    o = _ct(db, "2025-01-01_2025-12-31", accounting_profit_fils=500_000 * AED, revenue_fils=2_800_000 * AED, sbr_election="not_elected")
    assert o["tax_fils"] == 11_250 * AED and o["band_0_fils"] == 375_000 * AED and o["band_9_fils"] == 125_000 * AED and o["rate_percent"] == 9
    assert o["sbr"]["instrument"] == "Ministerial Decision 73/2023" and o["sbr"]["review_status"] == "not reviewed" and o["sbr"]["revenue_source"]
    assert "applicable" not in json.dumps(o["sbr"]).lower() and "granted" not in json.dumps(o["sbr"]).lower()


def test_sbr_fixture_b_ending_exactly_31_dec_2026(db):
    o = _ct(db, "2026-01-01_2026-12-31", accounting_profit_fils=600_000 * AED, revenue_fils=3_000_000 * AED, sbr_election="elected")
    assert o["sbr"]["indicator"] == "may be eligible" and o["tax_fils"] == 0 and o["sbr"]["tax_if_not_elected_fils"] == 20_250 * AED
    o = _ct(db, "2026-01-01_2026-12-31", accounting_profit_fils=600_000 * AED, revenue_fils=3_000_000 * AED, sbr_election="not_elected")
    assert o["tax_fils"] == 20_250 * AED


def test_sbr_fixture_c_revenue_one_dirham_over(db):
    o = _ct(db, "2026-01-01_2026-12-31", accounting_profit_fils=600_000 * AED, revenue_fils=3_000_001 * AED, sbr_election="elected")
    assert o["sbr"]["indicator"] == "not eligible" and o["tax_fils"] == 20_250 * AED and "revenue above" in o["sbr"]["reason"]


def test_sbr_fixture_d_period_ending_after_cutoff_blocked(db):
    o = _ct(db, "2027-01-01_2027-12-31", accounting_profit_fils=450_000 * AED, revenue_fils=2_000_000 * AED, sbr_election="elected")
    assert o["sbr"]["indicator"] == "not eligible" and o["sbr"]["election_allowed"] is False and o["sbr"]["reason"] == "period ends after 31 Dec 2026"
    assert o["tax_fils"] == 6_750 * AED and o["sbr"]["cutoff_date"] == "2026-12-31"
    o = _ct(db, "2026-01-02_2027-01-01", accounting_profit_fils=450_000 * AED, revenue_fils=2_000_000 * AED)
    assert o["sbr"]["indicator"] == "not eligible" and o["sbr"]["reason"] == "period ends after 31 Dec 2026"


def test_sbr_v2_extension_is_registered_but_never_applied(db):
    from app.modules.config.models import RuleRegisterEntry

    v2 = db.scalar(select(RuleRegisterEntry).where(RuleRegisterEntry.rule_id == "sbr-v2"))
    assert v2 is not None and v2.status == "to_be_confirmed" and v2.is_current is False and v2.parameters["applicable"] is False
    assert svc.rule_lookup(db, "sbr", date(2028, 12, 31)) is None and svc.current_rule(db, "sbr").rule_id == "sbr-v1"


def test_sbr_fixture_e_prior_period_over_limit(db):
    o = _ct(db, "2026-01-01_2026-12-31", accounting_profit_fils=500_000 * AED, revenue_fils=2_500_000 * AED, prior_revenues=[3_400_000 * AED], sbr_election="elected")
    assert o["sbr"]["indicator"] == "not eligible" and "previous tax period" in o["sbr"]["reason"] and o["tax_fils"] == 11_250 * AED


def test_sbr_fixture_f_fifteen_month_first_period_flips_with_pro_rate_flag(db):
    o = _ct(db, "2025-07-01_2026-09-30", accounting_profit_fils=400_000 * AED, revenue_fils=3_200_000 * AED, pro_rate=False)
    assert o["sbr"]["indicator"] == "not eligible" and o["sbr"]["period_months"] == 15
    o = _ct(db, "2025-07-01_2026-09-30", accounting_profit_fils=400_000 * AED, revenue_fils=3_200_000 * AED, pro_rate=True)
    assert o["sbr"]["indicator"] == "may be eligible" and o["sbr"]["revenue_limit_fils"] == 3_750_000 * AED and o["sbr"]["pro_rate"] is True


def _post_ledger(db, company, rows):
    created = bk.ingest_transactions(db, company, rows, source_kind="ledger", source_system="erp_demo")
    bk.classify_pending(db, company, gate=False)
    khalid = FakePrincipal(PERSONA_UUIDS["khalid"], "Khalid Al Mansoori", "owner", company, ["all"])
    out = []
    for t in created:
        cls = db.scalar(select(bk.Classification).where(bk.Classification.txn_id == t.id))
        if cls.status == "needs_review":
            cls = bk.correct(db, company, cls.id, khalid, category="purchases" if t.direction == "out" else "sales_revenue", vat_code=t.counterparty.split("|")[-1] if "|" in (t.counterparty or "") else "SR")
        else:
            cls = bk.accept(db, company, cls.id, khalid)
        out.append(cls)
    db.flush()
    return out


def test_vat_fixture_output_input_net_and_due_date(db):
    _post_ledger(db, CO_ALNOOR, [
        {"source_id": "v1", "txn_date": "2025-02-10", "description": "Invoice INV-9001 sale", "amount_fils": 100_000 * AED, "counterparty": "Buyer A", "invoice_number": "INV-9001"},
        {"source_id": "v2", "txn_date": "2025-02-20", "description": "Purchase PO-9 supplier", "amount_fils": -40_000 * AED, "counterparty": "Supplier B", "invoice_number": "S-1"},
    ])
    calc = svc.calculate_vat(db, CO_ALNOOR, "2025-Q1")
    o = calc.outputs
    assert calc.state == "current" and o["output_vat_fils"] == 5_000 * AED and o["input_vat_fils"] == 2_000 * AED and o["net_vat_fils"] == 3_000 * AED and o["net_direction"] == "payable"
    assert calc.due_date == date(2025, 4, 28) and calc.due_date_source == "computed"
    assert calc.rule_version.startswith("vat-rate:v1") and o["label"] == "Draft, not filed, not tax advice" and o["box_mapping_label"] == "configured, pending FTA confirmation"
    line = o["lines"][0]
    assert line["tax_point_rule"] and line["tax_point_date"] and line["rate_rule"]["version"] == "v1" and line["source_documents"][0]["source_id"] == "v1" and line["review_status"] == "draft, not reviewed"
    assert o["sbr_note"] == "Small Business Relief has no effect on VAT"
    assert svc.registration_indicator(db, 400_000 * AED, date(2025, 3, 31))["must_register"] is True
    reg = svc.registration_indicator(db, 200_000 * AED, date(2025, 3, 31))
    assert reg["must_register"] is False and reg["voluntary_only"] is True


def test_vat_tp_v1_tax_point_credit_note_special_sector_missing_fx_and_dedup(db):
    rows = [
        {"source_id": "tp1", "txn_date": "2025-05-20", "description": "Invoice INV-500 sale", "amount_fils": 10_000 * AED, "counterparty": "C1", "invoice_number": "INV-500", "invoice_date": "2025-05-10", "supply_date": "2025-05-05"},
        {"source_id": "cn1", "txn_date": "2025-05-25", "description": "Invoice credit note CN-1", "amount_fils": 2_000 * AED, "counterparty": "C1", "invoice_number": "CN-1", "invoice_date": "2025-05-25", "is_credit_note": True, "original_invoice_ref": "INV-500"},
        {"source_id": "rc1", "txn_date": "2025-05-26", "description": "Purchase PO-77 import", "amount_fils": -5_000 * AED, "counterparty": "Foreign Co", "invoice_number": "F-1", "special_sector": "import"},
        {"source_id": "fx1", "txn_date": "2025-05-27", "description": "Invoice INV-501 sale", "amount_fils": 1_000 * AED, "currency": "CHF", "counterparty": "C2", "invoice_number": "INV-501"},
    ]
    _post_ledger(db, CO_ALNOOR, rows)
    # the same sale also arrives from the e-invoice provider and the bank: one VAT line, three linked sources
    einv = bk.ingest_transactions(db, CO_ALNOOR, [{"source_id": "e-500", "txn_date": "2025-05-10", "description": "Invoice INV-500 sale", "amount_fils": 10_000 * AED, "counterparty": "C1", "invoice_number": "INV-500", "invoice_date": "2025-05-10"}], source_kind="einvoice", source_system="pint_ae")
    bank = bk.ingest_transactions(db, CO_ALNOOR, [{"source_id": "b-500", "txn_date": "2025-05-03", "description": "Invoice INV-500 sale", "amount_fils": 10_000 * AED, "counterparty": "C1", "invoice_number": "INV-500"}], source_kind="bank", source_system="demo_bank")
    bk.classify_pending(db, CO_ALNOOR, gate=False)
    khalid = FakePrincipal(PERSONA_UUIDS["khalid"], "Khalid", "owner", CO_ALNOOR, ["all"])
    for t in einv + bank:
        bk.accept(db, CO_ALNOOR, db.scalar(select(bk.Classification).where(bk.Classification.txn_id == t.id)).id, khalid)
    calc = svc.calculate_vat(db, CO_ALNOOR, "2025-Q2")
    o = calc.outputs
    lines = {ln["counterparty"]: ln for ln in o["lines"]}
    inv = lines["C1"] if not lines["C1"]["credit_note"] else next(ln for ln in o["lines"] if ln["counterparty"] == "C1" and not ln["credit_note"])
    assert inv["document_of_record"] == "einvoice" and len(inv["source_documents"]) == 3 and inv["tax_point_date"] == "2025-05-03" and "bank" in inv["tax_point_rule"]
    cn = next(ln for ln in o["lines"] if ln["credit_note"])
    assert cn["tax_point_date"] == "2025-05-25" and cn["vat_fils"] < 0 and cn["original_invoice_ref"] == "INV-500" and cn["tax_point_rule"] == "credit-note issue date"
    reasons = [e["reason"] for e in calc.excluded_items]
    assert any("special sector" in r for r in reasons) and any("missing FX rate" in r for r in reasons)
    assert calc.state == "incomplete" and calc.state_reason.startswith("Excludes")
    # disagreement between e-invoice and ERP on amount -> exception, no silent winner
    bk.ingest_transactions(db, CO_ALNOOR, [{"source_id": "e-9", "txn_date": "2025-05-12", "description": "Invoice INV-900 sale", "amount_fils": 520 * AED, "counterparty": "C9", "invoice_number": "INV-900"}], source_kind="einvoice", source_system="pint_ae")
    _post_ledger(db, CO_ALNOOR, [{"source_id": "l-9", "txn_date": "2025-05-12", "description": "Invoice INV-900 sale", "amount_fils": 500 * AED, "counterparty": "C9", "invoice_number": "INV-900"}])
    bk.classify_pending(db, CO_ALNOOR, gate=False)
    for c in db.scalars(select(bk.Classification).where(bk.Classification.company_id == CO_ALNOOR, bk.Classification.status == "proposed")):
        bk.accept(db, CO_ALNOOR, c.id, khalid)
    calc = svc.calculate_vat(db, CO_ALNOOR, "2025-Q2")
    assert any("disagree" in e["reason"] for e in calc.excluded_items) and not any(ln["counterparty"] == "C9" for ln in calc.outputs["lines"])


def test_blocked_ct_for_tax_group_and_unclear_with_fixed_wording_and_escalation(client, db):
    calc = svc.latest(db, CO_SAFWA, "ct", "FY2025")
    assert calc.state == "blocked" and calc.state_reason == SCOPE_BLOCK_WORDING and calc.outputs["escalation_state"] == ESCALATED_STATUS and calc.outputs.get("tax_fils") is None
    esc = db.get(EscalationRecord, calc.escalation_ids[0])
    assert esc.trigger_id == "scope" and esc.status == ESCALATED_STATUS
    unclear = svc.calculate_ct(db, CO_GULFTECH, "FY2025")
    assert unclear.state == "blocked" and unclear.outputs["wording"] == "This company is outside the pilot's supported scope; a specialist will contact you"
    db.commit()  # never hold a write on the test session while the app session writes (SQLite lock)
    sign_in(client, "khalid")
    r = client.get(f"/api/companies/{CO_SAFWA}/tax/ct/FY2025")
    assert r.status_code == 200 and r.json()["calculation"]["state"] == "blocked" and r.json()["calculation"]["can_approve"] is False
    assert "approved" not in json.dumps(r.json()["calculation"]["outputs"]).lower()


def test_no_rule_stop_shows_no_figure_and_notifies(client, db):
    calc = svc.calculate_vat(db, CO_ALNOOR, "2017-Q1")
    assert calc.state == "no_rule_stop" and calc.outputs is None and calc.notification_ref and calc.notification_sent_at
    assert db.scalar(select(AuditEvent).where(AuditEvent.event_type == "NO_RULE_STOP", AuditEvent.subject_id == calc.id)) is not None
    ct = svc.calculate_ct(db, CO_ALNOOR, "2022-01-01_2022-12-31")
    assert ct.state == "no_rule_stop"
    db.commit()
    sign_in(client, "khalid")
    body = client.get(f"/api/companies/{CO_ALNOOR}/tax/vat/2017-Q1").json()["calculation"]
    assert body["outputs"] is None and body["what_we_have"]["confirmed_transactions"] == 0 and body["notification_ref"] == calc.notification_ref and body["can_approve"] is False


def test_demo_vat_result_stale_after_transactions_change_and_mark_reviewed(client, db):
    sign_in(client, "khalid")
    body = client.get(f"/api/companies/{CO_ALNOOR}/tax/vat/2026-Q2").json()
    c = body["calculation"]
    assert c["state"] == "current" and c["ai_label"] == "AI-prepared calculation. Status: not reviewed" and c["rule_refs"]["vat-rate"]["instrument"]
    assert c["comparison"]["text"] == "Same result under current rules." and c["outputs"]["lines"]
    r = client.post(f"/api/companies/{CO_ALNOOR}/tax/vat/2026-Q2/mark-reviewed")
    assert r.status_code == 200 and r.json()["review_status"] == "reviewed" and r.json()["reviewed_by"]["role"] == "owner"
    _post_ledger(db, CO_ALNOOR, [{"source_id": "st-1", "txn_date": "2026-05-15", "description": "Invoice INV-77 sale", "amount_fils": 1_000 * AED, "counterparty": "New"}])
    db.commit()
    c = client.get(f"/api/companies/{CO_ALNOOR}/tax/vat/2026-Q2").json()["calculation"]
    assert c["state"] == "stale" and c["review_status"] == "not_reviewed" and c["can_approve"] is False
    assert client.post(f"/api/companies/{CO_ALNOOR}/tax/vat/2026-Q2/mark-reviewed").status_code == 409
    r = client.post(f"/api/companies/{CO_ALNOOR}/tax/vat/2026-Q2")
    assert r.status_code == 200 and r.json()["version"] == c["version"] + 1 and r.json()["state"] == "current"
    assert len(client.get(f"/api/companies/{CO_ALNOOR}/tax/vat/2026-Q2/versions").json()) == c["version"] + 1  # old versions kept


def test_incomplete_result_excludes_needs_review_items(client):
    sign_in(client, "khalid")
    r = client.post(f"/api/companies/{CO_ALNOOR}/tax/vat/2026-Q3")
    c = r.json()
    assert c["state"] == "incomplete" and c["excluded_count"] >= 1 and c["approval_disabled_reason"] == "Approval is off until all items are reviewed." and c["state_reason"].startswith("Excludes")
    assert all({"date", "description", "aed_amount_fils", "reason"} <= set(e) for e in c["excluded_items"])


def test_escalation_triggers_1_to_4_and_related_party_held(db):
    o = _ct(db, "2025-01-01_2025-12-31", accounting_profit_fils=500_000 * AED, revenue_fils=2_800_000 * AED, adjustments=[{"kind": "non_business", "label": "Owner car", "amount_fils": 60_000 * AED, "reason": "personal use"}])
    assert "2" in {e["trigger_id"] for e in o["escalations"]} and o["escalation_state"] == ESCALATED_STATUS
    o = _ct(db, "2025-01-01_2025-12-31", accounting_profit_fils=500_000 * AED, revenue_fils=2_800_000 * AED, adjustments=[{"kind": "related_party", "label": "Management fee to parent", "amount_fils": 10_000 * AED, "reason": "intra-group", "related_party": True}])
    rp = o["flagged_items"][0]
    assert rp["held_for_specialist"] is True and rp["class"] == "flagged" and "1" in {e["trigger_id"] for e in o["escalations"]}
    assert "3" in {e["trigger_id"] for e in o["escalations"]}  # tax payable moved >10% against the previous version
    o = _ct(db, "2025-01-01_2025-12-31", accounting_profit_fils=800_000 * AED, revenue_fils=50_000_000 * AED)
    assert "4" in {e["trigger_id"] for e in o["escalations"]} and o["audit_required"]["required"] is False
    assert all(e["status"] == ESCALATED_STATUS for e in o["escalations"]) and "approved" not in json.dumps(o["escalations"])


def test_loss_carry_forward_capped_at_75_percent(db):
    o = _ct(db, "2025-01-01_2025-12-31", accounting_profit_fils=400_000 * AED, revenue_fils=1_000_000 * AED, loss_cf_fils=900_000 * AED, sbr_election="not_elected")
    assert o["loss_carry_forward"]["applied_fils"] == 300_000 * AED and o["taxable_income_fils"] == 100_000 * AED and o["tax_fils"] == 0


def test_adjustment_needs_reason_and_api_read_only_variants(client, db):
    sign_in(client, "khalid")
    r = client.post(f"/api/companies/{CO_ALNOOR}/tax/ct/FY2025/adjustments", json={"kind": "non_deductible", "label": "Fines", "amount_fils": 500 * AED, "reason": ""})
    assert r.status_code == 422 and r.json()["error"] == "REASON_REQUIRED"
    r = client.post(f"/api/companies/{CO_ALNOOR}/tax/ct/FY2025/adjustments", json={"kind": "non_deductible", "label": "Fines", "amount_fils": 500 * AED, "reason": "traffic fines"})
    assert r.status_code == 200 and r.json()["class"] == "flagged" and r.json()["held_for_specialist"] is True
    c = client.post(f"/api/companies/{CO_ALNOOR}/tax/ct/FY2025").json()
    assert c["outputs"]["sbr"]["indicator"] == "may be eligible" and any(a["kind"] == "non_deductible" for a in c["outputs"]["adjustments"])
    assert "Tax Agent" not in json.dumps(c)
    client.cookies.clear()
    sign_in(client, "priya")
    body = client.get(f"/api/companies/{CO_BLUEDUNE}/tax/vat/2026-Q3").json()
    assert body["role"] == "remote_owner" and body["calculation"] is None and body["empty"] == "add_trn"
    client.cookies.clear()
    sign_in(client, "omar")
    r = client.post(f"/api/companies/{CO_GULFTECH}/tax/vat/2026-Q3")
    assert r.status_code == 403 and r.json()["error"] == "NO_FUNCTION"
    body = client.get(f"/api/companies/{CO_GULFTECH}/tax/vat/2026-Q3").json()
    assert body["view_only_reason"] == "You can view this calculation. You do not have the tax-preparation function."
    client.cookies.clear()
    sign_in(client, "hassan")
    r = client.get("/api/tax/escalations")
    assert r.status_code == 200 and any(e["trigger_id"] == "scope" for e in r.json())


def test_rule_lookup_uses_version_effective_on_period_end(db):
    from app.modules.config.service import register_rule_version

    register_rule_version(db, "ct-rate-v1", "Corporate tax rate and threshold", version="v2", instrument="hypothetical later instrument (test)", effective_from=date(2030, 1, 1), status="provisional", parameters={"rate_percent": 10, "threshold_fils": 375_000 * AED, "applies_from": "2023-06-01"})
    used = svc.rule_lookup(db, "ct-rate", date(2025, 12, 31))
    assert used.version == "v1" and svc.current_rule(db, "ct-rate").version == "v2"
    o = _ct(db, "2025-01-01_2025-12-31", accounting_profit_fils=500_000 * AED, revenue_fils=2_800_000 * AED, sbr_election="not_elected")
    assert o["rate_percent"] == 9
    calc = svc.latest(db, CO_ALNOOR, "ct", "2025-01-01_2025-12-31")
    assert calc.current_rule_version == "ct-rate:v2" and "ct-rate:v1" in calc.rule_version
    cmp_ = svc.comparison(db, calc)
    assert cmp_["same"] is False and cmp_["difference_fils"] == 1_250 * AED and cmp_["word"] == "higher by" and cmp_["text"].startswith("The earlier figure")
