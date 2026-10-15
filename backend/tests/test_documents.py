"""E7-S5 documents: sig-v1 fail closed, Auditor's report switched off, bilingual mismatch blocks official issue,
public verification without figures, rate limits and lockout, supersede/revoke keep records, sharing rules, K28."""

from __future__ import annotations

import re
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.errors import Conflict, Forbidden, PlatformError, SwitchedOff
from app.core.time import utcnow
from app.demo import CO_ALNOOR, CO_BLUEDUNE, PERSONA_UUIDS
from app.main import app
from app.modules.audit.models import AuditEvent
from app.modules.config.service import set_config
from app.modules.documents import service as svc
from app.modules.documents.models import BilingualCheck, DeliveryLog, IssuedDocument
from app.modules.documents.strings import STRINGS
from tests.conftest import sign_in


class Actor:
    identity_uuid = PERSONA_UUIDS["khalid"]
    display_name = "Khalid Al Mansoori"
    actor_key = None


def _events(db, event_type, outcome=None):
    stmt = select(AuditEvent).where(AuditEvent.event_type == event_type)
    if outcome:
        stmt = stmt.where(AuditEvent.outcome == outcome)
    return list(db.scalars(stmt))


def _client(persona: str) -> TestClient:
    c = TestClient(app, follow_redirects=False)
    sign_in(c, persona)
    return c


def _issued(db, doc_type="compliance_status_report") -> IssuedDocument:
    return db.scalar(select(IssuedDocument).where(IssuedDocument.company_id == CO_ALNOOR, IssuedDocument.doc_type == doc_type, IssuedDocument.status == "issued"))


def test_demo_documents_seeded(db):
    docs = list(db.scalars(select(IssuedDocument).where(IssuedDocument.company_id == CO_ALNOOR)))
    by = {(d.doc_type, d.status) for d in docs}
    assert ("licence_subscription_confirmation", "issued") in by and ("licence_subscription_confirmation", "superseded") in by
    assert ("compliance_status_report", "issued") in by and ("tax_pack_draft", "draft") in by
    for d in docs:
        if d.status in ("issued", "superseded"):
            assert re.fullmatch(r"[0-9A-HJKMNP-TV-Z]{16}", d.verification_code)
    draft = next(d for d in docs if d.doc_type == "tax_pack_draft")
    from app.modules.drafts.models import WATERMARK as DRAFTS_WATERMARK

    assert draft.verification_code is None and draft.watermark == DRAFTS_WATERMARK and not draft.official
    assert "Draft, not filed, not an audit opinion" in svc.render_file(draft, "en") and "مسودة، غير مقدَّمة، وليست رأي تدقيق" in svc.render_file(draft, "ar")


def test_sig_v1_fail_closed(db):
    for doc_type in ("not_in_table", "c1_unsigned_audit_named_output", "c3_legal_opinion", "assurance_or_agreed_procedures_report"):
        with pytest.raises(Forbidden) as exc:
            svc.issue_document(db, CO_ALNOOR, doc_type, {}, Actor())
        assert exc.value.reason_code in ("SIGNATURE_REQUIRED", "TYPE_NOT_OFFERED")
    assert svc.type_info(db, "not_in_table")["signature_required"] is True
    assert svc.type_info(db, "auditors_report")["class"] == "B" and svc.type_info(db, "licence_subscription_confirmation")["class"] == "A"
    assert _events(db, "ISSUE_REFUSED")


def test_auditors_report_switched_off_and_two_admin_toggle(db):
    with pytest.raises(SwitchedOff):
        svc.issue_document(db, CO_ALNOOR, "auditors_report", {}, Actor())
    db.commit()
    with _client("adel") as adel:
        req = adel.post("/api/documents/switches/auditors-report", json={"enabled": True, "reason": "test environment with seeded signer"}).json()
        r = adel.post(f"/api/documents/switches/requests/{req['id']}/approve")
        assert r.status_code == 403 and r.json()["error"] == "SECOND_APPROVER_REQUIRED"
    with _client("lina") as lina:
        assert lina.post(f"/api/documents/switches/requests/{req['id']}/approve").json()["status"] == "applied"
    db.expire_all()
    with pytest.raises(Forbidden) as exc:  # switched on, but no licensed signature recorded
        svc.issue_document(db, CO_ALNOOR, "auditors_report", {}, Actor())
    assert exc.value.reason_code == "SIGNATURE_REQUIRED"
    signed = svc.issue_document(db, CO_ALNOOR, "auditors_report", {"signer_name": "Layla Haddad", "signer_licence": "MOE-AUD-2201", "sign_record_id": "sign_test", "register_snapshot_id": "snap_test", "fields": {"period": "FY2025"}}, Actor())
    assert signed.status == "issued" and signed.title_en == "Auditor's report" and signed.precedence_clause_version is None  # never on auditor-signed docs
    out = svc.verify(db, signed.verification_code, ip="10.0.0.9")
    assert out["status"] == "valid" and out["status_label_en"] == "Valid. Signed by Layla Haddad, licence no. MOE-AUD-2201"
    assert _events(db, "ISSUE_SWITCH_TOGGLED")


def test_bilingual_mismatch_blocks_official_issue(db):
    src = svc.build_source_record(db, CO_ALNOOR, "compliance_status_report")
    with pytest.raises(Conflict) as exc:
        svc.issue_document(db, CO_ALNOOR, "compliance_status_report", {**src, "overrides": {"ar": {"licence_number": "DET-9999999"}}}, Actor())
    assert exc.value.reason_code == "BILINGUAL_MISMATCH" and exc.value.details["fields"] == ["licence_number"]
    assert "differ in licence_number" in exc.value.message
    with pytest.raises(Conflict):  # trade name must equal the DET record for that language (never translated)
        svc.issue_document(db, CO_ALNOOR, "compliance_status_report", {**src, "overrides": {"ar": {"company_name": "شركة أخرى"}}}, Actor())
    chk = db.scalars(select(BilingualCheck).where(BilingualCheck.document_mismatch.is_(True))).all()
    assert chk and chk[0].official
    assert _events(db, "DOCUMENT_CHECK", "failed") and _events(db, "BILINGUAL_MISMATCH_REVIEWER_NOTIFIED")
    # Normalisation: Arabic-Indic digits, written dates in both languages and AED amounts compare equal.
    ok = svc.issue_document(db, CO_ALNOOR, "compliance_status_report", {**src, "fields": {**src["fields"], "amount_fee": 1_250_000, "renewal_date": "2027-03-14"}, "overrides": {"ar": {"licence_number": "DET-١٠٢٣٤٥٦", "amount_fee": "AED ١٢٬٥٠٠٫٠٠", "renewal_date": "14 مارس 2027"}}}, Actor())
    assert ok.status == "issued" and ok.fields_en["renewal_date"] == "14 March 2027"
    # Missing source-of-truth field -> blank -> blocked (fail closed).
    with pytest.raises(Conflict):
        svc.issue_document(db, CO_ALNOOR, "compliance_status_report", {**src, "fields": {**src["fields"], "trn": None}}, Actor())
    # A draft with a mismatch is still only a watermarked draft (no code), never official.
    d = svc.issue_document(db, CO_ALNOOR, "audit_working_paper_summary", svc.build_source_record(db, CO_ALNOOR, "audit_working_paper_summary"), Actor())
    assert d.status == "draft" and d.verification_code is None and d.watermark["en"] == "DRAFT - NOT AN AUDIT REPORT"


def test_normalisation_helpers():
    assert svc.norm_amount("AED 12,500.00") == svc.norm_amount("١٢٬٥٠٠٫٠٠") == 1_250_000
    assert svc.norm_amount("0.005") == 1  # round half up once
    assert svc.norm_date("14 March 2027") == svc.norm_date("١٤ مارس ٢٠٢٧") == "2027-03-14"
    assert svc.norm_text("النور  للتجارة") == svc.norm_text("النور للتجارة")


def test_verification_page_shows_no_figures(client, db):
    doc = _issued(db)
    r = client.get(f"/api/documents/verify/{doc.verification_code}")  # no sign-in
    assert r.status_code == 200
    out = r.json()
    assert set(out) == {"status", "status_label_en", "status_label_ar", "reference", "doc_type_label_en", "doc_type_label_ar", "issued_at"}
    assert out["status"] == "valid" and out["reference"] == doc.reference
    blob = str(out)
    assert "AED" not in blob and "fils" not in blob and "Al Noor" not in blob and "DET-1023456" not in blob
    for bad in ("not-a-code", "0000000000000000", "ZZZZZZZZZZZZZZZZ"):
        nf = client.get(f"/api/documents/verify/{bad}").json()
        assert nf == {"status": "not_found", "status_label_en": STRINGS["not_found"]["en"], "status_label_ar": STRINGS["not_found"]["ar"], "reference": None, "doc_type_label_en": None, "doc_type_label_ar": None, "issued_at": None}
    # Drafts have no code and never show a status.
    assert db.scalar(select(IssuedDocument).where(IssuedDocument.status == "draft", IssuedDocument.verification_code.is_not(None))) is None
    # Integrity: tampered payload -> 'not valid'.
    doc.source_record = {**doc.source_record, "fields": {**doc.source_record["fields"], "as_of_date": "2000-01-01"}}
    doc.fields_en = {**doc.fields_en, "as_of_date": "1 January 2000"}
    db.commit()
    assert svc.verify(db, doc.verification_code, ip="10.1.1.1")["status"] == "not_valid"


def test_rate_limits_and_lockout(db):
    now = utcnow()
    # 30 lookups per IP per minute (lockout and per-code limits raised for this part only).
    set_config(db, "documents.verify.lockout", {"failed": 1000, "window_minutes": 10, "lockout_minutes": 15}, changed_by="test")
    for i in range(30):
        assert svc.verify(db, f"1111111111{i:06d}", ip="10.3.0.1", now=now + timedelta(seconds=i))["status"] == "not_found"
    with pytest.raises(svc.RateLimited) as exc:
        svc.verify(db, "1111111111999999", ip="10.3.0.1", now=now + timedelta(seconds=31))
    assert exc.value.reason_code == "RATE_LIMITED"
    assert svc.verify(db, "1111111111999999", ip="10.3.0.1", now=now + timedelta(seconds=95))["status"] == "not_found"
    set_config(db, "documents.verify.lockout", {"failed": 10, "window_minutes": 10, "lockout_minutes": 15}, changed_by="test")
    # 10 lookups per code per hour.
    code = _issued(db).verification_code
    for i in range(10):
        assert svc.verify(db, code, ip=f"10.4.0.{i}", now=now)["status"] == "valid"
    with pytest.raises(svc.RateLimited) as exc:
        svc.verify(db, code, ip="10.4.1.1", now=now)
    assert exc.value.reason_code == "RATE_LIMITED" and exc.value.details["text"]["en"].startswith("Too many checks from this connection.")
    # 10 failed lookups in 10 minutes -> 15-minute lockout with the generic bilingual message, then released.
    for i in range(10):
        svc.verify(db, f"2222222222{i:06d}", ip="10.5.0.1", now=now + timedelta(minutes=i * 0.5))
    with pytest.raises(svc.RateLimited) as exc:
        svc.verify(db, "2222222222999999", ip="10.5.0.1", now=now + timedelta(minutes=6))
    assert exc.value.reason_code == "LOCKED_OUT" and exc.value.details["text"] == {"en": "Too many attempts, try later", "ar": "محاولات كثيرة، حاول لاحقًا"}
    assert svc.verify(db, "2222222222888888", ip="10.5.0.1", now=now + timedelta(minutes=25))["status"] == "not_found"


def test_rate_limit_via_api_returns_429(client, db):
    set_config(db, "documents.verify.rate_limit_per_ip_per_minute", 3, changed_by="test")
    db.commit()
    for _ in range(3):
        assert client.get("/api/documents/verify/1111111111111111").status_code == 200
    r = client.get("/api/documents/verify/1111111111111111")
    assert r.status_code == 429 and r.json()["error"] in ("RATE_LIMITED", "LOCKED_OUT")


def test_supersede_and_revoke_keep_records(db):
    old = db.scalar(select(IssuedDocument).where(IssuedDocument.doc_type == "licence_subscription_confirmation", IssuedDocument.status == "superseded"))
    assert old is not None and old.superseded_by_id
    assert svc.verify(db, old.verification_code, ip="10.6.0.1")["status"] == "superseded"
    doc = _issued(db)
    db.commit()
    with _client("adel") as adel:
        r = adel.post(f"/api/documents/{doc.id}/revoke", json={"reason_code": "issued_in_error"})
        assert r.status_code == 422 and r.json()["error"] == "WRITTEN_REQUEST_REQUIRED"
        r = adel.post(f"/api/documents/{doc.id}/revoke", json={"reason_code": "bogus", "written_request_ref": "REQ-1"})
        assert r.status_code == 422
        r = adel.post(f"/api/documents/{doc.id}/revoke", json={"reason_code": "owner_written_request", "written_request_ref": "REQ-2026-0042", "requested_by_role": "owner"})
        assert r.status_code == 200 and r.json()["status"] == "revoked"
    with _client("noura") as noura:  # compliance reviewer: read-only, cannot revoke
        assert noura.post(f"/api/documents/{doc.id}/revoke", json={"reason_code": "issued_in_error", "written_request_ref": "R"}).status_code == 403
    db.expire_all()
    kept = db.get(IssuedDocument, doc.id)
    assert kept is not None and kept.status == "revoked"
    v = svc.verify(db, kept.verification_code, ip="10.6.0.2")
    assert v["status"] == "revoked" and v["status_label_en"].startswith("Revoked on ") and v["status_label_en"].endswith("Do not rely on it.")
    # Signed-output status layer changes only on instruction from the signing firm or an authority.
    with pytest.raises(PlatformError):
        svc.set_signed_status(db, kept, status="invalid", source="owner", ref="x", actor_key=None)


def test_delegate_sharing_rules(client, db):
    doc = _issued(db)
    with _client("omar") as omar:
        lst = omar.get(f"/api/companies/{CO_ALNOOR}/documents").json()
        assert lst["documents"] == [] and lst["delegate_note"]["en"] == "Ask the owner to give you access"
        r = omar.get(f"/api/companies/{CO_ALNOOR}/documents/{doc.id}")
        assert r.status_code == 403 and r.json()["error"] == "DOCUMENT_NOT_SHARED"
        sign_in(client, "khalid")
        r = client.post(f"/api/companies/{CO_ALNOOR}/documents/{doc.id}/share", json={"identity_uuid": PERSONA_UUIDS["layla"]})
        assert r.status_code == 422 and r.json()["error"] == "RECIPIENT_NOT_ASSIGNED"
        assert client.post(f"/api/companies/{CO_ALNOOR}/documents/{doc.id}/share", json={"identity_uuid": PERSONA_UUIDS["omar"]}).status_code == 200
        assert [d["id"] for d in omar.get(f"/api/companies/{CO_ALNOOR}/documents").json()["documents"]] == [doc.id]
        r = omar.post(f"/api/companies/{CO_ALNOOR}/documents/{doc.id}/share", json={"identity_uuid": PERSONA_UUIDS["omar"]})
        assert r.status_code == 403  # delegates cannot share
    with _client("priya") as priya:
        lst = priya.get(f"/api/companies/{CO_BLUEDUNE}/documents").json()
        assert lst["can_issue"] is False and lst["issue_note"]["en"].startswith("Issuing is not yet available")
        assert priya.post(f"/api/companies/{CO_BLUEDUNE}/documents/issue", json={"doc_type": "compliance_status_report"}).status_code == 403
    with _client("sara") as sara:  # DET administrator never sees the document list
        assert sara.get(f"/api/companies/{CO_ALNOOR}/documents").status_code == 403


def test_k28_events_on_download_and_render(client, db):
    sign_in(client, "khalid")
    doc = _issued(db)
    r = client.post(f"/api/companies/{CO_ALNOOR}/documents/{doc.id}/download", json={"kind": "downloaded", "lang": "ar"})
    assert r.status_code == 200 and r.json()["check"]["document_mismatch"] is False and r.json()["check"]["versions_match"]["en"] == "Arabic and English versions match"
    html = client.get(f"/api/companies/{CO_ALNOOR}/documents/{doc.id}/render?lang=both")
    assert html.status_code == 200 and "dir='rtl'" in html.text and "lang='ar'" in html.text and "the Arabic version prevails" in html.text
    log = client.get(f"/api/companies/{CO_ALNOOR}/documents/{doc.id}/download-log").json()
    assert {"downloaded", "opened"} <= {x["event"] for x in log}
    db.expire_all()
    assert db.scalar(select(BilingualCheck).where(BilingualCheck.document_id == doc.id, BilingualCheck.event == "download")) is not None
    assert db.scalar(select(DeliveryLog).where(DeliveryLog.document_id == doc.id, DeliveryLog.event == "downloaded")) is not None
    delivered = _events(db, "DOCUMENT_DELIVERED")
    assert delivered and delivered[-1].details["kpi"] == "K28"
    checks = _events(db, "DOCUMENT_CHECK")
    assert any(e.details["event"] == "download" for e in checks) and all("fields_mismatched" in e.details for e in checks)
    k = svc.k28(db)
    assert k["official"]["documents"] >= 1 and k["draft"]["documents"] >= 1


def test_owner_issue_and_tax_pack_draft(client, db):
    sign_in(client, "khalid")
    r = client.post(f"/api/companies/{CO_ALNOOR}/documents/issue", json={"doc_type": "compliance_status_report"})
    assert r.status_code == 200 and r.json()["status"] == "issued" and r.json()["verification_code"]
    r = client.post(f"/api/companies/{CO_ALNOOR}/documents/issue", json={"doc_type": "auditors_report"})
    assert r.status_code == 403 and r.json()["error"] == "FEATURE_SWITCHED_OFF"
    from app.modules.drafts.models import DraftPack

    pack = db.scalar(select(DraftPack).where(DraftPack.company_id == CO_ALNOOR).order_by(DraftPack.created_at.desc()).limit(1))
    d = svc.issue_tax_pack_draft(db, pack.id, Actor())
    assert d.status == "draft" and d.verification_code is None and "Draft, not filed" in svc.render_file(d, "en")
    assert d.supersedes_id is not None  # the earlier demo draft of the same pack period is superseded, not deleted


def test_banned_terms_never_on_unsigned_outputs(db, monkeypatch):
    for doc_type, info in svc.SIG_V1.items():
        if info.get("signature_required"):
            continue
        texts = [info["label_en"], info["label_ar"], *(info.get("watermark") or {}).values(), f"{doc_type}.html"]
        for t in texts:
            assert svc.banned_terms_found(t) == [], (doc_type, t)
    for d in db.scalars(select(IssuedDocument).where(IssuedDocument.signer_name.is_(None))):
        for t in (d.title_en, d.title_ar, d.file_name_en, d.file_name_ar, *(d.watermark or {}).values(), svc.render_file(d, "en"), svc.render_file(d, "ar")):
            assert svc.banned_terms_found(t) == [], t
    for key in ("valid", "superseded", "not_valid", "not_found", "rate_limited", "locked_out", "no_financial_data"):
        assert svc.banned_terms_found(STRINGS[key]["en"]) == [] and svc.banned_terms_found(STRINGS[key]["ar"]) == []
    assert svc.banned_terms_found("Audit certificate for 2025") == ["audit certificate"]
    assert svc.banned_terms_found("DRAFT - NOT AN AUDIT REPORT") == []
    table = {**svc.SIG_V1, "tmp_bad": {"class": "A", "signature_required": False, "issuable": True, "official": False, "label_en": "Certified statement", "label_ar": "x"}}
    monkeypatch.setattr(svc, "sig_table", lambda _db: table)
    with pytest.raises(Forbidden) as exc:  # wording blocklist on templates of unsigned outputs
        svc.issue_document(db, CO_ALNOOR, "tmp_bad", {}, Actor())
    assert exc.value.reason_code == "WORDING_BLOCKED"


def test_chain_check_and_hashes(db):
    out = svc.chain_check(db)
    assert out["ok"] is True
    doc = _issued(db)
    assert len(doc.hash_en) == len(doc.hash_ar) == len(doc.manifest_hash) == 64
    assert doc.manifest_hash == svc.sha(doc.hash_en + doc.hash_ar + doc.hash_payload)
