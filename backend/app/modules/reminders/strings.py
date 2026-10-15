"""Reminder template registry texts and SC11 reminder-settings wording (E3-S4, E3-S5).

Templates carry ONLY: trade name (never in SMS), a generic deadline category, due date, status, a neutral action
line, the source-of-date tag, the information disclaimer and a sign-in-only portal link. Arabic texts the spec does
not supply are drafts that need a qualified translator; templates marked ``pending_translation`` are never used
(the reminder is held, the owner is told, the reviewer is alerted)."""

from __future__ import annotations

# --- template registry: (template_id, kind, channel_class) -> {en, ar, ar_status} ---------------------------------
TEMPLATES: dict[str, dict] = {
    "standard.portal": {"kind": "standard", "channel_class": "portal",
                        "en": "{trade_name}: {category} is due on {due_date}. Status: {status}. Source of the date: {source_tag}. {action_line} Sign in to see details: {portal_link}",
                        "ar": "{trade_name}: موعد {category} في {due_date}. الحالة: {status}. مصدر التاريخ: {source_tag}. {action_line} سجّل الدخول لعرض التفاصيل: {portal_link}"},
    "standard.outbound": {"kind": "standard", "channel_class": "outbound",
                          "en": "{trade_name}: a {category} deadline is on {due_date}. Status: {status}. Source of the date: {source_tag}. {action_line} Sign in to see details: {portal_link}",
                          "ar": "{trade_name}: موعد {category} في {due_date}. الحالة: {status}. مصدر التاريخ: {source_tag}. {action_line} سجّل الدخول لعرض التفاصيل: {portal_link}"},
    "standard.sms": {"kind": "standard", "channel_class": "sms",
                     "en": "Qeonix: a {category} deadline is on {due_date}. Status: {status}. Sign in to see details: {portal_link}",
                     "ar": "Qeonix: موعد {category} في {due_date}. الحالة: {status}. سجّل الدخول لعرض التفاصيل: {portal_link}"},
    "catch_up.portal": {"kind": "catch_up", "channel_class": "portal",
                        "en": "{trade_name}: catch-up reminder. {category} is due on {due_date}. Status: {status}. Source of the date: {source_tag}. {action_line} Sign in to see details: {portal_link}",
                        "ar": "{trade_name}: تذكير استدراكي. موعد {category} في {due_date}. الحالة: {status}. مصدر التاريخ: {source_tag}. {action_line} سجّل الدخول لعرض التفاصيل: {portal_link}", "ar_status": "pending_translation"},
    "catch_up.outbound": {"kind": "catch_up", "channel_class": "outbound",
                          "en": "{trade_name}: catch-up reminder. A {category} deadline is on {due_date}. Status: {status}. Source of the date: {source_tag}. {action_line} Sign in to see details: {portal_link}",
                          "ar": "{trade_name}: تذكير استدراكي. موعد {category} في {due_date}. الحالة: {status}. مصدر التاريخ: {source_tag}. {action_line} سجّل الدخول لعرض التفاصيل: {portal_link}", "ar_status": "pending_translation"},
    "overdue.portal": {"kind": "overdue", "channel_class": "portal",
                       "en": "{trade_name}: our records show this {category} item is overdue (due {due_date}). Penalties may apply; check the authority's current schedule. {action_line} Sign in to see details: {portal_link}",
                       "ar": "{trade_name}: تُظهر سجلاتنا أن موعد {category} قد فات (كان في {due_date}). قد تُفرض غرامات؛ راجع الجدول الحالي لدى الجهة المختصة. {action_line} سجّل الدخول لعرض التفاصيل: {portal_link}", "ar_status": "pending_translation"},
    "overdue.outbound": {"kind": "overdue", "channel_class": "outbound",
                         "en": "{trade_name}: our records show a {category} item is overdue (due {due_date}). Penalties may apply; check the authority's current schedule. Sign in to see details: {portal_link}",
                         "ar": "{trade_name}: تُظهر سجلاتنا أن موعد {category} قد فات (كان في {due_date}). قد تُفرض غرامات؛ راجع الجدول الحالي لدى الجهة المختصة. سجّل الدخول لعرض التفاصيل: {portal_link}", "ar_status": "pending_translation"},
    "date_updated.portal": {"kind": "date_updated", "channel_class": "portal",
                            "en": "{trade_name}: Date updated. The {category} date is now {due_date}. Source of the date: {source_tag}. Sign in to see details: {portal_link}",
                            "ar": "{trade_name}: تم تحديث التاريخ. أصبح موعد {category} في {due_date}. مصدر التاريخ: {source_tag}. سجّل الدخول لعرض التفاصيل: {portal_link}"},
    "dates_changed.portal": {"kind": "dates_changed", "channel_class": "portal",
                             "en": "{trade_name}: dates changed. Some deadline dates were updated to the current rules. Sign in to see details: {portal_link}",
                             "ar": "{trade_name}: تغيّرت المواعيد. حُدّثت بعض المواعيد وفق القواعد الحالية. سجّل الدخول لعرض التفاصيل: {portal_link}"},
    "requested.portal": {"kind": "requested", "channel_class": "portal",
                         "en": "{trade_name}: the reminder you asked for. Check {category}, due on {due_date}. Status: {status}. Sign in to see details: {portal_link}",
                         "ar": "{trade_name}: التذكير الذي طلبته. راجع {category}، الموعد في {due_date}. الحالة: {status}. سجّل الدخول لعرض التفاصيل: {portal_link}"},
    "requested.outbound": {"kind": "requested", "channel_class": "outbound",
                           "en": "{trade_name}: the reminder you asked for. Check the {category} deadline on {due_date}. Status: {status}. Sign in to see details: {portal_link}",
                           "ar": "{trade_name}: التذكير الذي طلبته. راجع موعد {category} في {due_date}. الحالة: {status}. سجّل الدخول لعرض التفاصيل: {portal_link}"},
    "quarantine_decision_needed.portal": {"kind": "quarantine_decision_needed", "channel_class": "portal",
                                          "en": "{trade_name}: Quarantine decision needed. Drafts are held for your review. Sign in to see details: {portal_link}",
                                          "ar": "{trade_name}: مطلوب قرار بشأن المسودات المحتجزة. المسودات محتجزة لمراجعتك. سجّل الدخول لعرض التفاصيل: {portal_link}", "ar_status": "pending_translation"},
}

CATEGORY_LABELS = {
    "tax_return": {"en": "tax return", "ar": "الإقرار الضريبي"},
    "vat_return": {"en": "VAT return", "ar": "إقرار ضريبة القيمة المضافة"},
    "corporate_tax_return": {"en": "corporate tax return", "ar": "إقرار ضريبة الشركات"},
    "licence_renewal": {"en": "licence renewal", "ar": "تجديد الرخصة"},
    "tenancy_renewal": {"en": "tenancy (Ejari) renewal", "ar": "تجديد عقد الإيجار (إيجاري)"},
    "chamber_membership": {"en": "chamber membership renewal", "ar": "تجديد عضوية الغرفة"},
    "licence_requirement": {"en": "licence requirement", "ar": "متطلب الرخصة"},
}
STATUS_LABELS = {
    "upcoming": {"en": "upcoming", "ar": "قادم"},
    "due_soon": {"en": "due soon", "ar": "يستحق قريبًا"},
    "overdue": {"en": "overdue", "ar": "متأخر"},
    "date_not_confirmed": {"en": "date not confirmed", "ar": "التاريخ غير مؤكد"},
}
SOURCE_TAGS = {
    "company_entered": {"en": "company-entered", "ar": "أدخلته الشركة"},
    "computed_not_confirmed": {"en": "calculated from the standard rule, not confirmed with the FTA", "ar": "محسوب وفق القاعدة العامة، ولم يُؤكَّد مع الهيئة الاتحادية للضرائب"},
    "licence_record": {"en": "licence record", "ar": "سجل الرخصة"},
    "fta_data": {"en": "FTA data", "ar": "بيانات الهيئة الاتحادية للضرائب"},
    "manual_entry": {"en": "manual entry", "ar": "إدخال يدوي"},
}
ACTION_LINES = {
    "track": {"en": "This reminder helps you track deadlines.", "ar": "يساعدك هذا التذكير على متابعة المواعيد."},
    "upload_receipt": {"en": "If you have already filed, upload your receipt.", "ar": "إذا كنت قد قدّمت الإقرار، فارفع الإيصال."},
    "confirm_authority": {"en": "Confirm with the authority.", "ar": "يُرجى التأكد مع الجهة المختصة."},
}
FLAG_LINES = {
    "date_under_review": {"en": "date under review", "ar": "التاريخ قيد المراجعة"},
    "holiday_calendar_not_confirmed": {"en": "holiday calendar not confirmed", "ar": "تقويم العطلات غير مؤكد"},
    "no_owner_level_user": {"en": "This company has no owner-level user", "ar": "لا يوجد مستخدم بصلاحية المالك لهذه الشركة"},
}
DISCLAIMER = {
    "en": "Information reminder, not tax advice. Based on the information you gave us and the standard UAE rules, a tax return may be due on {due_date}. We have not confirmed this with the Federal Tax Authority. Please check your EmaraTax account or ask a registered tax agent. Sign in to see details.",
    "ar": "تذكير للعلم فقط، وليس استشارة ضريبية. بناءً على المعلومات التي قدمتها والقواعد العامة في الدولة، قد يكون موعد تقديم إقرار ضريبي في {due_date}. لم نؤكد ذلك مع الهيئة الاتحادية للضرائب. يُرجى مراجعة حسابك في EmaraTax أو سؤال وكيل ضريبي مسجّل. سجّل الدخول لعرض التفاصيل.",
}

STRINGS: dict[str, dict[str, str]] = {
    "settings.title": {"en": "Reminders", "ar": "التذكيرات"},
    "settings.phase_note": {"en": "Email and SMS reminders start in a later phase; in-portal reminders are on", "ar": "تبدأ تذكيرات البريد الإلكتروني والرسائل النصية في مرحلة لاحقة؛ التذكيرات داخل البوابة مفعّلة"},
    "settings.locked": {"en": "Always on. Deadline and consent-expiry reminders protect you from penalties and lost access. You can choose the channel but not turn them off.", "ar": "مفعّل دائمًا. تذكيرات المواعيد النهائية وانتهاء الموافقة تحميك من الغرامات وفقدان الوصول. يمكنك اختيار القناة ولا يمكنك إيقافها."},
    "settings.whatsapp_off": {"en": "WhatsApp reminders are switched off by configuration.", "ar": "تذكيرات واتساب متوقفة بحسب الإعدادات."},
    "settings.sms_off": {"en": "SMS reminders start in a later phase. Your choice is saved and nothing is sent yet.", "ar": "تبدأ تذكيرات الرسائل النصية في مرحلة لاحقة. تم حفظ اختيارك ولن يُرسل شيء بعد."},
    "settings.delegate_view": {"en": "You are viewing as a delegate. Only the owner can change these settings.", "ar": "أنت تعرض بصفتك مفوَّضًا. المالك وحده يمكنه تغيير هذه الإعدادات."},
    "contact.unverified": {"en": "Unverified", "ar": "غير موثّق"},
    "contact.not_delivered": {"en": "Not delivered, check this address", "ar": "لم تصل الرسالة، تحقق من هذا العنوان"},
    "inbox.empty": {"en": "No reminders yet. When a deadline is near, it will appear here and be sent by the channel you chose.", "ar": "لا توجد تذكيرات بعد. عند اقتراب أي موعد نهائي سيظهر هنا ويُرسل عبر القناة التي اخترتها."},
    "inbox.error": {"en": "We could not load your reminders. Your saved settings are not changed. Try again.", "ar": "تعذّر تحميل التذكيرات. لم تتغيّر إعداداتك المحفوظة. حاول مرة أخرى."},
    "inbox.held_notice": {"en": "A reminder about {obligation} is delayed. We are preparing it in your language. Your deadline is {date}, {n} days left. You can check it now in the calendar.", "ar": "تأخّر تذكير بشأن {obligation}. نُعدّه بلغتك. موعدك النهائي {date}، المتبقي {n} يومًا. يمكنك مراجعته الآن في التقويم."},
    "request.set": {"en": "Reminder set for {date} by {channel}. We will tell you what is still missing.", "ar": "تم ضبط التذكير في {date} عبر {channel}. سنخبرك بما ينقصك بعد."},
    "request.cancelled": {"en": "Reminder cancelled.", "ar": "تم إلغاء التذكير."},
    "request.failed": {"en": "We could not set the reminder just now. Your request was not saved. Try again in a few minutes, or add the date to your own calendar.", "ar": "تعذّر ضبط التذكير الآن. لم يُحفظ طلبك. حاول بعد دقائق، أو أضف الموعد إلى تقويمك."},
    "request.no_right": {"en": "Only the owner or a delegate with reminder rights can set reminders. Ask the owner.", "ar": "يمكن للمالك أو للمفوَّض الذي يملك صلاحية التذكير فقط ضبط التذكيرات. اسأل المالك."},
}
for _tid, _t in TEMPLATES.items():
    STRINGS[f"template.{_tid}"] = {"en": _t["en"], "ar": _t["ar"]}
STRINGS["template.disclaimer"] = dict(DISCLAIMER)
AUDIENCE = {k: "official" for k in STRINGS}


def s(key: str, lang: str = "en", **params: str) -> str:
    entry = STRINGS.get(key)
    if entry is None:
        return key
    text = entry.get(lang) or entry.get("en", key)
    for k, v in params.items():
        text = text.replace("{" + k + "}", str(v))
    return text


try:  # the catalogue module may be absent at build time
    from app.modules.catalogue.service import register_strings

    register_strings("reminders", STRINGS, AUDIENCE)
except ImportError:  # pragma: no cover
    pass
