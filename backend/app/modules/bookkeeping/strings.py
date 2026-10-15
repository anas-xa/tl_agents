"""Bilingual strings for E5-S1 (verbatim from the spec; Arabic is a draft pending native review)."""

from __future__ import annotations

STRINGS: dict[str, dict[str, str]] = {
    "empty_queue": {"en": "No transactions yet. Classification starts when you add a statement or link a bank account with your consent.", "ar": "لا توجد معاملات بعد. يبدأ التصنيف عند رفع كشف حساب أو ربط حساب بنكي بموافقتك."},
    "upload_statement": {"en": "Upload a statement", "ar": "رفع كشف حساب"},
    "open_consent_centre": {"en": "Open Consent Centre", "ar": "فتح مركز الموافقات"},
    "all_reviewed": {"en": "Nothing to review. Books are up to date.", "ar": "لا شيء للمراجعة. الدفاتر محدّثة."},
    "preparing": {"en": "AI is preparing categories: {done} of {total} done", "ar": "يجري الذكاء الاصطناعي تجهيز التصنيفات: {done} من {total}"},
    "awaiting_consent": {"en": "Waiting for your consent. We read no data from this account until you approve.", "ar": "بانتظار موافقتك. لا نقرأ أي بيانات من هذا الحساب قبل موافقتك."},
    "consent_ended": {"en": "Bank link paused: consent ended on {date}. No new transactions are read. Entries already posted stay. Renew in the Consent Centre.", "ar": "تم إيقاف الربط البنكي: انتهت الموافقة في {date}. لا تُقرأ معاملات جديدة. تبقى القيود المرحّلة. جدّد الموافقة من مركز الموافقات."},
    "ask_owner_renew": {"en": "Ask the owner to renew", "ar": "اطلب من المالك التجديد"},
    "stale_data": {"en": "Latest data is from {datetime}. Newer transactions may be missing.", "ar": "آخر بيانات بتاريخ {datetime}. قد تكون هناك معاملات أحدث غير ظاهرة."},
    "refresh": {"en": "Refresh", "ar": "تحديث"},
    "manual_unverified": {"en": "manual, unverified", "ar": "يدوي، غير موثّق"},
    "post_failed": {"en": "We could not post this entry because the ledger did not respond. Your correction is saved. Retry, or contact support.", "ar": "تعذّر ترحيل هذا القيد لأن دفتر الحسابات لم يستجب. تم حفظ تعديلك. أعد المحاولة أو تواصل مع الدعم."},
    "bulk_accept_title": {"en": "Accept {count} proposals?", "ar": "قبول {count} اقتراحًا؟"},
    "bulk_accept_body": {"en": "Total AED {total} (income AED {income}, expenses AED {expenses}). These match your earlier choices. You can undo until the period is approved.", "ar": "الإجمالي {total} درهم (إيرادات {income} ودخل مصروفات {expenses})"},
    "bulk_accept_done": {"en": "{count} entries accepted by {name}, {role}.", "ar": "تم قبول {count} قيدًا بواسطة {name}، {role}."},
    "no_function": {"en": "You do not have the bookkeeping function for this company. Ask the owner to assign it.", "ar": "ليست لديك صلاحية مسك الدفاتر لهذه الشركة. اطلب من المالك منحك إياها."},
    "ask_owner": {"en": "Ask the owner", "ar": "اطلب من المالك"},
    "access_removed": {"en": "Your access to this company was removed. You cannot view or change its data.", "ar": "تمت إزالة وصولك إلى هذه الشركة. لا يمكنك عرض بياناتها أو تعديلها."},
    "quarantined": {"en": "Quarantined: made by {name}, access removed on {date}", "ar": "محجوز: أعدّه {name}، أُزيل الوصول بتاريخ {date}"},
    "nothing_posted_until_decide": {"en": "Nothing posted until you decide.", "ar": "لن يُرحَّل شيء حتى تقرر."},
    "keep_and_review": {"en": "Keep and review", "ar": "الاحتفاظ والمراجعة"},
    "discard": {"en": "Discard", "ar": "تجاهل"},
    "ai_prepared_draft": {"en": "AI-prepared, draft. Please check before posting.", "ar": "مسودة أعدّها الذكاء الاصطناعي. يرجى التحقق قبل الترحيل."},
    "reason_no_basis": {"en": "Needs review: no basis found", "ar": "يحتاج إلى مراجعة: لم يُعثر على أساس"},
    "reason_matches_earlier": {"en": "Matches your earlier choices", "ar": "يطابق اختياراتك السابقة"},
    "posted_by": {"en": "Posted by {name}, {role}, {datetime}", "ar": "رحّله {name}، {role}، {datetime}"},
    "consent_withdrawn_row": {"en": "Consent withdrawn: no new transactions from this account", "ar": "تم سحب الموافقة: لا معاملات جديدة من هذا الحساب"},
    "draft_not_posted": {"en": "Draft, not posted", "ar": "مسودة، غير مرحّلة"},
    "retry": {"en": "Retry", "ar": "إعادة المحاولة"},
    "contact_support": {"en": "Contact support", "ar": "تواصل مع الدعم"},
    "treated_as_data": {"en": "Contains text we treated as data only", "ar": "يحتوي على نص تعاملنا معه كبيانات فقط"},
    "k14_label": {"en": "Correction rate on a labelled sample", "ar": "معدل التصحيح على عيّنة موسومة"},
    "k14_not_measurable": {"en": "Not yet measurable: {count} labelled in the rolling 3-month window", "ar": "غير قابل للقياس بعد: {count} موسومة خلال نافذة 3 أشهر"},
    "k14_too_small": {"en": "too small", "ar": "صغيرة جدًا"},
    "withdrawal_notice": {"en": "Bank data already used in a filing, return or audit draft is kept under legal hold, read-only. Other bank data is marked 'source consent withdrawn', excluded from new calculations and removed on the configured schedule.", "ar": "تُحفظ البيانات البنكية التي استُخدمت في إقرار أو مسودة تدقيق قيد الحجز القانوني للقراءة فقط. تُعلَّم البيانات البنكية الأخرى بأن الموافقة على مصدرها سُحبت، وتُستبعد من أي احتساب جديد وتُزال وفق الجدول المحدد."},
}
AUDIENCE: dict[str, str] = {k: "official" for k in STRINGS}

try:  # the catalogue module may be absent at build time
    from app.modules.catalogue.service import register_strings

    register_strings("bookkeeping", STRINGS, AUDIENCE)
except ImportError:  # pragma: no cover
    pass
