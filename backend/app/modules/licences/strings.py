"""Bilingual strings for licence-derived notices (SC3 wording, E2-S1). Arabic is a draft pending native review
except where the spec supplies it verbatim."""

from __future__ import annotations

STRINGS = {
    "mainland_issued_by_det": {"en": "Mainland licence issued by DET", "ar": "رخصة تجارية في البر الرئيسي صادرة عن دائرة الاقتصاد والسياحة"},
    "last_read": {"en": "Last read from DET: {datetime} (Dubai time)", "ar": "آخر قراءة من الدائرة: {datetime} (توقيت دبي)"},
    "renewal_due_in": {"en": "Renewal due in {n} days", "ar": "موعد التجديد خلال {n} يوماً"},
    "details_changed_expiry": {"en": "Details changed: expiry date", "ar": "تغيّرت التفاصيل: تاريخ الانتهاء"},
    "comes_from_det": {"en": "This information comes from DET. To correct it, contact DET.", "ar": "هذه المعلومات واردة من الدائرة. لتصحيحها، تواصل مع الدائرة."},
    "not_det_mainland": {"en": "Not a DET mainland licence: not covered by this service", "ar": "ليست رخصة بر رئيسي صادرة عن الدائرة: غير مشمولة بهذه الخدمة"},
    "pending_match_title": {"en": "We have not found your licence yet", "ar": "لم نعثر على رخصتك بعد"},
    "pending_match_body": {"en": "We could not link a Dubai mainland licence to your UAE Pass identity. This can take a short time after issue or renewal. Check that the licence is registered under your identity, or contact DET.", "ar": "تعذّر ربط رخصة تجارية صادرة من دائرة الاقتصاد والسياحة في دبي بهويتك في UAE Pass. قد يستغرق ذلك وقتاً قصيراً بعد الإصدار أو التجديد. تأكد من تسجيل الرخصة باسمك، أو تواصل مع الدائرة."},
    "loading": {"en": "Reading your licence from DET", "ar": "نقرأ بيانات رخصتك من الدائرة"},
    "det_not_responding": {"en": "DET did not respond. Your licence details may be out of date. We will retry automatically.", "ar": "لم تستجب الدائرة. قد تكون تفاصيل رخصتك غير محدّثة. سنعيد المحاولة تلقائياً."},
    "licence_not_affected": {"en": "Your licence and renewal are not affected.", "ar": "رخصتك وتجديدها غير متأثرين."},
    "stale_badge": {"en": "May be out of date", "ar": "قد تكون غير محدّثة"},
    "stale_banner": {"en": "This information was last read more than 24 hours ago. Details may have changed at DET.", "ar": "قُرئت هذه المعلومات قبل أكثر من 24 ساعة، وقد تكون التفاصيل تغيّرت لدى الدائرة."},
    "no_licence_right": {"en": "Your role does not include licence details. Ask the owner to change this.", "ar": "دورك لا يشمل تفاصيل الرخصة. اطلب من المالك تغيير ذلك."},
    "previous_value": {"en": "Previous value", "ar": "القيمة السابقة"},
    "current_value": {"en": "Current value", "ar": "القيمة الحالية"},
    "read_from_det": {"en": "Read from DET", "ar": "مقروء من الدائرة"},
    "unknown_status": {"en": "Status not mapped yet: under operations review. Nothing is billed or reminded for this licence.", "ar": "لم تُطابَق الحالة بعد: قيد مراجعة فريق التشغيل. لا تُفوتر هذه الرخصة ولا تُرسل لها تذكيرات."},
}
AUDIENCE = {k: "official" for k in STRINGS}

try:  # the catalogue module may be absent at build time
    from app.modules.catalogue.service import register_strings

    register_strings("licences", STRINGS, AUDIENCE)
except ImportError:  # pragma: no cover
    pass
