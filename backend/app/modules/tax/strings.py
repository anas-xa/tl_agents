"""Bilingual strings for E5-S2 (verbatim from the spec; Arabic is a draft pending native review)."""

from __future__ import annotations

STRINGS: dict[str, dict[str, str]] = {
    "no_rule_stop": {"en": "We cannot calculate {tax_type} for {period} yet. The rules for this period are not loaded. No figure is shown, so nothing can be approved. A specialist has been notified. Contact support if this is urgent.", "ar": "لا يمكننا احتساب {tax_type} لفترة {period} حتى الآن. قواعد هذه الفترة غير محمّلة. لا يظهر أي رقم، لذلك لا يمكن اعتماد أي شيء. تم إشعار مختص. تواصل مع الدعم إذا كان الأمر عاجلاً."},
    "calculating": {"en": "Calculating with rules in force for {period}", "ar": "جارٍ الاحتساب وفق القواعد السارية لفترة {period}"},
    "missing_vat_code": {"en": "Calculation stopped: {n} transactions have no VAT code. Review them, then recalculate.", "ar": "توقف الاحتساب: {n} معاملات بلا رمز ضريبة القيمة المضافة. راجعها ثم أعد الاحتساب."},
    "run_failed": {"en": "The calculation did not finish. Nothing was changed and no figure is shown. Try again. If it keeps failing, contact support with reference {ref}.", "ar": "لم يكتمل الاحتساب. لم يتغير شيء ولا يظهر أي رقم. حاول مرة أخرى. إذا تكرر الخطأ فتواصل مع الدعم مع الرقم المرجعي {ref}."},
    "excludes_warning": {"en": "This result leaves out {n} transactions (AED {x}) that need review. The figure may change once they are reviewed. Review them, then recalculate.", "ar": "تستثني هذه النتيجة {n} معاملات ({x} درهم) تحتاج إلى مراجعة. قد يتغير الرقم بعد مراجعتها. راجعها ثم أعد الاحتساب."},
    "stale": {"en": "Stale: transactions changed after this calculation on {datetime}. Recalculate before approval.", "ar": "قديمة: تغيّرت المعاملات بعد هذا الاحتساب في {datetime}. أعد الاحتساب قبل الاعتماد."},
    "recalculate": {"en": "Recalculate", "ar": "إعادة الاحتساب"},
    "view_only_no_function": {"en": "You can view this calculation. You do not have the tax-preparation function.", "ar": "يمكنك عرض هذا الاحتساب. ليست لديك صلاحية إعداد الضريبة."},
    "ask_owner_access": {"en": "Ask the owner for access", "ar": "اطلب الصلاحية من المالك"},
    "ai_not_reviewed": {"en": "AI-prepared calculation. Status: not reviewed", "ar": "حساب أعدّه الذكاء الاصطناعي. الحالة: لم تتم مراجعته"},
    "reviewed_by": {"en": "Reviewed by {name}, {role}, {date}", "ar": "راجعه {name}، {role}، {date}"},
    "incomplete": {"en": "Incomplete: not for approval", "ar": "غير مكتمل: غير جاهز للاعتماد"},
    "excludes_n": {"en": "Excludes {n} items", "ar": "يستثني {n} بنداً"},
    "approval_off": {"en": "Approval is off until all items are reviewed.", "ar": "الاعتماد متوقف حتى تتم مراجعة كل البنود."},
    "same_result": {"en": "Same result under current rules.", "ar": "النتيجة نفسها وفق القواعد الحالية."},
    "comparison_info": {"en": "The earlier figure is the one for that period. This comparison is for information.", "ar": "الرقم السابق هو المعتمد لتلك الفترة. هذه المقارنة للعلم فقط."},
    "summary_view": {"en": "Summary view. Detailed adjustments are made by your delegate or in the UAE portal session.", "ar": "عرض موجز. يُجري مندوبك التعديلات التفصيلية أو تُجرى في جلسة البوابة داخل الإمارات."},
    "sbr_applied_until": {"en": "Small Business Relief applied for periods ending on or before {date}", "ar": "يُطبَّق إعفاء الأعمال الصغيرة على الفترات المنتهية في {date} أو قبله"},
    "rules_used": {"en": "Rules used: version {version}, effective {date}", "ar": "القواعد المستخدمة: الإصدار {version}، سارية من {date}"},
    "not_advice": {"en": "This is a calculation, not tax advice. Complex case? Ask a specialist.", "ar": "هذا احتساب وليس استشارة ضريبية. حالة معقدة؟ اسأل مختصًا."},
    "confirm_to_calculate": {"en": "Confirm transactions in the review queue to calculate VAT for {period}.", "ar": "أكّد المعاملات في قائمة المراجعة لاحتساب ضريبة القيمة المضافة لفترة {period}."},
    "add_trn": {"en": "Add your TRN to see calculations.", "ar": "أضف رقم التسجيل الضريبي لعرض الاحتسابات."},
    "scope_block": {"en": "This company is outside the pilot's supported scope; a specialist will contact you", "ar": "هذه الشركة خارج النطاق المدعوم في البرنامج التجريبي؛ سيتواصل معك مختص"},
    "escalated": {"en": "escalated for specialist review", "ar": "أُحيلت لمراجعة مختص"},
    "sbr_indicator": {"en": "eligible, election needed", "ar": "مؤهل، يلزم الاختيار"},
    "sbr_not_eligible": {"en": "not eligible", "ar": "غير مؤهل"},
    "sbr_block_after_cutoff": {"en": "period ends after 31 Dec 2026", "ar": "تنتهي الفترة بعد 31 ديسمبر 2026"},
    "person_entered": {"en": "person-entered, not reviewed", "ar": "أدخله شخص، لم تتم مراجعته"},
    "higher_by": {"en": "higher by", "ar": "أعلى بمقدار"},
    "lower_by": {"en": "lower by", "ar": "أقل بمقدار"},
    "draft_label": {"en": "Draft, not filed, not tax advice", "ar": "مسودة، غير مقدَّمة، ليست استشارة ضريبية"},
    "estimates": {"en": "Figures are estimates until the instruments are verified.", "ar": "الأرقام تقديرية إلى أن يتم التحقق من الصكوك."},
    "configured_pending": {"en": "configured, pending FTA confirmation", "ar": "مُهيّأ، بانتظار تأكيد الهيئة الاتحادية للضرائب"},
    "test_data": {"en": "test data, not confirmed", "ar": "بيانات اختبار، غير مؤكدة"},
    "related_party_held": {"en": "Related-party item: calculated as a draft, held for specialist review", "ar": "بند طرف ذي علاقة: احتُسب كمسودة، محجوز لمراجعة مختص"},
}
AUDIENCE: dict[str, str] = {k: "official" for k in STRINGS}

try:
    from app.modules.catalogue.service import register_strings

    register_strings("tax", STRINGS, AUDIENCE)
except ImportError:  # pragma: no cover
    pass
