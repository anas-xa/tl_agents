"""Versioned KPI catalogue for SC14 (E9-S1 §2.1, KPI dictionary K1-K30).

The catalogue is seeded into ``kpi_definitions`` per ``CATALOGUE_VERSION``; release state comes from
configuration (``det_dashboard.later_phase_kpis.enabled`` flips K5-K8 together; ``det_dashboard.release_settings``
holds the per-tile phase label and state). Arabic text is a draft pending native review.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

CATALOGUE_VERSION = "kpi-cat-v1"
LATER_SWITCH = "det_dashboard.later_phase_kpis.enabled"
RELEASE_SETTINGS = "det_dashboard.release_settings"
LIVE_FIRST_RELEASE = ("K1", "K2", "K3", "K4", "K19")
SWITCHED_GROUP = ("K5", "K6", "K7", "K8")
BASE_DIMS = ["month", "cohort", "wave", "enrolment_basis", "licence_category"]
TBC = {"en": "To be confirmed", "ar": "قيد التأكيد"}

KPIS: list[dict] = [
    {
        "kpi_id": "K1", "name_en": "Active subscribed licences", "name_ar": "الرخص المشتركة النشطة",
        "definition_en": "Mainland licences with an active smart-services subscription at the end of the period.",
        "definition_ar": "رخص البر الرئيسي التي لديها اشتراك نشط في الخدمات الذكية في نهاية الفترة.",
        "formula_text": "Count of licences with subscription status = active at period end", "unit": "count", "target_en": None,
        "refresh_period": "daily", "source_list": ["DET licensing and billing", "Payment channel"], "rule_version_id": "k1-v1", "is_fairness_indicator": False,
        "dimensions": BASE_DIMS,
    },
    {
        "kpi_id": "K2", "name_en": "Subscription revenue billed", "name_ar": "إيرادات الاشتراك المفوترة",
        "definition_en": "Subscription fees on DET invoices, net of VAT, in AED. Billed view: period = calendar month of the invoice date; credit notes are separate negative lines in the month issued. Recognised view: billed amount spread evenly over the term months; the last month takes the rounding remainder.",
        "definition_ar": "رسوم الاشتراك في فواتير دائرة الاقتصاد والسياحة، صافية من ضريبة القيمة المضافة، بالدرهم. عرض الفوترة: الفترة هي شهر تاريخ الفاتورة؛ إشعارات الدائن بنود سالبة منفصلة في شهر إصدارها. عرض الإثبات: المبلغ المفوتر موزع بالتساوي على أشهر المدة، ويأخذ الشهر الأخير فرق التقريب.",
        "formula_text": "Billed: sum of net subscription line amounts (fils) by invoice month; net billed = billed - credit notes. Recognised: billed / term_months per month. Normalised annual = billed net / term_months x 12.",
        "unit": "AED", "target_en": None, "refresh_period": "daily", "source_list": ["DET licensing and billing", "Fee schedule (versioned)"], "rule_version_id": "k2-v1", "is_fairness_indicator": False,
        "dimensions": BASE_DIMS + ["payment_status"],
    },
    {
        "kpi_id": "K3", "name_en": "Subscription collection rate", "name_ar": "معدل تحصيل الاشتراك",
        "definition_en": "Payments collected ÷ amounts billed, for the selected period.",
        "definition_ar": "المدفوعات المحصّلة ÷ المبالغ المفوترة، للفترة المحددة.",
        "formula_text": "Final: (collected on billing-line or invoice-single-line basis - refunds) / (billed - refunds that cancel the charge) x 100; partial and goodwill refunds reduce collected only. Provisional: same including platform-derived allocations (alloc-v1), with platform-derived share = platform-derived collected / total collected x 100.",
        "unit": "%", "target_en": None, "refresh_period": "daily", "source_list": ["Payment channel", "DET billing", "Allocation table (alloc-v1)"], "rule_version_id": "alloc-v1", "is_fairness_indicator": False,
        "dimensions": BASE_DIMS + ["payment_method"],
    },
    {
        "kpi_id": "K4", "name_en": "Opt-out and complaint rate", "name_ar": "معدل إلغاء الاشتراك والشكاوى",
        "definition_en": "Share of subscriptions with at least one qualifying flag (refunded, opted out, complained) inside the 90-day window from the invoice date. Each subscription is counted once (refunded > opted out > complained). Split by enrolment mode.",
        "definition_ar": "نسبة الاشتراكات التي لديها مؤشر مؤهل واحد على الأقل (استرداد، إلغاء، شكوى) خلال 90 يوماً من تاريخ الفاتورة. يُحتسب كل اشتراك مرة واحدة (الاسترداد ثم الإلغاء ثم الشكوى). مقسّمة حسب طريقة التسجيل.",
        "formula_text": "Subscriptions with >= 1 of flag_refunded, flag_opted_out, flag_complained (event within window) / subscriptions in the denominator x 100; plus each flag separately, confirmed vs pending opt-outs and excluded counts.",
        "unit": "%", "target_en": None, "refresh_period": "daily", "source_list": ["DET billing", "Refund records", "Complaint log", "Opt-out events"], "rule_version_id": "k4-v1", "is_fairness_indicator": True,
        "dimensions": BASE_DIMS,
    },
    {
        "kpi_id": "K5", "name_en": "Subscription retention at renewal", "name_ar": "الاحتفاظ بالاشتراك عند التجديد",
        "definition_en": "Share of subscriptions due for renewal in the period that renew with the licence, by the cohort stamped at creation.",
        "definition_ar": "نسبة الاشتراكات المستحقة للتجديد في الفترة التي تُجدَّد مع الرخصة، حسب المجموعة المسجلة عند الإنشاء.",
        "formula_text": "Subscriptions renewed / subscriptions due for renewal (excluding cancelled before term end) x 100, by enrolment_basis and renewal_choice_marker",
        "unit": "%", "target_en": None, "refresh_period": "monthly", "source_list": ["DET licensing and billing", "Subscription state history", "Audit trail"], "rule_version_id": "k5-v1", "is_fairness_indicator": False,
        "dimensions": BASE_DIMS,
    },
    {
        "kpi_id": "K6", "name_en": "On-time licence renewal rate", "name_ar": "معدل تجديد الرخص في الموعد",
        "definition_en": "Share of mainland DET licences whose previous expiry date falls in the month and whose renewal was completed (Asia/Dubai day) on or before that date. Renewals in grace are late. Cancelled before expiry and suspended at expiry are excluded and counted.",
        "definition_ar": "نسبة رخص البر الرئيسي التي يقع تاريخ انتهائها السابق في الشهر واكتمل تجديدها (بتوقيت دبي) في ذلك التاريخ أو قبله. التجديد في فترة السماح متأخر. تُستبعد الرخص الملغاة قبل الانتهاء والموقوفة عند الانتهاء وتُعدّ بشكل منفصل.",
        "formula_text": "Licences with date(renewal_completed_at) <= previous_expiry_date / licences with previous_expiry_date in month (excluding mapped exclusions) x 100",
        "unit": "%", "target_en": None, "refresh_period": "monthly", "source_list": ["DET licensing and billing", "Versioned status mapping table"], "rule_version_id": "k6-v1", "is_fairness_indicator": False,
        "dimensions": BASE_DIMS,
    },
    {
        "kpi_id": "K7", "name_en": "Late-filing rate", "name_ar": "معدل التأخر في تقديم الإقرارات",
        "definition_en": "Share of measurable returns due in the period that were filed after the effective due date. Owner-reported, not FTA-verified.",
        "definition_ar": "نسبة الإقرارات القابلة للقياس المستحقة في الفترة التي قُدّمت بعد تاريخ الاستحقاق الفعلي. حسب إفادة المالك، وغير متحقق منها لدى الهيئة الاتحادية للضرائب.",
        "formula_text": "Returns filed after due_date_used / returns due in period and measurable x 100",
        "unit": "%", "target_en": None, "refresh_period": "monthly", "source_list": ["Manual receipt upload", "Due-date rule table (vat-due-v1, ct-due-v1)"], "rule_version_id": "k7k8-v1", "is_fairness_indicator": False,
        "dimensions": BASE_DIMS,
    },
    {
        "kpi_id": "K8", "name_en": "On-time filing rate", "name_ar": "معدل تقديم الإقرارات في الموعد",
        "definition_en": "Share of measurable returns due in the period that were filed on or before the effective due date. Owner-reported, not FTA-verified.",
        "definition_ar": "نسبة الإقرارات القابلة للقياس المستحقة في الفترة التي قُدّمت في تاريخ الاستحقاق الفعلي أو قبله. حسب إفادة المالك، وغير متحقق منها لدى الهيئة الاتحادية للضرائب.",
        "formula_text": "Returns filed on or before due_date_used / returns due in period and measurable x 100",
        "unit": "%", "target_en": None, "refresh_period": "monthly", "source_list": ["Manual receipt upload", "Due-date rule table (vat-due-v1, ct-due-v1)"], "rule_version_id": "k7k8-v1", "is_fairness_indicator": False,
        "dimensions": BASE_DIMS,
    },
    {
        "kpi_id": "K19", "name_en": "Audit deliverable sign-off status mix", "name_ar": "توزيع حالات اعتماد مخرجات التدقيق",
        "definition_en": "Counts by status of current deliverables that need a licensed signature (draft audit working files: draft, under review, signed, rejected) and a separate count of issued audit reports. Types that need no signature are shown on a separate line.",
        "definition_ar": "أعداد المخرجات الحالية التي تحتاج إلى توقيع مدقق مرخّص حسب الحالة (ملفات عمل التدقيق المسودة: مسودة، قيد المراجعة، موقّع، مرفوض) وعدد منفصل لتقارير مدقق الحسابات الصادرة. تُعرض الأنواع التي لا تحتاج إلى توقيع في سطر منفصل.",
        "formula_text": "Current deliverables with signature_required = yes (sig-v1; unknown type = yes) in each status / total current deliverables with signature_required = yes x 100; unsigned-release count must be 0",
        "unit": "count", "target_en": "100% of deliverables needing a signature carry a licensed signer before release; unsigned-release count = 0", "refresh_period": "daily", "source_list": ["Audit file", "Deliverable register", "sig-v1 rule table"], "rule_version_id": "sig-v1", "is_fairness_indicator": False,
        "dimensions": ["cohort", "wave", "licence_category"],
    },
    {
        "kpi_id": "K20", "name_en": "Audit-required share", "name_ar": "نسبة الرخص التي يُرجّح أن تتطلب تدقيقاً",
        "definition_en": "Share of pilot licences in each audit-required state for the tax period, using the latest evaluation per licence per period. An indicator, not a legal determination.",
        "definition_ar": "نسبة رخص المرحلة التجريبية في كل حالة من حالات الحاجة إلى التدقيق للفترة الضريبية، باستخدام أحدث تقييم لكل رخصة في كل فترة. مؤشر وليس قراراً قانونياً.",
        "formula_text": "Latest evaluation per licence-period: count in state / licences with >= 1 evaluation x 100; not yet evaluated shown separately",
        "unit": "%", "target_en": None, "refresh_period": "monthly", "source_list": ["Audit-required flag evaluations (MD 84/2025 thresholds, versioned)"], "rule_version_id": "k20-v1", "is_fairness_indicator": False,
        "dimensions": ["cohort", "wave", "licence_category"],
    },
    {
        "kpi_id": "K29", "name_en": "Cohort usage rate", "name_ar": "معدل استخدام المجموعة",
        "definition_en": "Share of active subscribed licences with at least one qualifying event in the last 30 days (sign-in, document download, approval, consent change, escalation opened).",
        "definition_ar": "نسبة الرخص المشتركة النشطة التي لديها حدث مؤهل واحد على الأقل خلال آخر 30 يوماً (تسجيل الدخول، تنزيل مستند، موافقة، تغيير موافقة، فتح تصعيد).",
        "formula_text": "Licences with >= 1 qualifying event in the last 30 days / active subscribed licences x 100",
        "unit": "%", "target_en": None, "refresh_period": "daily", "source_list": ["Audit trail (platform events only)", "DET licensing and billing"], "rule_version_id": "k29-v1", "is_fairness_indicator": False,
        "dimensions": ["cohort", "wave", "enrolment_basis", "licence_category"],
    },
]
KPI_INDEX = {k["kpi_id"]: k for k in KPIS}
DEFAULT_RELEASE_SETTINGS = {
    "K5": {"state": "not_yet_available", "phase": "1H"},
    "K6": {"state": "not_yet_available", "phase": "1H"},
    "K7": {"state": "not_yet_available", "phase": "1H"},
    "K8": {"state": "not_yet_available", "phase": "1H"},
    "K20": {"state": "not_yet_available", "phase": "1D"},
    "K29": {"state": "not_yet_available", "phase": "1A"},
}


def release_state(db: Session, kpi_id: str) -> tuple[str, str | None]:
    """(release_state, planned_phase_label). K1-K4 and K19 are live; K5-K8 flip together with one setting."""
    from app.modules.config.service import get_config

    if kpi_id in LIVE_FIRST_RELEASE:
        return "live", None
    settings = {**DEFAULT_RELEASE_SETTINGS, **(get_config(db, RELEASE_SETTINGS, {}) or {})}
    entry = settings.get(kpi_id, {"state": "not_yet_available", "phase": None})
    if kpi_id in SWITCHED_GROUP:
        return ("live" if bool(get_config(db, LATER_SWITCH, False)) else "not_yet_available"), entry.get("phase")
    return ("live" if entry.get("state") == "live" else "not_yet_available"), entry.get("phase")


def group_of(kpi_id: str) -> str:
    """Layout group is fixed per KPI so flipping the release setting never changes the layout."""
    return "live" if kpi_id in LIVE_FIRST_RELEASE else "later"


def definitions(db: Session) -> list[dict]:
    """Current catalogue rows (seeded); falls back to the in-code version before the seed has run."""
    from app.modules.kpis.models import KpiDefinition

    rows = {r.kpi_id: r for r in db.scalars(select(KpiDefinition).where(KpiDefinition.is_current.is_(True)))}
    out = []
    for k in KPIS:
        row = rows.get(k["kpi_id"])
        base = dict(k)
        if row is not None:
            base.update(name_en=row.name_en, name_ar=row.name_ar, definition_en=row.definition_en, definition_ar=row.definition_ar, formula_text=row.formula_text, unit=row.unit, target_en=row.target_en, refresh_period=row.refresh_period, source_list=row.source_list, rule_version_id=row.rule_version_id, dimensions=row.dimensions, catalogue_version=row.catalogue_version)
        base.setdefault("catalogue_version", CATALOGUE_VERSION)
        state, phase = release_state(db, k["kpi_id"])
        base.update(release_state=state, planned_phase_label=phase, group=group_of(k["kpi_id"]))
        base["target"] = {"en": base["target_en"], "ar": None} if base.get("target_en") else dict(TBC)
        out.append(base)
    return out


def ensure_catalogue(db: Session) -> None:
    from app.modules.kpis.models import KpiDefinition

    for k in KPIS:
        exists = db.scalar(select(KpiDefinition).where(KpiDefinition.kpi_id == k["kpi_id"], KpiDefinition.catalogue_version == CATALOGUE_VERSION))
        if exists is not None:
            continue
        for old in db.scalars(select(KpiDefinition).where(KpiDefinition.kpi_id == k["kpi_id"], KpiDefinition.is_current.is_(True))):
            old.is_current = False
        db.add(KpiDefinition(
            kpi_id=k["kpi_id"], catalogue_version=CATALOGUE_VERSION, name_en=k["name_en"], name_ar=k["name_ar"], definition_en=k["definition_en"], definition_ar=k["definition_ar"],
            formula_text=k["formula_text"], unit=k["unit"], target_en=k["target_en"], refresh_period=k["refresh_period"], source_list=k["source_list"], rule_version_id=k["rule_version_id"],
            group=group_of(k["kpi_id"]), planned_phase_label=DEFAULT_RELEASE_SETTINGS.get(k["kpi_id"], {}).get("phase"), is_fairness_indicator=k["is_fairness_indicator"], dimensions=k["dimensions"],
        ))
    db.flush()
