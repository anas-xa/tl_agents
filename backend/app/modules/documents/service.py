"""E7-S5 document store: sig-v1 deliverable classes (fail closed), bilingual generation from one source record with
bilingual-fields-v1 normalisation and a mismatch check that blocks official issue (K28), SHA-256 per file + payload
+ manifest with an append-only chain, 16-character Crockford base32 verification codes, a public verification
endpoint that never shows financial figures, rate limits and lockout, revoke/supersede that keep the record, a
signed-output status layer, delivery logging and sharing rules.

Documents are rendered as HTML (bilingual side by side, Arabic RTL); the browser prints. No PDF dependency.
"""

from __future__ import annotations

import hashlib
import html
import json
import re
import secrets
import unicodedata
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import Conflict, Forbidden, NotFound, PlatformError, SwitchedOff, ValidationFailed
from app.core.time import dubai_today, utcnow
from app.modules.audit.service import record_event
from app.modules.config.service import get_config, rule_params, set_config
from app.modules.documents.models import (
    REVOKE_REASONS,
    BilingualCheck,
    DeliveryLog,
    IssuedDocument,
    SwitchRequest,
    VerificationLookup,
)
from app.modules.documents.strings import REVOKE_REASON_LABELS, both, s

CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
AUDITORS_REPORT_SWITCH = "documents.auditors_report.enabled"
DRAFT_WATERMARK_TAX = {"en": "Draft, not filed, not an audit opinion", "ar": "مسودة، غير مقدَّمة، وليست رأي تدقيق"}
AUDIT_WATERMARK = {"en": "DRAFT - NOT AN AUDIT REPORT", "ar": "مسودة أعمال تدقيق - ليست تقرير تدقيق"}

# sig-v1: versioned deliverable type list in three classes. A type missing from the table = signature required.
SIG_V1: dict[str, dict[str, Any]] = {
    "licence_subscription_confirmation": {"class": "A", "signature_required": False, "issuable": True, "official": True, "label_en": "Licence and subscription confirmation (platform-generated, informational)", "label_ar": "تأكيد الرخصة والاشتراك (صادر عن المنصة، للعلم)", "note": "platform-generated, not an official certificate"},
    "compliance_status_report": {"class": "A", "signature_required": False, "issuable": True, "official": True, "label_en": "Compliance status summary (platform-generated, informational)", "label_ar": "ملخص حالة الامتثال (صادر عن المنصة، للعلم)", "note": "rules to be confirmed by DET"},
    "bookkeeping_summary": {"class": "A", "signature_required": False, "issuable": True, "official": True, "label_en": "Bookkeeping summary (prepared from supplied data, not audited)", "label_ar": "ملخص الدفاتر (أُعدّ من البيانات المقدَّمة، غير مدقق)", "note": "prepared from supplied data, not audited"},
    "tax_pack_draft": {"class": "A", "signature_required": False, "issuable": True, "official": False, "approval_required": True, "label_en": "Tax calculation summary (draft)", "label_ar": "ملخص الحساب الضريبي (مسودة)", "watermark": DRAFT_WATERMARK_TAX},
    "audit_working_paper_summary": {"class": "A", "signature_required": False, "issuable": True, "official": False, "label_en": "Audit work draft summary (draft)", "label_ar": "ملخص مسودة أعمال تدقيق (مسودة)", "watermark": AUDIT_WATERMARK},
    "auditors_report": {"class": "B", "signature_required": True, "issuable": True, "official": True, "switch": AUDITORS_REPORT_SWITCH, "label_en": "Auditor's report", "label_ar": "تقرير مدقق الحسابات", "signed_by_licensed_auditor": True},
    "assurance_or_agreed_procedures_report": {"class": "B", "signature_required": True, "issuable": False, "official": True, "label_en": "Assurance or agreed-upon procedures output (licensed signer only)", "label_ar": "مخرج تأكيد أو إجراءات متفق عليها (للموقّع المرخّص فقط)"},
    "c1_unsigned_audit_named_output": {"class": "C", "signature_required": True, "issuable": False, "official": False, "label_en": "Not offered", "label_ar": "غير متاح"},
    "c2_authority_acceptance_claim": {"class": "C", "signature_required": True, "issuable": False, "official": False, "label_en": "Not offered", "label_ar": "غير متاح"},
    "c3_legal_opinion": {"class": "C", "signature_required": True, "issuable": False, "official": False, "label_en": "Not offered", "label_ar": "غير متاح"},
}
BANNED = ("audit certificate", "audit report", "certified", "شهادة تدقيق")
ALLOWED_NEGATIONS = ("not an audit report or certificate", "not an audit report", "is not an audit report", "ليست تقرير تدقيق", "وليست تقرير تدقيق", "ليس تقرير تدقيق", "وليس تقرير تدقيق")


class RateLimited(PlatformError):
    status_code = 429
    reason_code = "RATE_LIMITED"


# --- banned terms -------------------------------------------------------------------------------------------


def banned_terms_found(text: str) -> list[str]:
    """Banned terms on unsigned outputs: 'audit report' (except in the negation), 'audit certificate', 'certified'."""
    low = (text or "").casefold()
    for neg in ALLOWED_NEGATIONS:
        low = low.replace(neg.casefold(), " ")
    return [t for t in BANNED if t.casefold() in low]


# --- type table ------------------------------------------------------------------------------------------------


def sig_table(db: Session) -> dict[str, dict]:
    params = rule_params(db, "sig-v1", {"types": SIG_V1})
    return params.get("types") or SIG_V1


def type_info(db: Session, doc_type: str) -> dict:
    info = sig_table(db).get(doc_type)
    if info is None:  # fail closed: missing type = signature required, not issuable without a signer
        return {"class": "unknown", "signature_required": True, "issuable": False, "official": False, "label_en": doc_type, "label_ar": doc_type}
    return info


# --- bilingual-fields-v1 normalisation --------------------------------------------------------------------------

ARABIC_INDIC = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹٫٬", "01234567890123456789.,")
AR_DIACRITICS = re.compile(r"[ؐ-ًؚ-ٰٟۖ-ۭـ]")
AR_VARIANTS = str.maketrans({"أ": "ا", "إ": "ا", "آ": "ا", "ى": "ي", "ة": "ه"})
MONTHS_EN = ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november", "december"]
MONTHS_AR = ["يناير", "فبراير", "مارس", "أبريل", "مايو", "يونيو", "يوليو", "أغسطس", "سبتمبر", "أكتوبر", "نوفمبر", "ديسمبر"]


def norm_digits(v: str) -> str:
    return (v or "").translate(ARABIC_INDIC)


def norm_text(v: Any) -> str:
    t = unicodedata.normalize("NFC", norm_digits(str(v or "")))
    t = AR_DIACRITICS.sub("", t).translate(AR_VARIANTS)
    return re.sub(r"\s+", " ", t).strip().casefold()


def norm_date(v: Any) -> str | None:
    if v is None or v == "":
        return None
    if isinstance(v, (date, datetime)):
        return (v.date() if isinstance(v, datetime) else v).isoformat()
    t = norm_digits(str(v)).strip()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", t):
        return t
    m = re.fullmatch(r"(\d{1,2})\s+(\S+)\s+(\d{4})", t)
    if m:
        name = m.group(2).casefold()
        months = [x.casefold() for x in MONTHS_EN]
        idx = months.index(name) if name in months else (MONTHS_AR.index(m.group(2)) if m.group(2) in MONTHS_AR else -1)
        if idx >= 0:
            return date(int(m.group(3)), idx + 1, int(m.group(1))).isoformat()
    return norm_text(t)


def norm_amount(v: Any) -> int | None:
    """AED two decimals in fils; round half up once at the final figure."""
    if v is None or v == "":
        return None
    if isinstance(v, int):
        return v
    t = norm_digits(str(v)).replace("AED", "").replace("درهم", "").replace(",", "").strip()
    try:
        return int((Decimal(t) * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    except Exception:  # noqa: BLE001 - unparsable amount counts as a mismatch
        return None


def fmt_date(iso: str | None, lang: str) -> str:
    if not iso:
        return ""
    d = date.fromisoformat(iso)
    month = MONTHS_AR[d.month - 1] if lang == "ar" else MONTHS_EN[d.month - 1].capitalize()
    return f"{d.day} {month} {d.year}"


def fmt_amount(fils: int | None) -> str:
    if fils is None:
        return ""
    return f"AED {Decimal(fils) / 100:,.2f}"


FIELD_KINDS = {"company_name": "name", "licence_number": "id", "trn": "id", "period": "text", "doc_type": "text", "status": "text", "generated_date": "date", "version": "id", "source_reference": "id"}


def _kind(key: str) -> str:
    if key.startswith("amount_"):
        return "amount"
    if key.endswith("_date"):
        return "date"
    return FIELD_KINDS.get(key, "text")


def build_language_fields(fields: dict, overrides: dict | None, lang: str) -> dict:
    out: dict[str, str] = {}
    for k, v in fields.items():
        kind = _kind(k)
        if isinstance(v, dict) and set(v) <= {"en", "ar"}:
            out[k] = v.get(lang) or ""
        elif kind == "date":
            out[k] = fmt_date(norm_date(v), lang)
        elif kind == "amount":
            out[k] = fmt_amount(norm_amount(v))
        else:
            out[k] = "" if v is None else str(v)
    out.update((overrides or {}).get(lang, {}))
    return out


def bilingual_check(db: Session, *, fields: dict, fields_en: dict, fields_ar: dict, company_id: str, doc_type: str, official: bool, event: str, document_id: str | None = None, det_names: dict | None = None) -> BilingualCheck:
    mismatched, missing, warnings = [], [], []
    for k, v in fields.items():
        kind = _kind(k)
        en, ar = fields_en.get(k, ""), fields_ar.get(k, "")
        if kind == "name":
            src = det_names or (v if isinstance(v, dict) else {})
            if not src.get("en") and not src.get("ar"):
                missing.append(k)
                continue
            if not src.get("ar") or not src.get("en"):
                warnings.append("second_language_name_not_on_det_record")
            for lang, val in (("en", en), ("ar", ar)):
                if src.get(lang) and norm_text(val) != norm_text(src[lang]):
                    mismatched.append(k)
                    break
            continue
        if v is None or v == "":
            missing.append(k)
            continue
        if kind == "date":
            same = norm_date(en) == norm_date(ar) == norm_date(v)
        elif kind == "amount":
            same = norm_amount(en) == norm_amount(ar) == norm_amount(v)
        elif kind == "id":
            same = norm_text(en) == norm_text(ar)
        elif isinstance(v, dict):
            same = bool(en) and bool(ar)  # translated text: both languages present (narrative quality is non-blocking)
        else:
            same = norm_text(en) == norm_text(ar)
        if not same:
            mismatched.append(k)
    chk = BilingualCheck(document_id=document_id, company_id=company_id, doc_type=doc_type, event=event, official=official, fields_checked=sorted(fields), fields_mismatched=sorted(set(mismatched)), fields_missing=sorted(missing), warnings=warnings, document_mismatch=bool(mismatched or missing))
    db.add(chk)
    db.flush()
    record_event(db, event_type="DOCUMENT_CHECK", category="document", outcome="failed" if chk.document_mismatch else "success", company_id=company_id, subject_type="document", subject_id=document_id, details={"kpi": "K28", "event": event, "class": "official" if official else "draft", "doc_type": doc_type, "fields_checked": len(chk.fields_checked), "fields_mismatched": chk.fields_mismatched, "fields_missing": chk.fields_missing, "document_mismatch": chk.document_mismatch})
    return chk


# --- generation ----------------------------------------------------------------------------------------------------


def new_code(db: Session) -> str:
    """16 Crockford base32 characters (80 bits, CSPRNG), never reused, no company data, no expiry."""
    while True:
        n = int.from_bytes(secrets.token_bytes(10), "big")
        code = "".join(CROCKFORD[(n >> (5 * i)) & 31] for i in range(16))[::-1]
        if db.scalar(select(IssuedDocument.id).where(IssuedDocument.verification_code == code)) is None:
            return code


def _reference(db: Session) -> str:
    while True:
        ref = "QX-DOC-" + "".join(secrets.choice(CROCKFORD) for _ in range(8))
        if db.scalar(select(IssuedDocument.id).where(IssuedDocument.reference == ref)) is None:
            return ref


def sha(text: str | bytes) -> str:
    return hashlib.sha256(text.encode() if isinstance(text, str) else text).hexdigest()


def canonical(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, default=str, separators=(",", ":"), ensure_ascii=False)


def _esc(v: Any) -> str:
    return html.escape("" if v is None else str(v))


def render_file(doc: IssuedDocument, lang: str) -> str:
    """One language file, deterministic from the pinned source record (hashes are computed over this)."""
    fields = doc.fields_ar if lang == "ar" else doc.fields_en
    title = doc.title_ar if lang == "ar" else doc.title_en
    rows = "".join(f"<tr><th scope='row'>{_esc(k)}</th><td><bdi>{_esc(v)}</bdi></td></tr>" for k, v in fields.items())
    body = doc.source_record.get("lines") or []
    lines = "".join(f"<tr><td>{_esc((ln.get('label') or {}).get(lang, ''))}</td><td dir='ltr'><bdi>{_esc(fmt_amount(ln.get('value_fils')) if ln.get('value_fils') is not None else (ln.get('text') or '—'))}</bdi></td></tr>" for ln in body)
    wm = doc.watermark or {}
    watermark = f"<div class='wm' aria-hidden='true' data-artifact='watermark'><div>{_esc(wm.get('en'))}</div><div lang='ar' dir='rtl'>{_esc(wm.get('ar'))}</div></div>" if wm else ""
    clause = f"<p class='clause' data-version='{_esc(doc.precedence_clause_version)}'>{_esc(s('precedence_clause', lang))}</p>" if doc.precedence_clause_version else ""
    code = f"<p class='code'>{_esc('Verification code' if lang == 'en' else 'رمز التحقق')}: <bdi dir='ltr'>{_esc(doc.verification_code)}</bdi></p>" if doc.verification_code else f"<p class='code'>{_esc('No verification code' if lang == 'en' else 'لا يوجد رمز تحقق')}</p>"
    draft_label = (doc.source_record.get("draft_label") or {}).get(lang)
    notes = f"<p>{_esc(s('no_assurance', lang))}</p>" if doc.official else f"<p><strong>{_esc(s('ai_draft_label', lang))}</strong></p>" + (f"<p><strong>{_esc(draft_label)}</strong></p>" if draft_label else "")
    return (f"<section lang='{lang}' dir='{'rtl' if lang == 'ar' else 'ltr'}' class='docfile'>{watermark}<h2>{_esc(title)}</h2>"
            f"<p>{_esc('Reference' if lang == 'en' else 'المرجع')}: <bdi dir='ltr'>{_esc(doc.reference)}</bdi> · {_esc('Version' if lang == 'en' else 'الإصدار')} <bdi>{doc.version_no}</bdi></p>{notes}"
            f"<table>{rows}</table>{'<table>' + lines + '</table>' if lines else ''}{clause}{code}</section>")


def _hashes(doc: IssuedDocument) -> tuple[str, str, str, str]:
    h_en, h_ar = sha(render_file(doc, "en")), sha(render_file(doc, "ar"))
    h_payload = sha(canonical(doc.source_record))
    return h_en, h_ar, h_payload, sha(h_en + h_ar + h_payload)


def _actor_fields(actor: Any) -> tuple[str | None, str, str | None]:
    if actor is None or isinstance(actor, str):
        return None, actor or "Qeonix platform (AI agent)", None
    return getattr(actor, "identity_uuid", None), getattr(actor, "display_name", "unknown"), getattr(actor, "actor_key", None)


def _det_names(db: Session, company_id: str) -> tuple[dict, str | None]:
    try:
        from app.modules.licences.models import Licence

        lic = db.scalar(select(Licence).where(Licence.company_id == company_id).order_by(Licence.issue_date.desc()).limit(1))
        if lic is not None:
            return {"en": lic.trade_name_en, "ar": lic.trade_name_ar}, lic.licence_number
    except ImportError:  # pragma: no cover
        pass
    return {}, None


def issue_document(db: Session, company_id: str, doc_type: str, source_record: dict, actor: Any, *, is_demo: bool = False, approval_ref: str | None = None) -> IssuedDocument:
    """Public entry point for other modules. Fails closed on unknown types, signature-required types, switched-off
    types, banned wording and (for official documents) any bilingual key-field mismatch or missing field."""
    info = type_info(db, doc_type)
    uuid, name, actor_key = _actor_fields(actor)
    if not info.get("issuable") or info.get("class") in ("C", "unknown"):
        record_event(db, event_type="ISSUE_REFUSED", category="document", outcome="refused", reason_code="TYPE_NOT_OFFERED" if info.get("class") != "unknown" else "TYPE_UNKNOWN_SIGNATURE_REQUIRED", actor_key=actor_key, company_id=company_id, details={"doc_type": doc_type})
        raise Forbidden(s("refused_signature", "en"), reason_code="SIGNATURE_REQUIRED" if info.get("signature_required") else "TYPE_NOT_OFFERED", details={"text": both("refused_signature")})
    if info.get("switch") and not get_config(db, info["switch"], False):
        record_event(db, event_type="ISSUE_REFUSED", category="document", outcome="refused", reason_code="FEATURE_SWITCHED_OFF", actor_key=actor_key, company_id=company_id, details={"doc_type": doc_type})
        raise SwitchedOff("This document type is switched off in this version.", reason_code="FEATURE_SWITCHED_OFF")
    if info.get("signature_required") and not (source_record.get("signer_name") and source_record.get("signer_licence") and source_record.get("sign_record_id") and source_record.get("register_snapshot_id")):
        record_event(db, event_type="ISSUE_REFUSED", category="document", outcome="refused", reason_code="SIGNATURE_REQUIRED", actor_key=actor_key, company_id=company_id, details={"doc_type": doc_type})
        raise Forbidden(s("refused_signature", "en"), reason_code="SIGNATURE_REQUIRED", details={"text": both("refused_signature")})
    official = bool(info.get("official"))
    det_names, lic_no = _det_names(db, company_id)
    fields = dict(source_record.get("fields") or {})
    fields.setdefault("company_name", det_names or None)
    fields.setdefault("licence_number", lic_no)
    fields.setdefault("doc_type", {"en": info["label_en"], "ar": info["label_ar"]})
    fields.setdefault("generated_date", source_record.get("generated_date") or dubai_today().isoformat())
    title = {"en": info["label_en"], "ar": info["label_ar"]}
    signed = bool(info.get("signature_required"))
    file_names = {lang: re.sub(r"[^A-Za-z0-9_-]+", "-", f"{doc_type}-{dubai_today().isoformat()}-{lang}").strip("-") + ".html" for lang in ("en", "ar")}
    watermark = (source_record.get("watermark") if not official else None) or info.get("watermark") or (None if official else both("ai_draft_label"))
    if not signed:
        texts = [title["en"], title["ar"], file_names["en"], file_names["ar"], *(watermark or {}).values()]
        hits = sorted({t for x in texts for t in banned_terms_found(x)})
        if hits:
            record_event(db, event_type="WORDING_BLOCKED", category="document", outcome="refused", reason_code="BANNED_TERM", actor_key=actor_key, company_id=company_id, details={"doc_type": doc_type, "terms": hits})
            raise Forbidden("This file cannot be issued: its wording is not allowed for an unsigned output.", reason_code="WORDING_BLOCKED")
    fields_en = build_language_fields(fields, source_record.get("overrides"), "en")
    fields_ar = build_language_fields(fields, source_record.get("overrides"), "ar")
    chk = bilingual_check(db, fields=fields, fields_en=fields_en, fields_ar=fields_ar, company_id=company_id, doc_type=doc_type, official=official, event="issue", det_names=det_names)
    if official and chk.document_mismatch:
        bad = ", ".join(chk.fields_mismatched + chk.fields_missing)
        record_event(db, event_type="BILINGUAL_MISMATCH_REVIEWER_NOTIFIED", category="document", outcome="refused", reason_code="BILINGUAL_MISMATCH", actor_key=actor_key, company_id=company_id, details={"fields": chk.fields_mismatched, "missing": chk.fields_missing, "to": "compliance_reviewer"})
        raise Conflict(s("refused_mismatch", "en", field=bad), reason_code="BILINGUAL_MISMATCH", details={"fields": chk.fields_mismatched, "missing": chk.fields_missing, "text": both("refused_mismatch", field=bad)})
    cands = db.scalars(select(IssuedDocument).where(IssuedDocument.company_id == company_id, IssuedDocument.doc_type == doc_type, IssuedDocument.status.in_(("issued", "draft", "signed")), IssuedDocument.superseded_by_id.is_(None)).order_by(IssuedDocument.issued_at.desc()))
    prev = next((d for d in cands if str(d.source_record.get("period_key")) == str(source_record.get("period_key"))), None)
    record = {**source_record, "fields": fields}
    record.pop("overrides", None)
    doc = IssuedDocument(company_id=company_id, doc_type=doc_type, type_class=info["class"], reference=_reference(db), title_en=title["en"], title_ar=title["ar"], file_name_en=file_names["en"], file_name_ar=file_names["ar"], version_no=(prev.version_no + 1) if prev else 1, status="issued" if official else "draft", official=official, watermark=watermark, source_record=record, fields_en=fields_en, fields_ar=fields_ar, data_version=sha(canonical(record))[:16], hash_en="", hash_ar="", hash_payload="", manifest_hash="", chain_hash="", issued_by_uuid=uuid, issued_by_name=name, approval_ref=approval_ref, supersedes_id=prev.id if prev else None, signer_name=source_record.get("signer_name"), signer_licence=source_record.get("signer_licence"), register_snapshot_id=source_record.get("register_snapshot_id"), signed_status="signed_valid" if signed else None, is_demo=is_demo, shared_with_uuids=[])
    if official:
        doc.verification_code = new_code(db)
        if not signed:
            doc.precedence_clause_version = str(get_config(db, "documents.precedence_clause.version", "pc-v1"))
    doc.hash_en, doc.hash_ar, doc.hash_payload, doc.manifest_hash = _hashes(doc)
    last = db.scalar(select(IssuedDocument).order_by(IssuedDocument.created_at.desc()).limit(1))
    doc.chain_prev = last.chain_hash if last else None
    doc.chain_hash = sha((doc.chain_prev or "") + doc.manifest_hash)
    db.add(doc)
    db.flush()
    chk.document_id = doc.id
    if prev is not None:
        prev.status, prev.superseded_by_id, prev.superseded_at = "superseded", doc.id, utcnow()
        if prev.signed_status:
            prev.signed_status = "withdrawn_or_superseded"
        record_event(db, event_type="DOCUMENT_SUPERSEDED", category="document", actor_key=actor_key, company_id=company_id, subject_type="document", subject_id=prev.id, details={"superseded_by": doc.id})
    record_event(db, event_type="DOCUMENT_ISSUED" if official else "DOCUMENT_DRAFT_GENERATED", category="document", actor_key=actor_key, company_id=company_id, subject_type="document", subject_id=doc.id, details={"doc_type": doc_type, "class": info["class"], "official": official, "manifest_hash": doc.manifest_hash, "version_no": doc.version_no})
    return doc


def issue_tax_pack_draft(db: Session, pack_id: str, actor: Any, *, is_demo: bool = False) -> IssuedDocument:
    """Watermarked tax-pack draft from the drafts module's pack (Class A, issuable as draft only)."""
    from app.modules.drafts.models import WATERMARK, DraftPack
    from app.modules.drafts.service import pack_dict

    pack = db.get(DraftPack, pack_id)
    if pack is None:
        raise NotFound("not available", reason_code="NOT_FOUND")
    d = pack_dict(db, pack)
    lines = [{"key": ln.get("key"), "label": ln.get("term") or {"en": ln.get("key"), "ar": ln.get("key")}, "value_fils": ln.get("value_fils"), "text": ln.get("text")} for ln in d.get("lines") or []]
    source = {"fields": {"period": d["period_id"], "status": {"en": d["review_status_label"]["en"], "ar": d["review_status_label"]["ar"]}, "version": str(d["version"]), "source_reference": d["data_version"]}, "lines": lines, "pack_id": pack.id, "period_key": f"{d['tax_type']}:{d['period_id']}", "watermark": dict(WATERMARK), "draft_label": DRAFT_WATERMARK_TAX}
    return issue_document(db, pack.company_id, "tax_pack_draft", source, actor, is_demo=is_demo)


# --- source records for the Phase 1 issuable types ------------------------------------------------------------------


def build_source_record(db: Session, company_id: str, doc_type: str, *, pack_id: str | None = None) -> dict:
    if doc_type == "licence_subscription_confirmation":
        from app.modules.licences.models import Licence

        lic = db.scalar(select(Licence).where(Licence.company_id == company_id).limit(1))
        sub = None
        try:
            from app.modules.subscriptions.models import Subscription

            sub = db.scalar(select(Subscription).where(Subscription.company_id == company_id).order_by(Subscription.start_date.desc()).limit(1))
        except ImportError:  # pragma: no cover
            pass
        return {"fields": {"licence_status": {"en": (lic.status if lic else "unknown"), "ar": {"active": "سارية", "expired": "منتهية"}.get(lic.status if lic else "", "غير معروف")}, "licence_expiry_date": lic.expiry_date.isoformat() if lic and lic.expiry_date else None, "subscription_status": {"en": sub.status if sub else "not started", "ar": {"active": "نشط"}.get(sub.status, sub.status) if sub else "لم يبدأ"}, "subscription_end_date": sub.end_date.isoformat() if sub else None}, "period_key": "current"}
    if doc_type == "compliance_status_report":
        from app.modules.licences.models import Licence

        lic = db.scalar(select(Licence).where(Licence.company_id == company_id).limit(1))
        rows = []
        if lic:
            rows = [{"label": {"en": "Trade licence expiry", "ar": "انتهاء الرخصة التجارية"}, "text": lic.expiry_date.isoformat() if lic.expiry_date else "—"}, {"label": {"en": "Ejari expiry", "ar": "انتهاء إيجاري"}, "text": lic.ejari_expiry.isoformat() if lic.ejari_expiry else "—"}, {"label": {"en": "Chamber membership", "ar": "عضوية الغرفة"}, "text": lic.chamber_membership_status or "—"}]
        return {"fields": {"as_of_date": dubai_today().isoformat(), "rules_status": {"en": "rules to be confirmed by DET", "ar": "القواعد بانتظار تأكيد الدائرة"}}, "lines": rows, "period_key": dubai_today().isoformat()[:7]}
    if doc_type == "bookkeeping_summary":
        return {"fields": {"as_of_date": dubai_today().isoformat(), "basis": {"en": "prepared from supplied data, not audited", "ar": "أُعدّ من البيانات المقدَّمة، غير مدقق"}}, "period_key": dubai_today().isoformat()[:7]}
    if doc_type == "audit_working_paper_summary":
        from app.modules.auditagent import workfile as wf

        f = wf.current_file(db, company_id)
        if f is None:
            raise NotFound("No audit work draft yet.", reason_code="NO_DRAFT")
        return {"fields": {"period": f"{f.period_start.isoformat()}_{f.period_end.isoformat()}", "status": wf.status_label(db, f), "version": str(f.version_no)}, "lines": [{"label": x["label"], "value_fils": x.get("value_fils"), "text": None if x.get("value_fils") is not None else f"Gap {x.get('gap') or '?'}"} for x in (f.ai_prepared_content or {}).get("figures", [])], "period_key": f.id}
    raise ValidationFailed("this document type cannot be prepared from here", reason_code="TYPE_NOT_SUPPORTED")


# --- access, delivery, sharing --------------------------------------------------------------------------------------


def role_on(principal: Any, company_id: str) -> str | None:
    roles = principal.roles_for(company_id)
    return roles[0].role if roles else None


def can_see(principal: Any, doc: IssuedDocument) -> bool:
    """Owner / authorised signatory: all; delegates only documents shared with them (assigned); others never."""
    role = role_on(principal, doc.company_id)
    if role in ("owner", "remote_owner"):
        return True
    if role == "delegate":
        return principal.identity_uuid in (doc.shared_with_uuids or [])
    return False


def visible_documents(db: Session, principal: Any, company_id: str) -> list[IssuedDocument]:
    docs = list(db.scalars(select(IssuedDocument).where(IssuedDocument.company_id == company_id).order_by(IssuedDocument.issued_at.desc())))
    return [d for d in docs if can_see(principal, d)]


def get_document(db: Session, principal: Any, company_id: str, doc_id: str) -> IssuedDocument:
    doc = db.get(IssuedDocument, doc_id)
    if doc is None or doc.company_id != company_id:
        raise NotFound("not available", reason_code="NOT_FOUND")
    if not can_see(principal, doc):
        record_event(db, event_type="ACCESS_REFUSED", category="access", outcome="refused", reason_code="DOCUMENT_NOT_SHARED", actor_key=principal.actor_key, company_id=company_id, subject_type="document", subject_id=doc_id)
        raise Forbidden(s("ask_owner_access", "en"), reason_code="DOCUMENT_NOT_SHARED", details={"text": both("ask_owner_access")})
    return doc


def log_delivery(db: Session, doc: IssuedDocument, *, event: str, actor_name: str, actor_role: str, actor_key: str | None, lang: str | None = None) -> DeliveryLog:
    row = DeliveryLog(document_id=doc.id, company_id=doc.company_id, event=event, actor_name=actor_name, actor_role=actor_role, lang=lang)
    db.add(row)
    db.flush()
    record_event(db, event_type="DOCUMENT_DELIVERED", category="document", actor_key=actor_key, actor_role=actor_role, company_id=doc.company_id, subject_type="document", subject_id=doc.id, details={"kpi": "K28", "event": event, "lang": lang, "class": "official" if doc.official else "draft"})
    return row


def download(db: Session, doc: IssuedDocument, *, actor_name: str, actor_role: str, actor_key: str | None, kind: str = "downloaded", lang: str | None = None) -> dict:
    """Every download re-runs the bilingual check and stores the result (K28)."""
    if kind not in ("downloaded", "exported"):
        raise ValidationFailed("kind must be downloaded or exported", reason_code="VALIDATION_FAILED")
    det_names, _ = _det_names(db, doc.company_id)
    chk = bilingual_check(db, fields=doc.source_record.get("fields") or {}, fields_en=doc.fields_en, fields_ar=doc.fields_ar, company_id=doc.company_id, doc_type=doc.doc_type, official=doc.official, event="download", document_id=doc.id, det_names=det_names)
    log_delivery(db, doc, event=kind, actor_name=actor_name, actor_role=actor_role, actor_key=actor_key, lang=lang)
    return {"file_name_en": doc.file_name_en, "file_name_ar": doc.file_name_ar, "render_url": f"/api/companies/{doc.company_id}/documents/{doc.id}/render", "check": {"document_mismatch": chk.document_mismatch, "fields_mismatched": chk.fields_mismatched, "versions_match": both("versions_match") if not chk.document_mismatch else None}}


def share(db: Session, doc: IssuedDocument, principal: Any, recipient_uuid: str) -> IssuedDocument:
    """Owner / authorised signatory shares with a delegate assigned to the company; outside: verification link only."""
    from app.modules.companies.models import CompanyRole

    if role_on(principal, doc.company_id) != "owner":
        raise Forbidden("Only the owner or authorised signatory can share documents.", reason_code="OWNER_ONLY")
    target = db.scalar(select(CompanyRole).where(CompanyRole.company_id == doc.company_id, CompanyRole.identity_uuid == recipient_uuid, CompanyRole.role == "delegate", CompanyRole.status == "active"))
    if target is None:
        raise ValidationFailed("documents are shared only with delegates assigned to this company", reason_code="RECIPIENT_NOT_ASSIGNED")
    doc.shared_with_uuids = sorted(set(doc.shared_with_uuids or []) | {recipient_uuid})
    log_delivery(db, doc, event="shared", actor_name=principal.display_name, actor_role="owner", actor_key=principal.actor_key)
    return doc


# --- revoke, signed-status layer, switch -------------------------------------------------------------------------------


def revoke(db: Session, doc: IssuedDocument, *, reason_code: str, note: str | None, request_ref: str | None, requested_by_role: str | None, actor_name: str, actor_role: str, actor_key: str | None) -> IssuedDocument:
    """Revoke needs a reason; by the signer or a Qeonix platform administrator on written request. Record is kept."""
    if actor_role == "compliance_reviewer":
        raise Forbidden("The compliance reviewer can submit a written request but cannot revoke.", reason_code="REVOKE_NOT_ALLOWED")
    if reason_code not in REVOKE_REASONS:
        raise ValidationFailed("a coded revocation reason is required", reason_code="REASON_REQUIRED", details={"codes": list(REVOKE_REASONS)})
    if actor_role == "platform_security_admin" and not request_ref:
        raise ValidationFailed("administrators revoke only on a written request (reference required)", reason_code="WRITTEN_REQUEST_REQUIRED")
    if doc.status == "revoked":
        return doc
    doc.status, doc.revoked_at, doc.revoked_reason_code, doc.revoked_note, doc.revoked_by, doc.revoke_request_ref = "revoked", utcnow(), reason_code, note, actor_name, request_ref
    if doc.signed_status:
        doc.signed_status = "withdrawn_or_superseded"
    record_event(db, event_type="REVOKE", category="document", actor_key=actor_key, actor_role=actor_role, company_id=doc.company_id, subject_type="document", subject_id=doc.id, details={"reason_code": reason_code, "request_ref": request_ref, "requested_by_role": requested_by_role})
    db.flush()
    return doc


def set_signed_status(db: Session, doc: IssuedDocument, *, status: str, source: str, ref: str, actor_key: str | None) -> IssuedDocument:
    """Signed-output status layer: changed only on instruction from the signing firm or an authority."""
    from app.modules.documents.models import SIGNED_STATUS_LAYER

    if not doc.signer_name:
        raise ValidationFailed("only signed outputs carry this status layer", reason_code="NOT_SIGNED_OUTPUT")
    if source not in ("signing_firm", "authority") or not ref:
        raise Forbidden("changed only on instruction from the signing firm or an authority", reason_code="INSTRUCTION_REQUIRED")
    if status not in SIGNED_STATUS_LAYER:
        raise ValidationFailed("unknown status", reason_code="VALIDATION_FAILED")
    doc.signed_status, doc.signed_status_source, doc.signed_status_ref = status, source, ref
    record_event(db, event_type="SIGNED_STATUS_CHANGED", category="document", actor_key=actor_key, company_id=doc.company_id, subject_type="document", subject_id=doc.id, details={"status": status, "source": source})
    return doc


def request_switch(db: Session, *, key: str, new_state: bool, reason: str, requested_by: str) -> SwitchRequest:
    if not reason:
        raise ValidationFailed("a reason is required", reason_code="REASON_REQUIRED")
    req = SwitchRequest(key=key, new_state=new_state, old_state=bool(get_config(db, key, False)), reason=reason, requested_by=requested_by)
    db.add(req)
    db.flush()
    record_event(db, event_type="ISSUE_SWITCH_TOGGLE_REQUESTED", category="config", subject_type="switch", subject_id=key, details={"new_state": new_state})
    return req


def approve_switch(db: Session, request_id: str, *, approver: str) -> SwitchRequest:
    req = db.get(SwitchRequest, request_id)
    if req is None or req.status != "pending":
        raise NotFound("not available", reason_code="NOT_FOUND")
    if approver == req.requested_by:
        record_event(db, event_type="ISSUE_SWITCH_TOGGLE_REFUSED", category="config", outcome="refused", reason_code="SECOND_APPROVER_REQUIRED", subject_type="switch", subject_id=req.key)
        raise Forbidden("a second, different administrator must approve", reason_code="SECOND_APPROVER_REQUIRED")
    set_config(db, req.key, req.new_state, changed_by=req.requested_by, approved_by=approver, change_reason=req.reason, require_second_approver=True)
    req.status, req.approved_by, req.approved_at = "applied", approver, utcnow()
    record_event(db, event_type="ISSUE_SWITCH_TOGGLED", category="config", subject_type="switch", subject_id=req.key, details={"old": req.old_state, "new": req.new_state})
    return req


# --- public verification --------------------------------------------------------------------------------------------


def _ip_hash(ip: str | None) -> str:
    return sha(f"ip|{ip or 'unknown'}")


def _rate_limit(db: Session, ip_hash: str, code_key: str, now: datetime) -> None:
    per_ip = int(get_config(db, "documents.verify.rate_limit_per_ip_per_minute", 30) or 30)
    per_code = int(get_config(db, "documents.verify.rate_limit_per_code_per_hour", 10) or 10)
    lock = get_config(db, "documents.verify.lockout", {"failed": 10, "window_minutes": 10, "lockout_minutes": 15}) or {}
    failed_n, window, lock_min = int(lock.get("failed", 10)), int(lock.get("window_minutes", 10)), int(lock.get("lockout_minutes", 15))
    fails = list(db.scalars(select(VerificationLookup.at).where(VerificationLookup.ip_hash == ip_hash, VerificationLookup.outcome == "not_found", VerificationLookup.at >= now - timedelta(minutes=window + lock_min)).order_by(VerificationLookup.at)))
    for i in range(failed_n - 1, len(fails)):
        if fails[i] - fails[i - failed_n + 1] <= timedelta(minutes=window) and now < fails[i] + timedelta(minutes=lock_min):
            record_event(db, event_type="VERIFY_LOOKUP", category="document", outcome="refused", reason_code="LOCKED_OUT", details={"limit": "lockout"})
            raise RateLimited(s("locked_out", "en"), reason_code="LOCKED_OUT", details={"text": both("locked_out"), "wait_minutes": lock_min})
    if db.scalar(select(func.count(VerificationLookup.id)).where(VerificationLookup.ip_hash == ip_hash, VerificationLookup.at >= now - timedelta(minutes=1))) >= per_ip:
        record_event(db, event_type="VERIFY_LOOKUP", category="document", outcome="refused", reason_code="RATE_LIMITED", details={"limit": "per_ip"})
        raise RateLimited(s("rate_limited", "en", n=1), reason_code="RATE_LIMITED", details={"text": both("rate_limited", n=1), "wait_minutes": 1})
    if db.scalar(select(func.count(VerificationLookup.id)).where(VerificationLookup.code_key == code_key, VerificationLookup.at >= now - timedelta(hours=1))) >= per_code:
        record_event(db, event_type="VERIFY_LOOKUP", category="document", outcome="refused", reason_code="RATE_LIMITED", details={"limit": "per_code"})
        raise RateLimited(s("rate_limited", "en", n=60), reason_code="RATE_LIMITED", details={"text": both("rate_limited", n=60), "wait_minutes": 60})


def verify(db: Session, code: str, *, ip: str | None, now: datetime | None = None) -> dict:
    """Public check: status and reference only, never financial figures. Unknown, malformed and never-issued codes
    return one identical 'not found' response."""
    now = now or utcnow()
    raw = norm_digits(code or "").strip().upper().replace("-", "")
    canon = raw.translate(str.maketrans({"O": "0", "I": "1", "L": "1"}))
    ip_h, code_key = _ip_hash(ip), sha(f"code|{canon}")
    _rate_limit(db, ip_h, code_key, now)
    doc = None
    if re.fullmatch(r"[0-9A-HJKMNP-TV-Z]{16}", canon):
        doc = db.scalar(select(IssuedDocument).where(IssuedDocument.verification_code == canon))
    if doc is not None and doc.status not in ("issued", "superseded", "revoked"):
        doc = None  # only issued codes show a status
    if doc is None:
        sha(canon)  # similar work for unknown codes
        out = {"status": "not_found", "status_label_en": s("not_found", "en"), "status_label_ar": s("not_found", "ar"), "reference": None, "doc_type_label_en": None, "doc_type_label_ar": None, "issued_at": None}
    else:
        h = _hashes(doc)
        intact = (h[0], h[1], h[2], h[3]) == (doc.hash_en, doc.hash_ar, doc.hash_payload, doc.manifest_hash)
        if not intact:
            status, en, ar = "not_valid", s("not_valid", "en"), s("not_valid", "ar")
        elif doc.status == "revoked":
            lbl = REVOKE_REASON_LABELS.get(doc.revoked_reason_code or "", {"en": "revoked", "ar": "ملغى"})
            d = doc.revoked_at.date().isoformat() if doc.revoked_at else ""
            status, en, ar = "revoked", s("revoked", "en", date=d, reason=lbl["en"]), s("revoked", "ar", date=d, reason=lbl["ar"])
        elif doc.status == "superseded":
            status, en, ar = "superseded", s("superseded", "en"), s("superseded", "ar")
        elif doc.signer_name:
            status, en, ar = "valid", s("valid_signed", "en", name=doc.signer_name, number=doc.signer_licence), s("valid_signed", "ar", name=doc.signer_name, number=doc.signer_licence)
        else:
            status, en, ar = "valid", s("valid", "en"), s("valid", "ar")
        out = {"status": status, "status_label_en": en, "status_label_ar": ar, "reference": doc.reference, "doc_type_label_en": doc.title_en, "doc_type_label_ar": doc.title_ar, "issued_at": doc.issued_at.date().isoformat()}
    db.add(VerificationLookup(ip_hash=ip_h, code_key=code_key, at=now, outcome=out["status"]))
    record_event(db, event_type="VERIFY_LOOKUP", category="document", outcome="success" if out["status"] != "not_found" else "not_found", subject_type="document", subject_id=doc.id if doc else None, details={"status": out["status"]})
    db.flush()
    return out


# --- integrity chain and KPIs ---------------------------------------------------------------------------------------------


def chain_check(db: Session) -> dict:
    prev = None
    broken = []
    for d in db.scalars(select(IssuedDocument).order_by(IssuedDocument.created_at)):
        if d.chain_prev != prev or d.chain_hash != sha((d.chain_prev or "") + d.manifest_hash):
            broken.append(d.id)
        prev = d.chain_hash
    record_event(db, event_type="CHAIN_CHECK_RESULT", category="system", outcome="failed" if broken else "success", details={"broken": len(broken)})
    return {"ok": not broken, "broken": broken}


def k28(db: Session) -> dict:
    """Bilingual document completeness: official (issued) and draft reported separately; partial mismatch = failed."""
    out = {}
    for cls, official in (("official", True), ("draft", False)):
        rows = list(db.scalars(select(BilingualCheck).where(BilingualCheck.official.is_(official))))
        docs = {r.document_id or r.id: r for r in rows}
        failed = sum(1 for r in docs.values() if r.document_mismatch)
        fields = sum(len(r.fields_checked) for r in rows)
        mism = sum(len(r.fields_mismatched) for r in rows)
        out[cls] = {"documents": len(docs), "pass_rate": round((len(docs) - failed) / len(docs), 4) if docs else None, "field_mismatch_rate": round(mism / fields, 4) if fields else None}
    return out


def status_label(doc: IssuedDocument) -> dict:
    key = {"draft": "status_draft", "issued": "status_issued", "superseded": "status_superseded", "revoked": "status_revoked", "signed": "status_signed", "in_review": "status_in_review", "withdrawn": "status_withdrawn"}.get(doc.status, "status_draft")
    return both(key)


def doc_dict(db: Session, doc: IssuedDocument, *, detail: bool = False) -> dict:
    out = {
        "id": doc.id, "reference": doc.reference, "doc_type": doc.doc_type, "type_class": doc.type_class, "title": {"en": doc.title_en, "ar": doc.title_ar}, "file_names": {"en": doc.file_name_en, "ar": doc.file_name_ar},
        "version_no": doc.version_no, "status": doc.status, "status_label": status_label(doc), "official": doc.official, "ai_prepared": True, "ai_label": both("ai_draft_label") if not doc.official else {"en": "AI-prepared, platform-generated", "ar": "أعدّه الذكاء الاصطناعي، صادر عن المنصة"},
        "watermark": doc.watermark, "verification_code": doc.verification_code if doc.status in ("issued", "superseded", "revoked") else None, "verify_path": f"/verify/{doc.verification_code}" if doc.verification_code else None,
        "signer_name": doc.signer_name, "signer_licence": doc.signer_licence, "signed_status": doc.signed_status, "issued_at": doc.issued_at.isoformat(), "issued_by": doc.issued_by_name,
        "superseded_by_id": doc.superseded_by_id, "superseded_at": doc.superseded_at.isoformat() if doc.superseded_at else None, "supersedes_id": doc.supersedes_id,
        "revoked_at": doc.revoked_at.isoformat() if doc.revoked_at else None, "revoked_label": None if doc.status != "revoked" else both("revoked", date=doc.revoked_at.date().isoformat() if doc.revoked_at else "", reason=REVOKE_REASON_LABELS.get(doc.revoked_reason_code or "", {}).get("en", "")),
        "banner": both("superseded") if doc.status == "superseded" else None, "is_demo": doc.is_demo, "shared_with": len(doc.shared_with_uuids or []),
    }
    if detail:
        last = db.scalar(select(BilingualCheck).where(BilingualCheck.document_id == doc.id).order_by(BilingualCheck.checked_at.desc()).limit(1))
        out.update({"fields_en": doc.fields_en, "fields_ar": doc.fields_ar, "hashes": {"en": doc.hash_en, "ar": doc.hash_ar, "payload": doc.hash_payload, "manifest": doc.manifest_hash}, "data_version": doc.data_version, "precedence_clause": both("precedence_clause") if doc.precedence_clause_version else None, "precedence_clause_version": doc.precedence_clause_version,
                    "provenance": {"source": doc.source_record.get("pack_id") or doc.source_record.get("period_key"), "model_version": "rules-v1", "review_status": doc.status, "sig_rule_version": doc.sig_rule_version},
                    "bilingual_check": None if last is None else {"event": last.event, "document_mismatch": last.document_mismatch, "fields_mismatched": last.fields_mismatched, "warnings": last.warnings, "versions_match": both("versions_match") if not last.document_mismatch else None}})
    return out


def render_view(db: Session, doc: IssuedDocument, lang: str = "both") -> str:
    """Bilingual side by side (Arabic RTL), with the live status banner outside the hashed files."""
    banner = ""
    if doc.status == "superseded":
        banner = f"<div role='status' class='banner'>{_esc(s('superseded', 'en'))} / <span lang='ar' dir='rtl'>{_esc(s('superseded', 'ar'))}</span></div>"
    elif doc.status == "revoked":
        lbl = REVOKE_REASON_LABELS.get(doc.revoked_reason_code or "", {"en": "", "ar": ""})
        d = doc.revoked_at.date().isoformat() if doc.revoked_at else ""
        banner = f"<div role='alert' class='banner'>{_esc(s('revoked', 'en', date=d, reason=lbl['en']))} / <span lang='ar' dir='rtl'>{_esc(s('revoked', 'ar', date=d, reason=lbl['ar']))}</span></div>"
    panes = {"en": render_file(doc, "en"), "ar": render_file(doc, "ar")}
    order = ["ar", "en"] if lang == "ar" else ["en", "ar"]
    shown = [panes[lang]] if lang in ("en", "ar") else [panes[x] for x in order]
    return (f"<!doctype html><html lang='{'ar' if lang == 'ar' else 'en'}'><head><meta charset='utf-8'><title>{_esc(doc.title_en)} / {_esc(doc.title_ar)}</title>"
            "<style>body{font-family:system-ui,sans-serif;margin:16px}.panes{display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));gap:16px}.docfile{position:relative;border:1px solid #999;padding:12px}"
            ".wm{position:absolute;top:40%;left:0;right:0;text-align:center;transform:rotate(-30deg);opacity:.15;font-size:28px;pointer-events:none}.banner{border:2px solid #333;padding:8px;margin-bottom:12px}"
            "table{border-collapse:collapse;width:100%}th,td{border:1px solid #ccc;padding:4px;text-align:start}@media print{.banner{border-width:1px}}</style></head>"
            f"<body>{banner}<div class='panes'>{''.join(shown)}</div></body></html>")
