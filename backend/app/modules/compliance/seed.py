"""Requirement catalogue (confirmed: licence expiry, Ejari, Chambers; others typed 'to be confirmed by DET'),
lead times as configuration, material_fields_v1, and a demo renewal checklist for Al Noor."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.time import dubai_today
from app.demo import CO_ALNOOR
from app.modules.compliance.models import ComplianceDraft, RequirementRule
from app.modules.compliance.service import LEAD_TIMES_DEFAULT, MATERIAL_FIELDS_V1
from app.modules.config.service import ensure_config, ensure_rule

ORDER = 42

CATALOGUE = [
    # requirement_type, code, title_en, title_ar, authority, instrument, status, activity_code
    ("licence_expiry", "licence_expiry", "Trade licence expiry (annual renewal)", "انتهاء الرخصة التجارية (تجديد سنوي)", "DET", "DET licence renewal procedure", "confirmed", None),
    ("ejari_expiry", "ejari_valid", "Valid Ejari for renewal", "عقد إيجاري ساري للتجديد", "Dubai Land Department / RERA (Ejari)", "Ejari rules of Dubai Land Department / RERA", "confirmed", None),
    ("chambers_membership", "chambers_membership", "Dubai Chambers membership", "عضوية غرف دبي", "Dubai Chambers", "Dubai Chambers membership rules (UX: confirmed for renewal)", "confirmed", None),
    ("other", "ubo_declaration", "Ultimate beneficial owner declaration", "إقرار المستفيد الحقيقي", "DET", "to be confirmed by DET", "to_be_confirmed", None),
    ("other", "renewal_grace_period", "Renewal grace period and late fines", "فترة السماح للتجديد والغرامات المتأخرة", "DET", "Cabinet Decision No. 58 of 2020 (to confirm); no fee amounts or grace length shown", "to_be_confirmed", None),
    ("other", "civil_defence_approval", "Civil Defence approval (activity-specific)", "موافقة الدفاع المدني (بحسب النشاط)", "Dubai Civil Defence", "activity-to-approval table [OPEN]; pilot cohort activities only", "to_be_confirmed", "Foodstuff trading"),
]


def seed(db: Session) -> None:
    for rtype, code, en, ar, authority, instr, status, activity in CATALOGUE:
        if db.scalar(select(RequirementRule).where(RequirementRule.code == code)) is not None:
            continue
        lt = LEAD_TIMES_DEFAULT.get(rtype) or LEAD_TIMES_DEFAULT["global_default"]
        db.add(RequirementRule(requirement_type=rtype, code=code, title_en=en, title_ar=ar, activity_code=activity, approving_authority=authority, instrument=instr, effective_date=None, confirmation_status=status,
                               source_reference=instr, last_confirmed=dubai_today() if status == "confirmed" else None, version="v1", due_soon_days=lt["due_soon"] if status == "confirmed" else None, at_risk_days=lt["at_risk"] if status == "confirmed" else None))
    for key, value, status, label, unit in (
        ("compliance.lead_times", LEAD_TIMES_DEFAULT, "provisional", "Phase 1 starting values (licence/Ejari 60/30, global 45/21)", "days"),
        ("compliance.ejari_dependency_days", 30, "confirmed", "settled: at risk whenever Ejari expiry < licence expiry or within 30 days of it", "days"),
        ("compliance.due_soon_window_days", 30, "provisional", "illustrative generic window", "days"),
        ("compliance.ejari_min_remaining_validity_at_event_days", 0, "to_be_confirmed", "assumption ('valid on the date of the event'); confirm with DET", "days"),
        ("compliance.source_refresh", "daily batch per source", "provisional", "configurable", None),
        ("compliance.threshold_version", "lead-times-v1", "provisional", "versioned thresholds", None),
        ("compliance.material_fields_v1", MATERIAL_FIELDS_V1, "provisional", "K15 material fields per output type (versioned)", None),
        ("compliance.k15.min_group_size", 10, "provisional", "demo suppression", "count"),
        ("compliance.k15.illustrative_range", "70-90% acceptance without material change", "provisional", "placeholder, not a target", None),
        ("compliance.upload.types", ["PDF", "JPG", "PNG", "DOCX", "XLSX", "CSV"], "provisional", "versioned config", None),
        ("compliance.upload.limits", {"max_mb": 10, "max_files": 10}, "provisional", "versioned config", None),
    ):
        ensure_config(db, key, value, status=status, label=label, unit=unit, owner="UX / Domain (E3-S3)")
    ensure_rule(db, "compliance-catalogue-v1", "Licence-linked requirement catalogue: Ejari, licence expiry, Chambers confirmed; others to be confirmed by DET", instrument="DET renewal procedure; Ejari rules; Dubai Chambers", status="provisional", owner_role="Compliance content owner (DET)", parameters={"confirmed": ["licence_expiry", "ejari_expiry", "chambers_membership"]})
    db.flush()


def seed_demo(db: Session) -> None:
    if db.scalar(select(ComplianceDraft).where(ComplianceDraft.company_id == CO_ALNOOR).limit(1)) is not None:
        return
    from app.modules.compliance.service import prepare_pack

    d = prepare_pack(db, None, CO_ALNOOR, "renewal_checklist")
    d.is_demo = True
    db.flush()
