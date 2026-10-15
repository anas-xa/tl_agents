"""SC3 company dashboard aggregate (E3-S1) and remote-owner view (E3-S5).

Five panels in a fixed order (tax status, audit status, deadlines, documents, compliance). Each carries its source,
'last updated' (Asia/Dubai) and its own freshness state from the per-panel TTL/limit configuration: fresh
(age <= TTL) | last_known (TTL < age <= limit) | cannot_be_confirmed (age > limit) | not_available
(SOURCE_TIMEOUT_NO_CACHE) | could_not_be_loaded | not_linked_yet | not_shared (delegate without the function,
locked placeholder with no status, counts or dates). Panels load independently and fail soft; one failing source
never blocks the others. Freshness is never merged into one dashboard-level value.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import Conflict, Forbidden, NotFound, PlatformError, Unauthenticated
from app.core.ids import new_id
from app.core.time import dubai_today, to_dubai, utcnow
from app.modules.audit.service import record_event
from app.modules.companies.models import Company, CompanyRole
from app.modules.config.service import get_config
from app.modules.dashboard.models import (
    PANELS,
    AccessRequest,
    DelegatePanelVisibility,
    PanelCache,
    RememberedCompany,
)
from app.modules.dashboard.strings import bi
from app.modules.licences.models import Licence, LicencePerson

OWNER_LEVEL = ("owner", "remote_owner")
FRESHNESS_DEFAULT = {
    "licence_subscription": {"ttl_minutes": 15, "limit_minutes": 36 * 60},
    "ejari": {"ttl_minutes": 24 * 60, "limit_minutes": 7 * 24 * 60},
    "tax_profile": {"ttl_minutes": 24 * 60, "limit_minutes": 7 * 24 * 60},
    "documents": {"ttl_minutes": 5, "limit_minutes": 24 * 60},
    "deadlines": {"ttl_minutes": 5, "limit_minutes": 24 * 60},
    "compliance_activity": {"ttl_minutes": 5, "limit_minutes": 24 * 60},
}
PANEL_SOURCE_CLASS = {"tax_status": "tax_profile", "audit_status": "tax_profile", "deadlines": "deadlines", "documents": "documents", "compliance": "licence_subscription"}
PANEL_FUNCTIONS_DEFAULT = {
    "tax_status": ["all", "tax_preparation", "tax_status"],
    "audit_status": ["all", "audit_preparation", "tax_preparation"],
    "deadlines": ["*"],
    "documents": ["all", "uploads", "bookkeeping", "tax_preparation", "documents"],
    "compliance": ["all", "licence", "compliance"],
}
OWNER_ONLY_FUNCTIONS = ("approve_submissions", "consent", "subscription")


class SourceTimeout(RuntimeError):
    pass


# --- freshness ---------------------------------------------------------------------------------------------------


def freshness_config(db: Session) -> dict:
    return get_config(db, "dashboard.panel_freshness", FRESHNESS_DEFAULT) or FRESHNESS_DEFAULT


def freshness_for(db: Session, source_class: str, data_as_of: datetime | None, now: datetime | None = None) -> dict:
    now = now or utcnow()
    cfg = freshness_config(db).get(source_class) or FRESHNESS_DEFAULT["deadlines"]
    if data_as_of is None:
        return {"state": "not_available", "age_minutes": None, "stale_flag": True}
    age = (now - data_as_of).total_seconds() / 60
    if age <= cfg["ttl_minutes"]:
        state = "fresh"
    elif age <= cfg["limit_minutes"]:
        state = "last_known"
    else:
        state = "cannot_be_confirmed"
    return {"state": state, "age_minutes": int(age), "stale_flag": state != "fresh", "ttl_minutes": cfg["ttl_minutes"], "limit_minutes": cfg["limit_minutes"]}


def _dubai_iso(dt: datetime | None) -> str | None:
    return to_dubai(dt).isoformat() if dt else None


# --- role helpers ------------------------------------------------------------------------------------------------


def role_on(principal, company_id: str) -> str:
    roles = [r.role for r in principal.roles_for(company_id)]
    if "owner" in roles:
        return "owner"
    if "remote_owner" in roles:
        return "remote_owner"
    return roles[0] if roles else "none"


def functions_on(principal, company_id: str) -> list[str]:
    out: list[str] = []
    for r in principal.roles_for(company_id):
        out += list(r.functions or [])
    return out


def panel_shared(db: Session, principal, company_id: str, panel: str) -> bool:
    role = role_on(principal, company_id)
    if role in OWNER_LEVEL:
        return True
    if role != "delegate":
        return False
    vis = db.scalar(select(DelegatePanelVisibility).where(DelegatePanelVisibility.company_id == company_id, DelegatePanelVisibility.identity_uuid == principal.identity_uuid, DelegatePanelVisibility.panel == panel))
    if vis is not None and not vis.visible:
        return False
    needed = (get_config(db, "dashboard.panel_functions", PANEL_FUNCTIONS_DEFAULT) or PANEL_FUNCTIONS_DEFAULT).get(panel, ["all"])
    if "*" in needed:
        return True
    return bool(set(needed) & set(functions_on(principal, company_id)))


def owner_name(db: Session, company_id: str) -> str | None:
    lic = db.scalar(select(Licence).where(Licence.company_id == company_id))
    if lic is not None:
        p = db.scalar(select(LicencePerson).where(LicencePerson.licence_id == lic.id, LicencePerson.capacity.in_(("owner", "partner")), LicencePerson.emirates_id_hash.is_not(None)).limit(1))
        if p is not None:
            return p.display_name
    return None


def acting_as(db: Session, principal, company_id: str) -> dict:
    company = db.get(Company, company_id)
    role = role_on(principal, company_id)
    abroad = bool(company and company.owner_location_self_declared == "abroad")
    if role in OWNER_LEVEL:
        label = bi("acting.owner")
        principal_name = None
    else:
        principal_name = owner_name(db, company_id) or "-"
        label = bi("acting.delegate", owner=principal_name)
    held = ["all"] if role in OWNER_LEVEL else functions_on(principal, company_id)
    return {"role": "owner" if role in OWNER_LEVEL else "delegate", "company_role": role, "person": principal.display_name, "principal": principal_name, "owner_abroad": abroad,
            "owner_abroad_label": bi("acting.owner_abroad") if abroad else None, "label": label, "held_functions": held,
            "owner_only_functions": [] if role in OWNER_LEVEL else list(OWNER_ONLY_FUNCTIONS),
            "accessible_name": f"{label['en'].replace(':', '')}{', owner abroad' if abroad else ''}"}


# --- panel builders (each returns payload, source, data_as_of) --------------------------------------------------


def _visible_obligations(db: Session, principal, company_id: str) -> tuple[list[dict], int]:
    from app.modules.deadlines import service as dl

    rows = dl.obligations_for(db, company_id)
    return dl.filter_for_principal(db, principal, company_id, rows)


def build_tax(db: Session, principal, company_id: str) -> tuple[dict, str, datetime | None, str | None]:
    try:
        from app.modules.tax.models import TaxEntityProfile

        prof = db.get(TaxEntityProfile, company_id)
    except ImportError:  # pragma: no cover
        prof = None
    try:
        from app.modules.datalinks.models import TaxProfile

        dl_profiles = list(db.scalars(select(TaxProfile).where(TaxProfile.company_id == company_id, TaxProfile.is_current.is_(True))))
    except ImportError:  # pragma: no cover
        dl_profiles = []
    rows, _ = _visible_obligations(db, principal, company_id)
    tax_rows = [r for r in rows if r["obligation_type"] in ("vat_return", "ct_return") and not r["done"]]
    if prof is None and not dl_profiles:
        return ({"status": "not_linked_yet", "status_label": bi("state.not_linked_yet"), "deadlines": [], "next_step": bi("next.add_tax_details"), "k10": bi("state.not_yet_measured")}, "owner-entered", None, "not_linked_yet")
    lines = []
    if prof is not None:
        lines.append({**bi("tax.declared_registered_vat" if prof.vat_registered else "tax.declared_not_registered_vat"), "unconfirmed": True, "unconfirmed_label": bi("tax.unconfirmed")})
        lines.append({**bi("tax.ct_status_unclear" if prof.ct_status == "unclear" else "tax.ct_status_declared"), "unconfirmed": True, "unconfirmed_label": bi("tax.unconfirmed")})
    sbr = None
    excluded = prof is not None and prof.ct_status in ("tax_group", "qualifying_free_zone_person", "qfzp", "free_zone")
    if excluded:
        sbr = {"kind": "not_available", "text": bi("tax.sbr_not_available")}
    elif prof is not None and prof.ct_status != "unclear":
        sbr = {"kind": "may_apply", "text": bi("tax.sbr_may_apply"), "cutoff": _rule("sbr.period_end_cutoff", db), "threshold_aed": _rule("sbr.threshold_aed", db)}
    as_of = max([p.as_of for p in dl_profiles] + ([prof.updated_at] if prof is not None else []), default=None)
    payload = {"status": "declared", "status_label": {"en": "Based on details you entered", "ar": "بحسب بيانات أدخلتموها"}, "lines": lines, "deadlines": [_mini(r) for r in tax_rows],
               "sbr": sbr, "audit_required_line": bi("tax.audit_may_be_required") if excluded else None, "k10": bi("state.not_yet_measured"), "phase_note": "Phase 1B: status and deadlines only; no return drafts, calculations or submissions on this panel."}
    return payload, "owner-entered", as_of, None


def _rule(key: str, db: Session) -> Any:
    try:
        from app.modules.deadlines.service import rule_value

        return rule_value(db, key)[0]
    except ImportError:  # pragma: no cover
        return None


def build_audit(db: Session, principal, company_id: str) -> tuple[dict, str, datetime | None, str | None]:
    try:
        from app.modules.auditagent.service import audit_flag_summary  # built by the audit-agent epic

        summary = audit_flag_summary(db, company_id)
        if summary:
            as_of = summary.get("evaluated_at") or summary.get("entered_at")
            when = datetime.fromisoformat(as_of) if isinstance(as_of, str) else as_of
            return ({**summary, "note": bi("audit.note")}, summary.get("source", "owner-entered"), when or utcnow(), None)
    except ImportError:  # the audit agent epic is not installed yet: 'Not yet assessed'
        pass
    return ({"state": "not_yet_assessed", "state_label": bi("state.not_yet_assessed"), "last_updated_label": bi("audit.no_entry"), "note": bi("audit.note"), "sign_off": None}, "owner-entered", utcnow(), None)


def build_deadlines(db: Session, principal, company_id: str) -> tuple[dict, str, datetime | None, str | None]:
    rows, withheld = _visible_obligations(db, principal, company_id)
    open_rows = [r for r in rows if not r["done"]]
    as_of = max((datetime.fromisoformat(r["calculation_time"]) for r in rows if r.get("calculation_time")), default=utcnow())
    return ({"items": [_mini(r) for r in open_rows], "withheld_count": withheld, "withheld_note": bi("state.withheld") if withheld else None, "count": len(open_rows)}, "computed", as_of, None)


def _mini(r: dict) -> dict:
    return {k: r.get(k) for k in ("obligation_id", "obligation_type", "subtype", "name", "due_date", "date_used", "date_status", "days_left", "days_left_tier", "status_chip", "status_chips", "readiness", "readiness_detail", "readiness_label", "missing_items", "is_stated", "calculated", "due_date_source", "deadline_source", "rule_version", "calendar_version", "period_end", "period_id", "draft_pack_id", "date_updated", "recommended_submit_by", "provisional_date", "updated_at", "is_demo")}


def build_documents(db: Session, principal, company_id: str) -> tuple[dict, str, datetime | None, str | None]:
    docs: list[dict] = []
    try:
        from app.modules.compliance.service import draft_dict, drafts_for

        for d in drafts_for(db, company_id):
            dd = draft_dict(d)
            docs.append({"document_id": dd["id"], "document_type": "compliance_pack" if dd["output_type"] == "document_pack" else "deadline_checklist", "status": "draft", "language_set": "ar+en", "ar_present": True, "en_present": True,
                         "fields_mismatched": 0 if dd["k28_ok"] else 1, "generation_blocked": not dd["released"], "title": dd["content"]["en"]["title"] if dd["content"]["en"] else None, "title_ar": dd["content"]["ar"]["title"] if dd["content"]["ar"] else None,
                         "ai_prepared": True, "review_status": dd["review_status"], "review_label": dd["ai_label"], "link": None, "is_demo": dd["is_demo"]})
    except ImportError:  # pragma: no cover
        pass
    try:
        from app.modules.drafts.models import STATUS_LABELS, DraftPack

        latest: dict[tuple, Any] = {}
        for p in db.scalars(select(DraftPack).where(DraftPack.company_id == company_id).order_by(DraftPack.version)):
            latest[(p.tax_type, p.period_id)] = p
        for (tt, pid), p in latest.items():
            docs.append({"document_id": p.id, "document_type": f"{tt}_return_draft", "status": "draft", "language_set": "ar+en", "ar_present": True, "en_present": True, "fields_mismatched": 0, "generation_blocked": False,
                         "title": f"{'VAT' if tt == 'vat' else 'Corporate tax'} return draft {pid}", "title_ar": f"{'مسودة إقرار ضريبة القيمة المضافة' if tt == 'vat' else 'مسودة إقرار ضريبة الشركات'} {pid}",
                         "ai_prepared": True, "review_status": p.review_status, "review_label": STATUS_LABELS.get(p.review_status, {"en": p.review_status, "ar": p.review_status}), "link": f"/returns/{p.id}", "is_demo": bool(getattr(p, "is_demo", False))})
    except ImportError:  # pragma: no cover
        pass
    return ({"items": docs, "k28": bi("state.not_yet_measured"), "note": "Listing a name is not delivery; K28 is emitted when a document is opened or exported."}, "computed", utcnow(), None)


def build_compliance(db: Session, principal, company_id: str) -> tuple[dict, str, datetime | None, str | None]:
    from app.modules.compliance.service import evaluate

    ev = evaluate(db, company_id, principal=principal)
    lic = db.scalar(select(Licence).where(Licence.company_id == company_id))
    if ev.get("empty"):
        return ({**ev}, "DET", None, "not_linked_yet")
    return (ev, "DET", lic.last_det_refresh_at if lic else None, None)


BUILDERS: dict[str, Callable] = {"tax_status": build_tax, "audit_status": build_audit, "deadlines": build_deadlines, "documents": build_documents, "compliance": build_compliance}


def _cache_put(db: Session, company_id: str, panel: str, payload: dict, source: str, as_of: datetime) -> None:
    row = db.scalar(select(PanelCache).where(PanelCache.company_id == company_id, PanelCache.panel == panel))
    if row is None:
        db.add(PanelCache(company_id=company_id, panel=panel, payload=payload, source=source, data_as_of=as_of))
    else:
        row.payload, row.source, row.data_as_of, row.cached_at = payload, source, as_of, utcnow()


def load_panel(db: Session, principal, company_id: str, panel: str, *, now: datetime | None = None) -> dict:
    """One panel, independently: live read with a 2 s timeout; cache between TTL and limit; never zero or blank."""
    now = now or utcnow()
    title = bi(f"panel.{panel}")
    if not panel_shared(db, principal, company_id, panel):
        req = db.scalar(select(AccessRequest).where(AccessRequest.company_id == company_id, AccessRequest.identity_uuid == principal.identity_uuid, AccessRequest.panel == panel))
        return {"panel": panel, "title": title, "freshness_state": "not_shared", "message": bi("state.not_shared"), "request_access": {"state": "sent", "sent_at": req.sent_at.isoformat()} if req else {"state": "available"}}
    source_class = PANEL_SOURCE_CLASS[panel]
    timeout = float(get_config(db, "dashboard.panel.live_timeout_seconds", 2) or 2)
    simulate = set(get_config(db, "dashboard.simulate_timeout_panels", []) or [])
    started = time.monotonic()
    try:
        if panel in simulate:
            raise SourceTimeout(panel)
        payload, source, as_of, special = BUILDERS[panel](db, principal, company_id)
        if time.monotonic() - started > timeout:
            raise SourceTimeout(panel)
    except SourceTimeout:
        cached = db.scalar(select(PanelCache).where(PanelCache.company_id == company_id, PanelCache.panel == panel))
        if cached is None:
            record_event(db, event_type="SOURCE_TIMEOUT_NO_CACHE", category="system", outcome="failure", reason_code="SOURCE_TIMEOUT_NO_CACHE", actor_key=principal.actor_key, company_id=company_id, details={"panel": panel, "source": source_class})
            return {"panel": panel, "title": title, "freshness_state": "not_available", "reason_code": "SOURCE_TIMEOUT_NO_CACHE", "message": bi("state.not_available"), "retry": True, "stale_flag": True, "last_updated": None}
        fr = freshness_for(db, source_class, cached.data_as_of, now)
        state = fr["state"] if fr["state"] != "fresh" else "last_known"
        out = {"panel": panel, "title": title, "source": cached.source, "last_updated": cached.data_as_of.isoformat(), "last_updated_dubai": _dubai_iso(cached.data_as_of), "freshness_state": state, "stale_flag": True, "from_cache": True}
        if state == "cannot_be_confirmed":
            out.update({"message": bi("state.cannot_be_confirmed"), "reason_code": "SOURCE_TIMEOUT", "last_good_time": cached.data_as_of.isoformat()})
        else:
            out["data"] = cached.payload
        return out
    except PlatformError:
        raise
    except Exception as exc:  # noqa: BLE001 - fail soft per panel
        record_event(db, event_type="DASHBOARD_PANEL_FAILED", category="system", outcome="failure", reason_code="PANEL_FAILED", actor_key=principal.actor_key, company_id=company_id, details={"panel": panel, "error": type(exc).__name__})
        msg = bi("error.deadlines") if panel == "deadlines" else bi("state.could_not_be_loaded")
        return {"panel": panel, "title": title, "freshness_state": "could_not_be_loaded", "message": msg, "retry": True, "stale_flag": True, "last_updated": None}
    if special == "not_linked_yet":
        return {"panel": panel, "title": title, "source": source, "freshness_state": "not_linked_yet", "message": bi("state.not_linked_yet"), "data": payload, "stale_flag": False, "last_updated": as_of.isoformat() if as_of else None, "last_updated_dubai": _dubai_iso(as_of)}
    fr = freshness_for(db, source_class, as_of, now)
    _cache_put(db, company_id, panel, payload, source, as_of or now)
    out = {"panel": panel, "title": title, "source": source, "last_updated": as_of.isoformat() if as_of else None, "last_updated_dubai": _dubai_iso(as_of), "freshness_state": fr["state"], "stale_flag": fr["stale_flag"], "age_minutes": fr.get("age_minutes")}
    if fr["state"] == "cannot_be_confirmed":
        out.update({"message": bi("state.cannot_be_confirmed"), "reason_code": "SOURCE_STALE", "last_good_time": as_of.isoformat() if as_of else None})
        if panel in ("deadlines", "compliance"):
            out["data"] = payload  # deadlines stay visible with statutory dates unchanged; flagged stale
    else:
        out["data"] = payload
    return out


# --- next steps and alerts ----------------------------------------------------------------------------------------


def next_steps(db: Session, panels: dict[str, dict]) -> list[dict]:
    steps: list[dict] = []
    dl = panels.get("deadlines", {}).get("data") or {}
    for r in dl.get("items", []):
        name = r["name"]
        if r.get("draft_pack_id") and r.get("readiness") == "draft_ready":
            steps.append({"kind": "review_draft", "title": {"en": f"Review the prepared draft for {name['en']}", "ar": f"راجع المسودة المُعدّة لـ {name['ar']}"}, "ai_prepared": True, "status_label": r.get("readiness_label"), "link": f"/returns/{r['draft_pack_id']}" if r["obligation_type"] in ("vat_return", "ct_return") else "/dashboard#compliance", "due_date": r.get("due_date")})
        elif r.get("readiness") == "draft_ready":
            steps.append({"kind": "review_draft", "title": {"en": f"Review the prepared draft for {name['en']}", "ar": f"راجع المسودة المُعدّة لـ {name['ar']}"}, "ai_prepared": True, "status_label": r.get("readiness_label"), "link": "/deadlines", "due_date": r.get("due_date")})
        elif r.get("missing_items"):
            steps.append({"kind": "missing", "title": {"en": f"Add the missing items for {name['en']}", "ar": f"أضف البنود الناقصة لـ {name['ar']}"}, "ai_prepared": False, "items": r["missing_items"], "link": "/deadlines", "due_date": r.get("due_date")})
    comp = panels.get("compliance", {}).get("data") or {}
    for b in comp.get("banners", []):
        if b.get("next_action") == "renew_ejari":
            steps.append({"kind": "renew_ejari", "title": bi("next.renew_ejari"), "ai_prepared": False, "link": "/dashboard#compliance"})
        if b.get("kind") == "licence_expired":
            steps.append({"kind": "renew_licence", "title": bi("next.renew_licence"), "ai_prepared": False, "link": None})
    for d in comp.get("drafts", []):
        if d["review_status"] in ("draft_not_reviewed", "reviewed"):
            steps.append({"kind": "review_checklist", "title": bi("next.review_checklist"), "ai_prepared": True, "status_label": d["ai_label"], "link": "/dashboard#compliance"})
            break
    tax = panels.get("tax_status", {})
    if tax.get("freshness_state") == "not_linked_yet":
        steps.append({"kind": "add_tax_details", "title": bi("next.add_tax_details"), "ai_prepared": False, "link": "/deadlines"})
    steps.sort(key=lambda s_: (s_.get("due_date") or "9999-12-31"))
    return steps


def alerts(db: Session, principal, company_id: str) -> list[dict]:
    """Failed links, expired consent, lapsed Ejari, unpaid fee (fail soft per source)."""
    out: list[dict] = []
    try:
        from app.modules.datalinks.service import link_rows

        for r in link_rows(db, company_id).get("rows", []):
            if r.get("badge") == "failed":
                out.append({"kind": "link_failed", "severity": "warning", "text": bi("alert.link_failed", name=str(r.get("source_name"))), "link": "/consent"})
    except Exception:  # noqa: BLE001
        pass
    try:
        from app.modules.consent.models import Consent

        for c in db.scalars(select(Consent).where(Consent.company_id == company_id, Consent.status == "expired")):
            when = getattr(c, "expires_at", None)
            out.append({"kind": "consent_expired", "severity": "warning", "text": bi("alert.consent_expired", date=when.date().isoformat() if when else "-"), "link": "/consent"})
    except Exception:  # noqa: BLE001
        pass
    lic = db.scalar(select(Licence).where(Licence.company_id == company_id))
    if lic is not None and lic.ejari_expiry and lic.ejari_status != "not_applicable" and lic.ejari_expiry < dubai_today():
        out.append({"kind": "ejari_lapsed", "severity": "critical", "text": bi("alert.ejari_lapsed", date=lic.ejari_expiry.isoformat()), "link": "/dashboard#compliance"})
    try:
        from app.modules.subscriptions.models import BillingRequest, Subscription

        for sub in db.scalars(select(Subscription).where(Subscription.company_id == company_id)):
            br = db.scalar(select(BillingRequest).where(BillingRequest.subscription_id == sub.id).order_by(BillingRequest.created_at.desc()).limit(1)) if hasattr(BillingRequest, "subscription_id") else None
            unpaid = br is not None and getattr(br, "collection_status", None) in ("failed", "not_collected") and getattr(br, "status", None) == "billed"
            if unpaid:
                out.append({"kind": "unpaid_fee", "severity": "info", "text": bi("alert.unpaid_fee", licence=sub.licence_number), "link": "/subscription"})
    except Exception:  # noqa: BLE001
        pass
    return out


# --- remote-owner view --------------------------------------------------------------------------------------------


def approval_card_fixtures(now: datetime | None = None) -> list[dict]:
    """The four approval card states (Demo data). Live approval requests come from the approval registry (SC7)."""
    now = now or utcnow()
    base = {"is_demo": True, "demo_label": "Demo data", "what": {"en": "VAT return draft for the last quarter", "ar": "مسودة إقرار ضريبة القيمة المضافة للربع الماضي"}, "prepared_by": {"en": "AI-prepared, sent by delegate Omar Haddad", "ar": "أعدّه الذكاء الاصطناعي، وأرسله المفوّض عمر حداد"}}
    return [
        {**base, "card_id": "demo-card-waiting", "state": "waiting", "approve_by": (now + timedelta(hours=48)).isoformat(), "text": {"en": "Waiting for your approval. Nothing has been submitted.", "ar": "بانتظار موافقتك. لم يتم تقديم أي شيء."}, "actions": ["review_and_approve", "decline"]},
        {**base, "card_id": "demo-card-approved", "state": "approved", "decided_at": (now - timedelta(days=2)).isoformat(), "approver": "Priya Raman", "text": {"en": "Approved by Priya Raman. Filing is done by you on EmaraTax. Not verified by the authority.", "ar": "تمت الموافقة من Priya Raman."}, "actions": ["view_record"]},
        {**base, "card_id": "demo-card-declined", "state": "declined", "decided_at": (now - timedelta(days=5)).isoformat(), "approver": "Priya Raman", "text": {"en": "Declined by Priya Raman. Nothing was submitted. You can ask for a new draft.", "ar": "تم الرفض من Priya Raman. لم يتم تقديم أي شيء. يمكنك طلب مسودة جديدة."}, "actions": ["ask_for_new_draft"]},
        {**base, "card_id": "demo-card-expired", "state": "expired", "expires_at": (now - timedelta(days=1)).isoformat(), "text": {"en": "This request expired. Nothing was submitted. Ask for a new request.", "ar": "انتهت صلاحية هذا الطلب. لم يتم تقديم أي شيء. اطلب طلباً جديداً."}, "actions": ["request_again"]},
    ]


def remote_view(db: Session, principal, company_id: str, panels: dict[str, dict]) -> dict:
    not_current = sum(1 for p in panels.values() if p.get("freshness_state") in ("last_known", "cannot_be_confirmed", "not_available", "could_not_be_loaded"))
    last = max((p.get("last_updated") for p in panels.values() if p.get("last_updated")), default=None)
    return {
        "allowed_areas": ["dashboard", "reminders", "deadlines"],
        "remote_services_agent_enabled": bool(get_config(db, "remote_services_agent.enabled", False)),
        "freshness_banner": {"last_update": last, "last_update_dubai": _dubai_iso(datetime.fromisoformat(last)) if last else None, "sources_not_current": not_current},
        "approval_cards": approval_card_fixtures(),
        "approvals_empty": {"en": "No approvals waiting. When something needs your approval, it will appear here and we will remind you by your chosen channel.", "ar": "لا توجد موافقات معلّقة. عندما يحتاج أمر إلى موافقتك سيظهر هنا وسنذكّرك عبر القناة التي اخترتها."},
        "generic_denial": bi("remote.generic_denial"),
        "no_company": bi("remote.no_company"),
        "dubai_time_note": True,
    }


def assertion_age_minutes(db: Session, principal) -> float:
    from app.modules.identity.models import UserSession

    sess = db.get(UserSession, principal.session_id)
    if sess is None:
        return 10**6
    ref = sess.step_up_at or sess.created_at
    return (utcnow() - ref).total_seconds() / 60


def approve_card(db: Session, principal, company_id: str, card_id: str) -> dict:
    """Remote-owner approval wait states (fixtures). Delegates and agents never approve; stale assertions re-authenticate."""
    role = role_on(principal, company_id)
    if role not in OWNER_LEVEL:
        record_event(db, event_type="APPROVAL_REFUSED", category="approval", outcome="refused", reason_code="APPROVAL_NOT_PERMITTED", actor_key=principal.actor_key, actor_role=role, company_id=company_id, subject_type="approval_card", subject_id=card_id)
        db.commit()
        raise Forbidden("Only the owner can approve", reason_code="APPROVAL_NOT_PERMITTED")
    max_age = float(get_config(db, "remote.assertion_max_age_minutes", 15) or 15)
    if assertion_age_minutes(db, principal) > max_age:
        raise Unauthenticated("confirm it is you with UAE Pass to continue", reason_code="REAUTH_REQUIRED")
    card = next((c for c in approval_card_fixtures() if c["card_id"] == card_id), None)
    if card is None:
        raise NotFound("approval request not found", reason_code="NOT_FOUND")
    if card["state"] == "expired":
        raise Conflict("This request has expired", reason_code="REQUEST_EXPIRED")
    if card["state"] != "waiting":
        raise Conflict("this request was already decided", reason_code="ALREADY_DECIDED")
    return {"card_id": card_id, "demo": True, "recorded": False, "message": {"en": "Demo data: approvals are recorded by the approval registry after review (SC7).", "ar": "بيانات تجريبية: تُسجَّل الموافقات في سجل الموافقات بعد المراجعة."}}


def remote_agent_action(db: Session, principal, company_id: str, action: str, *, request_id: str | None = None) -> dict:
    """Remote Services Agent: switched off by default; no side effects; denial logged with the listed fields only."""
    enabled = bool(get_config(db, "remote_services_agent.enabled", False))
    if not enabled:
        rid = request_id or new_id("req")
        record_event(db, event_type="FEATURE_SWITCH_DENIAL", category="access", outcome="denied", reason_code="FEATURE_DISABLED", actor_key=principal.actor_key, actor_role=role_on(principal, company_id), company_id=company_id,
                     details={"request_id": rid, "endpoint": f"/api/companies/{company_id}/remote-agent/{action}", "switch": "remote_services_agent.enabled", "switch_state": "off", "result": "denied", "country_code": None})
        db.commit()
        raise Forbidden("This service is not available.", reason_code="FEATURE_DISABLED")
    return {"status": "not_available", "message": bi("remote.not_available")}


# --- remembered company -----------------------------------------------------------------------------------------


def remembered_company(db: Session, principal) -> dict:
    ids = principal.company_ids()
    row = db.get(RememberedCompany, principal.identity_uuid)
    note = None
    if row is not None and row.company_id not in ids:
        record_event(db, event_type="REMEMBERED_COMPANY_DELETED", category="access", actor_key=principal.actor_key, company_id=row.company_id, details={"reason": "no_longer_assigned"})
        db.delete(row)
        db.flush()
        row = None
        note = bi("remembered.no_longer")
    if row is not None:
        return {"state": "remembered", "company_id": row.company_id, "note": None}
    if len(ids) == 1:
        return {"state": "single", "company_id": ids[0], "note": note}
    if not ids:
        return {"state": "none", "company_id": None, "note": bi("no_companies")}
    return {"state": "chooser", "company_id": None, "note": note, "companies": ids}


def remember_company(db: Session, principal, company_id: str) -> dict:
    if company_id not in principal.company_ids():
        raise Forbidden("company not available to you", reason_code="NOT_YOUR_COMPANY")
    row = db.get(RememberedCompany, principal.identity_uuid)
    if row is None:
        db.add(RememberedCompany(identity_uuid=principal.identity_uuid, company_id=company_id))
    else:
        row.company_id, row.updated_at = company_id, utcnow()
    db.flush()
    return {"state": "remembered", "company_id": company_id}


# --- access requests and per-delegate panel switches ------------------------------------------------------------


def request_access(db: Session, principal, company_id: str, panel: str) -> dict:
    if panel not in PANELS:
        raise NotFound("panel not found", reason_code="NOT_FOUND")
    if role_on(principal, company_id) != "delegate":
        raise Forbidden("only delegates request access", reason_code="NOT_A_DELEGATE")
    row = db.scalar(select(AccessRequest).where(AccessRequest.company_id == company_id, AccessRequest.identity_uuid == principal.identity_uuid, AccessRequest.panel == panel))
    if row is None:
        row = AccessRequest(company_id=company_id, identity_uuid=principal.identity_uuid, panel=panel)
        db.add(row)
        db.flush()
        record_event(db, event_type="ACCESS_REQUESTED", category="access", actor_key=principal.actor_key, actor_role="delegate", company_id=company_id, details={"panel": panel})
    return {"panel": panel, "state": "sent", "sent_at": row.sent_at.isoformat(), "label": {"en": f"Request sent {row.sent_at.date().isoformat()}", "ar": f"تم إرسال الطلب {row.sent_at.date().isoformat()}"}}


def set_delegate_panel(db: Session, principal, company_id: str, role_id: str, panel: str, visible: bool) -> dict:
    role = db.get(CompanyRole, role_id)
    if role is None or role.company_id != company_id or role.role != "delegate":
        raise NotFound("delegate not found", reason_code="NOT_FOUND")
    if panel not in PANELS:
        raise NotFound("panel not found", reason_code="NOT_FOUND")
    row = db.scalar(select(DelegatePanelVisibility).where(DelegatePanelVisibility.company_id == company_id, DelegatePanelVisibility.identity_uuid == role.identity_uuid, DelegatePanelVisibility.panel == panel))
    if row is None:
        row = DelegatePanelVisibility(company_id=company_id, identity_uuid=role.identity_uuid, panel=panel, visible=visible, changes=[])
        db.add(row)
    row.visible, row.changed_at = visible, utcnow()
    row.changes = list(row.changes or []) + [{"at": utcnow().isoformat(), "visible": visible}]
    db.flush()
    record_event(db, event_type="DELEGATE_PANEL_VISIBILITY_CHANGED", category="access", actor_key=principal.actor_key, actor_role="owner", company_id=company_id, subject_type="company_role", subject_id=role_id, details={"panel": panel, "visible": visible})
    return {"role_id": role_id, "panel": panel, "visible": visible}


# --- aggregate -------------------------------------------------------------------------------------------------


def dashboard(db: Session, principal, company_id: str, *, panels: list[str] | None = None) -> dict:
    company = db.get(Company, company_id)
    role = role_on(principal, company_id)
    out_panels: dict[str, dict] = {}
    order = ["deadlines"] + [p for p in PANELS if p != "deadlines"]  # the deadlines panel loads first
    for p in order:
        if panels and p not in panels:
            continue
        out_panels[p] = load_panel(db, principal, company_id, p)
    lic = db.scalar(select(Licence).where(Licence.company_id == company_id))
    banner = None
    if lic is not None and lic.status in ("expired", "suspended"):
        from app.modules.compliance.strings import bi as cbi

        banner = {"kind": f"licence_{lic.status}", "text": cbi("banner.licence_expired", date=lic.expiry_date.isoformat() if lic.expiry_date else "-") if lic.status == "expired" else cbi("banner.licence_suspended"),
                  "disabled_actions": ["new_data_pulls", "new_return_packs", "approval_requests"], "available_actions": ["consent_withdrawal", "documents", "escalation", "help", "export"]}
    any_not_shared = any(p.get("freshness_state") == "not_shared" for p in out_panels.values())
    record_event(db, event_type="DASHBOARD_VIEWED", category="data_access", actor_key=principal.actor_key, actor_role=role, company_id=company_id, details={"panels": [p for p, v in out_panels.items() if v.get("freshness_state") != "not_shared"], "delegate_view": role == "delegate"})
    result = {
        "company": {"company_id": company_id, "trade_name_en": company.trade_name_en if company else None, "trade_name_ar": company.trade_name_ar if company else None, "licence_number": lic.licence_number if lic else None, "licence_status": lic.status if lic else None, "licence_expiry": lic.expiry_date.isoformat() if lic and lic.expiry_date else None},
        "panel_order": list(PANELS),
        "panels": [out_panels[p] for p in PANELS if p in out_panels],
        "next_steps": next_steps(db, out_panels),
        "alerts": alerts(db, principal, company_id),
        "licence_banner": banner,
        "acting_as": acting_as(db, principal, company_id),
        "not_shared_note": bi("state.withheld") if any_not_shared else None,
        "view": "remote_owner" if role == "remote_owner" else ("delegate" if role == "delegate" else "owner"),
        "k10_tile": bi("state.not_yet_measured"),
        "generated_at": utcnow().isoformat(),
        "timezone": "Asia/Dubai",
    }
    if role == "remote_owner":
        result["remote"] = remote_view(db, principal, company_id, out_panels)
    return result


def portfolio(db: Session, principal) -> dict:
    """SC12 delegate portfolio: companies sorted by nearest deadline, missing items per obligation, access limits."""
    from app.modules.access.service import permissions_for
    from app.modules.deadlines import service as dl

    rows = []
    for cid in principal.company_ids():
        perms = permissions_for(db, principal, cid)
        if "deadlines.view" not in perms:
            continue
        company = db.get(Company, cid)
        obligations, withheld = dl.filter_for_principal(db, principal, cid, dl.obligations_for(db, cid, include_done=False))
        dated = [o for o in obligations if o["days_left"] is not None]
        nearest = min((o["days_left"] for o in dated), default=None)
        role = role_on(principal, cid)
        funcs = functions_on(principal, cid)
        rows.append({
            "company_id": cid, "trade_name_en": company.trade_name_en if company else cid, "trade_name_ar": company.trade_name_ar if company else cid,
            "role": role, "functions": funcs, "nearest_days_left": nearest, "obligations": obligations, "withheld_count": withheld,
            "can_send_for_approval": "returns.send_for_approval" in perms, "can_approve": "returns.approve" in perms,
            "access_limits": _access_limits(role, funcs, perms),
        })
    rows.sort(key=lambda r: (r["nearest_days_left"] if r["nearest_days_left"] is not None else 10**6, r["trade_name_en"]))
    return {"companies": rows}


def _access_limits(role: str, funcs: list[str], perms: set[str]) -> list[dict]:
    if role in OWNER_LEVEL:
        return [{"en": "You are the owner of this company.", "ar": "أنت مالك هذه الشركة."}]
    out = [{"en": "You can prepare and view: " + (", ".join(funcs) if funcs else "nothing yet") + ".", "ar": "يمكنك الإعداد والاطلاع على: " + ("، ".join(funcs) if funcs else "لا شيء بعد") + "."}]
    if "returns.approve" not in perms:
        out.append({"en": "Only the owner can approve submissions.", "ar": "المالك وحده يمكنه اعتماد الإقرارات."})
    if "consent.grant" not in perms:
        out.append({"en": "Only the owner can grant or withdraw consent.", "ar": "المالك وحده يمكنه منح الموافقة أو سحبها."})
    if "subscription.change" not in perms:
        out.append({"en": "Only the owner can change the subscription.", "ar": "المالك وحده يمكنه تغيير الاشتراك."})
    return out

