"""Bilingual strings for E7-S5 (verbatim from the spec where given; other Arabic is a draft pending native review)."""

from __future__ import annotations

STRINGS: dict[str, dict[str, str]] = {
    "ai_draft_label": {"en": "AI-prepared draft, not signed, not an audit report", "ar": "مسودة أعدّها الذكاء الاصطناعي، غير موقّعة، وليست تقرير تدقيق"},
    "refused_watermark": {"en": "AI-prepared draft, not signed, not an audit report or certificate", "ar": "مسودة أعدّها الذكاء الاصطناعي، غير موقّعة، وليست تقرير تدقيق ولا شهادة"},
    "awaiting_auditor": {"en": "Draft, awaiting licensed auditor", "ar": "مسودة، بانتظار مدقق مرخّص"},
    "valid_signed": {"en": "Valid. Signed by {name}, licence no. {number}", "ar": "ساري. وقّعه {name}، رقم الترخيص {number}"},
    "valid": {"en": "Valid", "ar": "ساري"},
    "superseded": {"en": "Superseded by a newer version. See the current document.", "ar": "تم استبداله بنسخة أحدث. راجع المستند الحالي."},
    "revoked": {"en": "Revoked on {date}: {reason}. Do not rely on it.", "ar": "أُلغي في {date}: {reason}. لا تعتمد عليه."},
    "not_valid": {"en": "Not valid. This document failed an integrity check. Do not rely on it.", "ar": "غير صالح. فشل هذا المستند في فحص السلامة. لا تعتمد عليه."},
    "not_found": {"en": "No document found for this code. Check the code or contact the issuer.", "ar": "لم يُعثر على مستند لهذا الرمز. تحقق من الرمز أو تواصل مع الجهة المُصدِرة."},
    "rate_limited": {"en": "Too many checks from this connection. Wait {n} minutes, then try again.", "ar": "عدد المحاولات كبير جدًا من هذا الاتصال. انتظر {n} دقيقة ثم أعد المحاولة."},
    "locked_out": {"en": "Too many attempts, try later", "ar": "محاولات كثيرة، حاول لاحقًا"},
    "no_financial_data": {"en": "This page shows no financial data.", "ar": "لا تعرض هذه الصفحة أي بيانات مالية."},
    "versions_match": {"en": "Arabic and English versions match", "ar": "النسختان العربية والإنجليزية متطابقتان"},
    "empty_list": {"en": "No documents yet. Your first draft will appear here once your books are linked and a period has closed.", "ar": "لا توجد مستندات بعد. ستظهر أول مسودة هنا بعد ربط دفاترك وإغلاق فترة."},
    "refused_signature": {"en": "Not issued. This document needs a licensed auditor's signature. Only a draft is available.", "ar": "لم يُصدر. يحتاج هذا المستند إلى توقيع مدقق مرخّص. المتاح مسودة فقط."},
    "refused_mismatch": {"en": "Not issued. The Arabic and English versions differ in {field}. A reviewer has been notified.", "ar": "لم يُصدر. تختلف النسختان العربية والإنجليزية في {field}. تم إخطار مراجع."},
    "issue_failed": {"en": "Issue failed, retry", "ar": "تعذّر الإصدار، أعد المحاولة"},
    "draft_not_filed": {"en": "Draft, not filed, not an audit opinion", "ar": "مسودة، غير مقدَّمة، وليست رأي تدقيق"},
    "supplied_not_audited": {"en": "prepared from supplied data, not audited", "ar": "أُعدّ من البيانات المقدَّمة، غير مدقق"},
    "platform_generated": {"en": "platform-generated, not an official certificate", "ar": "صادر عن المنصة، وليس شهادة رسمية"},
    "second_language_missing": {"en": "second-language name not on DET record", "ar": "الاسم باللغة الثانية غير موجود في سجل الدائرة"},
    "ask_owner_access": {"en": "Ask the owner to give you access", "ar": "اطلب من المالك منحك صلاحية الوصول"},
    "precedence_clause": {"en": "This document is issued in Arabic and English from one source record. If the two versions differ, the Arabic version prevails.", "ar": "صدر هذا المستند باللغتين العربية والإنجليزية من سجل مصدر واحد. وفي حال الاختلاف بين النسختين، يُعتدّ بالنسخة العربية."},
    "no_assurance": {"en": "No assurance is given. Verification confirms authenticity and integrity only.", "ar": "لا يُقدَّم أي تأكيد. يؤكد التحقق صحة المستند وسلامته فقط."},
    "status_draft": {"en": "Draft", "ar": "مسودة"},
    "status_issued": {"en": "Issued", "ar": "صادر"},
    "status_superseded": {"en": "Superseded", "ar": "مستبدَل"},
    "status_revoked": {"en": "Revoked", "ar": "ملغى"},
    "status_signed": {"en": "Signed", "ar": "موقّع"},
    "status_in_review": {"en": "Reviewed by licensed human", "ar": "روجع من مختص مرخّص"},
    "status_withdrawn": {"en": "Withdrawn", "ar": "مسحوب"},
    "status_not_found": {"en": "Not found", "ar": "غير موجود"},
    "status_not_valid": {"en": "Not valid", "ar": "غير صالح"},
    "remote_issue_note": {"en": "Issuing is not yet available for your role in this version.", "ar": "الإصدار غير متاح بعد لدورك في هذه النسخة."},
    "auditors_report": {"en": "Auditor's report", "ar": "تقرير مدقق الحسابات"},
}
REVOKE_REASON_LABELS = {
    "issued_in_error": {"en": "issued in error", "ar": "صدر عن طريق الخطأ"},
    "replaced_by_correction": {"en": "replaced by a corrected document", "ar": "استُبدل بمستند مصحَّح"},
    "signer_instruction": {"en": "on instruction from the signing firm", "ar": "بناءً على تعليمات الجهة الموقِّعة"},
    "authority_instruction": {"en": "on instruction from an authority", "ar": "بناءً على تعليمات جهة رسمية"},
    "owner_written_request": {"en": "on the owner's written request", "ar": "بناءً على طلب كتابي من المالك"},
}
AUDIENCE: dict[str, str] = {k: "official" for k in STRINGS}

try:
    from app.modules.catalogue.service import register_strings

    register_strings("documents", STRINGS, AUDIENCE)
except ImportError:  # pragma: no cover
    pass


def s(key: str, lang: str = "en", **params: object) -> str:
    text = STRINGS.get(key, {}).get(lang) or STRINGS.get(key, {}).get("en") or key
    for k, v in params.items():
        text = text.replace("{" + k + "}", str(v))
    return text


def both(key: str, **params: object) -> dict[str, str]:
    return {"en": s(key, "en", **params), "ar": s(key, "ar", **params)}
