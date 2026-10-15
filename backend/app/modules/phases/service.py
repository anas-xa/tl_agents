"""Phase map, gate register, demo-done rule, integration checklist and switch guard (E1-S7, E1-S8)."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.core.errors import Conflict, NotFound, SwitchedOff, ValidationFailed
from app.core.time import utcnow
from app.modules.audit.service import record_event
from app.modules.config.service import get_config
from app.modules.phases.models import (
    GATE_REGISTER_STATUSES,
    ROW_STATUSES,
    DemoRecord,
    GateRegisterRow,
    Increment,
    IntegrationChecklistRow,
    IntegrationSwitch,
)
from app.modules.phases.strings import both, s

GATE_PANEL_MAP = {"not_yet_confirmed": "not_met", "evidence_received": "in_progress", "open": "met", "closed": "not_met", "fallback_active": "not_met", "not_needed_in_pilot": "not_needed_in_pilot"}
REQUIRED_ITEM_FIELDS = ("owner_name", "evidence_reference", "evidence_date", "approver_identity")


# --- phase map -------------------------------------------------------------------------------------


def increments(db: Session) -> list[Increment]:
    return list(db.scalars(select(Increment).order_by(Increment.order)))


def current_gates(db: Session, increment: str | None = None) -> list[GateRegisterRow]:
    stmt = select(GateRegisterRow).where(GateRegisterRow.is_current.is_(True)).order_by(GateRegisterRow.increment, GateRegisterRow.gate_id)
    if increment:
        stmt = stmt.where(GateRegisterRow.increment == increment)
    return list(db.scalars(stmt))


def gate_history(db: Session, gate_id: str) -> list[GateRegisterRow]:
    return list(db.scalars(select(GateRegisterRow).where(GateRegisterRow.gate_id == gate_id).order_by(GateRegisterRow.version)))


def demo_record(db: Session, increment: str) -> DemoRecord | None:
    return db.scalar(select(DemoRecord).where(DemoRecord.increment == increment).order_by(desc(DemoRecord.recorded_at)).limit(1))


def increment_status(db: Session, inc: Increment) -> str:
    """Panel rules: Live only when the entry gate is Met or Not needed; Not met + working fallback ->
    Manual path live; otherwise In build / Not started. Demo done only when recorded, never inferred."""
    if demo_record(db, inc.id) is not None:
        return "demo_done"
    gates = [g for g in current_gates(db, inc.id) if g.gate_type == "entry_gate"]
    panel = [GATE_PANEL_MAP.get(g.status, "not_met") for g in gates]
    gate_ok = bool(panel) and all(p in ("met", "not_needed_in_pilot") for p in panel)
    if inc.build_state == "built" and gate_ok:
        return "live"
    if inc.build_state == "built" and inc.manual_fallback_en:
        return "manual_path_live"
    if inc.build_state == "in_build":
        return "in_build"
    return "not_started"


def gate_dict(g: GateRegisterRow) -> dict:
    panel = GATE_PANEL_MAP.get(g.status, "not_met")
    return {"gate_id": g.gate_id, "increment": g.increment, "story_id": g.story_id, "gate_type": g.gate_type, "integration_row": g.integration_row, "description": {"en": g.description_en, "ar": g.description_ar}, "status": g.status, "panel_status": panel, "panel_label": both(f"gate_{panel}"), "fallback_path": g.fallback_path, "required_evidence_list": g.required_evidence_list or [], "evidence_refs": g.evidence_refs or [], "evidence_provided_at": g.evidence_provided_at.isoformat() if g.evidence_provided_at else None, "version": g.version, "effective_from": g.effective_from.isoformat(), "effective_to": g.effective_to.isoformat() if g.effective_to else None, "changed_by": g.changed_by, "change_reason": g.change_reason, "approved_by": g.approved_by, "created_at": g.created_at.isoformat()}


def increment_dict(db: Session, inc: Increment, *, include_gates: bool = True) -> dict:
    status = increment_status(db, inc)
    gates = current_gates(db, inc.id)
    demo = demo_record(db, inc.id)
    last_change = max([g.effective_from for g in gates] + [inc.created_at])
    return {"id": inc.id, "order": inc.order, "name": {"en": inc.name_en, "ar": inc.name_ar}, "status": status, "status_label": both(f"inc_{status}"), "entry_gate": {"en": inc.entry_gate_en, "ar": inc.entry_gate_ar}, "manual_fallback": {"en": inc.manual_fallback_en, "ar": inc.manual_fallback_ar}, "demo_outcome": {"en": inc.demo_outcome_en, "ar": inc.demo_outcome_ar}, "stories": inc.stories or [], "manual_path": inc.manual_path or [], "gated": inc.gated or [], "functions": inc.functions or [], "build_state": inc.build_state, "gates": [gate_dict(g) for g in gates] if include_gates else None, "demo_done": {"recorded_at": demo.recorded_at.isoformat(), "recorded_by": demo.recorded_by, "criteria": demo.criteria} if demo else None, "released_at": inc.released_at.isoformat() if inc.released_at else None, "last_changed_at": last_change.isoformat(), "delivery_measures": {"gated_off": sum(1 for st in (inc.stories or []) if st.get("gated")), "stories_total": len(inc.stories or []), "stories_live": sum(1 for st in (inc.stories or []) if not st.get("gated")) if status in ("live", "demo_done", "manual_path_live") else 0}}


def phase_map(db: Session) -> dict:
    incs = increments(db)
    return {"published": bool(incs), "increments": [increment_dict(db, i) for i in incs], "waves": get_config(db, "phases.waves", []), "behind_switches": {k: bool(get_config(db, f"phases.switch.{k}.enabled", False)) for k in ("virtual_lawyer", "remote_owner_agent", "aml_monitoring", "other_emirates", "federal_level")}, "vocabulary": {k: both(k) for k in ("inc_not_started", "inc_in_build", "inc_manual_path_live", "inc_live", "inc_demo_done", "inc_status_unavailable", "gate_not_met", "gate_in_progress", "gate_met", "gate_not_needed_in_pilot", "gate_status_unavailable")}}


def change_gate_status(db: Session, gate_id: str, to_status: str, *, changed_by: str, change_reason: str, evidence_ref: str | None = None, approved_by: str | None = None) -> GateRegisterRow:
    """Append a new version. 'open' needs an evidence reference AND an owner approval; never by demo alone."""
    if to_status not in GATE_REGISTER_STATUSES:
        raise ValidationFailed(f"status must be one of {GATE_REGISTER_STATUSES}")
    current = db.scalar(select(GateRegisterRow).where(GateRegisterRow.gate_id == gate_id, GateRegisterRow.is_current.is_(True)))
    if current is None:
        raise NotFound("gate not found", reason_code="GATE_NOT_FOUND")
    refs = list(current.evidence_refs or [])
    if evidence_ref:
        refs.append(evidence_ref)
    if to_status == "open":
        if not refs:
            raise ValidationFailed("a gate opens only with an evidence reference attached", reason_code="GATE_EVIDENCE_REQUIRED")
        if not approved_by:
            raise ValidationFailed("a gate opens only with the owner's approval", reason_code="GATE_APPROVAL_REQUIRED")
    now = utcnow()
    current.is_current = False
    current.effective_to = now
    row = GateRegisterRow(gate_id=gate_id, increment=current.increment, story_id=current.story_id, gate_type=current.gate_type, integration_row=current.integration_row, description_en=current.description_en, description_ar=current.description_ar, status=to_status, fallback_path=current.fallback_path, required_evidence_list=current.required_evidence_list, evidence_refs=refs, evidence_provided_at=now if evidence_ref else current.evidence_provided_at, version=current.version + 1, effective_from=now, changed_by=changed_by, change_reason=change_reason, approved_by=approved_by if to_status == "open" else current.approved_by)
    db.add(row)
    db.flush()
    record_event(db, event_type="GATE_STATUS_CHANGED", category="config", actor_key=changed_by.split(":")[0], actor_role=changed_by.split(":")[-1] if ":" in changed_by else None, subject_type="gate", subject_id=gate_id, config_version=f"{gate_id}@v{row.version}", details={"gate_id": gate_id, "from_status": current.status, "to_status": to_status, "changed_by": changed_by, "changed_at": now.isoformat(), "evidence_ref": evidence_ref, "version": row.version, "approved_by": approved_by})
    if to_status == "fallback_active":
        record_event(db, event_type="FALLBACK_ACTIVATED", category="config", actor_key=changed_by.split(":")[0], subject_type="gate", subject_id=gate_id, details={"gate_id": gate_id, "fallback_type": current.fallback_path, "activated_at": now.isoformat()})
    return row


def record_register_load_failure(db: Session, reference: str) -> None:
    record_event(db, event_type="GATE_REGISTER_UNREADABLE", category="system", outcome="failed", reason_code="REGISTER_UNREADABLE", details={"reference": reference})


def record_demo_done(db: Session, increment: str, *, recorded_by: str, criteria: dict, notes: str | None = None) -> DemoRecord:
    """Demo-done rule: (a) every story meets its criteria, (b) gated stories shown off with their gate status,
    (c) manual-path flows run end to end in ar and en, (d) audit trail shows the demo actions."""
    inc = db.get(Increment, increment)
    if inc is None:
        raise NotFound("increment not found")
    missing = [k for k in ("a", "b", "c", "d") if not criteria.get(k)]
    if missing:
        raise ValidationFailed(f"demo criteria not met: {', '.join(missing)}", reason_code="DEMO_CRITERIA_NOT_MET", details={"missing": missing})
    gated_off = [{"story_id": st.get("story_id"), "title": st.get("title"), "shown": "off"} for st in (inc.stories or []) if st.get("gated")]
    rec = DemoRecord(increment=increment, criteria=criteria, gated_items_shown_off=gated_off, recorded_by=recorded_by, notes=notes)
    db.add(rec)
    db.flush()
    record_event(db, event_type="DEMO_DONE_RECORDED", category="config", actor_key=recorded_by, subject_type="increment", subject_id=increment, details={"criteria": criteria, "gated_items_shown_off": [g["story_id"] for g in gated_off]})
    return rec


def release_increment(db: Session, increment: str, *, approved_by: str) -> Increment:
    """increment_released only after the owner demo confirmation (a gate never opens by demo alone)."""
    inc = db.get(Increment, increment)
    if inc is None:
        raise NotFound("increment not found")
    if demo_record(db, increment) is None:
        raise Conflict("the increment is released only after the owner confirms the demo", reason_code="DEMO_NOT_CONFIRMED")
    inc.released_at = utcnow()
    inc.released_by = approved_by
    record_event(db, event_type="INCREMENT_RELEASED", category="config", actor_key=approved_by, subject_type="increment", subject_id=increment, details={"increment": increment, "released_at": inc.released_at.isoformat(), "approved_by": approved_by})
    return inc


# --- integration checklist register ----------------------------------------------------------------


def current_rows(db: Session) -> list[IntegrationChecklistRow]:
    return list(db.scalars(select(IntegrationChecklistRow).where(IntegrationChecklistRow.is_current.is_(True)).order_by(IntegrationChecklistRow.phase, IntegrationChecklistRow.row_id)))


def current_row(db: Session, row_id: str) -> IntegrationChecklistRow:
    row = db.scalar(select(IntegrationChecklistRow).where(IntegrationChecklistRow.row_id == row_id, IntegrationChecklistRow.is_current.is_(True)))
    if row is None:
        raise NotFound("integration row not found", reason_code="INTEGRATION_ROW_NOT_FOUND")
    return row


def row_history(db: Session, row_id: str) -> list[IntegrationChecklistRow]:
    return list(db.scalars(select(IntegrationChecklistRow).where(IntegrationChecklistRow.row_id == row_id).order_by(IntegrationChecklistRow.version)))


def item_complete(item: dict) -> bool:
    return all(item.get(f) for f in REQUIRED_ITEM_FIELDS)


def item_missing_fields(item: dict) -> list[str]:
    return [f for f in REQUIRED_ITEM_FIELDS if not item.get(f)]


def row_progress(row: IntegrationChecklistRow) -> dict:
    items = row.items or []
    n = sum(1 for i in items if item_complete(i))
    m = len(items)
    word = "Not started" if n == 0 else ("Complete" if n == m else "Incomplete")
    return {"n": n, "m": m, "label": both("n_of_m", n=n, m=m), "word": word}


def switch_for(db: Session, row: IntegrationChecklistRow) -> IntegrationSwitch:
    sw = db.get(IntegrationSwitch, row.switch_key)
    if sw is None:
        sw = IntegrationSwitch(switch_key=row.switch_key, row_id=row.row_id, state="OFF", history=[])
        db.add(sw)
        db.flush()
    return sw


def row_dict(db: Session, row: IntegrationChecklistRow, *, evidence_detail: bool = True) -> dict:
    sw = switch_for(db, row)
    items = row.items or []
    out = {"row_id": row.row_id, "integration": row.integration, "name": {"en": row.name_en, "ar": row.name_ar}, "switch_key": row.switch_key, "switch_state": sw.state, "bank_code": row.bank_code, "phase": row.phase, "fallback_path": row.fallback_path, "status": row.status, "mock": row.mock, "progress": row_progress(row), "version": row.version, "changed_by": row.changed_by, "change_reason": row.change_reason, "updated_at": row.updated_at.isoformat(), "evidence_expires_at": row.evidence_expires_at.isoformat() if row.evidence_expires_at else None, "live": row.status == "confirmed_live" and sw.state == "ON"}
    if evidence_detail:
        out["items"] = [{**i, "complete": item_complete(i), "missing": item_missing_fields(i)} for i in items]
        out["switch_history"] = sw.history or []
    else:
        out["items"] = [{"item_id": i.get("item_id"), "item_type": i.get("item_type"), "complete": item_complete(i)} for i in items]
    return out


def _new_version(db: Session, row: IntegrationChecklistRow, *, status: str | None = None, items: list | None = None, changed_by: str, change_reason: str, evidence_expires_at: datetime | None = None) -> IntegrationChecklistRow:
    now = utcnow()
    row.is_current = False
    nxt = IntegrationChecklistRow(row_id=row.row_id, integration=row.integration, name_en=row.name_en, name_ar=row.name_ar, switch_key=row.switch_key, bank_code=row.bank_code, phase=row.phase, fallback_path=row.fallback_path, status=status or row.status, items=items if items is not None else row.items, evidence_expires_at=evidence_expires_at if evidence_expires_at is not None else row.evidence_expires_at, mock=row.mock, version=row.version + 1, previous_version_id=row.id, changed_by=changed_by, change_reason=change_reason, updated_at=now)
    db.add(nxt)
    db.flush()
    record_event(db, event_type="INTEGRATION_ROW_VERSIONED", category="config", actor_key=changed_by.split(":")[0], subject_type="integration_row", subject_id=row.row_id, config_version=f"{row.row_id}@v{nxt.version}", details={"from_status": row.status, "to_status": nxt.status, "reason": change_reason, "version": nxt.version})
    return nxt


def complete_item(db: Session, row_id: str, item_id: str, *, owner_name: str | None, owner_role: str | None, evidence_reference: str | None, evidence_date: str | None, approver_identity: str | None, evidence_expires_at: str | None = None, changed_by: str) -> IntegrationChecklistRow:
    """Item complete only when owner, evidence reference, date and approver are all present."""
    row = current_row(db, row_id)
    items = [dict(i) for i in (row.items or [])]
    target = next((i for i in items if i.get("item_id") == item_id), None)
    if target is None:
        raise NotFound("checklist item not found")
    target.update({"owner_name": owner_name, "owner_role": owner_role, "evidence_reference": evidence_reference, "evidence_date": evidence_date, "approver_identity": approver_identity, "approved_at": utcnow().isoformat() if approver_identity else None, "evidence_expires_at": evidence_expires_at})
    missing = item_missing_fields(target)
    if missing:
        raise ValidationFailed(f"Missing: {missing[0]}", reason_code="ITEM_FIELD_MISSING", details={"missing": missing})
    target["tag"] = None  # [OPEN]/[READ] cleared once evidence is attached
    status = row.status if row.status in ("confirmed_live",) else ("evidence_pending" if row.status == "not_yet_confirmed" else row.status)
    return _new_version(db, row, status=status, items=items, changed_by=changed_by, change_reason=f"item {item_id} completed")


def set_row_status(db: Session, row_id: str, status: str, *, changed_by: str, change_reason: str) -> IntegrationChecklistRow:
    if status not in ROW_STATUSES:
        raise ValidationFailed(f"status must be one of {ROW_STATUSES}")
    row = current_row(db, row_id)
    if status == "confirmed_live":
        incomplete = [i.get("item_id") for i in (row.items or []) if not item_complete(i)]
        if incomplete:
            raise ValidationFailed("no row goes live until every item has owner, evidence reference, date and approver", reason_code="ROW_ITEMS_INCOMPLETE", details={"items": incomplete})
    nxt = _new_version(db, row, status=status, changed_by=changed_by, change_reason=change_reason)
    if status in ("switched_off", "expired", "not_yet_confirmed", "evidence_pending"):
        sw = switch_for(db, nxt)
        if sw.state == "ON":
            _switch_off(db, sw, changed_by=changed_by, reason=f"row status {status}")
    return nxt


def integration_live(db: Session, row_id: str) -> bool:
    """True only when the checklist row is confirmed_live AND its switch is ON (used by other modules)."""
    try:
        row = current_row(db, row_id)
    except NotFound:
        return False
    sw = db.get(IntegrationSwitch, row.switch_key)
    return row.status == "confirmed_live" and sw is not None and sw.state == "ON"


def require_integration(db: Session, row_id: str) -> None:
    if not integration_live(db, row_id):
        raise SwitchedOff(s("integration_off"), reason_code="FEATURE_SWITCHED_OFF", details={"integration": row_id})


def set_switch(db: Session, switch_key: str, state: str, *, changed_by: str, reason: str) -> IntegrationSwitch:
    """ON only when the linked row is confirmed_live; OFF stops new calls, marks in-flight unconfirmed, tells owners."""
    sw = db.get(IntegrationSwitch, switch_key)
    if sw is None:
        raise NotFound("switch not found", reason_code="SWITCH_NOT_FOUND")
    row = current_row(db, sw.row_id)
    if state == "ON":
        if row.status != "confirmed_live":
            record_event(db, event_type="INTEGRATION_SWITCH_REFUSED", category="config", outcome="refused", reason_code="ROW_NOT_CONFIRMED_LIVE", actor_key=changed_by.split(":")[0], subject_type="switch", subject_id=switch_key, details={"row_status": row.status})
            raise SwitchedOff("the switch stays OFF until its checklist row is confirmed live", reason_code="ROW_NOT_CONFIRMED_LIVE", details={"row_id": row.row_id, "row_status": row.status})
        sw.state = "ON"
        sw.changed_by, sw.changed_at, sw.change_reason = changed_by, utcnow(), reason
        sw.history = (sw.history or []) + [{"state": "ON", "changed_by": changed_by, "changed_at": sw.changed_at.isoformat(), "reason": reason}]
        record_event(db, event_type="INTEGRATION_SWITCH_ON", category="config", actor_key=changed_by.split(":")[0], subject_type="switch", subject_id=switch_key, details={"row_id": row.row_id, "reason": reason})
        return sw
    _switch_off(db, sw, changed_by=changed_by, reason=reason)
    return sw


def _switch_off(db: Session, sw: IntegrationSwitch, *, changed_by: str, reason: str) -> None:
    sw.state = "OFF"
    sw.changed_by, sw.changed_at, sw.change_reason = changed_by, utcnow(), reason
    sw.history = (sw.history or []) + [{"state": "OFF", "changed_by": changed_by, "changed_at": sw.changed_at.isoformat(), "reason": reason}]
    record_event(db, event_type="INTEGRATION_SWITCH_OFF", category="config", actor_key=changed_by.split(":")[0], subject_type="switch", subject_id=sw.switch_key, details={"row_id": sw.row_id, "reason": reason, "new_calls": "stopped", "in_flight": "marked_unconfirmed", "owners": "informed"})
    record_event(db, event_type="OWNERS_NOTIFIED", category="reminder", actor_role="platform", subject_type="switch", subject_id=sw.switch_key, details={"message_key": "phases.switched_off_note"})


def daily_check(db: Session, *, now: datetime | None = None, actor: str = "platform:daily") -> dict:
    """Evidence expiry reopens the row and turns the switch OFF automatically; counts ON-without-row (target 0)."""
    now = now or utcnow()
    expired: list[str] = []
    for row in current_rows(db):
        item_expiry = [datetime.fromisoformat(i["evidence_expires_at"]) for i in (row.items or []) if i.get("evidence_expires_at")]
        exp = min([d for d in [row.evidence_expires_at] + item_expiry if d is not None], default=None)
        if row.status == "confirmed_live" and exp is not None and exp <= now:
            set_row_status(db, row.row_id, "expired", changed_by=actor, change_reason="evidence expired")
            record_event(db, event_type="INTEGRATION_EVIDENCE_EXPIRED", category="config", actor_role="platform", subject_type="integration_row", subject_id=row.row_id, details={"expired_at": exp.isoformat()})
            expired.append(row.row_id)
    on_without_row = []
    for sw in db.scalars(select(IntegrationSwitch).where(IntegrationSwitch.state == "ON")):
        try:
            row = current_row(db, sw.row_id)
        except NotFound:
            on_without_row.append(sw.switch_key)
            continue
        if row.status != "confirmed_live":
            on_without_row.append(sw.switch_key)
    record_event(db, event_type="INTEGRATION_DAILY_CHECK", category="system", actor_role="platform", details={"expired": expired, "on_without_confirmed_row": on_without_row})
    return {"checked_at": now.isoformat(), "expired": expired, "on_without_confirmed_row": on_without_row, "target": 0}


def bank_routes_live(db: Session) -> list[str]:
    return [r.bank_code or r.row_id for r in current_rows(db) if r.integration == "bank" and integration_live(db, r.row_id)]


def k11_status(db: Session) -> dict:
    """K11 while no bank route is live: headline 'Not yet measurable'; secondary 'No bank route available'."""
    banks = bank_routes_live(db)
    return {"headline": both("k11_not_measurable") if not banks else None, "secondary": both("k11_no_bank_route") if not banks else None, "bank_routes_live": banks, "manual_statement_companies_count_as_covered": False}


def k12_manual_path_flags(db: Session) -> dict:
    return {"fta_profile_manual_accepted": not integration_live(db, "fta"), "manual_upload_counts": True, "manual_receipt_upload_satisfies_fta": False}


# --- SC3 'What is live' panel ---------------------------------------------------------------------


def whats_live(db: Session, *, role: str = "owner", functions: list[str] | None = None) -> dict:
    incs = increments(db)
    cards = []
    for inc in incs:
        d = increment_dict(db, inc, include_gates=True)
        assigned = True
        if role == "delegate":
            fns = set(functions or [])
            assigned = "all" in fns or "all" in (inc.functions or []) or bool(fns & set(inc.functions or []))
        if not assigned:
            cards.append({"id": inc.id, "name": d["name"], "status": "not_assigned", "status_label": both("not_assigned"), "gates": [], "manual_fallback": None, "demo_outcome": None})
            continue
        for g in d["gates"]:
            g.pop("evidence_refs", None)  # owners and delegates never see gate history or references
            g.pop("approved_by", None)
            g.pop("changed_by", None)
        d.pop("delivery_measures", None)
        d["gated_items"] = [{"title": st.get("title"), "label": both("not_yet_switched_on_full"), "clickable": False} for st in (inc.stories or []) if st.get("gated")]
        d["waiting_for"] = both("waiting_for", gate=d["entry_gate"]["en"]) if d["status"] not in ("live", "demo_done") else None
        d["waiting_for"] = {"en": s("waiting_for", "en", gate=inc.entry_gate_en), "ar": s("waiting_for", "ar", gate=inc.entry_gate_ar)} if d["waiting_for"] else None
        d["until_then"] = {"en": s("until_then", "en", fallback=inc.manual_fallback_en), "ar": s("until_then", "ar", fallback=inc.manual_fallback_ar)} if d["status"] == "manual_path_live" else None
        cards.append(d)
    features = []
    bank_live = bool(bank_routes_live(db))
    features.append({"key": "bank_link", "available": bank_live, "note": None if bank_live else both("bank_not_available"), "button": None if bank_live else both("btn_upload_statements"), "route": "/documents?upload=statements", "manual_label": both("manual_unverified")})
    features.append({"key": "fta_submission", "available": integration_live(db, "fta"), "note": both("fta_prepared_here"), "button": both("btn_open_filing_pack"), "route": "/returns?pack=1", "manual_label": None})
    erp_live = integration_live(db, "erp")
    features.append({"key": "erp_link", "available": erp_live, "note": None if erp_live else both("erp_not_available"), "button": None if erp_live else both("btn_enter_figures"), "route": "/tax?entry=manual", "manual_label": both("manual_unverified")})
    licence_live = integration_live(db, "det_licence_feed")
    features.append({"key": "licence_details", "available": licence_live, "note": None if licence_live else both("licence_not_available"), "button": None if licence_live else both("btn_enter_licence"), "route": "/welcome?licence=manual", "manual_label": None})
    pay_live = integration_live(db, "payment_channel")
    features.append({"key": "payment", "available": pay_live, "note": None if pay_live else both("payment_not_available"), "button": None, "route": None, "manual_label": None})
    phases = [{"phase": 1, "label": {"en": "Phase 1: manual upload, tax preparation, reminders", "ar": "المرحلة 1: الرفع اليدوي وإعداد الضرائب والتذكيرات"}}, {"phase": 2, "label": {"en": "Phase 2: bank links once licence and agreements are in place", "ar": "المرحلة 2: الربط المصرفي بعد توفر الترخيص والاتفاقيات"}}, {"phase": 3, "label": {"en": "Phase 3: FTA data exchange", "ar": "المرحلة 3: تبادل البيانات مع الهيئة الاتحادية للضرائب"}}, {"phase": 4, "label": {"en": "Phase 4: signed audit", "ar": "المرحلة 4: التدقيق الموقّع"}}]
    current_phase = 1 + sum(1 for p, rid in ((2, "bank"), (3, "fta"), (4, "signed_audit")) if (p == 2 and bank_live) or (p != 2 and integration_live(db, rid)))
    for p in phases:
        p["marker"] = "Current" if p["phase"] == current_phase else ("Later" if p["phase"] > current_phase else "Done")
    return {"panel_title": both("panel_title"), "published": bool(incs), "empty_message": None if incs else both("plan_empty"), "increments": cards, "features": features, "phase_strip": phases, "phase_strip_text": both("phase_strip"), "k11": k11_status(db), "k12_flags": k12_manual_path_flags(db), "integration_off": both("integration_off")}
