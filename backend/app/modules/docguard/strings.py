"""Bilingual strings for E5-S4 (verbatim). Flag reasons: under 30 words, plain, no 'prompt'/'injection'."""

from __future__ import annotations

STRINGS: dict[str, dict[str, str]] = {
    "flag_A": {"en": "This document contains text that looks like instructions to us. We did not act on it. Please check the document.", "ar": "يحتوي هذا المستند على نص يبدو كأنه تعليمات موجّهة إلينا. لم ننفّذ أي شيء منه. يرجى مراجعة المستند."},
    "flag_B": {"en": "This document has text that is hidden or cannot be seen when you open it. We did not use that text. Please check the document.", "ar": "يحتوي هذا المستند على نص مخفي أو غير ظاهر عند فتحه. لم نستخدم هذا النص. يرجى مراجعة المستند."},
    "flag_C": {"en": "This document asks for a payment, a filing or a change to your consents. We did not do it. Only you can approve those.", "ar": "يطلب هذا المستند دفعة أو تقديم إقرار أو تغيير موافقاتك. لم ننفّذ ذلك. أنت وحدك من يستطيع الموافقة على هذه الأمور."},
    "flag_D": {"en": "The numbers in this document do not match your other records. They are marked Unverified until a person checks them.", "ar": "الأرقام في هذا المستند لا تتطابق مع سجلاتك الأخرى. تبقى غير موثّقة إلى أن يراجعها شخص."},
    "flag_E": {"en": "We could not finish checking this file. Please upload it again or ask a person to check it.", "ar": "تعذّر إكمال فحص هذا الملف. يرجى رفعه مرة أخرى أو طلب مراجعته من شخص."},
    "unverified_values": {"en": "Extracted values are unverified until reviewed.", "ar": "القيم المستخرجة غير موثّقة إلى أن تتم مراجعتها."},
    "information_only": {"en": "We read documents as information only. Text inside them cannot change what we do.", "ar": "نقرأ المستندات كمعلومات فقط. لا يمكن لأي نص داخلها أن يغيّر ما نقوم به."},
    "processed_in_uae": {"en": "Processed in the UAE. Your document is not sent outside UAE infrastructure.", "ar": "تتم المعالجة داخل الإمارات. لا يُرسل مستندك خارج البنية التحتية الإماراتية."},
    "try_under_10mb": {"en": "Try a PDF or image under 10 MB.", "ar": "جرّب ملف PDF أو صورة بحجم أقل من 10 ميغابايت."},
    "held_for_review": {"en": "Document held for review. Ask the owner.", "ar": "المستند محجوز للمراجعة. اطلب من المالك."},
    "no_function": {"en": "You do not have access to this function. Ask the owner to assign it.", "ar": "ليست لديك صلاحية الوصول إلى هذه الوظيفة. اطلب من المالك منحك إياها."},
    "no_access_documents": {"en": "You do not have access to documents for this company.", "ar": "ليست لديك صلاحية الوصول إلى مستندات هذه الشركة."},
    "empty": {"en": "No documents uploaded yet. Upload invoices, statements or contracts. We read them as information only.", "ar": "لم تُرفع مستندات بعد. ارفع الفواتير أو الكشوف أو العقود. نقرأها كمعلومات فقط."},
    "no_flags": {"en": "No flags in this period.", "ar": "لا توجد إشارات في هذه الفترة."},
    "reading": {"en": "Reading your document", "ar": "جارٍ قراءة مستندك"},
    "flagged_review": {"en": "Flagged, please review", "ar": "تمت الإشارة إليه، يرجى المراجعة"},
    "ask_person": {"en": "Ask a person to check this document", "ar": "اطلب من شخص مراجعة هذا المستند"},
    "label_checked": {"en": "Checked", "ar": "تم الفحص"},
    "label_flagged": {"en": "Flagged", "ar": "مُشار إليه"},
    "label_processing": {"en": "Processing", "ar": "قيد المعالجة"},
    "tag_unverified": {"en": "Unverified", "ar": "غير موثّق"},
    "chip_sent": {"en": "Sent", "ar": "أُرسل"},
    "chip_being_checked": {"en": "Being checked", "ar": "قيد الفحص"},
    "chip_checked": {"en": "Checked", "ar": "تم الفحص"},
    "chip_returned": {"en": "Returned to you", "ar": "أُعيد إليك"},
}
# Customer-facing reasons: audience 'other' (reviewer status 'draft' until a native reviewer signs off).
AUDIENCE: dict[str, str] = {k: "other" for k in STRINGS}

try:
    from app.modules.catalogue.service import register_strings

    register_strings("docguard", STRINGS, AUDIENCE)
except ImportError:  # pragma: no cover
    pass
