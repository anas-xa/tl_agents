"""Bilingual strings for the residency panel (SC14), owner residency statement and K12 checklist (E1-S4).

Arabic is copied verbatim from the specification and is a draft pending native review.
"""

from __future__ import annotations

STRINGS: dict[str, dict[str, str]] = {
    "panel_title": {"en": "Data residency and security", "ar": "إقامة البيانات والأمان"},
    "empty_no_evidence": {
        "en": "No residency evidence yet. The inventory is created when the environment is deployed. Nothing is wrong. Check back after the first release.",
        "ar": "لا توجد أدلة إقامة البيانات بعد. يتم إنشاء الجرد عند نشر البيئة. لا يوجد أي خلل. يرجى المراجعة بعد أول إصدار.",
    },
    "empty_no_evidence_short": {"en": "No residency evidence yet", "ar": "لا توجد أدلة إقامة البيانات بعد"},
    "empty_no_components": {
        "en": "No components registered yet. Residency cannot be confirmed.",
        "ar": "لم يتم تسجيل أي مكوّنات بعد. لا يمكن تأكيد موقع الاستضافة.",
    },
    "error_failed": {
        "en": "We could not generate the residency inventory. No data was changed. Try again. If it fails again, raise it with the platform team.",
        "ar": "تعذّر إنشاء جرد إقامة البيانات. لم يتم تغيير أي بيانات. أعد المحاولة. إذا تكرر الخطأ فأبلغ فريق المنصة.",
    },
    "error_timed_out": {
        "en": "The inventory took too long to generate. No data was changed. Try again in a few minutes.",
        "ar": "استغرق إنشاء الجرد وقتًا طويلًا. لم يتم تغيير أي بيانات. أعد المحاولة بعد دقائق.",
    },
    "try_again": {"en": "Try again", "ar": "إعادة المحاولة"},
    "raise_platform_team": {"en": "Raise with the platform team", "ar": "إبلاغ فريق المنصة"},
    "last_successful_check": {"en": "Last successful check: {when}", "ar": "آخر فحص ناجح: {when}"},
    "blocked_unknown_location": {
        "en": "Blocked: UAE location not recorded for {component}",
        "ar": "محظور: لم يتم تسجيل موقع الاستضافة في الإمارات للمكوّن {component}",
    },
    "blocked_non_uae_path": {
        "en": "Blocked: a subprocessor or egress path outside the UAE is recorded for {component}",
        "ar": "محظور: تم تسجيل معالج فرعي أو مسار خروج خارج الإمارات للمكوّن {component}",
    },
    "blocked_stale": {"en": "Blocked: the inventory is stale and cannot count as a pass", "ar": "محظور: الجرد قديم ولا يمكن احتسابه كاجتياز"},
    "blocked_generator": {"en": "Blocked: the inventory generator is unavailable", "ar": "محظور: مولّد الجرد غير متاح"},
    "blocked_key_service": {"en": "Blocked: the key service is unavailable", "ar": "محظور: خدمة المفاتيح غير متاحة"},
    "blocked_no_components": {"en": "Blocked: no components registered", "ar": "محظور: لم يتم تسجيل أي مكوّنات"},
    "next_step_record_location": {
        "en": "Next step: record the UAE location or replace the component, then request a review.",
        "ar": "الخطوة التالية: سجّل موقع الاستضافة في الإمارات أو استبدل المكوّن، ثم اطلب مراجعة.",
    },
    "next_step_regenerate": {"en": "Next step: restore the generator and run the inventory again, then request a review.", "ar": "الخطوة التالية: أعد تشغيل المولّد وأعد إنشاء الجرد، ثم اطلب مراجعة."},
    "next_step_register": {"en": "Next step: register every component with its UAE location, then request a review.", "ar": "الخطوة التالية: سجّل كل مكوّن مع موقع استضافته في الإمارات، ثم اطلب مراجعة."},
    "needs_attention_one": {"en": "Needs attention: 1 component", "ar": "يحتاج إلى انتباه: مكوّن واحد"},
    "needs_attention_n": {"en": "Needs attention: {n} components", "ar": "يحتاج إلى انتباه: {n} مكوّنات"},
    "release_blocked": {"en": "Release blocked: {reason}", "ar": "الإصدار محظور: {reason}"},
    "release_pass": {"en": "Release check passed", "ar": "اجتاز فحص الإصدار"},
    "not_yet_available": {"en": "Not yet available", "ar": "غير متاح بعد"},
    "not_confirmed": {"en": "Not confirmed", "ar": "غير مؤكد"},
    "residency_under_review": {"en": "Residency under review", "ar": "موقع الاستضافة قيد المراجعة"},
    "refresh": {"en": "Refresh", "ar": "تحديث"},
    "refreshing": {"en": "Refreshing", "ar": "جارٍ التحديث"},
    "checking_latest": {"en": "Checking the latest evidence", "ar": "جارٍ فحص أحدث الأدلة"},
    "stale": {"en": "stale", "ar": "قديم"},
    "owner_neutral": {
        "en": "Our service is designed to keep your data in the UAE and to use local AI models only. No data is sent to external models. Detailed checks will appear here once the service is released.",
        "ar": "صُممت خدمتنا لإبقاء بياناتك داخل الإمارات واستخدام نماذج ذكاء اصطناعي محلية فقط. لا تُرسل أي بيانات إلى نماذج خارجية. ستظهر نتائج الفحص التفصيلية هنا بعد إطلاق الخدمة.",
    },
    "owner_approved": {
        "en": "Your company data is stored and processed on infrastructure located in the UAE. Local AI models are used and your data is not sent to external AI services.",
        "ar": "تُخزَّن بيانات شركتكم وتُعالَج على بنية تحتية داخل دولة الإمارات العربية المتحدة. تُستخدم نماذج ذكاء اصطناعي محلية ولا تُرسل بياناتكم إلى خدمات ذكاء اصطناعي خارجية.",
    },
    "owner_approved_release": {
        "en": "Your data is hosted in the UAE and processed by local AI models. No data is sent to external models.",
        "ar": "تُستضاف بياناتك في الإمارات وتُعالَج بنماذج ذكاء اصطناعي محلية. لا تُرسل أي بيانات إلى نماذج خارجية.",
    },
    "no_access": {"en": "You do not have access to this page.", "ar": "لا تملك صلاحية الوصول إلى هذه الصفحة."},
    # K12 checklist
    "k12_not_started": {
        "en": "Your setup window starts once your licence service is activated. We will show your checklist then.",
        "ar": "تبدأ مهلة الإعداد عند تفعيل خدمة الرخصة. سنعرض لك قائمة المهام حينها.",
    },
    "k12_pending_bank": {
        "en": "Waiting for your bank to confirm. This can take a short time. You do not need to do anything. We will tell you when it is done.",
        "ar": "بانتظار تأكيد البنك. قد يستغرق ذلك وقتًا قصيرًا. لا يلزمك أي إجراء. سنُعلمك عند اكتماله.",
    },
    "k12_pending_owner_consent": {"en": "Waiting for the owner's consent", "ar": "بانتظار موافقة المالك"},
    "k12_ask_owner_consent": {"en": "Ask the owner to give consent", "ar": "اطلب من المالك منح الموافقة"},
    "k12_expired": {
        "en": "Your 30-day setup window ended on {date}. These links are still missing: {list}. Your service works with the data you have. Link them any time to complete your setup.",
        "ar": "انتهت مهلة الإعداد البالغة 30 يومًا بتاريخ {date}. الروابط التالية ما زالت ناقصة: {list}. تعمل خدمتك بالبيانات المتوفرة. يمكنك ربطها في أي وقت لإكمال الإعداد.",
    },
    "k12_link_now": {"en": "Link now", "ar": "اربط الآن"},
    "k12_ask_owner": {"en": "Ask the owner", "ar": "اطلب من المالك"},
    "k12_based_on_incomplete": {"en": "Based on incomplete data", "ar": "مبنية على بيانات غير مكتملة"},
    "k12_linked": {"en": "Linked", "ar": "مرتبط"},
    "k12_pending": {"en": "Pending", "ar": "قيد الإنجاز"},
    "k12_missing": {"en": "Missing", "ar": "ناقص"},
    "k12_link_not_started": {"en": "Not started", "ar": "لم يبدأ"},
    "k12_window_not_started": {"en": "Window not started", "ar": "لم تبدأ المهلة"},
    "k12_window_expired_missing": {"en": "Window expired, links missing", "ar": "انتهت المهلة والروابط ناقصة"},
    "k12_complete_manual_path": {"en": "Complete via manual path only", "ar": "اكتمل عبر المسار اليدوي فقط"},
    "k12_link_det_licence_record": {"en": "DET licence record", "ar": "سجل رخصة دائرة الاقتصاد والسياحة"},
    "k12_link_fta_tax_profile": {"en": "FTA tax profile", "ar": "الملف الضريبي لدى الهيئة الاتحادية للضرائب"},
    "k12_link_data_source": {"en": "Bank feed, ledger connection or manual upload", "ar": "تغذية مصرفية أو ربط دفتر الأستاذ أو رفع يدوي"},
    "manual_upload_label": {"en": "uploaded by the company, not verified at source", "ar": "مرفوع من قبل الشركة، لم يُتحقق منه من المصدر"},
}

AUDIENCE: dict[str, str] = {k: ("official" if k.startswith("owner_") else "other") for k in STRINGS}

try:  # the catalogue module registers the strings for review and the release gate
    from app.modules.catalogue.service import register_strings

    register_strings("hosting", STRINGS, AUDIENCE)
except Exception:  # pragma: no cover - catalogue absent at build time
    pass


def s(key: str, lang: str = "en", **params: object) -> str:
    value = STRINGS[key][lang if lang in ("en", "ar") else "en"]
    return value.format(**params) if params else value


def both(key: str, **params: object) -> dict[str, str]:
    return {"en": s(key, "en", **params), "ar": s(key, "ar", **params)}
