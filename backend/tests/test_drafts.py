"""E5-S3 drafts: versioned packs, AI label and watermark, role-bound transitions, approval binding, hold, export."""

from __future__ import annotations

import json
from datetime import timedelta

from sqlalchemy import select

from app.demo import CO_ALNOOR, CO_BLUEDUNE, CO_SAFWA, PERSONA_UUIDS, demo_ct_year, demo_vat_quarters
from app.modules.audit.models import AuditEvent
from app.modules.bookkeeping import service as bk
from app.modules.companies.models import CompanyRole as Role
from app.modules.drafts import service as svc
from app.modules.drafts.models import LINE_CLASSES, DraftPack
from app.modules.drafts.service import get_pack, pack_hash
from app.modules.tax.models import TaxEntityProfile
from tests.conftest import sign_in

D = f"/api/companies/{CO_ALNOOR}/drafts"
QUARTERS, CT_FY = demo_vat_quarters(), demo_ct_year().period_id
OPEN, PREV = QUARTERS.open.period_id, QUARTERS.previous.period_id


class FakePrincipal:
    def __init__(self, uuid, name, role, company_id, functions):
        self.identity_uuid, self.display_name, self.session_id, self.actor_key, self.staff_roles = uuid, name, "s1", "k-" + uuid, []
        self._roles = [Role(identity_uuid=uuid, company_id=company_id, role=role, functions=functions)]

    def roles_for(self, company_id):
        return self._roles

    def primary_role(self):
        return self._roles[0].role


def _open_vat(packs):
    """The open demo quarter's VAT pack (the previous quarter's pack is filed and locked)."""
    return next(p for p in packs if p["tax_type"] == "vat" and p["period_id"] == OPEN)


def _packs(client):
    r = client.get(D)
    assert r.status_code == 200, r.text
    return r.json()


def _fresh_ct_pack(db, *, created_by: str | None = None) -> DraftPack:
    """An unreviewed corporate tax pack for the prior year (the demo year's return is already filed and locked)."""
    tmpl = db.scalar(select(DraftPack).where(DraftPack.company_id == CO_ALNOOR, DraftPack.tax_type == "ct"))
    prior = f"FY{demo_ct_year().start.year - 1}"
    pack = DraftPack(company_id=CO_ALNOOR, tax_type="ct", period_id=prior, version=1, data_version="test-prior-year", rule_version=tmpl.rule_version, assumptions=tmpl.assumptions, lines=tmpl.lines, sources=tmpl.sources, basis=tmpl.basis, review_status="not_reviewed", created_by_uuid=created_by, created_by_name="Omar Haddad" if created_by else "test", is_demo=True)
    db.add(pack)
    db.flush()
    svc._history(db, pack, "not_reviewed", actor=None, role=None, system=True)
    db.commit()
    return pack


def test_demo_packs_carry_label_watermark_marks_and_sbr_indicator(client):
    sign_in(client, "khalid")
    packs = _packs(client)["packs"]
    vat = _open_vat(packs)
    ct = next(p for p in packs if p["tax_type"] == "ct")
    # demo: the corporate tax return for the demo year was approved and filed before its due date (locked)
    assert vat["review_status"] == "under_review" and ct["review_status"] == "filed_user_confirmed"
    body = client.get(f"{D}/{vat['id']}").json()
    assert body["ai_label"] == {"en": "AI-generated draft: not a filed return", "ar": "مسودة مُعدّة بالذكاء الاصطناعي: ليست إقرارًا مقدَّمًا"}
    assert body["watermark"]["en"] == "Draft working figures arranged to follow the FTA return layout. Not a tax return. Not filed. Not tax advice."
    assert body["emaratax_sentence"]["en"] == "Submission to the FTA is made only by you or your authorised person through EmaraTax"
    assert body["product_name"]["en"] == "Tax preparation assistant" and body["pack_hash"] and body["data_version"] and body["rule_version"]
    assert all(ln["line_class"] in LINE_CLASSES and ln["term"]["ar"] and ln["gloss"]["en"] for ln in body["lines"])
    assert body["sources"] and body["basis"]["rule_refs"]["vat-rate"]["instrument"] and body["assumptions"]
    assert body["review_status_label"] == {"en": "Under review", "ar": "قيد المراجعة"} and body["history"][0]["to"] == "not_reviewed" and body["history"][0]["system"] is True
    for text in (body["watermark"]["en"], body["ai_label"]["en"], body["product_name"]["en"]):
        assert svc.check_banned(text) == [], text
    ct_body = client.get(f"{D}/{ct['id']}").json()
    sbr = next(ln for ln in ct_body["lines"] if ln["key"] == "sbr")
    assert sbr["sbr"]["indicator"] == "may be eligible" and sbr["sbr"]["text"] == "eligible, election needed" and sbr["sbr"]["election_status"] == "undecided"
    assert ct_body["not_reviewed_by_human"] is False  # the owner approved the filed return


def test_banned_terms_checker():
    assert svc.check_banned("Your Tax Agent prepared an audit certificate") == ["audit certificate", "Tax Agent"]
    assert svc.check_banned("Filed (user-confirmed)") == [] and svc.check_banned("Filed") == ["Filed"]


def test_role_bound_transitions_reasons_and_system_only_statuses(client):
    sign_in(client, "omar")
    vat = _open_vat(_packs(client)["packs"])
    url = f"{D}/{vat['id']}/record-review"
    r = client.post(url, json={"to_status": "superseded"})
    assert r.status_code == 403 and r.json()["error"] == "SYSTEM_ONLY_STATUS"
    r = client.post(url, json={"to_status": "approved_for_submission"})
    assert r.status_code == 403 and r.json()["message"].startswith("You cannot set this status. Owner can.")
    r = client.post(url, json={"to_status": "reviewed_by_specialist"})
    assert r.status_code == 403 and r.json()["error"] == "FEATURE_SWITCHED_OFF"
    r = client.post(url, json={"to_status": "accepted_by_reviewer"})
    assert r.status_code == 200 and r.json()["review_status"] == "accepted_by_reviewer" and r.json()["history"][-1]["by"] == "Omar Haddad"
    r = client.post(url, json={"to_status": "under_review"})
    assert r.status_code == 422 and r.json()["error"] == "REASON_REQUIRED"
    r = client.post(url, json={"to_status": "under_review", "reason_code": "figure_corrected", "reason_text": "re-check rent"})
    assert r.status_code == 200 and r.json()["review_status"] == "under_review" and r.json()["history"][-1]["reason_code"] == "figure_corrected"
    assert [h["to"] for h in r.json()["history"]][:3] == ["not_reviewed", "prepared", "under_review"]  # append-only


def test_self_edit_cannot_accept_and_owner_only_shows_no_independent_review(client, db):
    sign_in(client, "omar")
    vat = _open_vat(_packs(client)["packs"])
    r = client.post(f"{D}/{vat['id']}/edit", json={"key": "net_vat", "value_fils": 123_456, "reason_code": "nope"})
    assert r.status_code == 422 and r.json()["error"] == "REASON_REQUIRED"
    r = client.post(f"{D}/{vat['id']}/edit", json={"key": "net_vat", "value_fils": 123_456, "reason_code": "figure_corrected"})
    body = r.json()
    assert r.status_code == 200 and body["human_edited"] is True and body["ai_lines"] and body["last_human_change"]["by"] == "Omar Haddad"
    edited = next(ln for ln in body["lines"] if ln["key"] == "net_vat")
    assert edited["line_class"] == "person_entered" and edited["source_refs"][0]["person"] == "Omar Haddad"
    r = client.post(f"{D}/{vat['id']}/record-review", json={"to_status": "accepted_by_reviewer"})
    assert r.status_code == 403 and r.json()["error"] == "SELF_ACCEPT_REFUSED"
    client.cookies.clear()
    sign_in(client, "khalid")
    r = client.post(f"{D}/{vat['id']}/record-review", json={"to_status": "accepted_by_reviewer"})
    assert r.status_code == 200 and r.json()["review_status"] == "accepted_by_reviewer"
    # a pack where only the owner ever acted
    r = client.post(D, json={"tax_type": "ct", "period_id": CT_FY})
    assert r.status_code == 200, r.text
    pid = r.json()["id"]
    assert client.post(f"{D}/{pid}/record-review", json={"to_status": "under_review"}).status_code == 200
    r = client.post(f"{D}/{pid}/record-review", json={"to_status": "accepted_by_reviewer"})
    assert r.json()["review_status"] == "accepted_by_owner_no_independent_review" and r.json()["review_status_label"]["en"] == "Accepted by owner, no independent review"


def test_new_version_supersedes_and_approval_binds_to_one_version(client, db):
    sign_in(client, "khalid")
    old = _open_vat(_packs(client)["packs"])
    new = client.post(D, json={"tax_type": "vat", "period_id": OPEN, "what_changed": "bank data pulled"}).json()
    assert new["version"] == old["version"] + 1 and new["review_status"] == "not_reviewed"
    old_body = client.get(f"{D}/{old['id']}").json()
    assert old_body["superseded"] is True and old_body["review_status"] == "superseded" and old_body["can_approve"] is False and old_body["approve_disabled_reason"] == "Approval is only possible on the current version." and old_body["current_pack_id"] == new["id"]
    assert client.post(f"{D}/{old['id']}/record-review", json={"to_status": "under_review"}).status_code == 409
    khalid = FakePrincipal(PERSONA_UUIDS["khalid"], "Khalid Al Mansoori", "owner", CO_ALNOOR, ["all"])
    import pytest

    from app.core.errors import Conflict

    with pytest.raises(Conflict):
        svc.set_approval_status(db, old["id"], "approved_for_submission", actor=khalid, expected_hash=pack_hash(get_pack(db, old["id"])))
    with pytest.raises(Conflict):
        svc.set_approval_status(db, new["id"], "approved_for_submission", actor=khalid, expected_hash="stale-hash")
    pack = svc.set_approval_status(db, new["id"], "approved_for_submission", actor=khalid, expected_hash=new["pack_hash"])
    assert pack.review_status == "approved_for_submission" and pack_hash(pack) == new["pack_hash"]
    pack = svc.set_approval_status(db, new["id"], "filed_user_confirmed", actor=khalid, expected_hash=new["pack_hash"], filing_reference="EMARATAX-REF-1")
    assert pack.locked is True and pack.filing_reference == "EMARATAX-REF-1"


def test_out_of_date_when_source_data_changes(client, db):
    sign_in(client, "khalid")
    vat = _open_vat(_packs(client)["packs"])
    khalid = FakePrincipal(PERSONA_UUIDS["khalid"], "Khalid", "owner", CO_ALNOOR, ["all"])
    (t,) = bk.ingest_transactions(db, CO_ALNOOR, [{"source_id": "ood", "txn_date": (QUARTERS.open.start + timedelta(days=44)).isoformat(), "description": "Invoice INV-800 sale", "amount_fils": 100_000, "counterparty": "Z"}], source_kind="ledger", source_system="erp")
    bk.classify_pending(db, CO_ALNOOR, gate=False)
    bk.accept(db, CO_ALNOOR, db.scalar(select(bk.Classification).where(bk.Classification.txn_id == t.id)).id, khalid)
    db.commit()
    body = client.get(f"{D}/{vat['id']}").json()
    assert body["review_status"] == "stale" and body["can_approve"] is False and body["review_status_label"]["en"] == "Stale (source data changed)"
    assert db.scalar(select(AuditEvent).where(AuditEvent.event_type == "DRAFT_OUT_OF_DATE", AuditEvent.subject_id == vat["id"])) is not None


def test_held_drafts_owner_only_one_at_a_time_keep_and_discard(client, db):
    extra = _fresh_ct_pack(db, created_by=PERSONA_UUIDS["omar"])
    n = svc.hold_packs_for(db, PERSONA_UUIDS["omar"], CO_ALNOOR, display_name="Omar Haddad")
    db.commit()
    assert n == 2  # the open VAT pack and the prior-year draft: filed (locked) returns are never held
    sign_in(client, "omar")
    assert {p["period_id"] for p in _packs(client)["packs"]} == {PREV, demo_ct_year().period_id}
    held = db.scalar(select(DraftPack).where(DraftPack.company_id == CO_ALNOOR, DraftPack.tax_type == "vat", DraftPack.period_id == OPEN))
    assert client.get(f"{D}/{held.id}").status_code == 403
    client.cookies.clear()
    sign_in(client, "khalid")
    lst = _packs(client)
    assert lst["held_count"] == 2 and all(p["on_hold"] and p["held_delegate"] == "Omar Haddad" for p in lst["packs"] if p["period_id"] not in (PREV, demo_ct_year().period_id))
    assert client.get(f"{D}/{held.id}/export", params={"lang": "en"}).status_code == 409
    r = client.post(f"{D}/{held.id}/hold-decision", json={"decision": "keep_changes", "reason_code": ""})
    assert r.status_code == 422
    r = client.post(f"{D}/{held.id}/hold-decision", json={"decision": "keep_changes", "reason_code": "other", "reason_text": "figures checked"})
    assert r.status_code == 200 and r.json()["still_on_hold"] == 1
    new = client.get(f"{D}/{r.json()['new_pack_id']}").json()
    assert new["review_status"] == "reviewed_by_owner_after_hold" and new["review_status_label"]["en"] == "Reviewed by owner after hold, no independent review"
    ct = db.get(DraftPack, extra.id)
    r = client.post(f"{D}/{ct.id}/hold-decision", json={"decision": "discard_changes", "reason_code": "other"})
    assert r.status_code == 200 and r.json()["announcement"] == "Draft discarded. 0 drafts still on hold."
    client.cookies.clear()
    sign_in(client, "omar")
    assert client.post(f"{D}/{ct.id}/hold-decision", json={"decision": "discard_changes", "reason_code": "other"}).status_code == 403


def test_export_changes_labels_only_and_is_logged(client, db):
    sign_in(client, "khalid")
    vat = _open_vat(_packs(client)["packs"])
    en = client.get(f"{D}/{vat['id']}/export", params={"lang": "en"}).json()
    ar = client.get(f"{D}/{vat['id']}/export", params={"lang": "ar"}).json()
    assert en["watermark"] != ar["watermark"] and en["draft_statement"] != ar["draft_statement"]
    assert [ln["value_fils"] for ln in en["lines"]] == [ln["value_fils"] for ln in ar["lines"]]
    assert en["status"] == "Under review" and en["data_version"] == vat_data(client, vat["id"]) and svc.check_banned(en["title"]) == []
    assert db.scalar(select(AuditEvent).where(AuditEvent.event_type == "DRAFT_EXPORTED", AuditEvent.subject_id == vat["id"])) is not None
    classes = client.get(f"{D}/{vat['id']}").json()["retention"]["classes"]
    assert set(classes) == {"1", "2", "3", "4", "5"} and all("year" not in json.dumps(c).lower() for c in classes.values())


def vat_data(client, pid):
    return client.get(f"{D}/{pid}").json()["data_version"]


def test_incomplete_data_lists_missing_items_and_blocked_generation(client, db):
    sign_in(client, "omar")
    r = client.post(f"/api/companies/{CO_BLUEDUNE}/drafts", json={"tax_type": "vat", "period_id": OPEN})
    assert r.status_code == 422 and r.json()["error"] == "DATA_INCOMPLETE"
    items = {m["key"]: m for m in r.json()["details"]["missing_items"]}
    assert "trn" in items and items["trn"]["owner_only"] is True and "all_reviewed" in items
    chk = client.get(f"/api/companies/{CO_BLUEDUNE}/drafts/checklist/vat/{OPEN}").json()
    assert chk["passed"] is False and chk["heading"].startswith("We cannot prepare this draft yet.")
    client.cookies.clear()
    sign_in(client, "khalid")
    p = db.get(TaxEntityProfile, CO_SAFWA)
    p.revenue_confirmed_at = p.updated_at
    p.revenue_fils = 1
    db.commit()
    r = client.post(f"/api/companies/{CO_SAFWA}/drafts", json={"tax_type": "ct", "period_id": CT_FY})
    assert r.status_code == 422 and r.json()["error"] == "GENERATION_FAILED" and "outside the pilot's supported scope" in r.json()["details"]["cause"]


def test_remote_owner_and_k17_draft_ready(client):
    sign_in(client, "priya")
    r = client.get(f"/api/companies/{CO_BLUEDUNE}/drafts")
    assert r.status_code == 403 and r.json()["message"] == "Draft returns are not available to you yet. You can view your dashboard and reminders."
    client.cookies.clear()
    sign_in(client, "khalid")
    card = client.get(f"/api/companies/{CO_ALNOOR}/transactions/timing/vat/{OPEN}").json()
    assert card["draft_ready_at"] and card["data_complete_at"]


def test_send_for_review_by_delegate(client, db):
    pack = _fresh_ct_pack(db)
    sign_in(client, "omar")
    r = client.post(f"{D}/{pack.id}/send-for-review")
    assert r.status_code == 200 and r.json()["review_status"] == "under_review" and [h["to"] for h in r.json()["history"]] == ["not_reviewed", "prepared", "under_review"]
