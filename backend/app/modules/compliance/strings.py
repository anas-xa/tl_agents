"""Bilingual wording for the 'Licence requirements' card group (E3-S3). Banners are fixed, reviewer-approved texts
that state sourced facts and the authority's decision; never a legal conclusion or a renewal promise. Arabic for
English-only spec strings is a draft pending native-speaker review."""

from __future__ import annotations

STRINGS: dict[str, dict[str, str]] = {
    "chip.met": {"en": "Met", "ar": "مستوفى"},
    "chip.owner_declared": {"en": "Owner-declared, unverified", "ar": "مُقدَّم من المالك، غير مُتحقَّق منه"},
    "chip.due_soon": {"en": "Due soon", "ar": "يقترب موعده"},
    "chip.at_risk": {"en": "At risk", "ar": "معرّض للخطر"},
    "chip.overdue": {"en": "Overdue", "ar": "متأخر"},
    "chip.unknown": {"en": "Cannot confirm", "ar": "تعذّر التأكيد"},
    "chip.to_be_confirmed": {"en": "to be confirmed by DET", "ar": "بانتظار تأكيد دائرة الاقتصاد والسياحة"},
    "req.licence_expiry": {"en": "Trade licence expiry", "ar": "انتهاء الرخصة التجارية"},
    "req.ejari_expiry": {"en": "Valid Ejari (tenancy contract)", "ar": "عقد إيجاري ساري (عقد الإيجار)"},
    "req.chambers_membership": {"en": "Dubai Chambers membership", "ar": "عضوية غرف دبي"},
    "banner.ejari_at_risk": {"en": "Ejari at risk: it expires {n} days before your licence expires. Next step: renew your Ejari, then your licence renewal can go ahead.", "ar": "عقد إيجاري معرّض للخطر: ينتهي قبل انتهاء رخصتك بـ {n} يومًا. الخطوة التالية: جدّد عقد إيجاري، ثم يمكن المتابعة في تجديد الرخصة."},
    "banner.ejari_at_risk_short": {"en": "Ejari at risk: expires {n} days before your licence expiry", "ar": "عقد إيجاري معرّض للخطر: ينتهي قبل انتهاء رخصتك بـ {n} يومًا"},
    "banner.ejari_lapsed": {"en": "Ejari expired on {date}, as last received from DET. DET asks for a valid Ejari at licence renewal. Next step: renew your Ejari.", "ar": "انتهى عقد إيجاري بتاريخ {date} بحسب آخر بيانات وردت من دائرة الاقتصاد والسياحة. تطلب الدائرة عقد إيجاري ساريًا عند تجديد الرخصة. الخطوة التالية: جدّد عقد إيجاري."},
    "banner.licence_expired": {"en": "This licence expired on {date}. Renewal is done with DET. Your data stays visible. Data pulls from linked sources are paused.", "ar": "انتهت صلاحية هذه الرخصة بتاريخ {date}. يتم التجديد لدى دائرة الاقتصاد والسياحة. بياناتك ما زالت ظاهرة. تم إيقاف سحب البيانات من المصادر المرتبطة مؤقتًا."},
    "banner.licence_suspended": {"en": "This licence is suspended by DET. Contact DET for the reason and next step.", "ar": "هذه الرخصة موقوفة من دائرة الاقتصاد والسياحة. تواصل مع الدائرة لمعرفة السبب والخطوة التالية."},
    "source.ejari_det": {"en": "Ejari status as last received from DET, refreshed on {date}", "ar": "حالة عقد إيجاري كما وردت آخر مرة من دائرة الاقتصاد والسياحة، حُدّثت في {date}"},
    "source.det": {"en": "Read from DET, refreshed on {date}", "ar": "مقروء من دائرة الاقتصاد والسياحة، حُدّث في {date}"},
    "source.owner": {"en": "Entered by you on {date}, not checked against Ejari", "ar": "أدخلته أنت في {date}، ولم يُتحقق منه مقابل إيجاري"},
    "note.sources_differ": {"en": "Sources differ", "ar": "المصادر مختلفة"},
    "note.source_differs_entry": {"en": "Source differs from your entry", "ar": "المصدر يختلف عمّا أدخلته"},
    "note.declared_dates": {"en": "based on your declared dates", "ar": "بحسب التواريخ التي أدخلتها"},
    "note.needs_review": {"en": "needs review", "ar": "بحاجة إلى مراجعة"},
    "note.confirm_det": {"en": "confirm with DET", "ar": "يُرجى التأكد مع دائرة الاقتصاد والسياحة"},
    "note.checked_today": {"en": "Checked today, rule version {version}", "ar": "تم التحقق اليوم، إصدار القاعدة {version}"},
    "note.recommended_renew_by": {"en": "Recommended renew-by", "ar": "الموعد الموصى به للتجديد"},
    "note.last_confirmed": {"en": "Last confirmed", "ar": "آخر تأكيد"},
    "note.not_obligation": {"en": "to be confirmed by DET. Not shown as a legal obligation and not counted in the totals.", "ar": "بانتظار تأكيد دائرة الاقتصاد والسياحة. لا يُعرض كالتزام قانوني ولا يُحتسب ضمن المجاميع."},
    "note.holiday_working_days": {"en": "Days left count working days. {holiday} on {date} falls in this period, so you have {n} working days left, not {m}.", "ar": "تُحتسب الأيام المتبقية بأيام العمل. تقع {holiday} في {date} ضمن هذه المدة، لذا تبقى لديك {n} يوم عمل بدل {m}."},
    "note.holiday_on_date": {"en": "The date {date} falls on {holiday}. We show the statutory date and do not assume it moves. Check the official source.", "ar": "يصادف التاريخ {date} {holiday}. نعرض الموعد النظامي ولا نفترض تأجيله. راجع المصدر الرسمي."},
    "note.holiday_unavailable": {"en": "We cannot check holidays right now.", "ar": "لا يمكننا التحقق من الإجازات الآن."},
    "note.includes_holiday": {"en": "Includes a public holiday on {date}", "ar": "يتضمن عطلة رسمية في {date}"},
    "draft.ai_not_reviewed": {"en": "AI-prepared, not reviewed", "ar": "أعدّه الذكاء الاصطناعي، لم تتم مراجعته"},
    "draft.reviewed_by_you": {"en": "AI-prepared, reviewed by you, {date}", "ar": "أعدّه الذكاء الاصطناعي، راجعته أنت، {date}"},
    "draft.status.draft_not_reviewed": {"en": "Draft, not reviewed", "ar": "مسودة، لم تتم مراجعتها"},
    "draft.status.reviewed": {"en": "Reviewed by {role}", "ar": "راجعها {role}"},
    "draft.status.returned_for_changes": {"en": "Returned for changes", "ar": "أُعيدت لإجراء تعديلات"},
    "draft.status.approved_by_owner": {"en": "Approved by owner", "ar": "اعتمدها المالك"},
    "draft.status.discarded": {"en": "Discarded", "ar": "حُذفت"},
    "draft.footer": {"en": "Draft only. Nothing has been sent to DET or Ejari.", "ar": "مسودة فقط. لم يُرسَل أي شيء إلى دائرة الاقتصاد والسياحة أو إيجاري."},
    "draft.footer_approved": {"en": "Approved by owner on {date}. Recorded in this service only. Nothing has been sent to DET or Ejari.", "ar": "اعتمدها المالك في {date}. سُجّل ذلك في هذه الخدمة فقط. لم يُرسَل أي شيء إلى دائرة الاقتصاد والسياحة أو إيجاري."},
    "draft.title.renewal_checklist": {"en": "Licence renewal checklist (draft)", "ar": "قائمة تجديد الرخصة (مسودة)"},
    "draft.title.document_pack": {"en": "Renewal document pack (draft)", "ar": "حزمة مستندات التجديد (مسودة)"},
    "draft.not_usable": {"en": "document could not be used", "ar": "تعذّر استخدام المستند"},
    "doc.ejari_contract": {"en": "Ejari tenancy contract copy", "ar": "نسخة عقد الإيجار (إيجاري)"},
    "doc.chambers_certificate": {"en": "Dubai Chambers membership certificate", "ar": "شهادة عضوية غرف دبي"},
    "doc.licence_copy": {"en": "Current trade licence copy", "ar": "نسخة الرخصة التجارية الحالية"},
    "doc.passport_ids": {"en": "Partners' identity documents (as DET asks)", "ar": "وثائق هوية الشركاء (بحسب طلب الدائرة)"},
    "summary.all_clear": {"en": "All clear", "ar": "لا توجد ملاحظات"},
    "summary.counts": {"en": "{met} met, {unverified} unverified, {attention} need attention, {unknown} cannot confirm", "ar": "{met} مستوفى، {unverified} غير مُتحقَّق منه، {attention} بحاجة إلى متابعة، {unknown} تعذّر التأكيد"},
    "empty.no_licence": {"en": "No licence record is linked yet. Add your licence and Ejari details, or wait for DET data, to see your requirements.", "ar": "لم يُربط سجل رخصة بعد. أضف بيانات الرخصة وعقد إيجاري، أو انتظر بيانات الدائرة، لعرض المتطلبات."},
    "remote.prepare_disabled": {"en": "Preparing documents is not available in the remote-owner view. Your statuses are shown read-only; reminders stay available.", "ar": "إعداد المستندات غير متاح في عرض المالك المقيم خارج الدولة. تظهر الحالات للقراءة فقط، وتبقى التذكيرات متاحة."},
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

    register_strings("compliance", STRINGS, AUDIENCE)
except ImportError:  # pragma: no cover
    pass
