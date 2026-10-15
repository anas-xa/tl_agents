"""Bilingual strings for notices, refusals, labels and reminders (E8). Spec Arabic copied verbatim;
Arabic without a source value is a draft pending native review (audience_class 'other')."""

from __future__ import annotations

STRINGS: dict[str, dict[str, str]] = {
    # SC10 label and neutral states (E8-S1 §6)
    "information_not_advice": {"en": "This is general information, not legal or tax advice.", "ar": "هذه معلومات عامة وليست استشارة قانونية أو ضريبية."},
    "licensed_professional_can_review": {"en": "A licensed professional can review this matter. We will show the expected response time when a route is available.", "ar": "يمكن لمختص مرخّص مراجعة هذه المسألة. سنعرض مدة الرد المتوقعة عند توفر المسار."},
    "status.open": {"en": "Open", "ar": "مفتوحة"},
    "status.awaiting_consent": {"en": "Awaiting your consent", "ar": "بانتظار موافقتك"},
    "status.with_specialist": {"en": "With a specialist", "ar": "لدى مختص"},
    "status.rejected": {"en": "Rejected by you", "ar": "مرفوضة من قِبلك"},
    "status.resolved": {"en": "Resolved", "ar": "تمت المعالجة"},
    "status.closed": {"en": "Closed", "ar": "مغلقة"},
    "status.closed_no_consent": {"en": "Closed - no consent", "ar": "مغلقة - بدون موافقة"},
    "status.awaiting_specialist_assignment": {"en": "Awaiting specialist assignment", "ar": "بانتظار تعيين مختص"},
    "status.waiting_for_you": {"en": "Waiting for you", "ar": "بانتظارك"},
    "reject_case": {"en": "Reject case", "ar": "رفض الحالة"},
    "cancel": {"en": "Cancel", "ar": "إلغاء"},
    "choose_reason": {"en": "Choose a reason to continue.", "ar": "اختر سببًا للمتابعة."},
    "case_rejected": {"en": "Case rejected. Nothing was shared. You can reopen it from this list.", "ar": "تم رفض الحالة. لم تتم مشاركة أي بيانات. يمكنك إعادة فتحها من هذه القائمة."},
    "next_step.tax": {"en": "A tax specialist will review this. You will be told here when they pick it up.", "ar": "سيراجع مختص ضريبي هذه الحالة. سيتم إعلامك هنا عند استلامها."},
    "next_step.audit": {"en": "A licensed auditor will review the audit work. Nothing is signed until they do.", "ar": "سيراجع مدقق مرخّص أعمال التدقيق. لن يتم التوقيع على شيء قبل ذلك."},
    "next_step.compliance": {"en": "DET compliance will look at this. You will be told here if they need anything from you.", "ar": "ستنظر إدارة الامتثال في DET في هذه الحالة. سيتم إعلامك هنا إذا احتاجوا إلى شيء منك."},
    "consent_needed": {"en": "This case needs access to some of your data. Nothing is shared until you agree.", "ar": "تحتاج هذه الحالة إلى الاطلاع على بعض بياناتك. لن تتم مشاركة أي شيء قبل موافقتك."},
    "review_and_decide": {"en": "Review and decide", "ar": "مراجعة واتخاذ القرار"},
    "only_owner_can_reject": {"en": "Only the owner can reject a case.", "ar": "يمكن للمالك فقط رفض الحالة."},
    "reject.R1": {"en": "I do not need this", "ar": "لا أحتاج إلى هذا"},
    "reject.R2": {"en": "This is not my matter", "ar": "هذه ليست مسألتي"},
    "reject.R3": {"en": "I do not want to share my data", "ar": "لا أرغب في مشاركة بياناتي"},
    "reject.R4": {"en": "I will handle it myself or with my own adviser", "ar": "سأتولى الأمر بنفسي أو مع مستشاري"},
    "reject.R5": {"en": "Other (add a note)", "ar": "أخرى (أضف ملاحظة)"},
    "held_for_review": {"en": "We could not check this item; it is held for review.", "ar": "تعذّر التحقق من هذا العنصر؛ تم حجزه للمراجعة."},
    "case_setup_pending": {"en": "We are setting up your case; no action needed", "ar": "نقوم بإعداد حالتك؛ لا حاجة لأي إجراء"},
    "ai_label": {"en": "AI prepared, not human approved", "ar": "أعدّه الذكاء الاصطناعي، ولم يعتمده مختص"},
    # E8-S2
    "waiting_owner_consent": {"en": "Waiting for the owner's consent", "ar": "بانتظار موافقة المالك"},
    "consent_expired": {"en": "Consent expired", "ar": "انتهت صلاحية الموافقة"},
    "access_withdrawn": {"en": "Access withdrawn by the owner", "ar": "سحب المالك الإذن"},
    "no_access_item": {"en": "You do not have access to this item. Access depends on the owner's consent.", "ar": "لا تملك صلاحية الوصول إلى هذا العنصر. يعتمد الوصول على موافقة المالك."},
    "locked_until_consent": {"en": "Locked until the owner consents", "ar": "مقفل حتى موافقة المالك"},
    "supplied_documents_label": {"en": "Based only on documents supplied by the owner on {date}; not verified against bank, ledger or FTA records; not an audit opinion.", "ar": "استنادًا فقط إلى المستندات التي قدّمها المالك بتاريخ {date}؛ لم يتم التحقق منها مقابل سجلات البنك أو دفتر الأستاذ أو الهيئة الاتحادية للضرائب؛ وليست رأي تدقيق."},
    "consent_wait.reminder": {"en": "Reminder: a case is waiting for your decision on data access. Nothing has been shared and no advice has been given.", "ar": "تذكير: هناك حالة بانتظار قرارك بشأن الاطلاع على البيانات. لم تتم مشاركة أي شيء ولم تُقدَّم أي استشارة."},
    "consent_wait.closed": {"en": "This case was closed because no consent was given. Nothing was shared and no review was done. You can reopen it within {days} days with the same reference.", "ar": "أُغلقت هذه الحالة لعدم منح الموافقة. لم تتم مشاركة أي شيء ولم تُجرَ أي مراجعة. يمكنك إعادة فتحها خلال {days} يومًا بالمرجع نفسه."},
    "consent_wait.deadline_remains": {"en": "The filing deadline and any penalty risk remain yours.", "ar": "يبقى موعد التقديم وأي مخاطر غرامات على عاتقك."},
    "you_no_longer_have_access": {"en": "You no longer have access to this case.", "ar": "لم تعد تملك صلاحية الوصول إلى هذه الحالة."},
    "entitlement_invalid": {"en": "Your entitlement record is not current. Access is refused and the case owner has been told.", "ar": "سجل استحقاقك غير ساري. تم رفض الوصول وإبلاغ مالك الحالة."},
    # E8-S3
    "qa.status_chip": {"en": "AI-prepared · Draft · Not human-approved", "ar": "أعدّه الذكاء الاصطناعي · مسودة · لم يعتمده مختص"},
    "qa.label": {"en": "General information, not legal or tax advice.", "ar": "معلومات عامة، وليست استشارة قانونية أو ضريبية."},
    "qa.answered": {"en": "Answered from our sources.", "ar": "تمت الإجابة من مصادرنا."},
    "qa.not_answered": {"en": "We have not answered this question.", "ar": "لم نجب عن هذا السؤال."},
    "qa.refusal_line": {"en": "Our sources do not support a reliable answer. A licensed person will review this. We have not guessed.", "ar": "مصادرنا لا تدعم إجابة موثوقة. سيراجع هذا السؤال مختص مرخّص. لم نقدّم أي تخمين."},
    "qa.refusal_line_minimal": {"en": "We cannot answer this from our sources. A human will review it.", "ar": "لا يمكننا الإجابة عن هذا السؤال من مصادرنا. سيراجعه شخص مختص."},
    "qa.told_when_ready": {"en": "You will be told when a reply is ready.", "ar": "سنبلغك عند جاهزية الرد."},
    "qa.legal_neutral": {"en": "This service gives general information only. It cannot give legal advice. A licensed lawyer can help.", "ar": "تقدّم هذه الخدمة معلومات عامة فقط، ولا يمكنها تقديم استشارة قانونية. يمكن لمحامٍ مرخّص مساعدتك."},
    "qa.legal_own_choice": {"en": "The platform cannot advise on this. You may consult a licensed lawyer of your own choice.", "ar": "لا يمكن للمنصة تقديم استشارة في هذا الشأن. يمكنك استشارة محامٍ مرخّص من اختيارك."},
    "qa.original_language": {"en": "Shown in the original language. The summary above is AI-generated.", "ar": "معروض بلغته الأصلية. الملخص أعلاه أعدّه الذكاء الاصطناعي."},
    "qa.original_language_arabic": {"en": "Shown in the original language (Arabic). The summary above is AI-generated.", "ar": "معروض بلغته الأصلية (الإنجليزية). الملخص أعلاه أعدّه الذكاء الاصطناعي."},
    "qa.case_retrying": {"en": "We could not create your case yet. We are retrying.", "ar": "تعذّر إنشاء حالتك حتى الآن. نعيد المحاولة."},
    "qa.case_failed": {"en": "Your case was not created. Your question is saved. Try again or contact support.", "ar": "لم يتم إنشاء حالتك. تم حفظ سؤالك. أعد المحاولة أو تواصل مع الدعم."},
    "qa.retry_now": {"en": "Retry now", "ar": "أعد المحاولة الآن"},
    "qa.sources": {"en": "Sources", "ar": "المصادر"},
    "qa.ask_a_human": {"en": "Ask a human", "ar": "اسأل مختصاً"},
    "qa.open_case": {"en": "Open case", "ar": "فتح الحالة"},
    "qa.send_to_licensed_person": {"en": "Send to a licensed person", "ar": "إرسال إلى مختص مرخّص"},
    "qa.tax_disclaimer": {"en": "General information from the cited law. AI prepared, not human approved. Not tax advice. Confirm with the Federal Tax Authority or a registered tax agent.", "ar": "معلومات عامة من القانون المذكور. أعدّه الذكاء الاصطناعي ولم يعتمده مختص. ليست استشارة ضريبية. تأكد من الهيئة الاتحادية للضرائب أو وكيل ضريبي مسجّل."},
    "qa.unofficial_translation": {"en": "Unofficial translation. The Arabic text is authoritative.", "ar": "ترجمة غير رسمية. النص العربي هو المعتمد."},
    "qa.own_position_general_rule": {"en": "We cannot apply the rule to your own figures. The general rule is shown below; a human tax specialist will review your question.", "ar": "لا يمكننا تطبيق القاعدة على أرقامك الخاصة. القاعدة العامة معروضة أدناه؛ وسيراجع مختص ضريبي سؤالك."},
    # E8-S4
    "k21.title": {"en": "Human escalation rate (K21): escalated cases per 100 cases", "ar": "معدل التصعيد البشري (K21): الحالات المصعّدة لكل 100 حالة"},
    "k22.title": {"en": "Escalation turnaround (K22): average working days from escalation to resolution", "ar": "مدة معالجة التصعيد (K22): متوسط أيام العمل من التصعيد إلى الحل"},
    "k.fewer_than_n": {"en": "Fewer than {n} cases (hidden to protect privacy)", "ar": "أقل من {n} حالات (مخفية لحماية الخصوصية)"},
    "k.open_not_counted": {"en": "Open cases are not counted in turnaround", "ar": "الحالات المفتوحة لا تُحتسب في مدة المعالجة"},
    "k.aggregate_only": {"en": "Aggregate figures only. No company details are shown.", "ar": "أرقام إجمالية فقط. لا تُعرض أي تفاصيل عن الشركات."},
}

AUDIENCE_CLASS: dict[str, str] = {k: ("other" if k.startswith(("k21", "k22", "k.", "qa.own_position", "qa.unofficial", "consent_wait", "entitlement", "status.closed_no", "status.awaiting_spec", "status.waiting", "held_for", "case_setup", "supplied")) else "official") for k in STRINGS}

try:  # the catalogue module may be absent at build time
    from app.modules.catalogue.service import register_strings

    register_strings("escalation", STRINGS, AUDIENCE_CLASS)
except ImportError:  # pragma: no cover
    pass


def text(key: str, lang: str = "en", **params: object) -> str:
    item = STRINGS.get(key, {})
    value = item.get(lang) or item.get("en") or key
    try:
        return value.format(**params) if params else value
    except (KeyError, IndexError):
        return value


def bilingual(key: str, **params: object) -> dict[str, str]:
    return {"en": text(key, "en", **params), "ar": text(key, "ar", **params)}
