"""Bilingual strings for SC14 KPI payloads, exports and refusals (E9-S1 §6 wording list, verbatim).

Arabic is a draft pending native review. ``audience_class``: 'other' for dashboard text (not official-facing).
"""

from __future__ import annotations

STRINGS: dict[str, dict[str, str]] = {
    "banner": {"en": "Aggregate figures only. Company financial detail is not available to your role.", "ar": "أرقام مجمّعة فقط. التفاصيل المالية للشركات غير متاحة لدورك."},
    "revenue_note": {"en": "Revenue figures are billed amounts from the pilot, not forecasts", "ar": "أرقام الإيرادات هي مبالغ مفوترة من المرحلة التجريبية وليست توقعات."},
    "empty": {"en": "No subscribed licences yet. Figures will appear after the first licence is issued or renewed with the service.", "ar": "لا توجد رخص مشتركة بعد. ستظهر الأرقام بعد إصدار أول رخصة أو تجديدها مع الخدمة."},
    "no_data": {"en": "No data yet", "ar": "لا توجد بيانات بعد"},
    "not_applicable": {"en": "Not applicable", "ar": "غير منطبق"},
    "na.no_invoices": {"en": "No invoices fall in this period.", "ar": "لا توجد فواتير في هذه الفترة."},
    "na.no_subscriptions_in_period": {"en": "No subscriptions fall in this period.", "ar": "لا توجد اشتراكات في هذه الفترة."},
    "na.no_renewals_due_yet": {"en": "No renewals due yet", "ar": "لا توجد تجديدات مستحقة بعد"},
    "na.no_renewals_due_in_period": {"en": "No renewals fall due in this period.", "ar": "لا توجد تجديدات مستحقة في هذه الفترة."},
    "na.no_expiries_in_period": {"en": "No licence expiries fall in this period.", "ar": "لا توجد رخص تنتهي في هذه الفترة."},
    "na.no_returns_due": {"en": "No returns fall due in this period.", "ar": "لا توجد إقرارات مستحقة في هذه الفترة."},
    "na.not_yet_evaluated": {"en": "No licence has been evaluated for this period yet.", "ar": "لم يتم تقييم أي رخصة لهذه الفترة بعد."},
    "na.no_active_licences": {"en": "No active subscribed licences in this period.", "ar": "لا توجد رخص مشتركة نشطة في هذه الفترة."},
    "na.no_default_on": {"en": "No default-on subscriptions in this period.", "ar": "لا توجد اشتراكات مفعّلة تلقائياً في هذه الفترة."},
    "stale": {"en": "Stale: last updated {when}", "ar": "غير محدّث: آخر تحديث {when}"},
    "partial": {"en": "Partial: {n} of {m} sources included. This figure may change.", "ar": "جزئي: تم تضمين {n} من أصل {m} من المصادر. قد يتغير هذا الرقم."},
    "provisional_k3": {"en": "Provisional: payments still being collected. This rate can rise.", "ar": "مؤقت: لا تزال الدفعات قيد التحصيل. قد يرتفع هذا المعدل."},
    "not_yet_available": {"en": "Not yet available. Planned for Phase {x}.", "ar": "غير متاح بعد. مخطط له في المرحلة {x}."},
    "coming_later": {"en": "Coming in later phases", "ar": "قريباً في مراحل لاحقة"},
    "fewer_than_n": {"en": "Fewer than {n} licences (hidden to protect privacy)", "ar": "أقل من {n} رخص (مخفي لحماية الخصوصية)"},
    "other": {"en": "Other", "ar": "أخرى"},
    "other_note": {"en": "Includes groups with fewer than {n} licences.", "ar": "تشمل مجموعات تضم أقل من {n} رخص."},
    "combined_or_hidden": {"en": "Some groups are combined or hidden to protect privacy.", "ar": "تم دمج بعض المجموعات أو إخفاؤها لحماية الخصوصية."},
    "no_access": {"en": "This dashboard is for DET administrators. Your own company view is on Home.", "ar": "هذه اللوحة مخصصة لمسؤولي دائرة الاقتصاد والسياحة. يمكنك الاطلاع على بيانات شركتك في الصفحة الرئيسية."},
    "company_detail_refused": {"en": "Company financial detail is not available to this role.", "ar": "التفاصيل المالية للشركة غير متاحة لهذا الدور."},
    "k3_tooltip": {"en": "Payments collected ÷ amounts billed, for the selected period.", "ar": "المدفوعات المحصّلة ÷ المبالغ المفوترة، للفترة المحددة."},
    "vat_unconfirmed": {"en": "VAT treatment unconfirmed", "ar": "معاملة ضريبة القيمة المضافة غير مؤكدة"},
    "owner_reported": {"en": "owner-reported, not FTA-verified", "ar": "حسب إفادة المالك، وغير متحقق منه لدى الهيئة الاتحادية للضرائب"},
    "based_on": {"en": "based on {measured} of {due} returns", "ar": "استناداً إلى {measured} من أصل {due} إقرارات"},
    "window_open": {"en": "Window open: figures can still change until the 90-day window closes.", "ar": "الفترة مفتوحة: قد تتغير الأرقام حتى تنتهي فترة الـ 90 يوماً."},
    "pilot_data": {"en": "Pilot data", "ar": "بيانات المرحلة التجريبية"},
    "demo_data": {"en": "Demo data", "ar": "بيانات تجريبية للعرض"},
    "projection": {"en": "Arithmetic, not a forecast", "ar": "حساب رياضي وليس توقعاً"},
    "n_label": {"en": "Minimum group size N = {n} (provisional, set by DET)", "ar": "الحد الأدنى لحجم المجموعة N = {n} (مؤقت، تحدده دائرة الاقتصاد والسياحة)"},
    "restated": {"en": "Restated: figures for a closed period changed after a late file. The earlier figure is kept in the calculation log.", "ar": "معاد بيانه: تغيّرت أرقام فترة مغلقة بعد ورود ملف متأخر. يُحتفظ بالرقم السابق في سجل الاحتساب."},
    "unsigned_release_alert": {"en": "A deliverable that needs a licensed signature was released without one. Investigate now.", "ar": "تم إصدار مخرج يحتاج إلى توقيع مدقق مرخّص من دون توقيع. يجب التحقق فوراً."},
    "unmapped_status_alert": {"en": "Some DET licence statuses are not mapped yet. They are shown as unknown and not counted.", "ar": "بعض حالات الرخص لدى دائرة الاقتصاد والسياحة غير مربوطة بعد. تُعرض كغير معروفة ولا تُحتسب."},
}
AUDIENCE_CLASS = {k: "other" for k in STRINGS}


def bi(key: str, **kw: object) -> dict[str, str]:
    s = STRINGS[key]
    return {"en": s["en"].format(**kw) if kw else s["en"], "ar": s["ar"].format(**kw) if kw else s["ar"]}


try:  # register with the string catalogue when it exists
    from app.modules.catalogue.service import register_strings

    register_strings("kpis", STRINGS, AUDIENCE_CLASS)
except Exception:  # noqa: BLE001 - catalogue optional at build time
    pass
