"""Bilingual strings for E5-S3 (verbatim from the spec; Arabic is a draft pending native review)."""

from __future__ import annotations

from app.modules.drafts.models import AI_LABEL, EMARATAX_SENTENCE, PRODUCT_NAME, STATUS_LABELS, WATERMARK

STRINGS: dict[str, dict[str, str]] = {
    "ai_label": AI_LABEL,
    "watermark": WATERMARK,
    "emaratax_sentence": EMARATAX_SENTENCE,
    "product_name": PRODUCT_NAME,
    "preparing": {"en": "Preparing your draft. This can take a few minutes. You can leave this page; we will keep it for you.", "ar": "نُعدّ مسودتك. قد يستغرق ذلك بضع دقائق. يمكنك مغادرة الصفحة وسنحتفظ بها لك."},
    "shown_while": {"en": "Version {old}, shown while version {new} is prepared", "ar": "الإصدار {old} معروض إلى حين إعداد الإصدار {new}"},
    "still_working": {"en": "Still working. Your earlier version is unchanged.", "ar": "ما زلنا نعمل. إصدارك السابق لم يتغير."},
    "new_draft_ready": {"en": "New draft ready", "ar": "مسودة جديدة جاهزة"},
    "review_version": {"en": "Review version {n}", "ar": "راجع الإصدار {n}"},
    "could_not_prepare": {"en": "Draft could not be prepared. Cause: {cause}. Next step: {step}.", "ar": "تعذّر إعداد المسودة. السبب: {cause}. الخطوة التالية: {step}."},
    "generic_error": {"en": "Something went wrong on our side. Nothing was changed and nothing was submitted. Try again, or ask a human.", "ar": "حدث خطأ من جهتنا. لم يتغير شيء ولم يُقدَّم شيء. حاول مرة أخرى أو اطلب المساعدة من شخص."},
    "try_again": {"en": "Try again", "ar": "حاول مرة أخرى"},
    "ask_a_human": {"en": "Ask a human", "ar": "اطلب المساعدة من شخص"},
    "cannot_set_status": {"en": "You cannot set this status. {role} can. Ask them or ask a human.", "ar": "لا يمكنك تعيين هذه الحالة. يمكن لـ{role} ذلك. اطلب منهم أو اطلب المساعدة من شخص."},
    "missing_items": {"en": "We cannot prepare this draft yet. {n} items are missing.", "ar": "لا يمكننا إعداد هذه المسودة بعد. هناك {n} عناصر ناقصة."},
    "all_received": {"en": "All items received. We are preparing your draft.", "ar": "استلمنا كل العناصر. نُعدّ مسودتك الآن."},
    "no_draft": {"en": "We prepare one when your data is complete.", "ar": "نُعدّ واحدة عندما تكتمل بياناتك."},
    "out_of_date": {"en": "Out of date: your data changed. A new draft version is ready. Review the new version before you approve.", "ar": "قديمة: تغيّرت بياناتك. أصبح إصدار جديد من المسودة جاهزًا. راجع الإصدار الجديد قبل أن توافق."},
    "what_changed": {"en": "What changed: {description}", "ar": "ما الذي تغيّر: {description}"},
    "open_version": {"en": "Open version {n}", "ar": "افتح الإصدار {n}"},
    "approval_current_only": {"en": "Approval is only possible on the current version.", "ar": "الاعتماد ممكن على الإصدار الحالي فقط."},
    "no_source": {"en": "No source", "ar": "بلا مصدر"},
    "no_source_panel": {"en": "This figure has no source record. It cannot be checked from the data we hold.", "ar": "لا يوجد سجل مصدر لهذا الرقم. لا يمكن التحقق منه من البيانات التي نحتفظ بها."},
    "proceed_warning": {"en": "You can still proceed, but this figure has not been checked against a source.", "ar": "يمكنك المتابعة، لكن هذا الرقم لم يُطابَق مع مصدر."},
    "contains_no_source": {"en": "Contains {n} figures with no source", "ar": "تحتوي على {n} أرقام بلا مصدر"},
    "ask_human_check": {"en": "Ask a human to check", "ar": "اطلب من شخص التحقق"},
    "add_note": {"en": "Add a note", "ar": "أضف ملاحظة"},
    "review_touched_by": {"en": "Review drafts touched by {name}", "ar": "مراجعة المسودات التي عدّلها {name}"},
    "held_intro": {"en": "{name} no longer has access. These drafts were changed by them and are on hold. Decide what to do with each one.", "ar": "لم يعد لدى {name} صلاحية الوصول. هذه المسودات عدّلها وهي قيد الإيقاف. قرر ما تفعله بكل واحدة."},
    "on_hold": {"en": "On hold", "ar": "قيد الإيقاف"},
    "keep_changes": {"en": "Keep changes", "ar": "الاحتفاظ بالتعديلات"},
    "discard_changes": {"en": "Discard changes and return to the last unchanged version", "ar": "تجاهل التعديلات والعودة إلى آخر إصدار غير معدّل"},
    "no_drafts_on_hold": {"en": "No drafts on hold.", "ar": "لا توجد مسودات قيد الإيقاف."},
    "no_access_page": {"en": "You do not have access to this page.", "ar": "ليست لديك صلاحية الوصول إلى هذه الصفحة."},
    "why_changing": {"en": "Why are you changing this?", "ar": "لماذا تقوم بهذا التغيير؟"},
    "reason_saved": {"en": "This reason is saved in the history with your name and the time.", "ar": "يُحفظ هذا السبب في السجل مع اسمك والوقت."},
    "saved_in_history": {"en": "This is saved in the history with your name and the time.", "ar": "يُحفظ هذا في السجل مع اسمك والوقت."},
    "choose_reason": {"en": "Choose a reason to continue.", "ar": "اختر سببًا للمتابعة."},
    "tick_checked": {"en": "I have checked the figures and their source", "ar": "راجعت الأرقام ومصدرها"},
    "tick_ai": {"en": "I understand this was prepared by AI and its review status is {status}", "ar": "أفهم أن هذه المسودة أعدّها الذكاء الاصطناعي وأن حالة مراجعتها هي {status}"},
    "approve_continue": {"en": "Approve and continue", "ar": "اعتماد ومتابعة"},
    "back_to_draft": {"en": "Back to draft", "ar": "العودة إلى المسودة"},
    "remote_owner_no_access": {"en": "Draft returns are not available to you yet. You can view your dashboard and reminders.", "ar": "مسودات الإقرارات غير متاحة لك بعد. يمكنك عرض لوحتك والتذكيرات."},
    "no_access_company_drafts": {"en": "You do not have access to this company's drafts.", "ar": "ليست لديك صلاحية الوصول إلى مسودات هذه الشركة."},
    "only_owner_approves": {"en": "Only the owner can approve.", "ar": "المالك وحده يمكنه الاعتماد."},
    "draft_discarded": {"en": "Draft discarded. {n} drafts still on hold.", "ar": "تم تجاهل المسودة. لا تزال {n} مسودات قيد الإيقاف."},
    "not_reviewed_by_human": {"en": "Not reviewed by a human", "ar": "لم يراجعها شخص"},
    "audit_working_draft": {"en": "audit working draft", "ar": "مسودة عمل التدقيق"},
    "send_for_approval": {"en": "Send for owner approval", "ar": "إرسال لاعتماد المالك"},
    "responsibility": {"en": "You are responsible for what is filed. The platform prepares; it does not file.", "ar": "أنت مسؤول عمّا يُقدَّم. المنصة تُعدّ ولا تُقدّم."},
    "retention_note": {"en": "Your company remains responsible for its statutory records and can export them.", "ar": "تبقى شركتك مسؤولة عن سجلاتها النظامية ويمكنها تصديرها."},
}
for _k, _v in STATUS_LABELS.items():
    STRINGS[f"status_{_k}"] = _v
AUDIENCE: dict[str, str] = {k: "official" for k in STRINGS}

try:
    from app.modules.catalogue.service import register_strings

    register_strings("drafts", STRINGS, AUDIENCE)
except ImportError:  # pragma: no cover
    pass
