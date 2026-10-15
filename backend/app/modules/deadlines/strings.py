"""Bilingual strings for the deadline engine and SC4 (E3-S2, E1-S3 SC4). Spec Arabic copied verbatim; entries the
spec gives in English only carry a draft Arabic text pending native-speaker review (audience 'official', unreviewed)."""

from __future__ import annotations

STRINGS: dict[str, dict[str, str]] = {
    # status chips (SC4)
    "chip.upcoming": {"en": "Upcoming", "ar": "قادم"},
    "chip.due_soon": {"en": "Due soon", "ar": "يستحق قريبًا"},
    "chip.overdue": {"en": "Overdue", "ar": "متأخر"},
    "chip.date_not_confirmed": {"en": "Date not confirmed", "ar": "التاريخ غير مؤكد"},
    "chip.date_being_updated": {"en": "Date being updated", "ar": "التاريخ قيد التحديث"},
    "chip.falls_on_weekend": {"en": "Falls on a weekend", "ar": "يصادف عطلة نهاية الأسبوع"},
    "chip.falls_on_public_holiday": {"en": "Falls on a public holiday", "ar": "يصادف عطلة رسمية"},
    "chip.date_may_change": {"en": "Date may change", "ar": "قد يتغير التاريخ"},
    "chip.filed_outside_platform": {"en": "Filed outside platform, not verified by the authority", "ar": "قُدّم خارج المنصة، لم تتحقق منه الجهة"},
    "chip.status_unconfirmed": {"en": "Status unconfirmed", "ar": "الحالة غير مؤكدة"},
    "chip.overdue_status_unconfirmed": {"en": "Overdue, status unconfirmed", "ar": "متأخر، الحالة غير مؤكدة"},
    "chip.moved_to_next_working_day": {"en": "Moved to next working day", "ar": "نُقل إلى يوم العمل التالي"},
    "chip.date_updated": {"en": "Date updated", "ar": "تم تحديث التاريخ"},
    # source / basis chips
    "source.computed": {"en": "Computed by the platform from your details", "ar": "محسوب بالمنصة من بياناتكم"},
    "source.stated": {"en": "Stated by the authority", "ar": "محدد من الجهة"},
    "basis.entered": {"en": "Based on details you entered", "ar": "بحسب بيانات أدخلتموها"},
    "basis.verified": {"en": "Based on verified details", "ar": "بحسب بيانات موثقة"},
    "basis.delegate": {"en": "Entered by delegate, based on details entered", "ar": "أدخلها مفوَّض، بحسب بيانات مُدخلة"},
    "label.calculated": {"en": "calculated", "ar": "محسوب"},
    "note.calculated": {"en": "If this date falls on a weekend or public holiday, check the authority's rule; file early", "ar": "إذا صادف هذا التاريخ عطلة نهاية الأسبوع أو عطلة رسمية، فراجعوا قاعدة الجهة وقدّموا مبكرًا"},
    "note.not_confirmed_fta": {"en": "calculated from the standard rule, not confirmed with the FTA", "ar": "محسوب وفق القاعدة العامة، ولم يُؤكَّد مع الهيئة الاتحادية للضرائب"},
    "note.as_calculated": {"en": "due date as calculated; confirm with the FTA", "ar": "تاريخ الاستحقاق كما احتُسب؛ يُرجى التأكد مع الهيئة الاتحادية للضرائب"},
    "note.statutory": {"en": "Statutory date. Do not rely on a later date unless the FTA confirms it.", "ar": "هذا هو الموعد النظامي. لا تعتمدوا على تاريخ لاحق ما لم تؤكده الهيئة الاتحادية للضرائب."},
    "note.nonworking": {"en": "This date falls on a non-working day. Under the rule currently applied by this service, the due date is {date}. Confirm with the FTA.", "ar": "يصادف هذا التاريخ يوم عطلة. وفق القاعدة المطبقة حاليًا في هذه الخدمة، تاريخ الاستحقاق هو {date}. يُرجى التأكد مع الهيئة الاتحادية للضرائب."},
    "note.remind_earlier": {"en": "Shown as stated by the authority. We remind you earlier, on {date}, to be safe. Check EmaraTax for the date it accepts.", "ar": "التاريخ كما حددته الجهة. نذكّركم مبكرًا في {date} للاحتياط. راجعوا EmaraTax لمعرفة التاريخ المعتمد."},
    "note.weekend_or_holiday": {"en": "falls on a weekend or holiday, so we remind you earlier", "ar": "يصادف عطلة نهاية الأسبوع أو عطلة، لذا نذكّركم مبكرًا"},
    "note.provisional_holiday": {"en": "Provisional until officially announced", "ar": "مؤقت حتى الإعلان الرسمي"},
    "note.holiday_not_announced": {"en": "A holiday date has not been announced yet. We will update this date when it is announced and tell you.", "ar": "لم يُعلن عن تاريخ العطلة بعد. سنحدّث هذا التاريخ عند الإعلان ونخبركم."},
    "note.holiday_calendar_not_confirmed": {"en": "holiday calendar not confirmed", "ar": "تقويم العطلات غير مؤكد"},
    "note.upload_receipt": {"en": "If you have already filed, upload your receipt", "ar": "إذا كنتم قد قدّمتم الإقرار، فارفعوا الإيصال"},
    "note.confirm_with_det": {"en": "confirm with DET", "ar": "يُرجى التأكد مع دائرة الاقتصاد والسياحة"},
    "note.owner_declared": {"en": "owner-declared, unverified", "ar": "مُقدَّم من المالك، غير مُتحقَّق منه"},
    "note.owner_entered": {"en": "owner-entered, not verified", "ar": "أدخله المالك، غير مُتحقَّق منه"},
    "note.recommended_submit_by": {"en": "recommended submit-by", "ar": "الموعد الموصى به للتقديم"},
    "note.rules_version": {"en": "Rules version {version} – checked {date}", "ar": "إصدار القواعد {version} – تم التحقق {date}"},
    "note.date_under_review": {"en": "date under review", "ar": "التاريخ قيد المراجعة"},
    "note.recalc_pending": {"en": "Recalculation pending", "ar": "إعادة الاحتساب قيد الانتظار"},
    "note.stale": {"en": "stale", "ar": "قديم"},
    "note.recalc_failed": {"en": "recalculation failed", "ar": "تعذّرت إعادة الاحتساب"},
    "note.updating_rules": {"en": "Updating dates to the current rules", "ar": "جارٍ تحديث المواعيد وفق القواعد الحالية"},
    "note.public_holiday_official": {"en": "Public holiday (official list)", "ar": "عطلة رسمية (القائمة الرسمية)"},
    # states
    "state.empty_title": {"en": "No deadlines yet", "ar": "لا توجد مواعيد بعد"},
    "state.empty_body": {"en": "Add three details and we will work out your dates: tax period, VAT frequency and TRN.", "ar": "أضيفوا ثلاث بيانات لنحسب مواعيدكم: الفترة الضريبية، وتيرة ضريبة القيمة المضافة، ورقم التسجيل الضريبي (TRN)."},
    "state.empty_owner": {"en": "No deadlines yet. Add your tax period, VAT frequency and TRN and we will work out your dates.", "ar": "لا توجد مواعيد بعد. أضيفوا الفترة الضريبية ووتيرة ضريبة القيمة المضافة ورقم التسجيل الضريبي لنحسب مواعيدكم."},
    "state.empty_delegate": {"en": "The owner has not set up the tax details yet.", "ar": "لم يُدخل المالك البيانات الضريبية بعد."},
    "state.pending": {"en": "Dates are being recalculated. Reminders are paused until they are confirmed.", "ar": "يجري إعادة احتساب المواعيد. التذكيرات متوقفة إلى حين تأكيدها."},
    "state.pending_note": {"en": "Reminders for this date are paused until the update finishes. If it does not finish, we send the reminder using your last confirmed date and say so.", "ar": "تتوقف تذكيرات هذا الموعد مؤقتًا حتى يكتمل التحديث. وإن لم يكتمل نرسل التذكير بآخر تاريخ مؤكد ونذكر ذلك."},
    "state.error": {"en": "We could not load your deadlines. Check the date on the authority's portal.", "ar": "تعذّر تحميل المواعيد. يُرجى التحقق من التاريخ في بوابة الجهة المختصة."},
    "state.no_access": {"en": "You do not have access to this company's deadlines. Ask the owner to assign you.", "ar": "ليس لديكم صلاحية الاطلاع على مواعيد هذه الشركة. اطلبوا من المالك تعيينكم."},
    "state.withheld": {"en": "Some obligations are not shared with you.", "ar": "بعض الالتزامات غير مشاركة معك."},
    # obligation names
    "type.licence_renewal": {"en": "Trade licence renewal", "ar": "تجديد الرخصة التجارية"},
    "type.vat_return": {"en": "VAT return", "ar": "إقرار ضريبة القيمة المضافة"},
    "type.ct_return": {"en": "Corporate tax return", "ar": "إقرار ضريبة الشركات"},
    "type.audit": {"en": "Audited financial statements", "ar": "البيانات المالية المدققة"},
    "type.ejari_renewal": {"en": "Ejari tenancy renewal", "ar": "تجديد عقد إيجاري"},
    "type.other": {"en": "Other licence requirement", "ar": "متطلب آخر مرتبط بالرخصة"},
    "type.chambers_membership": {"en": "Dubai Chambers membership", "ar": "عضوية غرف دبي"},
    # readiness (UX Q358 suggested set: about preparation, never legal compliance)
    "readiness.not_started": {"en": "Not started", "ar": "لم يبدأ"},
    "readiness.data_missing": {"en": "Data missing", "ar": "بيانات ناقصة"},
    "readiness.in_preparation": {"en": "In preparation", "ar": "قيد الإعداد"},
    "readiness.draft_ready": {"en": "Ready for owner review", "ar": "جاهز لمراجعة المالك"},
    "readiness.owner_approved": {"en": "Approved by owner", "ar": "اعتمده المالك"},
    "readiness.receipt_recorded": {"en": "Filed by owner (recorded)", "ar": "قدّمه المالك (مسجّل)"},
    "readiness.audit_draft": {"en": "Draft - awaiting licensed auditor", "ar": "مسودة - بانتظار مدقق حسابات مرخّص"},
    # missing items
    "missing.trn": {"en": "TRN", "ar": "رقم التسجيل الضريبي (TRN)"},
    "missing.tax_period": {"en": "Tax period", "ar": "الفترة الضريبية"},
    "missing.vat_frequency": {"en": "VAT frequency", "ar": "وتيرة ضريبة القيمة المضافة"},
    "missing.transactions": {"en": "Transactions for the period", "ar": "معاملات الفترة"},
    "missing.all_reviewed": {"en": "Transactions still to review", "ar": "معاملات بانتظار المراجعة"},
    "missing.vat_codes": {"en": "VAT codes on confirmed lines", "ar": "رموز الضريبة على البنود المؤكدة"},
    "missing.fx_rates": {"en": "Exchange rates for foreign-currency lines", "ar": "أسعار الصرف لبنود العملات الأجنبية"},
    "missing.ct_status": {"en": "Corporate-tax status", "ar": "حالة ضريبة الشركات"},
    "missing.financial_year": {"en": "Financial year", "ar": "السنة المالية"},
    "missing.revenue_confirmed": {"en": "Revenue figure confirmed by the owner", "ar": "رقم الإيرادات مؤكد من المالك"},
    "missing.ejari_valid": {"en": "Valid Ejari for renewal", "ar": "عقد إيجاري ساري للتجديد"},
    "missing.ejari_expiry": {"en": "Ejari expiry date", "ar": "تاريخ انتهاء عقد إيجاري"},
    "missing.chambers_membership": {"en": "Dubai Chambers membership", "ar": "عضوية غرف دبي"},
    "missing.licence_expiry": {"en": "Licence expiry date", "ar": "تاريخ انتهاء الرخصة"},
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

    register_strings("deadlines", STRINGS, AUDIENCE)
except ImportError:  # pragma: no cover
    pass
