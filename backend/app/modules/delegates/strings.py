"""Bilingual strings for SC11 (team, delegates and settings) and SC15 (owner/delegate activity list).

Spec wording verbatim (E1-S2 §6, E1-S6 §6, E1-S3 SC15). Arabic is a draft pending native review.
"""

from __future__ import annotations

STRINGS: dict[str, dict[str, str]] = {
    # --- SC11 shared wording (E1-S2 §6) ---
    "access_changed": {
        "en": "Your access to [Company] changed. Work you started is held for the owner to review. You can still use your other companies.",
        "ar": "تغيّرت صلاحية وصولك إلى [الشركة]. الأعمال التي بدأتها محفوظة لمراجعة المالك. يمكنك مواصلة العمل في شركاتك الأخرى.",
    },
    "go_to_my_companies": {"en": "Go to my companies", "ar": "الانتقال إلى شركاتي"},
    "sign_out": {"en": "Sign out", "ar": "تسجيل الخروج"},
    "role_refusal": {
        "en": "You can't do this with your current role. Approvals need the owner's right. Ask the owner.",
        "ar": "لا يمكنك تنفيذ هذا الإجراء بدورك الحالي. الموافقات تتطلب صلاحية المالك. اطلب ذلك من المالك.",
    },
    "separation_refusal": {
        "en": "The person who prepared this can't also approve it. Ask another authorised person.",
        "ar": "لا يمكن لمن أعدّ هذا العنصر أن يعتمده أيضاً. اطلب ذلك من شخص مخوّل آخر.",
    },
    "engagement_closed": {"en": "This engagement is closed. Your access has ended.", "ar": "تم إغلاق هذا التكليف. انتهت صلاحية وصولك."},
    "suppressed": {"en": "Hidden to protect privacy. This group is too small to show.", "ar": "مخفي لحماية الخصوصية. المجموعة أصغر من أن تُعرض."},
    "hidden": {"en": "Hidden", "ar": "مخفي"},
    "page_unavailable": {"en": "Page not available. This page doesn't exist or you can't open it.", "ar": "الصفحة غير متاحة. هذه الصفحة غير موجودة أو لا يمكنك فتحها."},
    "page_unavailable_body": {"en": "This page doesn't exist or you can't open it. Go back to your dashboard.", "ar": "هذه الصفحة غير موجودة أو لا يمكنك فتحها. ارجع إلى لوحتك."},
    "go_to_my_dashboard": {"en": "Go to my dashboard", "ar": "الانتقال إلى لوحتي"},
    "rights_updated": {"en": "Rights updated for [Name]. They take effect on their next action.", "ar": "تم تحديث صلاحيات [الاسم]. تسري عند إجرائه التالي."},
    "drafts_on_hold": {"en": "[n] drafts by [Name] are on hold. Keep, reassign or discard.", "ar": "يوجد [n] مسودات أعدّها [الاسم] قيد الإيقاف. احتفظ بها أو أسندها أو احذفها."},
    "rights_edited_banner": {"en": "Your access for [Company] changed. Review what you can do now.", "ar": "تم تغيير صلاحياتك في [الشركة]. راجع ما يمكنك فعله الآن."},
    "review_my_access": {"en": "Review my access", "ar": "مراجعة صلاحياتي"},
    "access_removed": {
        "en": "Your access to [Company] was removed by the owner. Work you started is held for the owner to review.",
        "ar": "أزال المالك صلاحية وصولك إلى [الشركة]. الأعمال التي بدأتها محفوظة لمراجعة المالك.",
    },
    "back_to_my_companies": {"en": "Back to my companies", "ar": "العودة إلى شركاتي"},
    "delegate_refused_own_company": {"en": "This needs the owner's approval right. Ask the owner.", "ar": "هذا الإجراء يتطلب صلاحية الموافقة من المالك. اطلب ذلك من المالك."},
    "no_owner_panel": {
        "en": "We couldn't match your Emirates ID to the licence record. You can't manage delegates, consent or approvals yet.",
        "ar": "لم نتمكن من مطابقة هويتك الإماراتية مع سجل الرخصة. لا يمكنك إدارة المفوَّضين أو الموافقة على مشاركة البيانات أو الموافقات على التقديم بعد.",
    },
    "no_owner_next_step": {"en": "Next step: contact DET.", "ar": "الخطوة التالية: تواصل مع دائرة الاقتصاد والسياحة."},
    "masked_field_sr": {"en": "Hidden field, not available for your role", "ar": "حقل مخفي، غير متاح لدورك"},
    "acting_as": {"en": "Acting as: [Role] for [Company]", "ar": "تعمل بصفة: [الدور] لصالح [الشركة]"},
    "current": {"en": "Current", "ar": "الحالي"},
    "last_updated": {"en": "Last updated", "ar": "آخر تحديث"},
    "refresh": {"en": "Refresh", "ar": "تحديث"},
    "recent_access_changes": {"en": "Recent access changes", "ar": "تغييرات الوصول الأخيرة"},
    "saving": {"en": "Saving…", "ar": "جارٍ الحفظ…"},
    "go_to_sign_in": {"en": "Go to sign-in", "ar": "الانتقال إلى تسجيل الدخول"},
    "no_results": {"en": "No results", "ar": "لا توجد نتائج"},
    # English-only in source (E1-S2 §6); Arabic drafted for the portal, pending native review.
    "save_failed": {"en": "Rights were not changed. Nothing is different. Try again.", "ar": "لم تتغير الصلاحيات. لا شيء مختلف. حاول مرة أخرى."},
    "reauth_failed": {"en": "We couldn't confirm it's you. Your changes were not saved. Sign in again.", "ar": "لم نتمكن من التأكد من هويتك. لم تُحفظ تغييراتك. سجّل الدخول مرة أخرى."},
    "no_delegates": {"en": "Only you have access to this company. Add an accountant or PRO to help.", "ar": "أنت وحدك من يملك صلاحية الوصول إلى هذه الشركة. أضف محاسباً أو مندوب خدمات للمساعدة."},
    # --- SC11 E1-S6 wording (English only in source) ---
    "invite_a_delegate": {"en": "Invite a delegate", "ar": "دعوة مفوَّض"},
    "can_prepare_data_yes": {"en": "Can prepare data: yes", "ar": "يمكنه إعداد البيانات: نعم"},
    "can_grant_consent_off": {"en": "Can grant consent for bank data: off", "ar": "يمكنه منح الموافقة على البيانات المصرفية: معطّل"},
    "can_approve_off": {"en": "Can approve submissions: off", "ar": "يمكنه اعتماد التقديمات: معطّل"},
    "only_you_approve": {"en": "Only you can approve submissions unless you choose otherwise.", "ar": "أنت وحدك من يعتمد التقديمات ما لم تختر غير ذلك."},
    "gives_right_to_approve": {"en": "This gives [name] the right to approve submissions for [company]. You can remove it at any time.", "ar": "يمنح هذا [الاسم] حق اعتماد التقديمات لصالح [الشركة]. يمكنك إزالته في أي وقت."},
    "pending_waiting": {"en": "Pending: waiting for [name] to accept", "ar": "قيد الانتظار: بانتظار قبول [الاسم]"},
    "delegate_removed": {"en": "Delegate removed. Access ended.", "ar": "تمت إزالة المفوَّض. انتهت صلاحية الوصول."},
    "not_available_owner_only": {"en": "Not available yet: only the owner can do this.", "ar": "غير متاح بعد: المالك وحده من يمكنه القيام بذلك."},
    "proposed_wording": {"en": "Proposed wording - pending confirmation", "ar": "صياغة مقترحة - بانتظار التأكيد"},
    "step_of": {"en": "Step [n] of 4", "ar": "الخطوة [n] من 4"},
    "on": {"en": "On", "ar": "مفعّل"},
    "off": {"en": "Off", "ar": "معطّل"},
    "name_differs": {"en": "name differs", "ar": "الاسم مختلف"},
    "initiated_by_removed_delegate": {"en": "initiated by a removed delegate", "ar": "بدأه مفوَّض تمت إزالته"},
    "suspended_authority_changed": {"en": "suspended – authority changed", "ar": "موقوف – تغيّرت الصلاحية"},
    "delegation_statement": {
        "en": "delegates can prepare and review; consent and submission approval stay with the owner or recorded signatory unless the owner delegates and the pilot confirms it is accepted",
        "ar": "يمكن للمفوَّضين الإعداد والمراجعة؛ وتبقى الموافقة على مشاركة البيانات واعتماد التقديمات لدى المالك أو المفوَّض بالتوقيع المسجَّل ما لم يفوّض المالك ذلك ويؤكد البرنامج التجريبي قبوله",
    },
    "empty_delegates": {
        "en": "You have not added a delegate yet. Add an accountant or PRO to prepare data for you. They cannot approve submissions or grant consent unless you allow it.",
        "ar": "لم تضف مفوَّضاً بعد. أضف محاسباً أو مندوب خدمات لإعداد البيانات نيابة عنك. لا يمكنهم اعتماد التقديمات أو منح الموافقة ما لم تسمح بذلك.",
    },
    "invitation_not_sent": {"en": "Invitation not sent. Check the email or phone number and try again.", "ar": "لم تُرسل الدعوة. تحقق من البريد الإلكتروني أو رقم الهاتف وحاول مرة أخرى."},
    "changes_not_saved": {"en": "Changes not saved. Your previous settings still apply.", "ar": "لم تُحفظ التغييرات. إعداداتك السابقة لا تزال سارية."},
    "owner_only": {"en": "Only the company owner can do this. Ask the owner for this right.", "ar": "مالك الشركة وحده من يمكنه القيام بذلك. اطلب هذه الصلاحية من المالك."},
    "sc14_stub": {"en": "Delegation aggregates appear from Phase 1C", "ar": "تظهر إجماليات التفويض اعتباراً من المرحلة 1ج"},
    "sc14_not_enabled": {"en": "not enabled", "ar": "غير مفعّل"},
    "sc14_fewer_than": {"en": "<10", "ar": "<10"},
    "sc14_as_of": {"en": "as of [date time]", "ar": "حتى [التاريخ والوقت]"},
    "stale_data": {"en": "Licence data is older than 48 hours. You can view and prepare; consent, delegation, approval and subscription changes wait until the record refreshes.", "ar": "بيانات الرخصة أقدم من 48 ساعة. يمكنك العرض والإعداد؛ وتنتظر تغييرات الموافقة والتفويض والاعتماد والاشتراك حتى يتم تحديث السجل."},
    "on_hold": {"en": "This company is on hold while the signatory change is confirmed. You can view and receive reminders; approvals, consent, delegate and subscription changes wait.", "ar": "هذه الشركة قيد الإيقاف حتى يتم تأكيد تغيير المفوَّض بالتوقيع. يمكنك العرض وتلقي التذكيرات؛ وتنتظر الموافقات والتفويض وتغييرات الاشتراك."},
    "firewall_no_conflict": {"en": "No conflict found in DET records", "ar": "لم يُعثر على تعارض في سجلات دائرة الاقتصاد والسياحة"},
    "firewall_conflict": {"en": "Conflict found in DET records. This engagement cannot proceed in the portal.", "ar": "عُثر على تعارض في سجلات دائرة الاقتصاد والسياحة. لا يمكن متابعة هذا التكليف في البوابة."},
    "firewall_declaration_required": {"en": "Independence declaration required before this engagement can start.", "ar": "يلزم إقرار الاستقلالية قبل بدء هذا التكليف."},
    # --- SC15 owner/delegate activity list (E1-S3) ---
    "ev_1": {"en": "Signed in with UAE Pass.", "ar": "تم تسجيل الدخول عبر الهوية الرقمية (UAE Pass)."},
    "ev_2": {"en": "Company data was viewed for [purpose].", "ar": "تم الاطلاع على بيانات الشركة لغرض [الغرض]."},
    "ev_3": {"en": "A document was uploaded: [file name].", "ar": "تم رفع مستند: [اسم الملف]."},
    "ev_4": {"en": "AI prepared a draft [item]. Status: draft.", "ar": "أعدّ الذكاء الاصطناعي مسودة [البند]. الحالة: مسودة."},
    "ev_5": {"en": "Return pack approved for [tax type], [period].", "ar": "تمت الموافقة على حزمة الإقرار: [نوع الضريبة]، [الفترة]."},
    "ev_6": {"en": "Approval voided because the pack changed.", "ar": "أُلغيت الموافقة لأن الحزمة تغيّرت."},
    "ev_7": {"en": "Consent for [purpose] was [given / paused / resumed / withdrawn].", "ar": "تم [منح / إيقاف / استئناف / سحب] الموافقة على [الغرض]."},
    "ev_8": {"en": "Delegate [name] was [added / changed / removed].", "ar": "تم [إضافة / تعديل / إزالة] المفوَّض [الاسم]."},
    "ev_9": {"en": "A request for a human specialist was [opened / updated / closed].", "ar": "تم [فتح / تحديث / إغلاق] طلب الإحالة إلى مختص."},
    "ev_10": {"en": "An audit working draft was [reviewed / returned] by a licensed auditor.", "ar": "راجع المدقق المرخّص مسودة عمل التدقيق أو أعادها."},
    "ev_11": {"en": "Auditor's report signed by a licensed auditor.", "ar": "وقّع المدقق المرخّص تقرير المدقق."},
    "ev_12": {"en": "Document [name] was issued / marked superseded.", "ar": "صدر المستند [الاسم] / أصبح مستبدلاً."},
    "ev_13": {"en": "Subscription [started / renewed / cancelled / paused].", "ar": "تم [بدء / تجديد / إلغاء / إيقاف] الاشتراك."},
    "ev_14": {"en": "Company records were exported.", "ar": "تم تصدير سجلات الشركة."},
    "actor_owner": {"en": "Acted by: [Name], owner", "ar": "بواسطة: [الاسم]، المالك"},
    "actor_delegate": {"en": "Acted by: [Name], delegate", "ar": "بواسطة: [الاسم]، المفوَّض"},
    "actor_ai": {"en": "Acted by: AI preparing (draft)", "ar": "بواسطة: الذكاء الاصطناعي (مسودة)"},
    "actor_auditor": {"en": "Acted by: licensed auditor, [firm]", "ar": "بواسطة: مدقق مرخّص، [الشركة]"},
    "actor_specialist": {"en": "Acted by: specialist, [coded role label]", "ar": "بواسطة: مختص، [التسمية]"},
    "actor_det": {"en": "Acted by: DET support", "ar": "بواسطة: دعم دائرة الاقتصاد والسياحة"},
    "outcome_done": {"en": "Done", "ar": "تم"},
    "outcome_refused": {"en": "Refused", "ar": "مرفوض"},
    "outcome_quarantined": {"en": "Quarantined", "ar": "قيد الحجر"},
    "activity_title": {"en": "Activity", "ar": "النشاط"},
    "export_title": {"en": "Activity list", "ar": "قائمة النشاط"},
}

# Word slots for the bracketed alternatives in the SC15 wording (chosen per event).
WORDS: dict[str, dict[str, str]] = {
    "given": {"en": "given", "ar": "منح"}, "paused": {"en": "paused", "ar": "إيقاف"}, "resumed": {"en": "resumed", "ar": "استئناف"}, "withdrawn": {"en": "withdrawn", "ar": "سحب"},
    "added": {"en": "added", "ar": "إضافة"}, "changed": {"en": "changed", "ar": "تعديل"}, "removed": {"en": "removed", "ar": "إزالة"},
    "opened": {"en": "opened", "ar": "فتح"}, "updated": {"en": "updated", "ar": "تحديث"}, "closed": {"en": "closed", "ar": "إغلاق"},
    "reviewed": {"en": "reviewed", "ar": "راجع"}, "returned": {"en": "returned", "ar": "أعاد"},
    "issued": {"en": "was issued", "ar": "صدر"}, "superseded": {"en": "was marked superseded", "ar": "أصبح مستبدلاً"},
    "started": {"en": "started", "ar": "بدء"}, "renewed": {"en": "renewed", "ar": "تجديد"}, "cancelled": {"en": "cancelled", "ar": "إلغاء"},
}
# Coded purposes / items shown in rows (never free text).
PURPOSES: dict[str, dict[str, str]] = {
    "dashboard": {"en": "the dashboard", "ar": "لوحة المتابعة"},
    "bookkeeping": {"en": "bookkeeping", "ar": "مسك الدفاتر"},
    "tax_preparation": {"en": "tax preparation", "ar": "إعداد الضرائب"},
    "audit_preparation": {"en": "audit preparation", "ar": "التحضير للتدقيق"},
    "bank_data": {"en": "bank and financial data", "ar": "البيانات المصرفية والمالية"},
    "documents": {"en": "documents", "ar": "المستندات"},
    "review": {"en": "review", "ar": "المراجعة"},
    "tax_escalation": {"en": "a tax question", "ar": "سؤال ضريبي"},
    "vat_return": {"en": "VAT return", "ar": "إقرار ضريبة القيمة المضافة"},
    "ct_return": {"en": "Corporate Tax return", "ar": "إقرار ضريبة الشركات"},
    "bookkeeping_period": {"en": "bookkeeping period", "ar": "فترة مسك الدفاتر"},
    "vat": {"en": "VAT", "ar": "ضريبة القيمة المضافة"},
    "ct": {"en": "Corporate Tax", "ar": "ضريبة الشركات"},
}
SPECIALIST_LABELS: dict[str, dict[str, str]] = {
    "tax_specialist": {"en": "Specialist (tax)", "ar": "مختص (ضرائب)"},
    "legal_specialist": {"en": "Specialist (legal routing)", "ar": "مختص (إحالة قانونية)"},
}

AUDIENCE = {k: ("official" if k.startswith(("ev_", "actor_", "no_owner", "access_", "role_refusal", "separation", "firewall")) else "other") for k in STRINGS}

try:  # the catalogue module may be absent at build time
    from app.modules.catalogue.service import register_strings

    register_strings("delegates", STRINGS, AUDIENCE)
except ImportError:  # pragma: no cover
    pass


def s(key: str, lang: str, **params: str) -> str:
    """Resolve a string in one language and fill ``[slot]`` placeholders from ``params`` (keys without brackets)."""
    text = STRINGS[key].get(lang) or STRINGS[key]["en"]
    for k, v in params.items():
        text = text.replace(f"[{k}]", v)
    return text
