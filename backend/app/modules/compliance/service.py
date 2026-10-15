"""Compliance agent for licence-linked requirements (E3-S3).

Confirmed binding rules in Phase 1: valid Ejari, licence expiry and Dubai Chambers membership. Every other
licence-linked requirement is a typed 'to be confirmed by DET' rule: no deadline or penalty promise, never a legal
obligation, outside every total. Statuses: Overdue > At risk > Due soon > Met; 'Cannot confirm' only when no value
exists. Owner-declared values carry a permanent label and are never 'Met' (never a 'valid' mark on unverified
items). Days left are plain calendar days to the stated date (no roll). Documents prepared in advance are
AI-prepared drafts; approving one is an internal status change plus a registry record - nothing goes to DET/Ejari.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import Forbidden, NotFound, ValidationFailed
from app.core.time import dubai_today, utcnow
from app.modules.audit.service import record_event
from app.modules.companies.models import CompanyRole
from app.modules.compliance.models import (
    STATUS_PRECEDENCE,
    ApprovalRecord,
    ComplianceDraft,
    ConflictLog,
    Evaluation,
    RequirementRule,
    ReviewRecord,
    SourceValue,
)
from app.modules.compliance.strings import bi
from app.modules.config.service import get_config
from app.modules.licences.models import Licence

LEAD_TIMES_DEFAULT = {"licence_expiry": {"due_soon": 60, "at_risk": 30}, "ejari_expiry": {"due_soon": 60, "at_risk": 30}, "global_default": {"due_soon": 45, "at_risk": 21}}
MATERIAL_FIELDS_V1 = {
    "renewal_checklist": ["licence_number", "items.add", "items.remove", "items.*.due_date", "items.*.status", "ejari_number", "ejari_expiry", "fee_amount_fils", "responsible_person"],
    "document_pack": ["documents.add", "documents.remove", "documents.*.type", "period", "company_reference", "licence_number", "signatory"],
}
OWNER_LEVEL = ("owner", "remote_owner")
CONFIRMED_TYPES = ("licence_expiry", "ejari_expiry", "chambers_membership")


def lead_times(db: Session) -> dict:
    return get_config(db, "compliance.lead_times", LEAD_TIMES_DEFAULT) or LEAD_TIMES_DEFAULT


def catalogue(db: Session) -> list[RequirementRule]:
    return list(db.scalars(select(RequirementRule).where(RequirementRule.is_current.is_(True)).order_by(RequirementRule.confirmation_status, RequirementRule.code)))


def _thresholds(db: Session, requirement_type: str, rule: RequirementRule | None) -> tuple[int, int, str]:
    lt = lead_times(db)
    t = lt.get(requirement_type) or lt.get("global_default") or LEAD_TIMES_DEFAULT["global_default"]
    due_soon = rule.due_soon_days if rule and rule.due_soon_days is not None else int(t["due_soon"])
    at_risk = rule.at_risk_days if rule and rule.at_risk_days is not None else int(t["at_risk"])
    return due_soon, at_risk, str(get_config(db, "compliance.threshold_version", "lead-times-v1") or "lead-times-v1")


def status_from_days(days: int | None, due_soon: int, at_risk: int) -> str:
    if days is None:
        return "unknown"
    if days < 0:
        return "overdue"
    if days <= at_risk:
        return "at_risk"
    if days <= due_soon:
        return "due_soon"
    return "met"


def worst(*statuses: str) -> str:
    """Precedence Overdue > At risk > Due soon > Met. 'unknown' is never combined with a dated status."""
    dated = [s_ for s_ in statuses if s_ in STATUS_PRECEDENCE]
    if not dated:
        return "unknown"
    return min(dated, key=STATUS_PRECEDENCE.index)


# --- sources ------------------------------------------------------------------------------------------------------


def _licence_sources(lic: Licence, requirement_type: str) -> list[dict]:
    if requirement_type == "licence_expiry":
        return [{"value": lic.expiry_date, "source": "DET", "reference": lic.licence_number, "match_basis": "licence_number", "as_of": lic.last_det_refresh_at}] if lic.expiry_date else []
    if requirement_type == "ejari_expiry":
        if lic.ejari_status == "not_applicable" or lic.ejari_expiry is None:
            return []
        basis = "licence_number+ejari_contract" if lic.ejari_number else ("premises_text" if lic.premises else None)
        src = "Ejari" if lic.ejari_status == "verified" else "owner-declared"
        return [{"value": lic.ejari_expiry, "source": src, "reference": lic.ejari_number, "match_basis": basis, "as_of": lic.last_det_refresh_at}]
    if requirement_type == "chambers_membership":
        if lic.chamber_membership_expiry is None:
            return []
        src = "DET" if lic.chamber_membership_status == "verified" else "owner-declared"
        return [{"value": lic.chamber_membership_expiry, "source": src, "reference": None, "match_basis": "licence_number", "as_of": lic.last_det_refresh_at}]
    return []


def resolve_value(db: Session, company_id: str, lic: Licence, requirement_type: str, *, log: bool = True) -> dict:
    """Field authority: licence expiry from DET, Ejari validity from Ejari. Same field reported differently by two
    sources -> earlier date, 'Sources differ', conflict logged. A source read replaces an owner value (kept in history)."""
    rows = _licence_sources(lic, requirement_type)
    for sv in db.scalars(select(SourceValue).where(SourceValue.company_id == company_id, SourceValue.requirement_type == requirement_type, SourceValue.superseded.is_(False))):
        rows.append({"value": sv.value_date, "source": sv.source_label, "reference": sv.reference, "match_basis": sv.match_basis, "as_of": sv.recorded_at, "declared_at": sv.recorded_at, "id": sv.id})
    verified = [r for r in rows if r["source"] in ("DET", "Ejari") and r["value"]]
    owner = [r for r in rows if r["source"] == "owner-declared" and r["value"]]
    notes: list[dict] = []
    if verified:
        values = sorted({r["value"] for r in verified})
        chosen = min(verified, key=lambda r: r["value"])
        if len(values) > 1:
            notes.append(bi("note.sources_differ"))
            if log:
                db.add(ConflictLog(company_id=company_id, requirement_type=requirement_type, kind="sources_differ", values=[{"source": r["source"], "value": r["value"].isoformat()} for r in verified], chosen=chosen["value"].isoformat()))
        if owner and any(o["value"] != chosen["value"] for o in owner):
            notes.append(bi("note.source_differs_entry"))
            if log:
                db.add(ConflictLog(company_id=company_id, requirement_type=requirement_type, kind="source_differs_from_entry", values=[{"source": r["source"], "value": r["value"].isoformat()} for r in verified + owner], chosen=chosen["value"].isoformat()))
        evidence = "verified"
        if chosen.get("match_basis") == "premises_text":  # weak premises-text match: 'needs review', never 'valid'
            evidence = "unconfirmed"
            notes.append(bi("note.needs_review"))
        return {"value": chosen["value"], "source": chosen["source"], "evidence": evidence, "match_basis": chosen.get("match_basis"), "as_of": chosen.get("as_of"), "notes": notes, "history": [{"source": o["source"], "value": o["value"].isoformat()} for o in owner]}
    if owner:
        chosen = max(owner, key=lambda r: r.get("declared_at") or utcnow())
        notes.append(bi("note.declared_dates"))
        return {"value": chosen["value"], "source": "owner-declared", "evidence": "owner_declared", "match_basis": chosen.get("match_basis"), "as_of": chosen.get("as_of"), "declared_at": chosen.get("declared_at"), "notes": notes, "history": []}
    return {"value": None, "source": None, "evidence": "unconfirmed", "match_basis": None, "as_of": None, "notes": notes, "history": []}


def declare_value(db: Session, principal, company_id: str, requirement_type: str, value_date: date, *, reference: str | None = None, evidence_ref: str | None = None) -> SourceValue:
    if requirement_type not in CONFIRMED_TYPES:
        raise ValidationFailed("only the confirmed requirements take a declared date", reason_code="REQUIREMENT_INVALID")
    lic = db.scalar(select(Licence).where(Licence.company_id == company_id))
    sv = SourceValue(company_id=company_id, licence_number=lic.licence_number if lic else None, requirement_type=requirement_type, value_date=value_date, reference=reference, source_label="owner-declared", match_basis="owner_entry", declared_by_uuid=principal.identity_uuid, declared_by_role=principal.primary_role(), evidence_ref=evidence_ref)
    db.add(sv)
    db.flush()
    record_event(db, event_type="COMPLIANCE_VALUE_DECLARED", category="data_access", actor_key=principal.actor_key, actor_role=principal.primary_role(), company_id=company_id, subject_type="requirement", subject_id=requirement_type, details={"source_label": "owner-declared", "has_evidence": bool(evidence_ref)})
    return sv


def record_source_read(db: Session, company_id: str, requirement_type: str, value_date: date, *, source_label: str, reference: str | None = None, match_basis: str | None = None) -> SourceValue:
    """Adapter / manual entry of a source value (DET or Ejari). Replaces owner values for status; history kept;
    reminders rebuilt."""
    if source_label not in ("DET", "Ejari"):
        raise ValidationFailed("source must be DET or Ejari", reason_code="SOURCE_INVALID")
    lic = db.scalar(select(Licence).where(Licence.company_id == company_id))
    sv = SourceValue(company_id=company_id, licence_number=lic.licence_number if lic else None, requirement_type=requirement_type, value_date=value_date, reference=reference, source_label=source_label, match_basis=match_basis or "licence_number")
    db.add(sv)
    db.flush()
    record_event(db, event_type="COMPLIANCE_SOURCE_READ", category="data_access", company_id=company_id, subject_type="requirement", subject_id=requirement_type, details={"source_label": source_label, "match_basis": sv.match_basis})
    try:
        from app.modules.reminders.service import schedule_for_company

        schedule_for_company(db, company_id)
    except Exception:  # reminders unavailable: never blocks the evaluation
        pass
    return sv


# --- evaluation ---------------------------------------------------------------------------------------------------


def _holiday_note(db: Session, today: date, due: date | None) -> dict | None:
    if due is None or due < today:
        return None
    try:
        from app.modules.deadlines import service as dl

        jur = dl.calendar_for_authority(db, "DET")
        if dl.calendar_state(db, jur, due.year, today)["state"] != "current":
            return {"kind": "unavailable", "text": bi("note.holiday_unavailable")}
        hols = {d: h for d, h in dl.holidays(db, jur, today, due).items() if h.status == "confirmed" and d.weekday() not in (5, 6)}
        if due in hols:
            h = hols[due]
            return {"kind": "on_date", "source": h.source_reference, "as_of": h.loaded_at.date().isoformat(), "text": {"en": bi("note.holiday_on_date", date=due.isoformat(), holiday=h.name_en)["en"], "ar": bi("note.holiday_on_date", date=due.isoformat(), holiday=h.name_ar)["ar"]}}
        if hols:
            first = min(hols)
            h = hols[first]
            m = (due - today).days
            n = sum(1 for i in range(m) if dl.is_working_day(db, today + timedelta(days=i + 1), jur))
            return {"kind": "in_range", "source": h.source_reference, "as_of": h.loaded_at.date().isoformat(), "text": {"en": bi("note.holiday_working_days", holiday=h.name_en, date=first.isoformat(), n=str(n), m=str(m))["en"], "ar": bi("note.holiday_working_days", holiday=h.name_ar, date=first.isoformat(), n=str(n), m=str(m))["ar"]}, "short": bi("note.includes_holiday", date=first.isoformat())}
    except Exception:
        return {"kind": "unavailable", "text": bi("note.holiday_unavailable")}
    return None


def _chip(status: str, evidence: str) -> str:
    if status == "met" and evidence != "verified":
        return "owner_declared"  # never a 'Met'/'valid' mark on an unverified value
    return status


def _reminder_control(db: Session, principal, company_id: str, status: str, evidence: str, requirement_type: str) -> dict:
    if principal is None:
        return {"state": "hidden"}
    if status == "met" and evidence == "verified":
        return {"state": "hidden"}
    roles = [r.role for r in principal.roles_for(company_id)]
    if "delegate" in roles and not any(r in OWNER_LEVEL for r in roles):
        try:
            from app.modules.reminders.service import get_preference

            if not get_preference(db, company_id, principal.identity_uuid).delegate_reminder_right:
                return {"state": "disabled", "reason": {"en": "Only the owner or a delegate with reminder rights can set reminders. Ask the owner.", "ar": "يمكن للمالك أو للمفوَّض الذي يملك صلاحية التذكير فقط ضبط التذكيرات. اسأل المالك."}}
        except ImportError:  # pragma: no cover
            return {"state": "unavailable", "ics_fallback": True}
    try:
        from app.modules.reminders.models import ReminderRequest

        req = db.scalar(select(ReminderRequest).where(ReminderRequest.company_id == company_id, ReminderRequest.requirement_type == requirement_type, ReminderRequest.requested_by_uuid == principal.identity_uuid, ReminderRequest.status == "scheduled").limit(1))
    except ImportError:  # pragma: no cover
        return {"state": "unavailable", "ics_fallback": True}
    if req is not None:
        return {"state": "scheduled", "request_id": req.id, "reminder_date": req.reminder_date.isoformat(), "channel": req.channel}
    if evidence == "owner_declared" or status == "unknown":
        return {"state": "text_link"}
    return {"state": "available", "default_lead_days": int(get_config(db, "compliance.reminder.default_lead_days", 7) or 7), "overdue_repeat_days": int(get_config(db, "compliance.reminder.overdue_repeat_days", 3) or 3)}


def evaluate(db: Session, company_id: str, *, principal=None, today: date | None = None, persist: bool = True) -> dict:
    """Daily evaluation of the confirmed requirements plus typed 'to be confirmed' rows."""
    today = today or dubai_today()
    lic = db.scalar(select(Licence).where(Licence.company_id == company_id, Licence.scope != "out_of_scope"))
    rules = {r.requirement_type: r for r in catalogue(db) if r.confirmation_status == "confirmed"}
    if lic is None:
        return {"company_id": company_id, "empty": True, "empty_message": bi("empty.no_licence"), "cards": [], "to_be_confirmed": [], "summary": None, "banners": [], "all_clear": False}
    cards = []
    values: dict[str, dict] = {}
    for rtype in CONFIRMED_TYPES:
        values[rtype] = resolve_value(db, company_id, lic, rtype, log=persist)
    lic_expiry = values["licence_expiry"]["value"]
    for rtype in CONFIRMED_TYPES:
        v = values[rtype]
        rule = rules.get(rtype)
        due_soon, at_risk, thr_ver = _thresholds(db, rtype, rule)
        days = (v["value"] - today).days if v["value"] else None
        status = status_from_days(days, due_soon, at_risk)
        gap = None
        if rtype == "ejari_expiry" and v["value"] and lic_expiry:
            dep = int(get_config(db, "compliance.ejari_dependency_days", 30) or 30)
            if v["value"] < lic_expiry or (v["value"] - lic_expiry).days <= dep:
                gap = (lic_expiry - v["value"]).days
                status = worst(status, "at_risk")
        if v["evidence"] == "unconfirmed" and v["value"] is not None and status == "met":
            status = "unknown"  # weak match: never shown as met
        try:
            from app.modules.deadlines.service import recommended_submit_by

            renew_by = recommended_submit_by(db, v["value"], "DUBAI-GOV") if v["value"] else None
        except Exception:
            renew_by = None
        as_of = v.get("as_of")
        if v["source"] == "Ejari":
            source_line = bi("source.ejari_det", date=as_of.date().isoformat() if as_of else "-")
        elif v["source"] == "DET":
            source_line = bi("source.det", date=as_of.date().isoformat() if as_of else "-")
        elif v["source"] == "owner-declared":
            source_line = bi("source.owner", date=(v.get("declared_at") or as_of or utcnow()).date().isoformat())
        else:
            source_line = None
        card = {
            "requirement_type": rtype,
            "code": rule.code if rule else rtype,
            "title": bi(f"req.{rtype}"),
            "status": status,
            "chip": _chip(status, v["evidence"]),
            "chip_label": bi(f"chip.{_chip(status, v['evidence'])}"),
            "evidence": v["evidence"],
            "source_label": v["source"],
            "source_line": source_line,
            "due_date": v["value"].isoformat() if v["value"] else None,
            "days_left": days,
            "recommended_renew_by": renew_by.isoformat() if renew_by else None,
            "gap_days": gap,
            "match_basis": v["match_basis"],
            "notes": v["notes"],
            "history": v["history"],
            "rule_version": rule.version if rule else None,
            "threshold_version": thr_ver,
            "instrument": rule.instrument if rule else None,
            "last_confirmed": rule.last_confirmed.isoformat() if rule and rule.last_confirmed else None,
            "agent_note": bi("note.checked_today", version=rule.version if rule else "-"),
            "holiday_note": _holiday_note(db, today, v["value"]),
            "reminder_control": _reminder_control(db, principal, company_id, status, v["evidence"], rtype),
            "check_icon": status == "met" and v["evidence"] == "verified",
        }
        cards.append(card)
        if persist and not db.scalar(select(Evaluation).where(Evaluation.company_id == company_id, Evaluation.requirement_type == rtype, Evaluation.evaluated_on == today).limit(1)):
            db.add(Evaluation(company_id=company_id, requirement_type=rtype, code=card["code"], status=status, evidence=v["evidence"], due_date=v["value"], source_label=v["source"], as_of_date=as_of, gap_days=gap, rule_version=card["rule_version"], threshold_version=thr_ver, match_basis=v["match_basis"], notes=[n["en"] for n in v["notes"]], evaluated_on=today))
    tbc = [{"code": r.code, "title": {"en": r.title_en, "ar": r.title_ar}, "status": "to_be_confirmed", "chip_label": bi("chip.to_be_confirmed"), "note": bi("note.not_obligation"), "approving_authority": r.approving_authority, "source_reference": r.source_reference, "last_confirmed": r.last_confirmed.isoformat() if r.last_confirmed else None, "activity_code": r.activity_code} for r in catalogue(db) if r.confirmation_status != "confirmed" and (r.activity_code is None or r.activity_code in (lic.activities or []))]
    banners = []
    if lic.status == "expired":
        banners.append({"kind": "licence_expired", "text": bi("banner.licence_expired", date=lic.expiry_date.isoformat() if lic.expiry_date else "-"), "page_level": True})
    elif lic.status == "suspended":
        banners.append({"kind": "licence_suspended", "text": bi("banner.licence_suspended"), "page_level": True})
    ej = next(c for c in cards if c["requirement_type"] == "ejari_expiry")
    if ej["status"] == "overdue":
        banners.append({"kind": "ejari_lapsed", "text": bi("banner.ejari_lapsed", date=ej["due_date"]), "next_action": "renew_ejari"})
    elif ej["status"] == "at_risk" and ej["gap_days"] is not None and ej["gap_days"] > 0:
        banners.append({"kind": "ejari_at_risk", "text": bi("banner.ejari_at_risk", n=str(ej["gap_days"])), "short": bi("banner.ejari_at_risk_short", n=str(ej["gap_days"])), "next_action": "renew_ejari", "reminder_control": ej["reminder_control"]})
    met = sum(1 for c in cards if c["status"] == "met" and c["evidence"] == "verified")
    unverified = sum(1 for c in cards if c["evidence"] == "owner_declared")
    attention = sum(1 for c in cards if c["status"] in ("due_soon", "at_risk", "overdue"))
    unknown = sum(1 for c in cards if c["status"] == "unknown")
    summary = {"met": met, "unverified": unverified, "attention": attention, "cannot_confirm": unknown, "text": bi("summary.counts", met=str(met), unverified=str(unverified), attention=str(attention), unknown=str(unknown)), "to_be_confirmed_excluded": len(tbc)}
    overall = worst(*[c["status"] for c in cards]) if any(c["status"] in STATUS_PRECEDENCE for c in cards) else "unknown"
    if persist:
        db.flush()
    return {"company_id": company_id, "empty": False, "licence_number": lic.licence_number, "licence_status": lic.status, "cards": cards, "to_be_confirmed": tbc, "summary": summary, "banners": banners,
            "overall_status": overall, "all_clear": met == len(cards), "all_clear_label": bi("summary.all_clear") if met == len(cards) else None, "checked_on": today.isoformat(), "drafts": [draft_dict(d) for d in drafts_for(db, company_id)],
            "last_refreshed_at": lic.last_det_refresh_at.isoformat() if lic.last_det_refresh_at else None}


# --- documents prepared in advance (AI-prepared drafts) -----------------------------------------------------------


def drafts_for(db: Session, company_id: str) -> list[ComplianceDraft]:
    return list(db.scalars(select(ComplianceDraft).where(ComplianceDraft.company_id == company_id, ComplianceDraft.review_status != "discarded").order_by(ComplianceDraft.created_at.desc())))


def _data_version(content: dict) -> str:
    return hashlib.sha256(json.dumps(content, sort_keys=True, default=str).encode()).hexdigest()[:16]


def _k28_check(content: dict) -> list[str]:
    """Arabic and English generated together; key fields must match (normalised digits/whitespace)."""
    mism = []
    en, ar = content.get("en", {}), content.get("ar", {})
    for k in ("licence_number", "item_keys", "dates"):
        if str(en.get(k)) != str(ar.get(k)):
            mism.append(k)
    return mism


def prepare_pack(db: Session, principal, company_id: str, output_type: str = "renewal_checklist") -> ComplianceDraft:
    if output_type not in ("renewal_checklist", "document_pack"):
        raise ValidationFailed("output type not recognised", reason_code="OUTPUT_TYPE_INVALID")
    ev = evaluate(db, company_id, principal=principal, persist=False)
    if ev["empty"]:
        raise ValidationFailed("no licence record linked", reason_code="NO_LICENCE")
    owner_role = db.scalar(select(CompanyRole).where(CompanyRole.company_id == company_id, CompanyRole.role.in_(OWNER_LEVEL), CompanyRole.status == "active").limit(1))
    responsible = "owner" if owner_role else None
    items = [{"key": c["requirement_type"], "due_date": c["due_date"], "status": c["status"], "evidence": c["evidence"]} for c in ev["cards"]]
    docs = ["licence_copy", "ejari_contract", "chambers_certificate", "passport_ids"]

    def lang_block(lang: str) -> dict:
        from app.modules.compliance.strings import s as _s

        return {
            "title": _s(f"draft.title.{output_type}", lang),
            "licence_number": ev["licence_number"],
            "item_keys": [i["key"] for i in items],
            "dates": [i["due_date"] for i in items],
            "items": [{"key": i["key"], "label": _s(f"req.{i['key']}", lang), "due_date": i["due_date"], "status": _s(f"chip.{_chip(i['status'], i['evidence'])}", lang)} for i in items],
            "documents": [{"key": d, "label": _s(f"doc.{d}", lang)} for d in docs] if output_type == "document_pack" else [],
            "to_be_confirmed": [t["title"][lang] + " — " + _s("chip.to_be_confirmed", lang) for t in ev["to_be_confirmed"]],
            "footer": _s("draft.footer", lang),
        }

    content = {"en": lang_block("en"), "ar": lang_block("ar"), "fields": {"licence_number": ev["licence_number"], "items": items, "responsible_person": responsible, "documents": docs if output_type == "document_pack" else []}}
    mism = _k28_check(content)
    draft = ComplianceDraft(company_id=company_id, output_type=output_type, content=content, original_content=json.loads(json.dumps(content)), review_status="draft_not_reviewed", k28_ok=not mism, k28_mismatched=mism, released=not mism, created_by_role=principal.primary_role() if principal else "agent")
    db.add(draft)
    db.flush()
    record_event(db, event_type="COMPLIANCE_PACK_PREPARED", category="agent", actor_key=getattr(principal, "actor_key", None), actor_role=principal.primary_role() if principal else "agent", company_id=company_id, subject_type="compliance_draft", subject_id=draft.id, details={"output_type": output_type, "k28_ok": not mism, "checklist_generated": True})
    return draft


def _get_draft(db: Session, company_id: str, draft_id: str) -> ComplianceDraft:
    d = db.get(ComplianceDraft, draft_id)
    if d is None or d.company_id != company_id:
        raise NotFound("draft not found", reason_code="NOT_FOUND")
    return d


def classify_change(output_type: str, field: str) -> bool:
    """material_fields_v1: True when the changed field is material. Unknown output type -> every data-field change
    is material (fail closed). Wording, ordering, formatting and translation phrasing are non-material."""
    if field.startswith(("wording", "order", "format", "translation", "reminder_text")):
        return False
    fields = MATERIAL_FIELDS_V1.get(output_type)
    if fields is None:
        return True
    for f in fields:
        if f == field:
            return True
        if "*" in f:
            pre, post = f.split("*", 1)
            if field.startswith(pre) and field.endswith(post):
                return True
    return False


def edit_draft(db: Session, principal, company_id: str, draft_id: str, changes: list[dict]) -> ComplianceDraft:
    d = _get_draft(db, company_id, draft_id)
    if d.review_status in ("approved_by_owner", "discarded"):
        raise ValidationFailed("this draft can no longer be edited", reason_code="DRAFT_CLOSED")
    content = json.loads(json.dumps(d.content))
    changed = list(d.changed_fields or [])
    for ch in changes:
        field = str(ch.get("field", ""))
        if not field:
            raise ValidationFailed("each change names a field", reason_code="FIELD_REQUIRED")
        content.setdefault("edits", []).append({"field": field, "new": ch.get("new")})
        changed.append({"field": field, "material": classify_change(d.output_type, field)})
    d.content, d.changed_fields, d.version = content, changed, d.version + 1
    d.review_status, d.reviewed_by_role, d.reviewed_at = "draft_not_reviewed", None, None  # any edit after review resets
    d.updated_at = utcnow()
    db.flush()
    record_event(db, event_type="COMPLIANCE_PACK_EDITED", category="agent", actor_key=principal.actor_key, actor_role=principal.primary_role(), company_id=company_id, subject_type="compliance_draft", subject_id=d.id, details={"fields": [c["field"] for c in changes]})
    return d


def mark_reviewed(db: Session, principal, company_id: str, draft_id: str) -> ComplianceDraft:
    d = _get_draft(db, company_id, draft_id)
    role = "owner" if any(r.role in OWNER_LEVEL for r in principal.roles_for(company_id)) else "delegate"
    d.review_status, d.reviewed_by_role, d.reviewed_by_name, d.reviewed_at = "reviewed", role, principal.display_name, utcnow()
    db.flush()
    record_event(db, event_type="COMPLIANCE_PACK_REVIEWED", category="sign_off", actor_key=principal.actor_key, actor_role=role, company_id=company_id, subject_type="compliance_draft", subject_id=d.id)
    return d


def approve_draft(db: Session, principal, company_id: str, draft_id: str) -> dict:
    """Owner-only (a delegate needs a recorded delegation of approval rights, switched off in the pilot).
    Status change + one approval-registry record + K15 review record. No external write."""
    if not any(r.role == "owner" for r in principal.roles_for(company_id)):
        record_event(db, event_type="ACCESS_REFUSED", category="approval", outcome="refused", reason_code="APPROVAL_NOT_PERMITTED", actor_key=principal.actor_key, actor_role=principal.primary_role(), company_id=company_id, subject_type="compliance_draft", subject_id=draft_id)
        raise Forbidden("only the owner can approve", reason_code="APPROVAL_NOT_PERMITTED")
    d = _get_draft(db, company_id, draft_id)
    if not d.released:
        raise ValidationFailed("this draft failed the bilingual check and is not released", reason_code="K28_NOT_RELEASED")
    material = [c for c in (d.changed_fields or []) if c.get("material")]
    if not d.changed_fields:
        outcome, cls = "accepted", "accepted_without_material_change"
    elif material:
        outcome, cls = "accepted_edited", "accepted_with_material_change"
    else:
        outcome, cls = "accepted_edited", "accepted_with_non_material_change"
    rr = ReviewRecord(output_id=d.id, output_type=d.output_type, output_version_original=1, output_version_final=d.version, reviewer_key=principal.actor_key, reviewer_role="owner", outcome=outcome, changed_fields=d.changed_fields or [], classification=cls)
    db.add(rr)
    ar = ApprovalRecord(draft_id=d.id, company_id=company_id, approver_key=principal.actor_key, approver_role="owner", data_version=_data_version(d.content), external_write=False)
    db.add(ar)
    d.review_status, d.approved_by_name, d.approved_at = "approved_by_owner", principal.display_name, utcnow()
    db.flush()
    record_event(db, event_type="COMPLIANCE_PACK_APPROVED", category="approval", actor_key=principal.actor_key, actor_role="owner", company_id=company_id, subject_type="compliance_draft", subject_id=d.id, details={"k15": cls, "external_write": False, "registry_record": ar.id})
    return {"draft": draft_dict(d), "k15": {"outcome": outcome, "classification": cls}, "approval_record": {"id": ar.id, "action": ar.action, "data_version": ar.data_version, "external_write": False}}


def discard_draft(db: Session, principal, company_id: str, draft_id: str) -> ComplianceDraft:
    d = _get_draft(db, company_id, draft_id)
    d.review_status = "discarded"
    db.add(ReviewRecord(output_id=d.id, output_type=d.output_type, output_version_original=1, output_version_final=d.version, reviewer_key=principal.actor_key, reviewer_role=principal.primary_role(), outcome="rejected", changed_fields=d.changed_fields or [], classification=None))
    db.flush()
    return d


def draft_dict(d: ComplianceDraft) -> dict:
    from app.modules.compliance.strings import bi as _bi

    status_label = _bi(f"draft.status.{d.review_status}", role=d.reviewed_by_role or "-")
    label = _bi("draft.ai_not_reviewed") if d.review_status == "draft_not_reviewed" else (_bi("draft.reviewed_by_you", date=d.reviewed_at.date().isoformat()) if d.review_status == "reviewed" and d.reviewed_by_role == "owner" and d.reviewed_at else status_label)
    footer = _bi("draft.footer_approved", date=d.approved_at.date().isoformat()) if d.review_status == "approved_by_owner" and d.approved_at else _bi("draft.footer")
    return {"id": d.id, "output_type": d.output_type, "version": d.version, "ai_prepared": True, "review_status": d.review_status, "status_label": status_label, "ai_label": label, "footer": footer,
            "content": {"en": d.content.get("en"), "ar": d.content.get("ar")}, "k28_ok": d.k28_ok, "released": d.released, "approved_by": d.approved_by_name, "approved_at": d.approved_at.isoformat() if d.approved_at else None, "created_at": d.created_at.isoformat(), "is_demo": d.is_demo}


def pack_readiness(db: Session, company_id: str, obligation_type: str) -> dict | None:
    """Readiness of licence-linked obligations from the latest renewal checklist pack (used by SC4)."""
    d = db.scalar(select(ComplianceDraft).where(ComplianceDraft.company_id == company_id, ComplianceDraft.output_type == "renewal_checklist", ComplianceDraft.review_status != "discarded").order_by(ComplianceDraft.created_at.desc()).limit(1))
    if d is None or obligation_type not in ("licence_renewal", "ejari_renewal"):
        return None
    if d.review_status == "approved_by_owner":
        return {"readiness": "owner_approved", "detail": "owner_approved", "draft_id": d.id}
    return {"readiness": "draft_ready", "detail": "draft_ready" if d.review_status == "reviewed" else "in_preparation", "draft_id": d.id}


def k15_summary(db: Session) -> dict:
    rows = list(db.scalars(select(ReviewRecord)))
    n = int(get_config(db, "compliance.k15.min_group_size", 10) or 10)
    reviewed = [r for r in rows]
    without = sum(1 for r in reviewed if r.classification == "accepted_without_material_change")
    never_reviewed = sum(1 for d in db.scalars(select(ComplianceDraft)) if d.review_status == "draft_not_reviewed")
    if len(reviewed) < n:
        return {"suppressed": True, "reviewed": None, "never_reviewed": never_reviewed, "note": "Fewer than 10 reviewed outputs"}
    return {"suppressed": False, "reviewed": len(reviewed), "accepted_without_material_change": without, "rate": round(without / len(reviewed), 3), "never_reviewed": never_reviewed}


def det_aggregate(db: Session) -> dict:
    """DET admin tile: aggregated status counts only, with minimum group size suppression."""
    counts: dict[str, int] = {}
    today = dubai_today()
    for e in db.scalars(select(Evaluation).where(Evaluation.evaluated_on == today)):
        counts[e.status] = counts.get(e.status, 0) + 1
    n = int(get_config(db, "cohorts.suppression_n", 10) or 10)
    return {"counts": {k: (v if v >= n else None) for k, v in counts.items()}, "min_group_size": n}

