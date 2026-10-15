"""Bilingual company notices and SC14 cohort wording (E2-S5). Fixed templates with placeholders only; sample
text in the demo, reviewed by DET communications before a real pilot. Arabic from the spec where supplied."""

from __future__ import annotations

STRINGS = {
    "notice_enrolled": {"en": "Your licence is in a pilot. Included modules: {modules}. Contact: {route}", "ar": "رخصتك ضمن المرحلة التجريبية. الوحدات المشمولة: {modules}. للتواصل: {route}"},
    "notice_removed": {"en": "Your licence is no longer part of the pilot. Pilot modules are no longer available from {date}. Your licence and renewal are not affected. Your data stays in your account as shown in Settings. Contact: {route}.", "ar": "لم يعد ترخيصك ضمن المرحلة التجريبية. لن تتوفر وحدات المرحلة التجريبية ابتداءً من {date}. ترخيصك وتجديده غير متأثرين. تبقى بياناتك في حسابك كما هو موضح في الإعدادات. للتواصل: {route}."},
    "notice_paused": {"en": "The pilot is paused for your licence. Existing data is kept. We will tell you here when it resumes.", "ar": "تم تعليق المرحلة التجريبية لترخيصك. بياناتك محفوظة. سنبلغك هنا عند استئنافها."},
    "notice_closed": {"en": "Cohort closed. No new enrolments; existing subscriptions continue.", "ar": "أُغلقت المجموعة. لا تسجيلات جديدة؛ تستمر الاشتراكات القائمة."},
    "not_in_pilot": {"en": "not in pilot", "ar": "ليست ضمن المرحلة التجريبية"},
    "enrolled_starts_next_event": {"en": "enrolled, starts at next event", "ar": "مسجّلة، تبدأ عند الحدث التالي"},
    "new_pilot_cohort": {"en": "New pilot cohort", "ar": "مجموعة تجريبية جديدة"},
    "preview_match": {"en": "Preview: {n} mainland licences match", "ar": "معاينة: {n} رخصة بر رئيسي مطابقة"},
    "last_pulled": {"en": "Licence data from DET, last pulled {datetime}, {age} ago", "ar": "بيانات الرخص من الدائرة، آخر سحب {datetime}، قبل {age}"},
    "confirm_blocked_stale": {"en": "Confirmation is blocked: licence data is out of date. Refresh the preview to continue.", "ar": "التأكيد متوقف: بيانات الرخص غير محدّثة. حدّث المعاينة للمتابعة."},
    "no_match": {"en": "No mainland licences match these criteria. Widen a criterion or check the renewal month.", "ar": "لا توجد رخص بر رئيسي مطابقة لهذه المعايير. وسّع أحد المعايير أو تحقق من شهر التجديد."},
    "over_limit": {"en": "{n} licences match; the size limit is {limit}. {excess} over the limit.", "ar": "{n} رخصة مطابقة؛ الحد الأقصى {limit}. {excess} فوق الحد."},
    "fewer_than": {"en": "Fewer than {n}", "ar": "أقل من {n}"},
    "small_groups_hidden": {"en": "Small groups are hidden to protect company privacy.", "ar": "تُخفى المجموعات الصغيرة لحماية خصوصية الشركات."},
    "reason_required": {"en": "Reason for this change (required, saved in the audit trail, not shown to the company)", "ar": "سبب هذا التغيير (مطلوب، يُحفظ في سجل التدقيق، ولا يُعرض للشركة)"},
    "fixed_message": {"en": "The company will be told through its portal with a fixed message", "ar": "سيتم إبلاغ الشركة عبر بوابتها برسالة ثابتة"},
    "no_access": {"en": "You do not have access to cohort management.", "ar": "ليست لديك صلاحية إدارة المجموعات التجريبية."},
    "no_cohorts": {"en": "No cohorts yet. Create the first pilot cohort to start a controlled rollout.", "ar": "لا توجد مجموعات بعد. أنشئ أول مجموعة تجريبية لبدء طرح متحكم به."},
}
AUDIENCE = {k: ("official" if k.startswith("notice_") else "other") for k in STRINGS}

try:
    from app.modules.catalogue.service import register_strings

    register_strings("cohorts", STRINGS, AUDIENCE)
except ImportError:  # pragma: no cover
    pass
