"""Hosting and residency services (E1-S4): inventory generation, release decision, checklist document,
owner residency statement, key register with simulated rotation, and the K12 onboarding checklist."""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.core.errors import Conflict, Forbidden, NotFound, ValidationFailed
from app.core.time import to_dubai, utcnow
from app.modules.audit.service import record_event
from app.modules.companies.models import Company
from app.modules.config.service import get_config
from app.modules.hosting.models import (
    KEY_TYPES,
    LINK_EVENT_TYPES,
    LINK_TYPES,
    ROTATION_STEPS,
    UAE_LOCATIONS,
    KeyCompromise,
    KeyRecord,
    LinkEvent,
    OnboardingCohortRow,
    ReleaseDecision,
    ResidencyChecklistDoc,
    ResidencyComponent,
    ResidencyInventory,
)
from app.modules.hosting.strings import both, s

CHECKLIST_VERSION = "v1"

# --- deployment / component register (the generator's input) -----------------------------------
# Demo variants: 'blocked' (one backup component with unknown location) and 'pass' (all UAE-flagged).
_BASE_COMPONENTS: list[dict] = [
    {"component_id": "api", "name": "Portal API (FastAPI)", "component_type": "compute", "data_types": ["licence", "subscription", "personal"], "support_access_path": "UAE bastion, just-in-time approval, named staff"},
    {"component_id": "web", "name": "Portal web shell", "component_type": "compute", "data_types": ["session"], "support_access_path": "UAE bastion, just-in-time approval, named staff"},
    {"component_id": "db-primary", "name": "Primary database (PostgreSQL)", "component_type": "database", "data_types": ["licence", "subscription", "financial", "personal"], "backup_location": "UAE region", "dr_location": "UAE region"},
    {"component_id": "object-store", "name": "Document object store", "component_type": "storage", "data_types": ["documents", "uploads"], "backup_location": "UAE region", "dr_location": "UAE region"},
    {"component_id": "backup-vault", "name": "Encrypted backup vault", "component_type": "backup", "data_types": ["database backups", "document backups"], "backup_location": "UAE region", "dr_location": "UAE region"},
    {"component_id": "audit-log", "name": "Audit trail log archive", "component_type": "log", "data_types": ["audit events"], "log_destinations": [{"name": "UAE log archive", "location": "UAE region"}]},
    {"component_id": "monitoring", "name": "Monitoring and probe runner", "component_type": "monitoring", "data_types": ["probe records", "metrics"], "log_destinations": [{"name": "UAE monitoring store", "location": "UAE region"}]},
    {"component_id": "key-service", "name": "Key service (KMS/HSM)", "component_type": "key", "data_types": ["key material"], "key_custody": "UAE-located and UAE-operated; admin by UAE-based staff"},
    {"component_id": "local-model", "name": "Local AI model runtime", "component_type": "ai_model", "data_types": ["document text for classification"], "egress_paths": []},
    {"component_id": "queue", "name": "Job queue", "component_type": "queue", "data_types": ["job references"]},
]


def component_register(variant: str) -> list[dict]:
    rows = []
    for base in _BASE_COMPONENTS:
        row = {
            "hosting_location": "UAE region",
            "operator": "Qeonix (UAE entity)",
            "jurisdiction": "UAE",
            "key_custody": "UAE key service",
            "backup_location": None,
            "dr_location": None,
            "log_destinations": [{"name": "UAE log archive", "location": "UAE region"}],
            "support_access_path": "UAE bastion, just-in-time approval, named staff",
            "support_access_location": "UAE region",
            "subprocessors": [],
            "egress_paths": [],
        }
        row.update(base)
        rows.append(row)
    if variant == "blocked":
        for row in rows:
            if row["component_id"] == "backup-vault":
                row["hosting_location"] = "unknown"
    return rows


def evaluate_component(row: dict, check_mode: str) -> tuple[str, list[str]]:
    reasons: list[str] = []
    loc = row.get("hosting_location") or "unknown"
    if loc not in UAE_LOCATIONS:
        reasons.append("unknown_location")
    elif check_mode == "Dubai Government cloud / DESC-accredited" and loc != check_mode:
        reasons.append("check_mode_mismatch")
    for key in ("backup_location", "dr_location", "support_access_location"):
        val = row.get(key)
        if val and val not in UAE_LOCATIONS:
            reasons.append(f"non_uae_{key}")
    for item in row.get("subprocessors") or []:
        if (item.get("location") or "unknown") not in UAE_LOCATIONS:
            reasons.append("non_uae_subprocessor")
    for item in row.get("egress_paths") or []:
        if (item.get("location") or "unknown") not in UAE_LOCATIONS:
            reasons.append("non_uae_egress")
    for item in row.get("log_destinations") or []:
        if (item.get("location") or "unknown") not in UAE_LOCATIONS:
            reasons.append("non_uae_log_destination")
    if reasons:
        return "fail", reasons
    if not row.get("operator") or not row.get("jurisdiction"):
        return "pending", ["register_incomplete"]
    return "pass", []


def latest_inventory(db: Session) -> ResidencyInventory | None:
    return db.scalar(select(ResidencyInventory).where(ResidencyInventory.generator_status == "ok").order_by(desc(ResidencyInventory.generated_at), desc(ResidencyInventory.created_at)).limit(1))


def inventory_is_stale(db: Session, inv: ResidencyInventory | None, now: datetime | None = None) -> bool:
    if inv is None:
        return True
    if inv.stale:
        return True
    max_age = int(get_config(db, "hosting.inventory_max_age_hours", 24) or 24)
    return (now or utcnow()) - inv.generated_at > timedelta(hours=max_age)


def generator_mode(db: Session) -> str:
    return str(get_config(db, "hosting.generator.simulate", "ok") or "ok")


def generate_inventory(db: Session, *, actor_key: str | None = None, variant: str | None = None, is_demo: bool = False) -> dict:
    """Generate a new inventory version from the component register. Failure marks the last one stale."""
    mode = generator_mode(db)
    if mode in ("failed", "timed_out", "unavailable"):
        prev = latest_inventory(db)
        if prev is not None:
            prev.stale = True
            for c in db.scalars(select(ResidencyComponent).where(ResidencyComponent.inventory_version == prev.inventory_version)):
                c.stale = True
        record_event(db, event_type="RESIDENCY_INVENTORY_GENERATION_FAILED", category="system", outcome="failed", reason_code=mode.upper(), actor_key=actor_key, details={"mode": mode}, log_class="security")
        return {"status": mode, "inventory_version": prev.inventory_version if prev else None}
    variant = variant or str(get_config(db, "hosting.demo_inventory_variant", "blocked") or "blocked")
    check_mode = str(get_config(db, "hosting.residency_check_mode", "UAE region") or "UAE region")
    now = utcnow()
    inv = ResidencyInventory(generated_at=now, generator_status="ok", checklist_version=CHECKLIST_VERSION, check_mode=check_mode, variant=variant, is_demo=is_demo)
    db.add(inv)
    db.flush()
    for row in component_register(variant):
        status, reasons = evaluate_component(row, check_mode)
        db.add(ResidencyComponent(inventory_version=inv.inventory_version, status=status, fail_reasons=reasons, residency_checklist_version=CHECKLIST_VERSION, generated_at=now, **{k: v for k, v in row.items()}))
    db.flush()
    record_event(db, event_type="RESIDENCY_INVENTORY_GENERATED", category="system", actor_key=actor_key, subject_type="inventory", subject_id=inv.inventory_version, details={"variant": variant, "check_mode": check_mode}, log_class="security")
    return {"status": "ok", "inventory_version": inv.inventory_version}


def inventory_components(db: Session, inventory_version: str) -> list[ResidencyComponent]:
    return list(db.scalars(select(ResidencyComponent).where(ResidencyComponent.inventory_version == inventory_version).order_by(ResidencyComponent.component_id)))


def key_service_available(db: Session) -> bool:
    return not bool(get_config(db, "hosting.key_service.simulate_unavailable", False))


def run_release_check(db: Session, *, actor_key: str | None = None) -> ReleaseDecision:
    """Release decision: stale inventory never passes; generator or key service unavailable -> blocked."""
    now = utcnow()
    inv = latest_inventory(db)
    reasons: list[dict] = []
    checks: list[dict] = []
    next_step = both("next_step_record_location")
    if generator_mode(db) != "ok":
        reasons.append({"code": "GENERATOR_UNAVAILABLE", "component_id": None, **both("blocked_generator")})
        next_step = both("next_step_regenerate")
        if inv is not None:
            inv.stale = True
    checks.append({"check": "inventory_generator", "result": "pass" if generator_mode(db) == "ok" else "fail"})
    if not key_service_available(db):
        reasons.append({"code": "KEY_SERVICE_UNAVAILABLE", "component_id": None, **both("blocked_key_service")})
    checks.append({"check": "key_service", "result": "pass" if key_service_available(db) else "fail"})
    components = inventory_components(db, inv.inventory_version) if inv else []
    if inv is None or not components:
        reasons.append({"code": "NO_COMPONENTS", "component_id": None, **both("blocked_no_components")})
        next_step = both("next_step_register")
        checks.append({"check": "inventory_present", "result": "fail"})
    else:
        checks.append({"check": "inventory_present", "result": "pass"})
        if inventory_is_stale(db, inv, now):
            reasons.append({"code": "STALE_INVENTORY", "component_id": None, **both("blocked_stale")})
            next_step = both("next_step_regenerate")
            checks.append({"check": "inventory_fresh", "result": "fail"})
        else:
            checks.append({"check": "inventory_fresh", "result": "pass"})
        for c in components:
            if c.status == "fail":
                key = "blocked_unknown_location" if "unknown_location" in (c.fail_reasons or []) else "blocked_non_uae_path"
                reasons.append({"code": "COMPONENT_FAIL", "component_id": c.component_id, "component": c.name, **both(key, component=c.name)})
            elif c.status == "pending":
                reasons.append({"code": "COMPONENT_PENDING", "component_id": c.component_id, "component": c.name, **both("blocked_unknown_location", component=c.name)})
        checks.append({"check": "components_uae_flagged", "result": "pass" if all(c.status == "pass" for c in components) else "fail"})
    from app.modules.hosting.egress import policy_enabled

    checks.append({"check": "egress_policy_enabled", "result": "pass" if policy_enabled(db) else "fail"})
    if not policy_enabled(db):
        reasons.append({"code": "EGRESS_POLICY_DISABLED", "component_id": None, "en": "Blocked: the egress policy is disabled", "ar": "محظور: سياسة الخروج معطّلة"})
    dep = get_config(db, "hosting.dependency_check.last_result", None)
    checks.append({"check": "dependency_check", "result": (dep or {}).get("result", "not_run") if isinstance(dep, dict) else "not_run"})
    checks.append({"check": "tls_policy", "result": "pass" if get_config(db, "hosting.tls.min_version", None) else "fail"})
    probe_result = "not_run"
    try:
        from app.modules.probes.service import release_probe_test

        probe_result = "pass" if release_probe_test(db)["passed"] else "fail"
    except Exception:  # pragma: no cover - probes module absent
        probe_result = "not_run"
    checks.append({"check": "probe_release_test", "result": probe_result})
    if probe_result == "fail" and bool(get_config(db, "hosting.release.require_probe_test", False)):
        reasons.append({"code": "PROBE_RELEASE_TEST_FAILED", "component_id": None, "en": "Blocked: the 30-minute probe release test did not pass", "ar": "محظور: لم يجتز اختبار الإصدار للمجسات لمدة 30 دقيقة"})
    result = "blocked" if reasons else "pass"
    decision = ReleaseDecision(inventory_version=inv.inventory_version if inv else None, result=result, reasons=reasons, next_step=next_step if reasons else None, checks=checks, decided_at=now, decided_by=actor_key)
    db.add(decision)
    db.flush()
    record_event(db, event_type="RELEASE_CHECK_DECIDED", category="system", outcome=result, actor_key=actor_key, subject_type="release_decision", subject_id=decision.release_id, details={"inventory_version": decision.inventory_version, "reason_codes": [r["code"] for r in reasons]}, log_class="security")
    return decision


def latest_release_decision(db: Session) -> ReleaseDecision | None:
    return db.scalar(select(ReleaseDecision).order_by(desc(ReleaseDecision.decided_at), desc(ReleaseDecision.release_id)).limit(1))


def release_decisions(db: Session, limit: int = 20) -> list[ReleaseDecision]:
    return list(db.scalars(select(ReleaseDecision).order_by(desc(ReleaseDecision.decided_at)).limit(limit)))


def residency_summary(db: Session) -> dict:
    """SC14 panel data: cards, inventory table, release checks and state. Never 'Pass' while empty/stale."""
    inv = latest_inventory(db)
    decision = latest_release_decision(db)
    mode = generator_mode(db)
    now = utcnow()
    if inv is None:
        state = "generation_failed" if mode in ("failed", "timed_out") else "no_inventory"
    else:
        state = "ok"
        if mode in ("failed", "timed_out"):
            state = "generation_failed"
        elif inventory_is_stale(db, inv, now):
            state = "stale"
    components = inventory_components(db, inv.inventory_version) if inv else []
    failing = [c for c in components if c.status != "pass"]
    stale = inventory_is_stale(db, inv, now) if inv else True
    all_pass = bool(components) and not failing and not stale
    unknown = sum("unknown_location" in (c.fail_reasons or []) for c in components)
    from app.modules.hosting.egress import alert_counts

    hosting_card = both("not_yet_available") if not components else (both("not_confirmed") if stale else ({"en": "All components UAE-flagged", "ar": "جميع المكوّنات مسجّلة داخل الإمارات"} if not failing else (both("needs_attention_one") if len(failing) == 1 else both("needs_attention_n", n=len(failing)))))
    keys = list(db.scalars(select(KeyRecord)))
    encryption_card = both("not_yet_available") if not keys else ({"en": f"TLS {get_config(db, 'hosting.tls.min_version', '1.2')} minimum; {len(keys)} keys registered", "ar": f"الحد الأدنى TLS {get_config(db, 'hosting.tls.min_version', '1.2')}؛ {len(keys)} مفاتيح مسجّلة"} if not stale else both("not_confirmed"))
    ai_components = [c for c in components if c.component_type == "ai_model"]
    ai_card = both("not_yet_available") if not components else ({"en": "Local models only; no external model endpoint registered", "ar": "نماذج محلية فقط؛ لا توجد نقطة نهاية لنموذج خارجي"} if ai_components and all(not (c.egress_paths or []) and c.status == "pass" for c in ai_components) and not stale else both("not_confirmed"))
    counts = alert_counts(db)
    egress_card = {"en": f"Blocked egress attempts: {counts['total']} (open alerts: {counts['open']})", "ar": f"محاولات الخروج المحظورة: {counts['total']} (تنبيهات مفتوحة: {counts['open']})"}
    if decision is None:
        release_card = both("not_yet_available")
    elif decision.result == "pass" and not stale and inventory_is_current(inv, decision):
        release_card = both("release_pass")
    else:
        first = (decision.reasons or [{}])[0]
        reason_text = {"en": first.get("en", ""), "ar": first.get("ar", "")}
        release_card = {"en": s("release_blocked", "en", reason=reason_text["en"]), "ar": s("release_blocked", "ar", reason=reason_text["ar"])}
    message = None
    if state == "no_inventory":
        message = both("empty_no_evidence")
    elif state == "generation_failed":
        message = both("error_timed_out" if mode == "timed_out" else "error_failed")
    elif inv is not None and not components:
        message = both("empty_no_components")
    return {
        "state": state,
        "message": message,
        "panel_title": both("panel_title"),
        "inventory": None if inv is None else {"inventory_version": inv.inventory_version, "generated_at": inv.generated_at.isoformat(), "checklist_version": inv.checklist_version, "check_mode": inv.check_mode, "stale": stale, "variant": inv.variant, "is_demo": inv.is_demo},
        "last_successful_check_at": inv.generated_at.isoformat() if inv else None,
        "cards": {"hosting": hosting_card, "encryption": encryption_card, "egress": egress_card, "ai_models": ai_card, "release": release_card},
        "all_pass": all_pass,
        "unknown_location_count": unknown,
        "components": [component_dict(c) for c in components],
        "release_decision": decision_dict(decision) if decision else None,
        "egress_alerts": counts,
        "key_usage": {"keys": len(keys), "due_within_30_days": sum(k.rotation_due <= now + timedelta(days=30) for k in keys)},
        "evidence_export": {"available": False, "label": "later phase", "max_mb": get_config(db, "hosting.evidence_export_max_mb", 50)},
    }


def inventory_is_current(inv: ResidencyInventory | None, decision: ReleaseDecision) -> bool:
    return inv is not None and decision.inventory_version == inv.inventory_version


def component_dict(c: ResidencyComponent) -> dict:
    return {
        "component_id": c.component_id, "name": c.name, "component_type": c.component_type, "data_types": c.data_types or [], "hosting_location": c.hosting_location,
        "operator": c.operator, "jurisdiction": c.jurisdiction, "key_custody": c.key_custody, "backup_location": c.backup_location, "dr_location": c.dr_location,
        "log_destinations": c.log_destinations or [], "support_access_path": c.support_access_path, "support_access_location": c.support_access_location, "subprocessors": c.subprocessors or [],
        "egress_paths": c.egress_paths or [], "status": c.status, "fail_reasons": c.fail_reasons or [], "residency_checklist_version": c.residency_checklist_version, "generated_at": c.generated_at.isoformat(), "stale": c.stale,
    }


def decision_dict(d: ReleaseDecision) -> dict:
    return {"release_id": d.release_id, "inventory_version": d.inventory_version, "result": d.result, "reasons": d.reasons or [], "next_step": d.next_step, "checks": d.checks or [], "decided_at": d.decided_at.isoformat(), "decided_by": d.decided_by}


# --- owner residency statement ---------------------------------------------------------------------


def owner_residency_statement(db: Session) -> dict:
    """'hosted in the UAE' wording only when every registered component (backups, logs, support access
    included) is UAE-flagged and the latest release decision passed; otherwise 'Residency under review';
    neutral wording while no inventory exists."""
    inv = latest_inventory(db)
    neutral = both("owner_neutral")
    if inv is None:
        return {"state": "neutral", **neutral, "neutral": neutral, "last_check_at": None, "label": None}
    components = inventory_components(db, inv.inventory_version)
    decision = latest_release_decision(db)
    stale = inventory_is_stale(db, inv)
    every_uae = bool(components) and all(c.status == "pass" for c in components)
    release_ok = decision is not None and decision.result == "pass" and inventory_is_current(inv, decision)
    if every_uae and release_ok and not stale:
        wording = str(get_config(db, "hosting.owner_statement.approved_wording", "q277_placeholder") or "q277_placeholder")
        key = "owner_approved_release" if wording == "release_approved" else "owner_approved"
        return {"state": "approved", **both(key), "neutral": neutral, "last_check_at": decision.decided_at.isoformat(), "label": "Proposed wording - pending DET and counsel approval"}
    return {"state": "under_review", **both("residency_under_review"), "neutral": neutral, "last_check_at": inv.generated_at.isoformat(), "label": None}


# --- checklist document ------------------------------------------------------------------------------

CHECKLIST_DEFINITION = {
    "en": [
        "Data is stored and processed on infrastructure physically located in the UAE.",
        "The operator is subject to UAE jurisdiction.",
        "No copy, replica, backup, log, index, embedding, training set or telemetry containing company or personal data leaves the UAE.",
    ],
    "ar": [
        "تُخزَّن البيانات وتُعالَج على بنية تحتية موجودة فعليًا داخل الإمارات.",
        "يخضع المشغّل للاختصاص القضائي لدولة الإمارات.",
        "لا تغادر الإمارات أي نسخة أو نسخة مطابقة أو نسخة احتياطية أو سجل أو فهرس أو تضمين أو مجموعة تدريب أو بيانات قياس تحتوي على بيانات شركة أو بيانات شخصية.",
    ],
}
CHECKLIST_INSTRUMENTS = [
    {"ref": "PDPL Federal Decree-Law 45/2021", "scope": "cross-border transfer limits", "status": "executive regulations OPEN", "tag": "[REG]"},
    {"ref": "Dubai Law 26/2015 and DESC rules", "scope": "which rules bind the service", "status": "OPEN", "tag": "[REG]"},
    {"ref": "CBUAE Open Finance Regulation Circular 7/2023", "scope": "bank data", "status": "confirm text", "tag": "[REG]"},
    {"ref": "FTA terms", "scope": "tax data", "status": "to be confirmed", "tag": "[OPEN]"},
    {"ref": "DET data-sharing agreement", "scope": "hosting, residency, retention, subprocessor terms", "status": "to be confirmed", "tag": "[OPEN]"},
    {"ref": "Federal Decree-Law 46/2021 (trust services)", "scope": "signatures and timestamps when a provider is used", "status": "to be confirmed", "tag": "[REG]"},
]


def ensure_checklist(db: Session) -> ResidencyChecklistDoc:
    doc = db.get(ResidencyChecklistDoc, CHECKLIST_VERSION)
    if doc is None:
        doc = ResidencyChecklistDoc(version=CHECKLIST_VERSION, title="Residency checklist (working definition; never a compliance or DESC approval claim)", definition=CHECKLIST_DEFINITION, instruments=CHECKLIST_INSTRUMENTS, check_mode_options=list(UAE_LOCATIONS), status="provisional")
        db.add(doc)
        db.flush()
    return doc


def checklist_dict(doc: ResidencyChecklistDoc) -> dict:
    return {"version": doc.version, "title": doc.title, "definition": doc.definition, "instruments": doc.instruments, "check_mode_options": doc.check_mode_options, "status": doc.status, "created_at": doc.created_at.isoformat(), "note": "Working definition. The platform never claims 'compliant' or 'DESC-approved'."}


# --- key register and simulated rotation -----------------------------------------------------------


class KeyRotationFailed(Conflict):
    reason_code = "KEY_ROTATION_STEP_FAILED"


def rotation_period(db: Session, key_type: str) -> timedelta:
    if key_type in ("kek", "dek"):
        return timedelta(days=30 * int(get_config(db, "hosting.keys.kek_rotation_months", 12) or 12))
    return timedelta(days=int(get_config(db, "hosting.keys.credential_tls_rotation_days", 90) or 90))


def ensure_key(db: Session, key_id: str, key_type: str) -> KeyRecord:
    if key_type not in KEY_TYPES:
        raise ValidationFailed(f"key_type must be one of {KEY_TYPES}")
    key = db.get(KeyRecord, key_id)
    if key is None:
        key = KeyRecord(key_id=key_id, key_type=key_type, rotation_due=utcnow() + rotation_period(db, key_type))
        db.add(key)
        db.flush()
    return key


def list_keys(db: Session) -> list[KeyRecord]:
    return list(db.scalars(select(KeyRecord).order_by(KeyRecord.key_id)))


def key_dict(k: KeyRecord) -> dict:
    return {"key_id": k.key_id, "key_type": k.key_type, "version": k.version, "custody": k.custody, "rotation_due": k.rotation_due.isoformat(), "status": k.status, "last_rotated_at": k.last_rotated_at.isoformat() if k.last_rotated_at else None, "rotation_state": k.rotation_state, "compromise_declared_at": k.compromise_declared_at.isoformat() if k.compromise_declared_at else None, "compromise_deadline_at": k.compromise_deadline_at.isoformat() if k.compromise_deadline_at else None}


def key_use(db: Session, key_id: str, *, purpose: str, actor_key: str | None = None) -> KeyRecord:
    """Every key use is audited; key service unavailable -> refused with a neutral error, no cached keys."""
    if not key_service_available(db):
        record_event(db, event_type="KEY_USE_REFUSED", category="system", outcome="refused", reason_code="KEY_SERVICE_UNAVAILABLE", actor_key=actor_key, subject_type="key", subject_id=key_id, log_class="security")
        raise Conflict("Service temporarily unavailable, please try again", reason_code="KEY_SERVICE_UNAVAILABLE")
    key = db.get(KeyRecord, key_id)
    if key is None:
        raise NotFound("key not found")
    record_event(db, event_type="KEY_USED", category="system", actor_key=actor_key, subject_type="key", subject_id=key_id, details={"purpose": purpose, "version": key.version}, log_class="security")
    return key


def rotate_key(db: Session, key_id: str, *, actor_key: str | None, fail_at_step: str | None = None, resume: bool = False) -> KeyRecord:
    """Simulated rotation routine. Each step is audited; a failure keeps the last audited step so the
    routine can auto-resume; ``rollback_rotation`` restores the old version (valid until re-wrap)."""
    key = db.get(KeyRecord, key_id)
    if key is None:
        raise NotFound("key not found")
    if not key_service_available(db):
        raise Conflict("Service temporarily unavailable, please try again", reason_code="KEY_SERVICE_UNAVAILABLE")
    state = dict(key.rotation_state or {})
    if resume and state.get("last_audited_step"):
        start = ROTATION_STEPS.index(state["last_audited_step"]) + 1
        record_event(db, event_type="KEY_ROTATION_RESUMED", category="system", actor_key=actor_key, subject_type="key", subject_id=key_id, details={"from_step": state["last_audited_step"]}, log_class="security")
    else:
        start = 0
        state = {"target_version": key.version + 1, "started_at": utcnow().isoformat(), "last_audited_step": None}
        key.status = "rewrapping"
        record_event(db, event_type="KEY_ROTATION_STARTED", category="system", actor_key=actor_key, subject_type="key", subject_id=key_id, details={"target_version": state["target_version"]}, log_class="security")
    for step in ROTATION_STEPS[start:]:
        if step == fail_at_step:
            state["outcome"] = "failed"
            key.rotation_state = state
            record_event(db, event_type="KEY_ROTATION_STEP_FAILED", category="system", outcome="failed", reason_code="ROTATION_STEP_FAILED", actor_key=actor_key, subject_type="key", subject_id=key_id, details={"step": step, "last_audited_step": state.get("last_audited_step")}, log_class="security")
            db.flush()
            raise KeyRotationFailed(f"rotation step {step} failed; old key version stays valid", details={"step": step})
        state["last_audited_step"] = step
        record_event(db, event_type="KEY_ROTATION_STEP", category="system", actor_key=actor_key, subject_type="key", subject_id=key_id, details={"step": step, "target_version": state["target_version"]}, log_class="security")
    key.version = int(state["target_version"])
    key.status = "active"
    key.last_rotated_at = utcnow()
    key.rotation_due = utcnow() + rotation_period(db, key.key_type)
    key.rotation_state = None
    if key.compromise_declared_at and key.compromise_deadline_at is not None:
        for comp in db.scalars(select(KeyCompromise).where(KeyCompromise.key_id == key_id, KeyCompromise.rotation_completed_at.is_(None))):
            comp.rotation_completed_at = utcnow()
        key.compromise_declared_at = None
        key.compromise_deadline_at = None
    record_event(db, event_type="KEY_ROTATED", category="system", actor_key=actor_key, subject_type="key", subject_id=key_id, details={"version": key.version}, log_class="security")
    db.flush()
    return key


def rollback_rotation(db: Session, key_id: str, *, actor_key: str | None) -> KeyRecord:
    key = db.get(KeyRecord, key_id)
    if key is None:
        raise NotFound("key not found")
    key.rotation_state = None
    key.status = "active"
    record_event(db, event_type="KEY_ROTATION_ROLLED_BACK", category="system", actor_key=actor_key, subject_type="key", subject_id=key_id, details={"version_kept": key.version}, log_class="security")
    return key


def declare_compromise(db: Session, key_id: str, *, actor_key: str, actor_role: str) -> KeyCompromise:
    """Only the Qeonix security owner declares a compromise; rotation starts with the configured deadline."""
    if actor_role != "platform_security_admin":
        raise Forbidden("only the security owner can declare a key compromise", reason_code="NO_PERMISSION")
    key = db.get(KeyRecord, key_id)
    if key is None:
        raise NotFound("key not found")
    hours = int(get_config(db, "hosting.keys.compromise_rotation_deadline_hours", 24) or 24)
    now = utcnow()
    comp = KeyCompromise(key_id=key_id, declared_by_key=actor_key, declared_at=now, deadline_at=now + timedelta(hours=hours))
    db.add(comp)
    key.compromise_declared_at = now
    key.compromise_deadline_at = comp.deadline_at
    record_event(db, event_type="KEY_COMPROMISE_DECLARED", category="system", actor_key=actor_key, actor_role=actor_role, subject_type="key", subject_id=key_id, details={"who": actor_key, "when": now.isoformat(), "key_id": key_id, "deadline_at": comp.deadline_at.isoformat()}, log_class="security")
    db.flush()
    rotate_key(db, key_id, actor_key=actor_key)
    return comp


# --- K12 onboarding checklist --------------------------------------------------------------------

REQUIRED_GROUPS = (
    ("det_licence_record", ("det_licence_record",)),
    ("fta_tax_profile", ("fta_tax_profile", "fta_profile_manual")),
    ("data_source", ("bank_feed", "ledger_connection", "manual_upload")),
)


def k12_window_hours(db: Session) -> int:
    return int(get_config(db, "hosting.k12_window_hours", 720) or 720)


def _fta_integration_live(db: Session) -> bool:
    try:
        from app.modules.phases.service import integration_live

        return integration_live(db, "fta")
    except Exception:  # phases module absent: manual profile entry is accepted
        return False


def current_cohort_row(db: Session, company_id: str) -> OnboardingCohortRow | None:
    return db.scalar(select(OnboardingCohortRow).where(OnboardingCohortRow.company_id == company_id).order_by(desc(OnboardingCohortRow.onboarding_at), desc(OnboardingCohortRow.created_at)).limit(1))


def ensure_cohort_row(db: Session, company_id: str, *, onboarding_at: datetime | None = None, onboarding_id: str | None = None, subscription_id: str | None = None, licence_number: str | None = None) -> OnboardingCohortRow | None:
    """Cohort entry once per onboarding episode; the first onboarding_at is never moved."""
    row = current_cohort_row(db, company_id)
    if row is not None and row.status != "closed":
        return row
    company = db.get(Company, company_id)
    at = onboarding_at or (company.onboarding_at if company else None)
    if at is None:
        return None
    oid = onboarding_id or (company.onboarding_id if company and company.onboarding_id else None) or f"onb_{company_id}_{int(at.timestamp())}"
    if db.get(OnboardingCohortRow, oid) is not None:
        return db.get(OnboardingCohortRow, oid)
    row = OnboardingCohortRow(onboarding_id=oid, company_id=company_id, subscription_id=subscription_id, licence_number=licence_number, onboarding_at=at, cohort_month=to_dubai(at).strftime("%Y-%m"), cohort_version=str(get_config(db, "hosting.k12_cohort_version", "k12-v1") or "k12-v1"))
    db.add(row)
    db.flush()
    return row


def record_restart(db: Session, company_id: str, *, at: datetime | None = None) -> OnboardingCohortRow:
    row = ensure_cohort_row(db, company_id)
    if row is None:
        raise NotFound("no onboarding episode for this company", reason_code="NO_ONBOARDING")
    row.restart_count += 1
    row.last_restart_at = at or utcnow()
    record_event(db, event_type="K12_ONBOARDING_RESTARTED", category="system", company_id=company_id, subject_type="onboarding", subject_id=row.onboarding_id, details={"restart_count": row.restart_count})
    return row


def record_renewal(db: Session, company_id: str) -> OnboardingCohortRow | None:
    """A licence renewal is not a new onboarding: same row, same clock."""
    row = ensure_cohort_row(db, company_id)
    if row is not None:
        record_event(db, event_type="K12_RENEWAL_NOTED", category="system", company_id=company_id, subject_type="onboarding", subject_id=row.onboarding_id, details={"new_row": False})
    return row


def record_exit(db: Session, company_id: str, *, reason: str, at: datetime | None = None) -> OnboardingCohortRow:
    row = ensure_cohort_row(db, company_id)
    if row is None:
        raise NotFound("no onboarding episode for this company", reason_code="NO_ONBOARDING")
    row.status = "exited"
    row.exit_reason = reason
    row.exited_at = at or utcnow()
    record_event(db, event_type="K12_ONBOARDING_EXITED", category="system", company_id=company_id, subject_type="onboarding", subject_id=row.onboarding_id, details={"reason": reason})
    return row


def record_resubscribe(db: Session, company_id: str, *, new_onboarding_id: str, subscription_id: str | None = None, at: datetime | None = None) -> OnboardingCohortRow:
    """Re-subscribe after an ended subscription: earlier row closed, new row with a new clock."""
    at = at or utcnow()
    old = current_cohort_row(db, company_id)
    if old is not None and old.status != "closed":
        old.status = "closed"
        old.closed_at = at
    row = OnboardingCohortRow(onboarding_id=new_onboarding_id, company_id=company_id, subscription_id=subscription_id, onboarding_at=at, cohort_month=to_dubai(at).strftime("%Y-%m"))
    db.add(row)
    db.flush()
    record_event(db, event_type="K12_ONBOARDING_STARTED", category="system", company_id=company_id, subject_type="onboarding", subject_id=row.onboarding_id, details={"previous": old.onboarding_id if old else None})
    return row


def record_link_event(db: Session, company_id: str, link_type: str, event_type: str, source: str | None = None, *, event_at: datetime | None = None, actor_key: str | None = None, corrects_link_id: str | None = None) -> LinkEvent:
    """Entry point for the datalinks / consent modules. Validates the vocabulary and audits the event."""
    if link_type not in LINK_TYPES:
        raise ValidationFailed(f"link_type must be one of {LINK_TYPES}", reason_code="LINK_TYPE_INVALID")
    if event_type not in LINK_EVENT_TYPES:
        raise ValidationFailed(f"event_type must be one of {LINK_EVENT_TYPES}", reason_code="LINK_EVENT_INVALID")
    row = ensure_cohort_row(db, company_id)
    ev = LinkEvent(company_id=company_id, onboarding_id=row.onboarding_id if row else None, link_type=link_type, event_type=event_type, event_at=event_at or utcnow(), source=source, corrects_link_id=corrects_link_id)
    db.add(ev)
    db.flush()
    record_event(db, event_type="K12_LINK_EVENT", category="system", actor_key=actor_key, company_id=company_id, subject_type="link", subject_id=ev.link_id, details={"link_type": link_type, "event_type": event_type, "source": source, "corrects": corrects_link_id})
    if row is not None:
        _refresh_first_all_active(db, row)
    return ev


def _events_for(db: Session, company_id: str, onboarding_id: str | None) -> list[LinkEvent]:
    stmt = select(LinkEvent).where(LinkEvent.company_id == company_id)
    if onboarding_id:
        stmt = stmt.where((LinkEvent.onboarding_id == onboarding_id) | (LinkEvent.onboarding_id.is_(None)))
    return sorted(db.scalars(stmt), key=lambda e: (e.event_at, e.created_at))


def _link_state_at(events: list[LinkEvent], link_type: str, at: datetime, *, inclusive: bool = True) -> tuple[str, LinkEvent | None]:
    latest = None
    for e in events:
        if e.link_type != link_type:
            continue
        if (e.event_at <= at) if inclusive else (e.event_at < at):
            latest = e
    if latest is None:
        return "none", None
    if latest.event_type in ("activated", "reactivated"):
        return "active", latest
    if latest.event_type == "requested":
        return "pending", latest
    return "inactive", latest


def _group_state_at(db: Session, events: list[LinkEvent], group: str, link_types: tuple[str, ...], at: datetime, *, inclusive: bool = True) -> dict:
    fta_live = _fta_integration_live(db) if group == "fta_tax_profile" else False
    best = {"status": "missing", "source": None, "link_type": None, "via_manual": False, "pending_reason": None}
    for lt in link_types:
        if group == "fta_tax_profile" and lt == "fta_profile_manual" and fta_live:
            continue  # manual tax-profile entry only satisfies the link while the FTA link is not live
        state, ev = _link_state_at(events, lt, at, inclusive=inclusive)
        if state == "active":
            return {"status": "linked", "source": ev.source if ev else None, "link_type": lt, "via_manual": lt in ("fta_profile_manual", "manual_upload"), "pending_reason": None}
        if state == "pending" and best["status"] != "linked":
            best = {"status": "pending", "source": ev.source if ev else None, "link_type": lt, "via_manual": False, "pending_reason": (ev.source if ev and ev.source in ("owner_consent", "bank") else "bank")}
    return best


def _all_active_at(db: Session, events: list[LinkEvent], at: datetime, *, inclusive: bool = True) -> bool:
    return all(_group_state_at(db, events, g, lts, at, inclusive=inclusive)["status"] == "linked" for g, lts in REQUIRED_GROUPS)


def _refresh_first_all_active(db: Session, row: OnboardingCohortRow) -> None:
    events = _events_for(db, row.company_id, row.onboarding_id)
    first = None
    for e in events:
        if e.event_at < row.onboarding_at:
            continue
        if _all_active_at(db, events, e.event_at):
            first = e.event_at
            break
    row.first_all_links_active_at = first


def k12_status(db: Session, company_id: str, *, now: datetime | None = None, viewer_role: str = "owner") -> dict:
    """Checklist state for SC2/SC3 and the DET aggregate (window, chips, days left, wording)."""
    now = now or utcnow()
    row = ensure_cohort_row(db, company_id)
    hours = k12_window_hours(db)
    if row is None or row.onboarding_at > now:
        return {"state": "not_started", "message": both("k12_not_started"), "det_label": both("k12_window_not_started"), "window_start": None, "window_end": None, "days_left": None, "links": [{"group": g, "label": both(f"k12_link_{g}" if g != "data_source" else "k12_link_data_source"), "status": "not_started", "chip": both("k12_link_not_started"), "source": None, "via_manual": False, "action_enabled": False, "action_reason": both("k12_not_started")} for g, _ in REQUIRED_GROUPS], "buttons": [], "based_on_incomplete_data": False, "complete_via_manual_path_only": False, "achieved_then_lost": False, "completed_after_window_days": None, "restart_count": 0, "cohort_month": None, "onboarding_id": None}
    window_end = row.onboarding_at + timedelta(hours=hours)
    events = _events_for(db, company_id, row.onboarding_id)
    at_mark = _all_active_at(db, events, window_end, inclusive=False)
    links = []
    for group, lts in REQUIRED_GROUPS:
        st = _group_state_at(db, events, group, lts, now)
        chip_key = {"linked": "k12_linked", "pending": "k12_pending", "missing": "k12_missing"}[st["status"]]
        pending_msg = None
        if st["status"] == "pending":
            pending_msg = both("k12_pending_owner_consent") if st["pending_reason"] == "owner_consent" else both("k12_pending_bank")
        links.append({"group": group, "label": both(f"k12_link_{group}" if group != "data_source" else "k12_link_data_source"), "status": st["status"], "chip": both(chip_key), "source": st["source"], "link_type": st["link_type"], "via_manual": st["via_manual"], "pending_message": pending_msg, "action_enabled": st["status"] != "linked", "action_reason": None})
    all_now = all(link["status"] == "linked" for link in links)
    achieved_within = False
    for e in events:
        if row.onboarding_at <= e.event_at < window_end and _all_active_at(db, events, e.event_at):
            achieved_within = True
            break
    missing = [link["label"] for link in links if link["status"] != "linked"]
    days_left = max(0, (window_end - now).days) if now < window_end else 0
    via_manual_only = all_now and any(link["via_manual"] for link in links) and not any(link["link_type"] in ("bank_feed", "fta_tax_profile") for link in links if link["status"] == "linked")
    out = {"onboarding_id": row.onboarding_id, "cohort_month": row.cohort_month, "restart_count": row.restart_count, "window_start": row.onboarding_at.isoformat(), "window_end": window_end.isoformat(), "days_left": days_left, "links": links, "all_linked_now": all_now, "complete_at_mark": at_mark, "achieved_then_lost": achieved_within and not at_mark and now >= window_end, "complete_via_manual_path_only": via_manual_only, "first_all_links_active_at": row.first_all_links_active_at.isoformat() if row.first_all_links_active_at else None, "completed_after_window_days": None, "buttons": [], "message": None, "det_label": None, "based_on_incomplete_data": not all_now}
    if row.status == "exited":
        out.update({"state": "exited", "det_label": {"en": "Exited before day 30", "ar": "خرج قبل اليوم 30"}})
        return out
    if now < window_end:
        out["state"] = "window_open"
        out["det_label"] = {"en": "Window still open", "ar": "المهلة ما زالت مفتوحة"}
    elif at_mark:
        out["state"] = "complete"
        out["det_label"] = {"en": "Complete", "ar": "مكتمل"}
    elif all_now:
        done_at = row.first_all_links_active_at or now
        out["state"] = "completed_after_window"
        out["completed_after_window_days"] = (done_at - row.onboarding_at).days
        out["det_label"] = {"en": "Completed after day 30", "ar": "اكتمل بعد اليوم 30"}
    else:
        out["state"] = "expired_missing"
        out["det_label"] = both("k12_window_expired_missing")
        date_en = window_end.strftime("%-d %B %Y")
        out["message"] = {"en": s("k12_expired", "en", date=date_en, list=", ".join(m["en"] for m in missing)), "ar": s("k12_expired", "ar", date=date_en, list="، ".join(m["ar"] for m in missing))}
    if any(link["status"] != "linked" for link in links):
        out["buttons"] = [both("k12_ask_owner")] if viewer_role == "delegate" else [both("k12_link_now")]
    if viewer_role == "delegate":
        for link in links:
            if link["status"] == "pending" and link.get("pending_message"):
                link["pending_message"] = both("k12_ask_owner_consent")
    return out


def k12_aggregate(db: Session, *, now: datetime | None = None) -> dict:
    """DET admin aggregate: counts per state and per cohort month; link-source breakdown; no company detail."""
    now = now or utcnow()
    rows = list(db.scalars(select(OnboardingCohortRow)))
    states: dict[str, int] = {}
    by_month: dict[str, dict[str, int]] = {}
    sources: dict[str, int] = {}
    manual_only = 0
    for row in rows:
        st = k12_status(db, row.company_id, now=now)
        states[st["state"]] = states.get(st["state"], 0) + 1
        bucket = by_month.setdefault(row.cohort_month, {})
        bucket[st["state"]] = bucket.get(st["state"], 0) + 1
        for link in st.get("links", []):
            if link["status"] == "linked" and link.get("link_type"):
                sources[link["link_type"]] = sources.get(link["link_type"], 0) + 1
        if st.get("complete_via_manual_path_only"):
            manual_only += 1
    closed_members = [r for r in rows if r.onboarding_at + timedelta(hours=k12_window_hours(db)) <= now]
    return {
        "cohort_version": str(get_config(db, "hosting.k12_cohort_version", "k12-v1")),
        "window_hours": k12_window_hours(db),
        "rows": len(rows),
        "states": states,
        "labels": {"window_not_started": both("k12_window_not_started"), "window_expired_missing": both("k12_window_expired_missing"), "complete_via_manual_path_only": both("k12_complete_manual_path")},
        "by_cohort_month": by_month,
        "link_sources": sources,
        "complete_via_manual_path_only": manual_only,
        "headline_final": len(closed_members) == len(rows) and bool(rows),
        "estimate_note": "Realistic early range 30-60% (estimate); seasonal effects (Ramadan, Eid, summer) flagged.",
    }
