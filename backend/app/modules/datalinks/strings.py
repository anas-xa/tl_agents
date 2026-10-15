"""Bilingual strings for data-link notices, upload rejections and the tax link (E4-S3..S6). Arabic from the spec
where given; otherwise a draft pending native review."""

from __future__ import annotations

STRINGS: dict[str, dict[str, str]] = {
    "upload.label": {"en": "Manual, unverified", "ar": "يدوي، غير موثّق"},
    "upload.ready": {"en": "Ready. Manual, unverified.", "ar": "جاهز. يدوي، غير موثّق."},
    "upload.not_bank_link": {"en": "Uploading a file does not link your bank.", "ar": "رفع ملف لا يربط حسابك المصرفي."},
    "upload.you_uploaded": {"en": "You uploaded this file. We have not checked it with your bank. Figures built from it are drafts.", "ar": "لقد رفعت هذا الملف. لم نتحقق منه لدى بنكك. الأرقام المبنية عليه مسودات."},
    "upload.notice": {"en": "By uploading this file you submit it for the purpose you chose. This is a data submission, not a consent for onward sharing. The file is stored in the UAE, labelled 'Manual, unverified', and you can delete the batch at any time.", "ar": "برفع هذا الملف فإنك تقدّمه للغرض الذي اخترته. هذا تقديم بيانات وليس موافقة على المشاركة اللاحقة. يُخزَّن الملف في الإمارات ويُعلَّم 'يدوي، غير موثّق'، ويمكنك حذف الدفعة في أي وقت."},
    "upload.rejected.wrong_type": {"en": "This file type or size is not accepted. Use CSV, XLSX or a text PDF up to {limit} MB.", "ar": "نوع الملف أو حجمه غير مقبول. استخدم CSV أو XLSX أو PDF نصي بحجم يصل إلى {limit} ميغابايت."},
    "upload.rejected.over_size_limit": {"en": "This file is over the size limit of {limit} MB. Nothing was saved.", "ar": "يتجاوز هذا الملف حد الحجم البالغ {limit} ميغابايت. لم يُحفظ شيء."},
    "upload.rejected.unreadable": {"en": "We could not read this file. Nothing was saved.", "ar": "تعذّرت قراءة هذا الملف. لم يُحفظ شيء."},
    "upload.rejected.password_protected": {"en": "This file is password-protected or encrypted. Nothing was saved.", "ar": "هذا الملف محمي بكلمة مرور أو مشفّر. لم يُحفظ شيء."},
    "upload.rejected.image_only": {"en": "This PDF has no readable text. Use a text-based PDF, CSV or XLSX.", "ar": "لا يحتوي ملف PDF هذا على نص قابل للقراءة. استخدم PDF نصياً أو CSV أو XLSX."},
    "upload.rejected.failed_security_check": {"en": "This file failed the security check and was quarantined. Nothing was read from it.", "ar": "لم يجتز هذا الملف فحص الأمان وتم حجره. لم تتم قراءة أي شيء منه."},
    "upload.rejected.unknown_header": {"en": "We could not recognise the columns in this file. Nothing was saved.", "ar": "تعذّر التعرّف على أعمدة هذا الملف. لم يُحفظ شيء."},
    "upload.rejected.too_many_invalid_rows": {"en": "More than {threshold}% of the rows could not be read. The file was not accepted.", "ar": "تعذّرت قراءة أكثر من {threshold}% من الصفوف. لم يُقبل الملف."},
    "upload.rejected.too_many_rows": {"en": "This file has more than {limit} rows. Split it and try again.", "ar": "يحتوي هذا الملف على أكثر من {limit} صف. قسّمه وحاول مرة أخرى."},
    "upload.rejected.overlapping_period": {"en": "This period overlaps a file already on record. Matching rows were skipped.", "ar": "تتداخل هذه الفترة مع ملف مسجّل بالفعل. تم تخطي الصفوف المطابقة."},
    "upload.quarantined.no_notice_record": {"en": "This file is held in quarantine because the notice was not acknowledged. Nothing was read from it.", "ar": "هذا الملف محجور لأن الإشعار لم يُقرّ به. لم تتم قراءة أي شيء منه."},
    "upload.data_as_of": {"en": "Data as of {date}", "ar": "البيانات حتى {date}"},
    "upload.update_due": {"en": "Update due", "ar": "يلزم التحديث"},
    "upload.delete_warning": {"en": "Deleting this file makes figures built from it out of date. Records required by law are kept.", "ar": "حذف هذا الملف يجعل الأرقام المبنية عليه غير محدّثة. تُحفظ السجلات التي يوجب القانون الاحتفاظ بها."},
    "bank.not_yet_available": {"en": "Direct bank link is not yet available. You can upload statements instead.", "ar": "الربط المباشر مع البنك غير متاح بعد. يمكنك رفع كشوف الحساب بدلاً من ذلك."},
    "bank.cannot_link_yet": {"en": "This bank cannot be linked yet. You can upload statements instead.", "ar": "لا يمكن ربط هذا البنك بعد. يمكنك رفع كشوف الحساب بدلاً من ذلك."},
    "bank.through_provider": {"en": "Bank data comes through the licensed provider and only with your company's consent.", "ar": "تأتي البيانات المصرفية عبر المزوّد المرخّص وفقط بموافقة شركتك."},
    "bank.read_only": {"en": "We read balances and transactions only for these accounts. We do not move money or read other accounts.", "ar": "نقرأ الأرصدة والمعاملات لهذه الحسابات فقط. لا نحوّل أموالاً ولا نقرأ حسابات أخرى."},
    "erp.not_available": {"en": "No accounting system connector is available yet. Upload an export file instead.", "ar": "لا يتوفر موصّل لنظام محاسبي بعد. ارفع ملف تصدير بدلاً من ذلك."},
    "erp.notice": {"en": "Data is read from your accounting export and held in the UAE. Figures built from uploads are drafts.", "ar": "تُقرأ البيانات من ملف تصدير نظامك المحاسبي وتُحفظ في الإمارات. الأرقام المبنية على الملفات المرفوعة مسودات."},
    "tax.not_available": {"en": "We cannot read your tax record until the data-exchange agreement is in place. Nothing is pulled from the authority.", "ar": "لا يمكننا قراءة سجلك الضريبي إلى أن يتم الاتفاق على تبادل البيانات. لا يتم سحب أي بيانات من الهيئة."},
    "tax.cause.authority_not_responding": {"en": "The authority service is not responding", "ar": "خدمة الهيئة لا تستجيب"},
    "tax.cause.consent_expired": {"en": "Your consent has expired", "ar": "انتهت صلاحية موافقتك"},
    "tax.as_provided": {"en": "as provided by the company, {date}", "ar": "كما قدّمتها الشركة، {date}"},
    "tax.unverified": {"en": "Unverified", "ar": "غير موثّق"},
    "tax.not_confirmed": {"en": "Not confirmed by the authority", "ar": "لم تؤكدها الهيئة"},
    "tax.remote_owner_status": {"en": "company-provided data only; no live FTA link", "ar": "بيانات مقدّمة من الشركة فقط؛ لا يوجد ربط مباشر مع الهيئة"},
    "links.status_check_delayed": {"en": "Status check delayed · we could not confirm this link just now. Last known: {status} at {time}. We will retry automatically.", "ar": "تأخر فحص الحالة · لم نتمكن من تأكيد هذا الربط الآن. آخر حالة معروفة: {status} في {time}. سنعيد المحاولة تلقائيًا."},
    "links.holiday_note": {"en": "Source may be closed for a holiday", "ar": "قد يكون المصدر مغلقاً بسبب عطلة"},
}
AUDIENCE: dict[str, str] = {k: ("official" if k.startswith(("upload.notice", "upload.rejected", "upload.quarantined", "tax.not_available", "bank.through_provider", "erp.notice")) else "other") for k in STRINGS}

try:
    from app.modules.catalogue.service import register_strings

    register_strings("datalinks", STRINGS, AUDIENCE)
except ImportError:  # pragma: no cover
    pass


def s(key: str, lang: str, **params: object) -> str:
    item = STRINGS.get(key, {})
    value = item.get(lang) or item.get("en") or key
    try:
        return value.format(**params) if params else value
    except (KeyError, IndexError):
        return value
