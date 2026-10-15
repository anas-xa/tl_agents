"""Bilingual strings for E7-S1..E7-S4 (verbatim from the spec where given; other Arabic is a draft pending native review).

Every string that ends up in a draft file, notice, reminder, refusal or watermark lives here.
"""

from __future__ import annotations

# Fixed, non-editable watermark of every unsigned audit work draft (file) and the image strip.
WATERMARK = {"en": "DRAFT - NOT AN AUDIT REPORT", "ar": "مسودة أعمال تدقيق - ليست تقرير تدقيق"}
WATERMARK_STRIP = {"en": "DRAFT - NOT AN AUDIT REPORT", "ar": "مسودة - ليست تقرير تدقيق"}
DELIVERABLE_NAME = {"en": "audit work draft", "ar": "مسودة أعمال تدقيق"}

STRINGS: dict[str, dict[str, str]] = {
    "watermark": WATERMARK,
    "watermark_strip": WATERMARK_STRIP,
    "deliverable_name": DELIVERABLE_NAME,
    "file_title": {"en": "Draft audit working file", "ar": "مسودة ملف أعمال تدقيق"},
    "page1_notice": {"en": "Not an audit opinion. Not for submission to any authority.", "ar": "ليس رأي تدقيق. ليس للتقديم إلى أي جهة."},
    "fixed_draft_text": {"en": "Draft prepared by AI from company data. Not an audit. Not signed by a licensed auditor. Not tax advice. Not for submission to any authority.", "ar": "مسودة أعدّها الذكاء الاصطناعي من بيانات الشركة. ليست تدقيقًا. غير موقّعة من مدقق حسابات مرخّص. ليست استشارة ضريبية. ليست للتقديم إلى أي جهة."},
    "header_label": {"en": "AI-prepared audit work draft, not signed. Status: {status}", "ar": "مسودة أعمال تدقيق أعدّها الذكاء الاصطناعي، غير موقّعة. الحالة: {status}"},
    "export_header": {"en": "AI-prepared audit work draft. Status: {status}", "ar": "مسودة أعمال تدقيق أعدّها الذكاء الاصطناعي. الحالة: {status}"},
    "status_awaiting_auditor": {"en": "Draft, awaiting licensed auditor", "ar": "مسودة، بانتظار مدقق مرخّص"},
    "status_no_auditor": {"en": "Draft, no auditor assigned", "ar": "مسودة، لم يُعيَّن مدقق"},
    "status_under_review": {"en": "Under review by a licensed auditor", "ar": "قيد مراجعة مدقق مرخّص"},
    "status_under_review_short": {"en": "Under review", "ar": "قيد المراجعة"},
    "status_rejected": {"en": "Rejected", "ar": "مرفوضة"},
    "status_not_started": {"en": "Not started", "ar": "لم يبدأ"},
    "status_signed_outside": {"en": "Signed outside platform", "ar": "موقّع خارج المنصة"},
    "out_of_date": {"en": "Out of date", "ar": "لم تعد محدّثة"},
    "signing_not_available": {"en": "Signing not available in this version", "ar": "التوقيع غير متاح في هذه النسخة"},
    "incomplete": {"en": "INCOMPLETE", "ar": "غير مكتملة"},
    "data_gaps": {"en": "Data gaps", "ar": "فجوات البيانات"},
    "gap_n": {"en": "Gap {n}", "ar": "فجوة {n}"},
    "page_n_of_m": {"en": "Page {n} of {m}", "ar": "صفحة {n} من {m}"},
    "export_footer": {"en": "Not verified. No verification code. Not for submission to any authority. Generated {date} by AI. Page {n} of {m}", "ar": "غير متحقق منه. لا يوجد رمز تحقق. ليس للتقديم إلى أي جهة. أُنشئ بتاريخ {date} بواسطة الذكاء الاصطناعي. صفحة {n} من {m}"},
    "no_code_until_signed": {"en": "No verification code until signed by a licensed auditor", "ar": "لا يوجد رمز تحقق قبل توقيع مدقق مرخّص"},
    "incomplete_banner": {"en": "Incomplete draft. {n} of {m} items still missing. Figures that depend on them show Gap {n}.", "ar": "مسودة غير مكتملة. ما زال {n} من {m} بنداً ناقصاً. الأرقام المرتبطة بها تظهر كـ «فجوة {n}»."},
    "no_draft_yet": {"en": "No audit work draft yet. Your period ends on {date}. We will prepare a draft once your data is complete.", "ar": "لا توجد مسودة أعمال تدقيق بعد. تنتهي فترتك في {date}. سنعدّ المسودة عند اكتمال بياناتك."},
    "refused_run": {"en": "We did not prepare a draft because {cause}. No data was read. Next step: {step}.", "ar": "لم نُعدّ مسودة لأن {cause}. لم تُقرأ أي بيانات. الخطوة التالية: {step}."},
    "no_data_read": {"en": "No data was read", "ar": "لم تُقرأ أي بيانات"},
    "blocked_release": {"en": "This file cannot be released. It is an unsigned draft and is not an audit report. {reason}.", "ar": "لا يمكن إصدار هذا الملف. إنه مسودة غير موقّعة وليس تقرير تدقيق. {reason}."},
    "invalid_since": {"en": "Invalid since {date}, reason: data edited", "ar": "غير صالحة"},
    "returned_heading": {"en": "Returned by the reviewing auditor", "ar": "أعادها المدقق المراجع"},
    "returned_next": {"en": "The draft has returned to preparation. Fix the items below; we will prepare a revised draft.", "ar": "عادت المسودة إلى مرحلة الإعداد. عالج البنود أدناه وسنعدّ مسودة معدّلة."},
    "not_yet_translated": {"en": "Not yet translated", "ar": "لم تُترجم بعد"},
    "bank_evidence_not_provided": {"en": "bank evidence not provided", "ar": "لم تُقدَّم أدلة بنكية"},
    "to_be_obtained_by_auditor": {"en": "to be obtained by auditor", "ar": "يحصل عليها المدقق"},
    "supplied_documents_only": {"en": "Based only on supplied documents, not an audit opinion.", "ar": "استنادًا إلى المستندات المقدَّمة فقط، وليس رأي تدقيق."},
    # E7-S4
    "sc13_badge": {"en": "Draft audit working file, unsigned", "ar": "مسودة ملف أعمال تدقيق، غير موقّعة"},
    "sc13_ai_notice": {"en": "This document is AI-prepared. Your review is recorded. It is not an audit report or certificate.", "ar": "هذا المستند أعدّه الذكاء الاصطناعي. تُسجَّل مراجعتك. وهو ليس تقرير تدقيق ولا شهادة."},
    "review_recorded": {"en": "Review recorded by {name}, register no. {x}, on {date}. Draft audit working file, unsigned. Not an audit report, not an opinion.", "ar": "سُجّلت المراجعة من {name}، رقم القيد {x}، بتاريخ {date}. مسودة ملف أعمال تدقيق، غير موقّعة. ليست تقرير تدقيق ولا رأيًا."},
    "signed_outside": {"en": "Signed outside the platform, reported by {name}, {role}, on {date}. Not verified by the platform or by any authority.", "ar": "موقّع خارج المنصة، أفاد به {name}، {role}، بتاريخ {date}. لم تتحقق منه المنصة ولا أي جهة."},
    "signing_blocked": {"en": "Signing blocked: licence not confirmed or engagement not assigned", "ar": "التوقيع متوقف: الترخيص غير مؤكد أو المهمة غير مسندة"},
    "signature_void": {"en": "Signature void: data changed after signing. Review again.", "ar": "التوقيع لاغٍ: تغيّرت البيانات بعد التوقيع. راجع مرة أخرى."},
    "register_unreachable": {"en": "We cannot reach the auditor register, so signing is blocked. You can keep reviewing. Try again, or contact support.", "ar": "لا يمكننا الوصول إلى سجل المدققين، لذلك تم إيقاف التوقيع. يمكنك متابعة المراجعة. أعد المحاولة أو تواصل مع الدعم."},
    "licence_not_checked": {"en": "Your licence could not be checked. Review cannot be recorded until it is.", "ar": "تعذّر التحقق من ترخيصك. لا يمكن تسجيل المراجعة قبل ذلك."},
    "licence_not_found": {"en": "Your licence was not found on the auditor register. Signing is blocked. Contact support.", "ar": "لم يتم العثور على ترخيصك في سجل المدققين. التوقيع متوقف. تواصل مع الدعم."},
    "not_assigned": {"en": "This engagement is not assigned to you.", "ar": "هذه المهمة غير مسندة إليك."},
    "resolve_open_first": {"en": "Resolve all open exceptions first ({n} open).", "ar": "عالج جميع الاستثناءات المفتوحة أولاً ({n} مفتوحة)."},
    "reminder_deadline": {"en": "Reminder: the review deadline for engagement {ref} is on {date}. Status: {status}.", "ar": "تذكير: موعد المراجعة للمهمة {ref} هو {date}. الحالة: {status}."},
    "escalation_inactive": {"en": "Engagement {ref} has had no review activity for {n} working days.", "ar": "لم يُسجَّل أي نشاط مراجعة على المهمة {ref} منذ {n} أيام عمل."},
    "auditors_report": {"en": "Auditor's report", "ar": "تقرير مدقق الحسابات"},
    # E7-S1
    "ai_pending": {"en": "AI-generated, pending human review", "ar": "أُنشئ بالذكاء الاصطناعي، بانتظار المراجعة البشرية"},
    "ai_reviewed": {"en": "AI-generated, reviewed by {name}", "ar": "أُنشئ بالذكاء الاصطناعي، راجعه {name}"},
    "flag_prompt": {"en": "A flag is a prompt to check, not a finding of wrongdoing.", "ar": "التنبيه دعوة للتحقق وليس إثباتًا لمخالفة"},
    "cash_rule_label": {"en": "internal review threshold, not a legal limit", "ar": "حد مراجعة داخلي، وليس حدًا قانونيًا"},
    "hidden_withdrawn": {"en": "Hidden: source withdrawn", "ar": "مخفي: تم سحب المصدر"},
    # E7-S2 indicator wording (fixed approved wording; 'may', never 'must')
    "badge_indicative": {"en": "Indicative, pending expert confirmation", "ar": "إرشادي، بانتظار تأكيد الخبير"},
    "headline_likely_required": {"en": "Likely required: based on {reason}. Confirm with a licensed auditor.", "ar": "مطلوب على الأرجح: بناءً على {reason}. تحقّق من ذلك مع مدقق حسابات مرخّص."},
    "may_be_required": {"en": "Audited financial statements may be required for corporate tax. Check with the FTA or a licensed auditor.", "ar": "قد تكون القوائم المالية المدققة مطلوبة لأغراض ضريبة الشركات. تحقّق من ذلك مع الهيئة الاتحادية للضرائب أو مدقق حسابات مرخّص."},
    "headline_likely_not_required": {"en": "Likely not required: the current criteria do not indicate an audit for your company. This is not advice.", "ar": "غير مطلوب على الأرجح: المعايير الحالية لا تشير إلى حاجة شركتك إلى تدقيق. هذا ليس استشارة."},
    "not_indicated_detail": {"en": "Indicative: based on the information in your account and the current corporate tax criteria, an audit is not indicated for tax purposes. Other authorities or your bank may still ask for one. This is general information, not advice. Pending expert confirmation.", "ar": "إرشادي: بناءً على المعلومات في حسابك ومعايير ضريبة الشركات الحالية، لا يُشار إلى تدقيق لأغراض ضريبية. قد تطلبه جهات أخرى أو مصرفك. هذه معلومات عامة وليست استشارة. بانتظار تأكيد الخبير."},
    "headline_cannot_determine": {"en": "Cannot determine", "ar": "تعذّر التحديد"},
    "cannot_determine_items": {"en": "Cannot determine: we need {items}", "ar": "تعذّر التحديد: نحتاج إلى {items}"},
    "near_threshold_strip": {"en": "Close to the threshold. Referred to a human specialist.", "ar": "قريب من الحد. أُحيل إلى مختص."},
    "at_threshold": {"en": "at the threshold, confirm with a specialist", "ar": "عند الحد تمامًا، تحقّق مع مختص"},
    "caveat_revenue_only": {"en": "Based on revenue only. Tax group status not confirmed. Audited statements are also required for tax groups.", "ar": "استنادًا إلى الإيرادات فقط. وضع المجموعة الضريبية غير مؤكد. القوائم المدققة مطلوبة أيضًا للمجموعات الضريبية."},
    "disclaimer_basis": {"en": "Indicative information only. Based on the figures held in this portal and on corporate tax rules as versioned [{rule_set}, {date}].", "ar": "معلومات إرشادية فقط. مبنية على الأرقام المحفوظة في هذه البوابة وعلى قواعد ضريبة الشركات وفق الإصدار [{rule_set}، {date}]."},
    "disclaimer": {"en": "This is not a legal, tax or audit determination and not advice. Whether your company needs audited financial statements depends on facts this portal may not hold, such as your total revenue for the tax period, your tax group or free-zone status, and requirements set by other authorities or your bank. Please confirm with the Federal Tax Authority or a licensed professional of your choice.", "ar": "هذا ليس قرارًا قانونيًا أو ضريبيًا أو قرار تدقيق وليس استشارة. تعتمد حاجة شركتك إلى قوائم مالية مدققة على وقائع قد لا تتوفر في هذه البوابة، مثل إجمالي إيراداتك للفترة الضريبية، ووضع المجموعة الضريبية أو المنطقة الحرة، ومتطلبات جهات أخرى أو مصرفك. يُرجى التأكد من الهيئة الاتحادية للضرائب أو من مختص مرخّص تختاره."},
    "shown_because_revenue": {"en": "Shown because revenue recorded for the period is above AED 50 million.", "ar": "يظهر لأن الإيرادات المسجّلة للفترة تتجاوز 50 مليون درهم."},
    "next_steps": {"en": "You may wish to check the requirement with the Federal Tax Authority or with a licensed auditor of your choice. A list of licensed auditors is kept by the Ministry of Economy.", "ar": "قد ترغب في التحقق من هذا المتطلب مع الهيئة الاتحادية للضرائب أو مع مدقق حسابات مرخّص تختاره. تحتفظ وزارة الاقتصاد بقائمة مدققي الحسابات المرخّصين."},
    "free_choice": {"en": "You are free to choose any licensed auditor.", "ar": "لك حرية اختيار أي مدقق حسابات مرخّص."},
    "ask_review": {"en": "Ask for a review by a human specialist", "ar": "اطلب مراجعة من مختص بشري"},
    "review_target": {"en": "A person will look at this. Pilot target: {n} working days (a target, not a commitment).", "ar": "سينظر شخص في هذا. الهدف التجريبي: {n} أيام عمل (هدف وليس التزامًا)."},
    "reason_revenue_threshold": {"en": "revenue above the threshold for the tax period", "ar": "إيرادات تتجاوز الحد للفترة الضريبية"},
    "reason_qualifying_free_zone_person": {"en": "a declared Qualifying Free Zone Person status", "ar": "صفة شخص مؤهل في منطقة حرة مُصرَّح بها"},
    "reason_tax_group": {"en": "declared membership of a corporate tax group", "ar": "عضوية مُصرَّح بها في مجموعة ضريبية"},
}
STATUS_LABEL_KEYS = {"draft": "status_no_auditor", "under_review": "status_under_review", "rejected": "status_rejected", "signed": "status_signed_outside"}
AUDIENCE: dict[str, str] = {k: "official" for k in STRINGS}

try:
    from app.modules.catalogue.service import register_strings

    register_strings("auditagent", STRINGS, AUDIENCE)
except ImportError:  # pragma: no cover
    pass


def s(key: str, lang: str = "en", **params: object) -> str:
    text = STRINGS.get(key, {}).get(lang) or STRINGS.get(key, {}).get("en") or key
    for k, v in params.items():
        text = text.replace("{" + k + "}", str(v))
    return text


def both(key: str, **params: object) -> dict[str, str]:
    return {"en": s(key, "en", **params), "ar": s(key, "ar", **params)}
