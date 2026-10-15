"""Bilingual strings for E6 (verbatim from the spec; Arabic is a draft pending native review). Where the spec
gives English only, the Arabic is marked as a draft pending translation ('to be confirmed')."""

from __future__ import annotations

TBC_AR = "(الترجمة قيد المراجعة)"

STRINGS: dict[str, dict[str, str]] = {
    # E6-S1 approval act (declaration wording shown at approval; versioned)
    "approve_title": {"en": "Approve this return for submission", "ar": "الموافقة على هذا الإقرار للتقديم"},
    "approving_version": {"en": "You are approving version [ID] of [date, time]. Nothing is filed until you submit.", "ar": "أنت توافق على النسخة [ID] بتاريخ [التاريخ والوقت]. لن يتم تقديم أي شيء قبل أن تقدّمه."},
    "ai_draft_label": {"en": "AI-prepared draft, not yet signed off", "ar": "مسودة أعدّها الذكاء الاصطناعي، لم تُعتمد بعد"},
    "validity_line": {"en": "This approval is valid until [date]. It confirms you reviewed this draft. It is not a filing and not tax advice.", "ar": TBC_AR},
    "platform_line": {"en": "Your approval is recorded in this platform. Filing with the Federal Tax Authority is done in EmaraTax by the company's authorised user.", "ar": TBC_AR},
    "expired_pack_label": {"en": "approval expired, review and approve again", "ar": TBC_AR},
    "decision_recorded": {"en": "Your decision has been recorded.", "ar": "تم تسجيل قرارك."},
    "nothing_waiting": {"en": "Nothing is waiting for your approval. We will notify you when a return is ready.", "ar": "لا يوجد ما ينتظر موافقتك. سنخطرك عند جاهزية إقرار."},
    "save_failed": {"en": "Your approval was not saved. Nothing has been filed. Try again.", "ar": "لم تُحفظ موافقتك. لم يتم تقديم أي شيء. حاول مرة أخرى."},
    "uaepass_failed": {"en": "We could not confirm your identity. Your approval was not saved. Nothing has been filed. Try again.", "ar": "تعذّر التحقق من هويتك. لم تُحفظ موافقتك. لم يتم تقديم أي شيء. حاول مرة أخرى."},
    "uaepass_cancelled": {"en": "Sign-in was cancelled. Your approval was not saved. Nothing has been filed.", "ar": "أُلغي تسجيل الدخول. لم تُحفظ موافقتك. لم يتم تقديم أي شيء."},
    "superseded_while_viewing": {"en": "The figures changed after you opened this return. Your approval was not saved. Review the new version [ID] before approving.", "ar": "تغيّرت الأرقام بعد فتحك هذا الإقرار. لم تُحفظ موافقتك. راجع النسخة الجديدة [ID] قبل الموافقة."},
    "request_expired": {"en": "This approval request has expired. A new request will be raised.", "ar": "انتهت صلاحية طلب الموافقة. سيتم إنشاء طلب جديد."},
    "hash_mismatch": {"en": "Version [ID] you reviewed is no longer the latest. Nothing was approved or filed.", "ar": "النسخة [ID] التي راجعتها لم تعد الأحدث. لم تتم أي موافقة ولم يتم تقديم أي شيء."},
    "view_only": {"en": "View only. Only the owner, or a delegate with approval rights, can approve this return.", "ar": "عرض فقط. يمكن للمالك أو لمفوَّض لديه صلاحية الموافقة فقط الموافقة على هذا الإقرار."},
    "on_hold_owner_decides": {"en": "On hold until the owner decides", "ar": "قيد الانتظار حتى يقرر المالك"},
    "reason_required": {"en": "Please add a reason (at least 5 characters).", "ar": "يرجى إضافة سبب (5 أحرف على الأقل)."},
    "owner_reminded": {"en": "The owner has been reminded.", "ar": "تم تذكير المالك."},
    "authority_unclear": {"en": "We cannot confirm who may approve for this company. A reviewer will check the authority documents before anyone can approve.", "ar": TBC_AR},
    # E6-S2 refusal lines (the four fixed codes)
    "NO_OWNER_ROLE": {"en": "Only an owner can give approval rights. Your record has no Emirates ID, so you do not have an owner role.", "ar": "يمكن للمالك فقط منح صلاحيات الموافقة. سجلك لا يتضمن هوية إماراتية، لذلك ليس لديك دور المالك."},
    "NOT_OWNER_DELEGATE": {"en": "Only the owner can give approval rights.", "ar": "يمكن للمالك فقط منح صلاحيات الموافقة."},
    "STALE_DATA": {"en": "Your details are out of date, so this was not done. Refresh and try again.", "ar": "بياناتك غير محدّثة، لذلك لم يتم تنفيذ الإجراء. حدّث البيانات وحاول مرة أخرى."},
    "REAUTH_FAILED": {"en": "Identity not confirmed, so this was not done.", "ar": "لم يتم تأكيد الهوية، لذلك لم يتم تنفيذ الإجراء."},
    "generic_error": {"en": "Something went wrong. Nothing has changed. Try again.", "ar": "حدث خطأ. لم يتغير شيء. حاول مرة أخرى."},
    "phase_b_off": {"en": "Approval rights are not available yet. You can prepare and view. Only the owner can approve.", "ar": "صلاحيات الموافقة غير متاحة بعد. يمكنك الإعداد والاطلاع. المالك وحده يستطيع الموافقة."},
    "dates_invalid": {"en": "End date must be after the start date.", "ar": "يجب أن يكون تاريخ الانتهاء بعد تاريخ البدء."},
    "grant_too_long": {"en": "The end date can be at most [n] days after the start date.", "ar": TBC_AR},
    "grant_summary": {"en": "[Name] will be able to approve [VAT / corporate tax] returns for [company] up to AED [amount] from [date] to [date].", "ar": TBC_AR},
    "grant_not_shared": {"en": "Not shared: this does not let them change your bank consent or your subscription.", "ar": TBC_AR},
    "grant_revoked": {"en": "Right revoked. [Name] can no longer approve. Open requests are back with you.", "ar": TBC_AR},
    "approved_by_delegate": {"en": "Approved by [delegate] under a right given by [owner], grant [ID]", "ar": TBC_AR},
    "permission_inside_platform": {"en": "This is a permission inside this platform.", "ar": "هذه صلاحية داخل هذه المنصة."},
    # E6-S3 filing states (live Phase 1)
    "not_filed": {"en": "Not filed. Approve the return, then file it on EmaraTax and record it here.", "ar": "لم يُقدَّم بعد. اعتمد الإقرار، ثم قدّمه عبر إيماراتاكس وسجّله هنا."},
    "submission_not_available": {"en": "Submission from this platform is not available yet. Nothing is sent from here.", "ar": "التقديم من هذه المنصة غير متاح بعد. لا يُرسل أي شيء من هنا."},
    "filed_self_declared": {"en": "Filed outside the platform. Self-declared by [name] on [date, time]. Not verified by the tax authority.", "ar": "قُدِّم خارج المنصة. إقرار ذاتي من [الاسم] بتاريخ [التاريخ والوقت]. لم تتحقق منه الهيئة."},
    "filed_values_differ": {"en": "Filed outside the platform, values differ.", "ar": "قُدِّم خارج المنصة، والقيم مختلفة."},
    "values_differ_body": {"en": "We cannot tell which is correct. Check the figures against your EmaraTax record.", "ar": "لا يمكننا تحديد الصحيح. قارن الأرقام بسجلك في إيماراتاكس."},
    "authority_unavailable": {"en": "The tax authority service is not responding at the moment. Status is pending. Due date shown: [date, source]. Check EmaraTax directly.", "ar": "خدمة الهيئة لا تستجيب حالياً. الحالة: قيد الانتظار. تاريخ الاستحقاق: [التاريخ، المصدر]. يُرجى التحقق مباشرةً عبر EmaraTax."},
    "blocked": {"en": "Not sent: approval is missing / expired / data changed since approval / approver no longer has rights.", "ar": "لم يُرسل: الاعتماد مفقود / منتهٍ / البيانات تغيّرت بعد الاعتماد / لم تعد للمعتمِد صلاحية الاعتماد."},
    "recorded_as_declared": {"en": "Recorded as declared by you. Not verified by the tax authority.", "ar": TBC_AR},
    "manual_heading": {"en": "Filing is done by you on EmaraTax. This platform prepares the return and does not submit it.", "ar": "تقدّمون الإقرار بأنفسكم عبر EmaraTax. تُعِدّ هذه المنصة الإقرار ولا تقدّمه."},
    "attached_not_verified": {"en": "Attached by you, not verified", "ar": TBC_AR},
    "demo_data": {"en": "Demo data", "ar": "بيانات تجريبية"},
    "filed_date_rule": {"en": "Enter the date you filed on EmaraTax. It cannot be in the future.", "ar": "أدخل تاريخ التقديم في إيماراتاكس. لا يمكن أن يكون في المستقبل."},
    "reference_rule": {"en": "Use letters and numbers only.", "ar": "استخدم حروفًا وأرقامًا فقط."},
    "record_save_failed": {"en": "We could not save your record. Nothing was lost. Try again.", "ar": "تعذّر حفظ سجلك. لم يُفقد شيء. حاول مرة أخرى."},
    # E6-S4 monitoring
    "k23_no_data": {"en": "No data. No submissions in this period.", "ar": "لا توجد بيانات. لا عمليات تقديم في هذه الفترة."},
    "k24_no_data": {"en": "No data. No approval requests have been decided in this period.", "ar": "لا توجد بيانات. لم يُبتّ في أي طلب موافقة في هذه الفترة."},
    "k24_no_target": {"en": "No target has been set for this figure.", "ar": "لم يُحدَّد هدف لهذا المؤشر."},
    "k23_breach": {"en": "Below 100%: {x} of {y} submissions have no valid approval. Review the exceptions.", "ar": "أقل من 100%: {x} من أصل {y} من عمليات التقديم بلا موافقة صالحة. راجع الاستثناءات."},
    "read_back_na": {"en": "Read-back from EmaraTax is not available. Filing status is self-declared by the company and has not been checked against the authority.", "ar": "قراءة الحالة من منصة EmaraTax غير متاحة. حالة التقديم مُقرّ بها ذاتيًا من الشركة ولم يتم التحقق منها لدى الهيئة."},
    "not_available": {"en": "Not available", "ar": "غير متاح"},
    "records_read_only": {"en": "Records cannot be edited. This attempt has been logged.", "ar": "لا يمكن تعديل السجلات. تم تسجيل هذه المحاولة."},
}

# Exact wording shown at the approval act, versioned (declaration wording [OPEN]: counsel/FTA to confirm).
DECLARATION_WORDING_VERSION = "apw-v1"
DECLARATION_WORDING = {k: STRINGS[k] for k in ("approve_title", "approving_version", "validity_line", "platform_line", "permission_inside_platform")}
GRANT_WORDING_VERSION = "grw-v1"

FILING_STATE_LABELS = {
    "not_filed": {"en": "Not filed", "ar": "لم يُقدَّم بعد"},
    "filed_outside_self_declared": {"en": "Filed outside platform (self-declared)", "ar": "قُدِّم خارج المنصة (إقرار ذاتي)"},
    "filed_outside_values_differ": {"en": "Filed outside platform, values differ", "ar": "قُدِّم خارج المنصة، والقيم مختلفة"},
    "authority_unavailable": {"en": "Authority unavailable", "ar": "الهيئة غير متاحة"},
    "blocked": {"en": "Blocked", "ar": "محظور"},
}
BLOCKED_CAUSE_LABELS = {
    "approval_missing": {"en": "approval is missing", "ar": "الاعتماد مفقود", "next_en": "Approve the return"},
    "approval_expired": {"en": "approval expired", "ar": "منتهٍ", "next_en": "Review and approve again"},
    "data_changed_since_approval": {"en": "data changed since approval", "ar": "البيانات تغيّرت بعد الاعتماد", "next_en": "Review the changes and approve again"},
    "approver_no_longer_has_rights": {"en": "approver no longer has rights", "ar": "لم تعد للمعتمِد صلاحية الاعتماد", "next_en": "Ask the owner to approve"},
}
EXCEPTION_LABELS = {
    "no_valid_approval_found": {"en": "no valid approval found", "ar": "لا توجد موافقة صالحة", "owner_en": "No approval found."},
    "wrong_version": {"en": "wrong version", "ar": "نسخة مختلفة", "owner_en": "This return was changed after you approved it. Review the new figures and approve again."},
    "approval_after_submission": {"en": "Approval came after submission", "ar": "الموافقة بعد التقديم", "owner_en": "Approval came after filing."},
    "expired": {"en": "expired", "ar": "منتهية الصلاحية", "owner_en": "Approval expired."},
    "withdrawn": {"en": "withdrawn", "ar": "مسحوبة", "owner_en": "Approval withdrawn."},
    "approver_not_entitled": {"en": "approver not entitled", "ar": "المعتمِد غير مخوَّل", "owner_en": "This approval was given by a delegate whose right to approve has been removed. The owner needs to approve."},
    "record_incomplete": {"en": "approval record incomplete", "ar": "سجل الموافقة غير مكتمل", "owner_en": "The approval record is incomplete. The owner needs to approve."},
}
AUDIENCE: dict[str, str] = {k: "official" for k in STRINGS}

try:
    from app.modules.catalogue.service import register_strings

    register_strings("approvals", STRINGS, AUDIENCE)
except ImportError:  # pragma: no cover
    pass
