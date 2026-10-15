"""E5-S1 bookkeeping: classification routing, review/correction, undo, quarantine, K14, K15, K17, intake rules."""

from __future__ import annotations

import hashlib
import json
from datetime import date

from sqlalchemy import select

from app.demo import CO_ALNOOR, CO_BLUEDUNE, CO_GULFTECH, PERSONA_UUIDS
from app.modules.audit.models import AuditEvent
from app.modules.bookkeeping import service as svc
from app.modules.bookkeeping.models import Classification, ReviewerLabel, ReviewRecord, Transaction
from app.modules.companies.models import CompanyRole as Role
from app.modules.config.service import set_config
from tests.conftest import sign_in

TX = f"/api/companies/{CO_ALNOOR}/transactions"


class FakePrincipal:
    def __init__(self, uuid: str, name: str, role: str, company_id: str, functions: list[str], session_id: str = "s1"):
        self.identity_uuid, self.display_name, self.session_id, self.actor_key, self.staff_roles = uuid, name, session_id, "key-" + uuid, []
        self._roles = [Role(identity_uuid=uuid, company_id=company_id, role=role, functions=functions)]

    def roles_for(self, company_id):
        return self._roles

    def primary_role(self):
        return self._roles[0].role


def _rows(client, company=CO_ALNOOR, **params):
    r = client.get(f"/api/companies/{company}/transactions", params=params)
    assert r.status_code == 200, r.text
    return r.json()


def test_queue_rows_are_ai_labelled_with_fixed_rule_routing_and_no_confidence(client):
    sign_in(client, "khalid")
    body = _rows(client)
    assert body["view"] == "full" and body["rows"]
    statuses = {r["status"] for r in body["rows"]}
    assert {"proposed", "needs_review", "posted"} <= statuses
    for row in body["rows"]:
        assert row["ai_generated"] is True and row["ai_label"] == "AI-prepared, draft. Please check before posting."
        assert "confidence" not in json.dumps(row) and "sample_flag" not in row
        if row["status"] == "needs_review":
            assert row["review_reason"] == "Needs review: no basis found"
    injected = [r for r in body["rows"] if r["treated_as_data"]]
    assert injected and injected[0]["status"] == "needs_review"  # instruction-like text is data only; no action
    assert body["strings"]["treated_as_data"] == "Contains text we treated as data only"
    assert body["consent"]["ledger"]["allowed"] is True


def test_no_basis_cannot_be_accepted_until_a_person_chooses(client):
    sign_in(client, "khalid")
    row = next(r for r in _rows(client, status="needs_review")["rows"] if r["proposed"]["category"] is None)
    r = client.post(f"{TX}/{row['id']}/accept")
    assert r.status_code == 422 and r.json()["error"] == "BASIS_REQUIRED"


def test_correct_posts_with_reviewer_identity_k14_label_k15_record_then_undo(client, db):
    sign_in(client, "omar")
    row = next(r for r in _rows(client, CO_BLUEDUNE, status="needs_review")["rows"])
    r = client.post(f"/api/companies/{CO_BLUEDUNE}/transactions/{row['id']}/correct", json={"category": "sales_revenue", "vat_code": "SR"})
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["status"] == "posted" and out["reviewer"]["name"] == "Omar Haddad" and out["reviewer"]["role"] == "delegate" and out["reviewer"]["at"]
    assert out["final"] == {"category": "sales_revenue", "vat_code": "SR", "ledger_account": "4000"}
    lbl = db.scalar(select(ReviewerLabel).where(ReviewerLabel.classification_id == row["id"]))
    assert lbl and lbl.label_source == "reviewer_unsampled" and lbl.corrected is True and lbl.language_class in ("ar", "en", "mixed") and lbl.bank == "demo_statement"
    rec = db.scalar(select(ReviewRecord).where(ReviewRecord.output_id == row["id"]))
    assert rec and rec.outcome == "corrected" and "vat_code" in rec.changed_fields and rec.material is True and rec.material_fields_version == "material_fields_v1"
    assert db.scalar(select(AuditEvent).where(AuditEvent.event_type == "ENTRY_POSTED", AuditEvent.subject_id == row["id"])) is not None
    # undo within the session, before period approval: reversal = no-change for K14 (label withdrawn)
    r = client.post(f"/api/companies/{CO_BLUEDUNE}/transactions/{row['id']}/undo")
    assert r.status_code == 200 and r.json()["status"] == "needs_review" and r.json()["reviewer"] is None
    db.expire_all()
    assert db.scalar(select(ReviewerLabel).where(ReviewerLabel.classification_id == row["id"])) is None
    r = client.post(f"/api/companies/{CO_BLUEDUNE}/transactions/{row['id']}/undo")
    assert r.status_code == 409


def test_undo_refused_from_another_session(client):
    sign_in(client, "omar")
    row = next(r for r in _rows(client, CO_BLUEDUNE, status="needs_review")["rows"])
    assert client.post(f"/api/companies/{CO_BLUEDUNE}/transactions/{row['id']}/correct", json={"category": "purchases", "vat_code": "SR"}).status_code == 200
    client.cookies.clear()
    sign_in(client, "omar")
    r = client.post(f"/api/companies/{CO_BLUEDUNE}/transactions/{row['id']}/undo")
    assert r.status_code == 409 and r.json()["error"] == "UNDO_WINDOW_CLOSED"


def test_delegate_without_bookkeeping_function_sees_no_rows_and_cannot_confirm(client, db):
    role = db.scalar(select(Role).where(Role.identity_uuid == PERSONA_UUIDS["omar"], Role.company_id == CO_BLUEDUNE))
    role.functions = ["uploads"]
    db.commit()
    sign_in(client, "omar")
    body = _rows(client, CO_BLUEDUNE)
    assert body["view"] == "no_function" and body["rows"] == []
    assert body["message"] == "You do not have the bookkeeping function for this company. Ask the owner to assign it."
    cls = db.scalar(select(Classification).where(Classification.company_id == CO_BLUEDUNE))
    r = client.post(f"/api/companies/{CO_BLUEDUNE}/transactions/{cls.id}/accept")
    assert r.status_code == 403 and r.json()["error"] == "NO_FUNCTION"


def test_bulk_accept_only_for_items_matching_earlier_choices(client, db):
    sign_in(client, "khalid")
    rows = [
        {"source_id": "t-bulk-1", "txn_date": "2026-09-25", "description": "Cheque 00500 Al Rashid", "amount_fils": -300_000_00, "counterparty": "Al Rashid"},
        {"source_id": "t-bulk-2", "txn_date": "2026-09-26", "description": "Transfer 9911 Al Rashid", "amount_fils": 123_10, "counterparty": "Al Rashid"},
        {"source_id": "t-bulk-3", "txn_date": "2026-09-27", "description": "Transfer 4411 Zed Co", "amount_fils": -50_000_00, "counterparty": "Zed Co"},
    ]
    svc.ingest_transactions(db, CO_ALNOOR, rows, source_kind="manual", source_system="t")
    svc.classify_pending(db, CO_ALNOOR, gate=False)
    db.commit()
    preview = client.post(f"{TX}/bulk-accept", json={"confirm": False}).json()
    assert preview["count"] == 2 and preview["total_fils"] == 300_000_00 + 123_10 and preview["income_fils"] == 123_10 and preview["expenses_fils"] == 300_000_00
    matching = {r["id"] for r in _rows(client)["rows"] if r["bulk_eligible"]}
    assert set(preview["ids"]) == matching and len(matching) == 2
    out = client.post(f"{TX}/bulk-accept", json={"confirm": True}).json()
    assert out["count"] == 2 and out["accepted_by"] == "Khalid Al Mansoori" and out["role"] == "owner"
    zed = next(r for r in _rows(client, status="needs_review")["rows"] if r["counterparty"] == "Zed Co")
    assert zed["review_reason"] == "Needs review: no basis found"  # never offered for bulk accept


def test_quarantined_drafts_owner_only_not_counted_until_decided(client, db):
    sign_in(client, "khalid")
    q = _rows(client, status="quarantined")["rows"]
    assert q and q[0]["quarantine"]["made_by"] == "Former delegate (Demo data)" and q[0]["quarantine"]["access_removed_on"] == "2026-09-01"
    qid = q[0]["id"]
    assert client.post(f"{TX}/{qid}/accept").status_code == 409
    assert client.post(f"{TX}/bulk-accept", json={"ids": [qid], "confirm": False}).json()["count"] == 0
    txn = db.get(Transaction, db.get(Classification, qid).txn_id)
    assert all(c.id != qid for c, _ in svc.confirmed_transactions(db, CO_ALNOOR, txn.txn_date, txn.txn_date))
    r = client.post(f"{TX}/quarantine-decision", json={"decision": "keep_and_review", "reason": "", "ids": [qid]})
    assert r.status_code == 422 and r.json()["error"] == "REASON_REQUIRED"
    r = client.post(f"{TX}/quarantine-decision", json={"decision": "keep_and_review", "reason": "supplier is genuine", "ids": [qid]})
    assert r.status_code == 200 and r.json()["decided"] == 1
    db.expire_all()
    cls = db.get(Classification, qid)
    assert cls.status == "needs_review" and cls.quarantine_decided_by == PERSONA_UUIDS["khalid"] and cls.quarantine_reason
    assert db.scalar(select(AuditEvent).where(AuditEvent.event_type == "QUARANTINE_DECISION", AuditEvent.subject_id == qid)) is not None
    client.cookies.clear()
    sign_in(client, "omar")
    assert not [r for r in _rows(client)["rows"] if r["status"] == "quarantined"]
    assert client.post(f"{TX}/quarantine-decision", json={"decision": "discard", "reason": "x"}).status_code == 403


def test_quarantine_drafts_for_removed_delegate(db):
    cls = db.scalar(select(Classification).where(Classification.company_id == CO_ALNOOR, Classification.status == "proposed"))
    cls.made_by_uuid = PERSONA_UUIDS["omar"]
    db.flush()
    n = svc.quarantine_drafts_for(db, PERSONA_UUIDS["omar"], CO_ALNOOR, removed_on=date(2026, 10, 1), display_name="Omar Haddad")
    assert n >= 1 and cls.status == "quarantined" and cls.access_removed_on == date(2026, 10, 1) and cls.made_by_name == "Omar Haddad"


def test_k14_sample_sizes_census_too_small_and_cap():
    assert svc.k14_sample_size(5) == (0, "too_small")
    assert svc.k14_sample_size(10) == (10, "closed")
    assert svc.k14_sample_size(30) == (30, "closed")
    assert svc.k14_sample_size(31) == (30, "closed")
    assert svc.k14_sample_size(1000) == (50, "closed")
    assert svc.k14_sample_size(10_000) == (200, "closed")


def _ingest_month(db, company, n, month="2026-05", lang="en"):
    rows = []
    for i in range(n):
        desc = f"Transfer ref {1000 + i}" if lang == "en" else f"تحويل {1000 + i}"
        rows.append({"source_id": f"k14-{lang}-{i}", "txn_date": f"{month}-{(i % 27) + 1:02d}", "description": desc, "amount_fils": 1000 + i, "counterparty": f"CP{i}"})
    svc.ingest_transactions(db, company, rows, source_kind="bank", source_system="demo_bank")
    svc.classify_pending(db, company, gate=False)
    db.commit()


def test_k14_draw_is_deterministic_blind_and_labelled_a_correction_rate(client, db):
    _ingest_month(db, CO_BLUEDUNE, 40)
    run1 = svc.draw_sample(db, CO_BLUEDUNE, "2026-05", "en")
    run2 = svc.draw_sample(db, CO_BLUEDUNE, "2026-05", "en")
    assert run1.id == run2.id and run1.population_count == 40 and run1.n == 30 and run1.status == "closed"
    assert run1.seed == hashlib.sha256(b"co_bluedune|2026-05|en|k14-v1").hexdigest() and run1.sampling_rule_version == "k14-v1"
    ar = svc.draw_sample(db, CO_BLUEDUNE, "2026-05", "ar")
    assert ar.status == "too_small" and ar.n == 0 and ar.pooled_platform_level is True
    db.commit()
    sign_in(client, "omar")
    for row in _rows(client, CO_BLUEDUNE, period="2026-05")["rows"]:
        assert "sample" not in json.dumps(row).lower()  # blind review: no sampled marker
    rate = svc.k14_rate(db, CO_BLUEDUNE, "2026-05")
    assert rate["label"] == "Correction rate on a labelled sample" and "accuracy" not in json.dumps(rate).lower()
    assert rate["measurable"] is False and rate["not_measurable_text"].startswith("Not yet measurable: 0 labelled")
    # late arrivals do not alter the closed run
    svc.ingest_transactions(db, CO_BLUEDUNE, [{"source_id": "late", "txn_date": "2026-05-30", "description": "Late transfer", "amount_fils": 5}], source_kind="bank", source_system="demo_bank")
    svc.classify_pending(db, CO_BLUEDUNE, gate=False)
    assert svc.draw_sample(db, CO_BLUEDUNE, "2026-05", "en").sample_ids == run1.sample_ids


def test_k14_weighted_and_unweighted_rates_and_unsampled_count(client, db):
    _ingest_month(db, CO_BLUEDUNE, 40)
    run = svc.draw_sample(db, CO_BLUEDUNE, "2026-05", "en")
    db.commit()
    sign_in(client, "omar")
    sampled = list(run.sample_ids)
    unsampled = [c.id for c, t in db.execute(select(Classification, Transaction).join(Transaction, Transaction.id == Classification.txn_id).where(Classification.company_id == CO_BLUEDUNE, Classification.sample_flag.is_(False), Transaction.source_id.like("k14-%"))).all() if c.id not in sampled][:1]
    for i, cid in enumerate(sampled):
        cat = "purchases" if i < 10 else "sales_revenue"
        assert client.post(f"/api/companies/{CO_BLUEDUNE}/transactions/{cid}/correct", json={"category": cat, "vat_code": "SR"}).status_code == 200
    assert client.post(f"/api/companies/{CO_BLUEDUNE}/transactions/{unsampled[0]}/correct", json={"category": "rent", "vat_code": "SR"}).status_code == 200
    r = client.get(f"/api/companies/{CO_BLUEDUNE}/bookkeeping/samples", params={"month": "2026-05"})
    assert r.status_code == 200, r.text
    rate = r.json()
    assert rate["measurable"] is True and rate["labelled_count"] == 30 and rate["corrected_count"] == 30  # all were no-basis -> corrected
    assert rate["display"]["unweighted_rate"] == 1.0 and rate["display"]["weighted_rate"] == 1.0 and rate["display"]["agreement_rate"] == 0.0
    assert rate["unsampled_correction_count"] == 1 and rate["by_language_class"]["en"]["labelled"] == 30
    assert all("seed" not in s for s in rate["strata"])  # company view hides the seed
    client.cookies.clear()
    sign_in(client, "hassan")  # tax specialist: staff cases.queue.tax
    r = client.get(f"/api/companies/{CO_BLUEDUNE}/bookkeeping/samples", params={"month": "2026-05"})
    assert r.status_code == 200 and r.json()["strata"][0]["seed"]
    client.cookies.clear()
    sign_in(client, "noura")
    assert client.get(f"/api/companies/{CO_BLUEDUNE}/bookkeeping/samples", params={"month": "2026-05"}).status_code == 403


def test_k15_material_change_rule():
    assert svc.is_material(["vat_code"]) and svc.is_material(["counterparty"]) and svc.is_material(["monetary_amount", "wording"])
    assert not svc.is_material(["wording"]) and not svc.is_material(["formatting", "category"]) and not svc.is_material([])
    assert svc.MATERIAL_FIELDS_VERSION == "material_fields_v1"


def test_k17_data_complete_supersedes_and_keeps_history(client, db):
    sign_in(client, "khalid")
    card = client.get(f"{TX}/timing/vat/2026-Q2").json()
    assert card["data_complete_at"] and card["draft_ready_at"] and card["elapsed_seconds"] is not None
    first = card["data_complete_at"]
    svc.ingest_transactions(db, CO_ALNOOR, [{"source_id": "k17-new", "txn_date": "2026-06-20", "description": "Unknown thing 77", "amount_fils": -900}], source_kind="manual", source_system="t")
    svc.classify_pending(db, CO_ALNOOR, gate=False)
    db.commit()
    r = client.post(f"{TX}/timing/vat/2026-Q2/evaluate").json()
    assert r["passed"] is False and "all_reviewed" in [m["key"] for m in r["missing_items"]] and r["card"]["data_complete_at"] is None
    cls = db.scalar(select(Classification).where(Classification.company_id == CO_ALNOOR, Classification.status == "needs_review").join(Transaction, Transaction.id == Classification.txn_id).where(Transaction.source_id == "k17-new"))
    assert client.post(f"{TX}/{cls.id}/reject").status_code == 200
    r = client.post(f"{TX}/timing/vat/2026-Q2/evaluate").json()
    assert r["passed"] is True and r["card"]["data_complete_at"] and r["card"]["data_complete_at"] != first
    assert [h["superseded"] for h in r["card"]["history"]] == [True, False]


def test_k17_missing_items_name_who_and_action_and_blocked_only_when_configured(db):
    check = svc.evaluate_completeness(db, CO_BLUEDUNE, "vat", "2026-Q3", facts={"trn": False})
    keys = {m["key"]: m for m in check.missing_items}
    assert "trn" in keys and keys["trn"]["owner_only"] is True and keys["trn"]["action"] and keys["trn"]["why"]
    assert check.passed is False and check.blocked_missing_data is False and check.version == "dc-v1"
    set_config(db, "bookkeeping.dc_v1.deadline_minus_days", 5, changed_by="test")
    check = svc.evaluate_completeness(db, CO_BLUEDUNE, "vat", "2026-Q3", facts={"trn": False}, deadline=date.today())
    assert check.blocked_missing_data is True


def test_pre_consent_rows_not_ingested_and_fx_stored_with_carried_flag(db):
    rows = [
        {"source_id": "pc-1", "txn_date": "2026-03-30", "description": "before data from", "amount_fils": 100},
        {"source_id": "pc-2", "txn_date": "2026-04-06", "description": "USD supplier", "amount_fils": -10_000, "currency": "USD"},
        {"source_id": "pc-3", "txn_date": "2026-04-05", "description": "USD weekend", "amount_fils": -10_000, "currency": "USD"},
        {"source_id": "pc-4", "txn_date": "2026-04-07", "description": "CHF no rate", "amount_fils": -10_000, "currency": "CHF"},
    ]
    created = svc.ingest_transactions(db, CO_GULFTECH, rows, source_kind="bank", source_system="demo_bank", consent_id="c1", data_from=date(2026, 4, 1))
    by = {t.source_id: t for t in created}
    assert "pc-1" not in by and len(created) == 3
    assert by["pc-2"].original_currency == "USD" and by["pc-2"].original_amount_fils == 10_000 and by["pc-2"].aed_amount_fils == 36725 and by["pc-2"].fx_rate_source == "CBUAE published rate" and by["pc-2"].fx_rate_date == date(2026, 4, 6)
    assert by["pc-3"].fx_carried is True  # Sunday 5 Apr 2026 is a weekend row flagged carried
    assert by["pc-4"].fx_missing is True and by["pc-4"].consent_id == "c1" and by["pc-4"].pull_time


def test_post_failed_keeps_draft_not_posted_then_retry(client, db):
    sign_in(client, "khalid")
    set_config(db, "bookkeeping.ledger.simulate_no_response", True, changed_by="test")
    db.commit()
    row = next(r for r in _rows(client, status="proposed")["rows"])
    out = client.post(f"{TX}/{row['id']}/accept").json()
    assert out["status"] == "draft_not_posted" and out["status_label"] == "Draft, not posted" and out["post_result"] == "ledger_no_response" and out["reviewer"]["name"]
    set_config(db, "bookkeeping.ledger.simulate_no_response", False, changed_by="test")
    db.commit()
    assert client.post(f"{TX}/{row['id']}/post").json()["status"] == "posted"


def test_vat_code_lookup_before_first_effective_date_routes_to_review(db):
    assert svc.vat_code_for(db, "SR", date(2017, 6, 1)) is None and svc.vat_code_for(db, "SR", date(2018, 1, 1)).rate_percent == 5.0
    (txn,) = svc.ingest_transactions(db, CO_GULFTECH, [{"source_id": "old", "txn_date": "2017-06-01", "description": "DEWA bill", "amount_fils": -100}], source_kind="manual", source_system="t")
    cls = svc.classify_transaction(db, txn)
    assert cls.status == "needs_review" and cls.proposed_vat_code is None and cls.review_reason == "Needs review: no basis found"


def test_consent_withdrawal_applies_class_a_and_b(db):
    created = svc.ingest_transactions(db, CO_GULFTECH, [{"source_id": f"w{i}", "txn_date": "2026-05-01", "description": "x", "amount_fils": 1} for i in range(3)], source_kind="bank", source_system="demo_bank", consent_id="c9")
    out = svc.withdraw_consent(db, CO_GULFTECH, "c9", used_txn_ids={created[0].id})
    assert out == {"class_a_flagged": 2, "class_b_locked": 1} and created[0].retention_class == "B" and created[1].source_consent_withdrawn is True


def test_remote_owner_summary_and_reference_pickers(client):
    sign_in(client, "priya")
    body = _rows(client, CO_BLUEDUNE)
    assert body["view"] == "summary" and body["rows"] == [] and body["counts"]["needs_review"] >= 1
    ref = client.get(f"/api/companies/{CO_BLUEDUNE}/bookkeeping/reference").json()
    codes = {v["code"]: v for v in ref["vat_codes"]}
    assert {"SR", "ZR", "EX", "OS", "RC"} <= set(codes) and codes["SR"]["gloss_ar"] and codes["SR"]["status_label"] == "configured, pending FTA confirmation"
    assert any(a["code"] == "4000" for a in ref["accounts"])

