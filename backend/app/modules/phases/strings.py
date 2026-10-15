"""Bilingual strings for the phase map (SC3 'What is live in your pilot') and integration register (E1-S7/S8)."""

from __future__ import annotations

STRINGS: dict[str, dict[str, str]] = {
    "panel_title": {"en": "What is live in your pilot", "ar": "ما هو متاح في تجربتك"},
    "inc_not_started": {"en": "Not started", "ar": "لم يبدأ"},
    "inc_in_build": {"en": "In build", "ar": "قيد التطوير"},
    "inc_manual_path_live": {"en": "Manual path live", "ar": "المسار اليدوي متاح"},
    "inc_live": {"en": "Live", "ar": "متاح"},
    "inc_demo_done": {"en": "Demo done", "ar": "اكتمل العرض"},
    "inc_status_unavailable": {"en": "Status unavailable", "ar": "الحالة غير متاحة"},
    "gate_not_met": {"en": "Not met", "ar": "لم يتحقق"},
    "gate_in_progress": {"en": "In progress", "ar": "قيد التنفيذ"},
    "gate_met": {"en": "Met", "ar": "تحقق"},
    "gate_not_needed_in_pilot": {"en": "Not needed in the pilot", "ar": "غير مطلوب في التجربة"},
    "gate_status_unavailable": {"en": "Gate status unavailable", "ar": "حالة الشرط غير متاحة"},
    "not_yet_switched_on_full": {"en": "Not yet switched on. We will tell you when it is ready.", "ar": "لم يتم التفعيل بعد. سنخبرك عند جاهزيته."},
    "not_yet_switched_on": {"en": "Not yet switched on", "ar": "لم يتم التفعيل بعد"},
    "not_assigned": {"en": "Not assigned to you", "ar": "غير مُسند إليك"},
    "history_unavailable": {"en": "History unavailable", "ar": "السجل غير متاح"},
    "loading": {"en": "Loading what is live", "ar": "جارٍ تحميل ما هو متاح"},
    "plan_empty": {"en": "The phase plan has not been published. Nothing is switched on yet.", "ar": "لم تُنشر خطة المراحل بعد. لم يتم تفعيل أي شيء حتى الآن."},
    "plan_error": {"en": "We could not load the phase plan. Features you already use still work. Try again, or contact the pilot team.", "ar": "تعذّر تحميل خطة المراحل. الخدمات التي تستخدمها ما زالت تعمل. حاول مرة أخرى أو تواصل مع فريق التجربة."},
    "gates_error": {"en": "We could not load the entry gates. Features you already use still work. Try again, or contact the pilot team.", "ar": "تعذّر تحميل شروط التفعيل. الخدمات التي تستخدمها ما زالت تعمل. حاول مرة أخرى أو تواصل مع فريق التجربة."},
    "waiting_for": {"en": "Waiting for: {gate}", "ar": "بانتظار: {gate}"},
    "until_then": {"en": "Until then: {fallback}", "ar": "حتى ذلك الحين: {fallback}"},
    "demo_outcome": {"en": "Demo outcome: what you will be able to do at this step", "ar": "نتيجة العرض: ما ستتمكن من فعله في هذه الخطوة"},
    "status_changed": {"en": "Status changed on {date}. Recorded in the audit trail.", "ar": "تغيّرت الحالة في {date}. مسجّل في سجل التدقيق."},
    "last_known": {"en": "Last known, {date}", "ar": "آخر حالة معروفة، {date}"},
    # integration register (E1-S8)
    "integration_off": {"en": "This integration is off. Use manual upload instead.", "ar": "هذا الربط متوقف. استخدم الرفع اليدوي بدلًا منه."},
    "bank_not_available": {"en": "Bank link: not available yet. You can upload statements yourself.", "ar": "الربط المصرفي: غير متاح بعد. يمكنك رفع كشوف الحساب بنفسك."},
    "btn_upload_statements": {"en": "Upload statements", "ar": "رفع الكشوف"},
    "fta_prepared_here": {"en": "Tax authority submission: prepared here, filed by you on the FTA portal (EmaraTax).", "ar": "التقديم إلى الهيئة الاتحادية للضرائب: يُعدّ هنا ويُقدَّم من قبلك عبر بوابة الهيئة (إمارات تاكس)."},
    "btn_open_filing_pack": {"en": "Open the filing pack", "ar": "فتح ملف التقديم"},
    "erp_not_available": {"en": "Accounting software link: not available yet. You can enter figures or upload a file.", "ar": "الربط ببرنامج المحاسبة: غير متاح بعد. يمكنك إدخال الأرقام أو رفع ملف."},
    "btn_enter_figures": {"en": "Enter figures", "ar": "إدخال الأرقام"},
    "licence_not_available": {"en": "Licence details are not available right now. You can enter them yourself and they will be marked as not checked.", "ar": "بيانات الرخصة غير متاحة الآن. يمكنك إدخالها بنفسك وستُعلَّم بأنها غير مدققة."},
    "btn_enter_licence": {"en": "Enter licence details", "ar": "إدخال بيانات الرخصة"},
    "payment_not_available": {"en": "Online payment from this page is not available yet. Pay through your usual government payment channel.", "ar": "الدفع الإلكتروني من هذه الصفحة غير متاح بعد. ادفع عبر قناة الدفع الحكومية المعتادة."},
    "checklist_incomplete": {"en": "Checklist incomplete: {n} of {m} items have evidence.", "ar": "قائمة التحقق غير مكتملة: {n} من {m} بنود لديها دليل."},
    "n_of_m": {"en": "{n} of {m} items have evidence", "ar": "{n} من {m} بنود لديها دليل"},
    "switched_off_note": {"en": "Switched off. New requests have stopped. Work in progress is marked unconfirmed.", "ar": "تم الإيقاف. توقفت الطلبات الجديدة. العمل الجاري مُعلَّم كغير مؤكد."},
    "phase_strip": {"en": "Phase 1: manual upload, tax preparation, reminders. Phase 2: bank links once licence and agreements are in place.", "ar": "المرحلة 1: الرفع اليدوي وإعداد الضرائب والتذكيرات. المرحلة 2: الربط المصرفي بعد توفر الترخيص والاتفاقيات."},
    "register_empty": {"en": "No checklist rows yet. All integrations are OFF.", "ar": "لا توجد بنود في قائمة التحقق بعد. جميع عمليات الربط متوقفة."},
    "register_empty_owners": {"en": "Owners are using manual upload and entry.", "ar": "يستخدم المالكون الرفع والإدخال اليدوي."},
    "owner_empty": {"en": "Everything you need works through manual upload and entry.", "ar": "كل ما تحتاجه يعمل عبر الرفع والإدخال اليدوي."},
    "register_error": {"en": "Could not load the register. Showing the last saved state from {when}. Switch states are unchanged. Try again.", "ar": "تعذر تحميل السجل. نعرض آخر حالة محفوظة بتاريخ {when}. لم تتغير حالات التشغيل. حاول مرة أخرى."},
    "owner_error": {"en": "We could not check this feature. Use manual upload for now.", "ar": "تعذّر التحقق من هذه الميزة. استخدم الرفع اليدوي الآن."},
    "manual_route_down": {"en": "Manual upload is not working right now. Your data is safe and nothing was lost. Try again later, or contact support.", "ar": "رفع الملفات لا يعمل حاليًا. بياناتك محفوظة ولم يُفقد شيء. حاول لاحقًا أو تواصل مع الدعم."},
    "checking_availability": {"en": "Checking availability…", "ar": "جارٍ التحقق من التوفر…"},
    "manual_unverified": {"en": "manual, unverified", "ar": "يدوي، غير مدقق"},
    "k11_not_measurable": {"en": "Not yet measurable", "ar": "غير قابل للقياس بعد"},
    "k11_no_bank_route": {"en": "No bank route available", "ar": "لا يوجد مسار مصرفي متاح"},
}
AUDIENCE: dict[str, str] = {k: "other" for k in STRINGS}

try:
    from app.modules.catalogue.service import register_strings

    register_strings("phases", STRINGS, AUDIENCE)
except Exception:  # pragma: no cover
    pass


def s(key: str, lang: str = "en", **params: object) -> str:
    value = STRINGS[key][lang if lang in ("en", "ar") else "en"]
    return value.format(**params) if params else value


def both(key: str, **params: object) -> dict[str, str]:
    return {"en": s(key, "en", **params), "ar": s(key, "ar", **params)}
