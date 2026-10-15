"""Backend wording for the SC3 dashboard aggregate (E3-S1) and the remote-owner view (E3-S5). Spec Arabic verbatim;
English-only spec strings carry a draft Arabic pending native-speaker review."""

from __future__ import annotations

STRINGS: dict[str, dict[str, str]] = {
    "panel.tax_status": {"en": "Tax status", "ar": "الحالة الضريبية"},
    "panel.audit_status": {"en": "Audit status", "ar": "حالة التدقيق"},
    "panel.deadlines": {"en": "Deadlines", "ar": "المواعيد"},
    "panel.documents": {"en": "Documents", "ar": "المستندات"},
    "panel.compliance": {"en": "Licence requirements", "ar": "متطلبات الرخصة"},
    "state.not_linked_yet": {"en": "Not linked yet", "ar": "لم يتم الربط بعد"},
    "state.not_shared": {"en": "Not shared with you. Ask the owner.", "ar": "غير مشارك معك. اسأل المالك."},
    "state.withheld": {"en": "Some obligations are not shared with you.", "ar": "بعض الالتزامات غير مشاركة معك."},
    "state.not_yet_assessed": {"en": "Not yet assessed", "ar": "لم يتم التقييم بعد"},
    "state.not_indicated": {"en": "Audit is not currently indicated for this company", "ar": "التدقيق غير مطلوب حاليًا لهذه الشركة بحسب المؤشرات"},
    "state.not_yet_measured": {"en": "Not yet measured", "ar": "لم يُقَس بعد"},
    "state.cannot_be_confirmed": {"en": "Cannot be confirmed", "ar": "تعذّر التأكيد"},
    "state.last_known": {"en": "Last known", "ar": "آخر قيمة معروفة"},
    "state.not_available": {"en": "Not available", "ar": "غير متاح"},
    "state.could_not_be_loaded": {"en": "Could not be loaded", "ar": "تعذّر التحميل"},
    "error.deadlines": {"en": "Deadlines could not be loaded. Try again, or see your licence expiry on the licence card.", "ar": "تعذّر تحميل المواعيد. حاول مرة أخرى، أو اطّلع على تاريخ انتهاء رخصتك في بطاقة الرخصة."},
    "audit.note": {"en": "Indicator only, not a legal determination. Audit is not required for every licence.", "ar": "مؤشر فقط، وليس قرارًا قانونيًا. التدقيق غير مطلوب لكل رخصة."},
    "audit.no_entry": {"en": "No entry yet", "ar": "لا يوجد إدخال بعد"},
    "tax.unconfirmed": {"en": "unconfirmed", "ar": "غير مؤكد"},
    "tax.declared_registered_vat": {"en": "VAT: registered (declared)", "ar": "ضريبة القيمة المضافة: مسجّل (بحسب الإقرار)"},
    "tax.declared_not_registered_vat": {"en": "VAT: not registered (declared)", "ar": "ضريبة القيمة المضافة: غير مسجّل (بحسب الإقرار)"},
    "tax.ct_status_declared": {"en": "Corporate tax: status declared by the company", "ar": "ضريبة الشركات: الحالة بحسب إقرار الشركة"},
    "tax.ct_status_unclear": {"en": "Corporate tax: status not set yet", "ar": "ضريبة الشركات: لم تُحدَّد الحالة بعد"},
    "tax.sbr_may_apply": {"en": "Small Business Relief may apply. It depends on revenue of AED 3 million or less in this period and every earlier period since 1 June 2023, resident status, and your election in the corporate tax return. Confirm with the FTA or a licensed tax adviser.", "ar": "قد ينطبق إعفاء الأعمال الصغيرة. يعتمد ذلك على ألا تتجاوز الإيرادات 3 ملايين درهم في هذه الفترة وفي كل فترة سابقة منذ 1 يونيو 2023، وعلى صفة الإقامة، وعلى اختيارك في إقرار ضريبة الشركات. تأكد مع الهيئة الاتحادية للضرائب أو مستشار ضريبي مرخّص."},
    "tax.sbr_not_available": {"en": "Small Business Relief: not available, based on declared data", "ar": "إعفاء الأعمال الصغيرة: غير متاح، بحسب البيانات المُقدَّمة"},
    "tax.audit_may_be_required": {"en": "Audited statements may be required. For corporate tax they are required only above AED 50 million revenue, for Qualifying Free Zone Persons and for tax groups.", "ar": "قد تكون البيانات المالية المدققة مطلوبة. وهي مطلوبة لأغراض ضريبة الشركات فقط عند تجاوز الإيرادات 50 مليون درهم، وللأشخاص المؤهلين في المناطق الحرة، وللمجموعات الضريبية."},
    "next.missing": {"en": "Add the missing items for {name}", "ar": "أضف البنود الناقصة لـ {name}"},
    "next.review_draft": {"en": "Review the prepared draft for {name}", "ar": "راجع المسودة المُعدّة لـ {name}"},
    "next.add_tax_details": {"en": "Add tax details", "ar": "إضافة البيانات الضريبية"},
    "next.renew_ejari": {"en": "Renew your Ejari, then your licence renewal can go ahead", "ar": "جدّد عقد إيجاري، ثم يمكن المتابعة في تجديد الرخصة"},
    "next.review_checklist": {"en": "Review the licence renewal checklist", "ar": "راجع قائمة تجديد الرخصة"},
    "next.renew_licence": {"en": "Renew the licence with DET", "ar": "جدّد الرخصة لدى دائرة الاقتصاد والسياحة"},
    "alert.link_failed": {"en": "A data link failed: {name}. Reconnect in the Consent Centre.", "ar": "تعذّر ربط مصدر بيانات: {name}. أعد الربط من مركز الموافقات."},
    "alert.consent_expired": {"en": "Consent expired on {date}", "ar": "انتهت الموافقة بتاريخ {date}"},
    "alert.ejari_lapsed": {"en": "Ejari expired on {date}, as last received from DET.", "ar": "انتهى عقد إيجاري بتاريخ {date} بحسب آخر بيانات وردت من دائرة الاقتصاد والسياحة."},
    "alert.unpaid_fee": {"en": "The subscription fee for licence {licence} is not paid yet. Your licence renewal is not affected.", "ar": "لم تُدفع رسوم الاشتراك للرخصة {licence} بعد. تجديد رخصتك غير متأثر."},
    "acting.owner": {"en": "Acting as: Owner", "ar": "تعمل بصفة: المالك"},
    "acting.delegate": {"en": "Acting as: Delegate for {owner}", "ar": "تعمل بصفة: مفوّض عن {owner}"},
    "acting.owner_abroad": {"en": "Owner abroad", "ar": "المالك خارج الدولة"},
    "remote.no_company": {"en": "We could not find a company for this sign-in. If you expect to see one, ask your company's authorised signatory to check your access, or contact DET support.", "ar": "لم نعثر على شركة مرتبطة بهذا الحساب. إذا كنت تتوقع ظهور شركة، يرجى مطالبة المفوّض بالتوقيع في شركتك بمراجعة صلاحياتك أو التواصل مع دعم دائرة الاقتصاد والسياحة."},
    "remote.generic_denial": {"en": "We could not sign you in to this service. Check that you used your own UAE Pass, then try again. If the problem continues, contact DET support.", "ar": "تعذّر تسجيل دخولك إلى هذه الخدمة. تأكد من استخدام هويتك الرقمية (UAE Pass) الخاصة بك ثم حاول مرة أخرى. إذا استمرت المشكلة، يرجى التواصل مع دعم دائرة الاقتصاد والسياحة."},
    "remote.not_available": {"en": "This service is not available.", "ar": "هذه الخدمة غير متاحة."},
    "remote.only_owner_approve": {"en": "Only the owner can approve", "ar": "يمكن للمالك فقط الموافقة"},
    "remote.request_expired": {"en": "This request has expired", "ar": "انتهت صلاحية هذا الطلب"},
    "remote.freshness_banner": {"en": "Last updated: {time} (Dubai time). {n} sources not current.", "ar": "آخر تحديث: {time} (بتوقيت دبي). {n} مصادر غير محدّثة."},
    "remembered.no_longer": {"en": "The company you used last time is no longer available to you. Choose a company.", "ar": "الشركة التي استخدمتها آخر مرة لم تعد متاحة لك. اختر شركة."},
    "no_companies": {"en": "No companies linked to your sign-in.", "ar": "لا توجد شركات مرتبطة بحسابك."},
}
AUDIENCE = {k: "official" for k in STRINGS}


def s(key: str, lang: str = "en", **params: str) -> str:
    entry = STRINGS.get(key)
    if entry is None:
        return key
    text = entry.get(lang) or entry.get("en", key)
    for k, v in params.items():
        text = text.replace("{" + k + "}", str(v))
    return text


def bi(key: str, **params: str) -> dict[str, str]:
    return {"en": s(key, "en", **params), "ar": s(key, "ar", **params)}


try:  # the catalogue module may be absent at build time
    from app.modules.catalogue.service import register_strings

    register_strings("dashboard", STRINGS, AUDIENCE)
except ImportError:  # pragma: no cover
    pass
