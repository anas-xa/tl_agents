"""Draft seeds (ORDER 58): config (FTA link off, retention classes, rubric); demo packs for Al Noor."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.demo import CO_ALNOOR, PERSONA_UUIDS
from app.modules.config.service import ensure_config
from app.modules.drafts import service as svc
from app.modules.drafts.models import DraftPack, DraftStatusHistory

ORDER = 58


def seed(db: Session) -> None:
    ensure_config(db, "drafts.fta_direct_link.enabled", False, owner="Qeonix product owner", status="to_be_confirmed", label="off until the FTA format agreement is in place [OPEN]; the owner files on EmaraTax")
    ensure_config(db, "drafts.still_working_seconds", 30, unit="seconds", owner="UX", status="provisional", label="demo default; tuned for production")
    ensure_config(db, "drafts.reason_rubric", svc.REASON_RUBRIC_DEFAULT, owner="Qeonix product owner", status="to_be_confirmed", label="six options plus free text, bilingual; options not enumerated in source")
    ensure_config(db, "drafts.retention_classes", svc.RETENTION_CLASSES_DEFAULT, owner="Qeonix product owner", status="to_be_confirmed", label="provisional; no year count; anything tied to an approved submission under legal hold")
    ensure_config(db, "drafts.specialist_status.enabled", False, owner="Qeonix product owner", status="to_be_confirmed", label="Increment C: specialist and licensed-auditor statuses off until service models are agreed")
    ensure_config(db, "drafts.export.formats", ["json"], owner="Tech Lead", status="to_be_confirmed", label="Open (Q435): export formats and logging")
    ensure_config(db, "drafts.out_of_date.detection", "data version hash on read", owner="Tech Lead", status="to_be_confirmed", label="Open (Q434): triggers and detection delay")
    ensure_config(db, "drafts.date_format", "Gregorian, e.g. 14 Mar 2027", owner="UX", status="confirmed", label="settled")


class _Actor:
    def __init__(self, uuid: str, name: str, role: str, company_id: str, functions: list[str]):
        from app.modules.companies.models import CompanyRole

        self.identity_uuid, self.display_name, self.session_id, self.actor_key, self.staff_roles = uuid, name, "demo-seed-session", None, []
        self._roles = [CompanyRole(identity_uuid=uuid, company_id=company_id, role=role, functions=functions)]

    def roles_for(self, company_id: str):
        return self._roles

    def primary_role(self):
        return self._roles[0].role


def seed_demo(db: Session) -> None:
    if db.scalar(select(DraftPack).where(DraftPack.company_id == CO_ALNOOR).limit(1)) is not None:
        return
    omar = _Actor(PERSONA_UUIDS["omar"], "Omar Haddad", "delegate", CO_ALNOOR, ["bookkeeping", "tax_preparation"])
    # VAT Q2 2026: prepared by the delegate and sent for owner review ('ready for owner review').
    vat = svc.create_pack(db, CO_ALNOOR, "vat", "2026-Q2", actor=omar, run_calculation=False, is_demo=True)
    svc.transition(db, vat, "prepared", omar)
    svc.transition(db, vat, "under_review", omar)
    # CT FY2025: in preparation (not reviewed) with the SBR indicator 'may be eligible'.
    svc.create_pack(db, CO_ALNOOR, "ct", "FY2025", actor=omar, run_calculation=False, is_demo=True)
    db.flush()
    _ = DraftStatusHistory
