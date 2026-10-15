"""Demo data for the mock UAE PASS personas: companies, licences, DET persons, company and staff roles.

Loaded by ``scripts/seed_demo.py`` and by the test-suite. Feature modules extend it via ``DEMO_SEEDERS``.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.time import utcnow
from app.modules.companies.models import Company, CompanyRole
from app.modules.identity.models import StaffRole
from app.modules.identity.service import hash_emirates_id
from app.modules.licences.models import Licence, LicencePerson

DEMO_SEEDERS: list[Callable[[Session], None]] = []

# Stable ids so tests and the frontend demo can reference them.
CO_ALNOOR = "co_alnoor"
CO_BLUEDUNE = "co_bluedune"
CO_SAFWA = "co_safwa"
CO_GULFTECH = "co_gulftech"

PERSONA_UUIDS = {
    "khalid": "uuid-khalid-owner",
    "priya": "uuid-priya-remote",
    "omar": "uuid-omar-delegate",
    "layla": "uuid-layla-auditor",
    "sara": "uuid-sara-detadmin",
    "faisal": "uuid-faisal-pilot",
    "noura": "uuid-noura-reviewer",
    "hassan": "uuid-hassan-taxspec",
    "mariam": "uuid-mariam-legal",
    "yusuf": "uuid-yusuf-escops",
    "adel": "uuid-adel-secadmin",
    "lina": "uuid-lina-po",
    "ahmed": "uuid-ahmed-complaints",
}
PERSONA_IDN = {
    "khalid": "784-1980-1234567-1",
    "priya": "784-1985-7654321-2",
    "omar": "784-1990-1111111-3",
    "layla": "784-1975-2222222-4",
}


def demo_seeder(fn: Callable[[Session], None]) -> Callable[[Session], None]:
    DEMO_SEEDERS.append(fn)
    return fn


def seed_demo(db: Session) -> None:
    from app.discovery import run_demo_seeds

    if db.get(Company, CO_ALNOOR) is not None:
        for fn in DEMO_SEEDERS:
            fn(db)
        run_demo_seeds(db)
        return
    today = date.today()
    companies = [
        Company(id=CO_ALNOOR, trade_name_en="Al Noor Trading LLC", trade_name_ar="النور للتجارة ذ.م.م", legal_form="LLC", owner_location_self_declared="uae", onboarding_at=utcnow() - timedelta(days=40), onboarding_id="onb_alnoor_1"),
        Company(id=CO_BLUEDUNE, trade_name_en="Blue Dune Consultancy", trade_name_ar="بلو ديون للاستشارات", legal_form="Sole establishment", owner_location_self_declared="abroad", onboarding_at=utcnow() - timedelta(days=20), onboarding_id="onb_bluedune_1"),
        Company(id=CO_SAFWA, trade_name_en="Safwa Foods LLC", trade_name_ar="صفوة للأغذية ذ.م.م", legal_form="LLC", owner_location_self_declared="uae", onboarding_at=utcnow() - timedelta(days=90), onboarding_id="onb_safwa_1"),
        Company(id=CO_GULFTECH, trade_name_en="Gulf Tech Systems LLC", trade_name_ar="جلف تك للأنظمة ذ.م.م", legal_form="LLC", owner_location_self_declared="uae", onboarding_at=utcnow() - timedelta(days=120), onboarding_id="onb_gulftech_1"),
    ]
    db.add_all(companies)
    db.flush()
    licences = [
        Licence(id="lic_alnoor", company_id=CO_ALNOOR, licence_number="DET-1023456", trade_name_en="Al Noor Trading LLC", trade_name_ar="النور للتجارة ذ.م.م", legal_form="LLC", category="Commercial", activities=["General trading"], issue_date=today.replace(year=today.year - 3), expiry_date=today + timedelta(days=45), previous_expiry_date=today - timedelta(days=320), status="active", raw_status="ACTIVE", ejari_number="EJ-55-2024-1188", ejari_expiry=today + timedelta(days=30), ejari_status="verified", premises="Office 1204, Business Bay", chamber_membership_status="verified", chamber_membership_expiry=today + timedelta(days=45), last_det_refresh_at=utcnow() - timedelta(hours=3)),
        Licence(id="lic_bluedune", company_id=CO_BLUEDUNE, licence_number="DET-2045678", trade_name_en="Blue Dune Consultancy", trade_name_ar="بلو ديون للاستشارات", legal_form="Sole establishment", category="Professional", activities=["Management consultancy"], issue_date=today.replace(year=today.year - 1), expiry_date=today + timedelta(days=200), previous_expiry_date=today - timedelta(days=165), status="active", raw_status="ACTIVE", ejari_number="EJ-55-2025-2210", ejari_expiry=today + timedelta(days=190), ejari_status="owner_declared", premises="Flexi desk, Deira", chamber_membership_status="unconfirmed", last_det_refresh_at=utcnow() - timedelta(hours=5)),
        Licence(id="lic_safwa", company_id=CO_SAFWA, licence_number="DET-3067890", trade_name_en="Safwa Foods LLC", trade_name_ar="صفوة للأغذية ذ.م.م", legal_form="LLC", category="Commercial", activities=["Foodstuff trading"], issue_date=today.replace(year=today.year - 5), expiry_date=today - timedelta(days=10), previous_expiry_date=today - timedelta(days=375), status="expired", raw_status="EXPIRED", ejari_number="EJ-55-2023-9901", ejari_expiry=today - timedelta(days=12), ejari_status="verified", premises="Shop 3, Al Quoz", chamber_membership_status="verified", chamber_membership_expiry=today - timedelta(days=10), last_det_refresh_at=utcnow() - timedelta(hours=30)),
        Licence(id="lic_gulftech", company_id=CO_GULFTECH, licence_number="DET-4089012", trade_name_en="Gulf Tech Systems LLC", trade_name_ar="جلف تك للأنظمة ذ.م.م", legal_form="LLC", category="Commercial", activities=["IT systems trading", "Software"], issue_date=today.replace(year=today.year - 4), expiry_date=today + timedelta(days=120), previous_expiry_date=today - timedelta(days=245), status="active", raw_status="ACTIVE", ejari_number="EJ-55-2024-4477", ejari_expiry=today + timedelta(days=110), ejari_status="verified", premises="Office 7, Dubai Internet City", chamber_membership_status="verified", chamber_membership_expiry=today + timedelta(days=120), last_det_refresh_at=utcnow() - timedelta(hours=2)),
    ]
    db.add_all(licences)
    db.flush()
    db.add_all(
        [
            LicencePerson(licence_id="lic_alnoor", display_name="Khalid Al Mansoori", capacity="owner", emirates_id_hash=hash_emirates_id(PERSONA_IDN["khalid"]), share_percent=100, signing_rule="any_one", source_document="DET licence record"),
            LicencePerson(licence_id="lic_bluedune", display_name="Priya Raman", capacity="owner", emirates_id_hash=hash_emirates_id(PERSONA_IDN["priya"]), share_percent=100, signing_rule="any_one", source_document="DET licence record"),
            LicencePerson(licence_id="lic_safwa", display_name="Khalid Al Mansoori", capacity="partner", emirates_id_hash=hash_emirates_id(PERSONA_IDN["khalid"]), share_percent=60, signing_rule="any_one", source_document="DET licence record"),
            LicencePerson(licence_id="lic_safwa", display_name="Mohammed Saif", capacity="partner", emirates_id_hash=None, has_emirates_id=False, share_percent=40, signing_rule="any_one", source_document="DET licence record"),
            LicencePerson(licence_id="lic_gulftech", display_name="Owner Without Emirates ID", capacity="owner", emirates_id_hash=None, has_emirates_id=False, share_percent=100, signing_rule="unclear", source_document="DET licence record"),
        ]
    )
    db.add_all(
        [
            CompanyRole(identity_uuid=PERSONA_UUIDS["khalid"], company_id=CO_ALNOOR, role="owner", capacity="owner", functions=["all"], granted_by_uuid="det_onboarding"),
            CompanyRole(identity_uuid=PERSONA_UUIDS["khalid"], company_id=CO_SAFWA, role="owner", capacity="owner", functions=["all"], granted_by_uuid="det_onboarding"),
            CompanyRole(identity_uuid=PERSONA_UUIDS["priya"], company_id=CO_BLUEDUNE, role="remote_owner", capacity="owner", functions=["all"], granted_by_uuid="det_onboarding"),
            CompanyRole(identity_uuid=PERSONA_UUIDS["omar"], company_id=CO_ALNOOR, role="delegate", capacity="delegate", functions=["bookkeeping", "tax_preparation", "uploads"], rights=["prepare", "view"], granted_by_uuid=PERSONA_UUIDS["khalid"], valid_to=today + timedelta(days=200)),
            CompanyRole(identity_uuid=PERSONA_UUIDS["omar"], company_id=CO_BLUEDUNE, role="delegate", capacity="delegate", functions=["bookkeeping", "tax_preparation", "uploads"], rights=["prepare", "view"], granted_by_uuid=PERSONA_UUIDS["priya"], valid_to=today + timedelta(days=150)),
            CompanyRole(identity_uuid=PERSONA_UUIDS["omar"], company_id=CO_GULFTECH, role="delegate", capacity="delegate", functions=["bookkeeping"], rights=["prepare", "view"], granted_by_uuid="uuid-no-eid-owner", valid_to=today + timedelta(days=90)),
            CompanyRole(identity_uuid="uuid-no-eid-owner", company_id=CO_GULFTECH, role="owner", capacity="owner", functions=["all"], granted_by_uuid="det_onboarding"),
        ]
    )
    staff = [
        ("layla", "licensed_auditor", "MoE auditor register ref AUD-2201"),
        ("sara", "det_admin", None),
        ("faisal", "det_pilot_manager", None),
        ("noura", "compliance_reviewer", None),
        ("hassan", "tax_specialist", "FTA tax agent register ref TAA-3310"),
        ("mariam", "legal_specialist", "Legal Affairs Department firm licence ref LAD-0871"),
        ("yusuf", "escalation_ops", None),
        ("adel", "platform_security_admin", None),
        ("lina", "qeonix_product_owner", None),
        ("ahmed", "det_complaint_handler", None),
        ("sara", "det_compliance_lead", None),
    ]
    for persona, role, ent in staff:
        db.add(StaffRole(identity_uuid=PERSONA_UUIDS[persona], role=role, scope="det" if role.startswith("det") else "qeonix", work_email=f"{persona}@example.ae", status="active", requester="seed-script", approver="security-admin-2", reason="initial seed under two-person rule", entitlement_ref=ent, bound_at=utcnow()))
    db.flush()
    for fn in DEMO_SEEDERS:
        fn(db)
    run_demo_seeds(db)
    db.flush()


def company_ids(db: Session) -> list[str]:
    return list(db.scalars(select(Company.id)))
