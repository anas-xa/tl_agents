"""Reminder template registry, scheduling, delivery (outbox adapters) and K30 timeliness (E3-S4, E3-S5).

* Channels: portal (Phase 1A baseline, mandatory, cannot be switched off), email (Phase 1B, per-channel switch),
  SMS (Phase 1C, own switch, recorded opt-in), WhatsApp disabled by configuration, push not in Phase 1.
  Nothing leaves the platform: the email/SMS adapters only write ``reminder_outbox`` rows.
* Content: fixed bilingual templates; only allowed, enumerated parameters; a validator refuses amounts, identifiers,
  tax type (outbound / remote owners), status judgements, penalty amounts, promotional text and free text.
* Scheduling in Asia/Dubai on working days from the shared calendar; earlier only (never later, never past the due
  date) except the single overdue notice; catch-up and merge rules; one reminder per deadline per recipient per day.
"""

from __future__ import annotations

import hashlib
import re
from datetime import date, datetime, time, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import Forbidden, NotFound, SwitchedOff, ValidationFailed
from app.core.settings import get_settings
from app.core.time import to_dubai, utcnow
from app.modules.audit.service import record_event
from app.modules.companies.models import Company, CompanyRole
from app.modules.config.service import get_config
from app.modules.reminders.models import (
    K30Event,
    Reminder,
    ReminderOutbox,
    ReminderPreference,
    ReminderRequest,
    ReminderTemplate,
)
from app.modules.reminders.strings import (
    ACTION_LINES,
    CATEGORY_LABELS,
    DISCLAIMER,
    FLAG_LINES,
    SOURCE_TAGS,
    STATUS_LABELS,
    s,
)

POLICY_DEFAULT: dict[str, Any] = {
    "version": "reminder_policy_v1",
    "lead_times": {"licence_renewal": [60, 30, 14, 7, 1], "ejari_renewal": [90, 60, 30, 14, 7], "vat_return": [14, 7, 3, 1], "ct_return": [90, 60, 30, 14, 7, 1], "fta_registration": [14, 7, 3, 1], "other": [30, 14, 7]},
    "send_window": {"start": "08:00", "end": "18:00"},
    "max_reminders_per_deadline_per_day": 1,
    "retry_minutes": [15, 60, 240],
    "attempts": 3,
    "bounce": {"hard_to_unverified": 1, "soft_consecutive_to_undeliverable": 3, "check_hours": 24},
    "k30_window_minutes": 60,
    "overdue_notice": "once_next_working_day",
    "mandatory_types": ["licence_renewal", "ejari_renewal", "vat_return", "ct_return", "overdue", "consent_expiry"],
    "peak_windows": {"vat_days_before_due": 14, "ct_days_before_30_september": 30, "licence_expiry_cluster_days": 30},
    "delay": {"ops_alert_minutes": 60, "pilot_manager_summary_minutes": 240},
    "remote": {"bounce_retry_minutes": [60, 240, 1440], "local_window": {"start": "08:00", "end": "20:00"}},
    "held_send_within_hours": 24,
}
OWNER_LEVEL = ("owner", "remote_owner")

# --- content validator ---------------------------------------------------------------------------------------------
_I = re.IGNORECASE
FORBIDDEN_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("amount", re.compile(r"\bAED\s*\d|د\.إ|\b\d{1,3}(?:,\d{3})+(?:\.\d+)?\b|\b\d+\.\d{2}\b|درهم\s*\d", _I)),
    ("trn", re.compile(r"(?<!\d)\d{15}(?!\d)")),
    ("emirates_id", re.compile(r"784-?\d{4}-?\d{7}-?\d")),
    ("iban_or_account", re.compile(r"\bAE\d{2}[A-Z0-9]{8,}\b")),
    ("passport", re.compile(r"\b[A-Z]{1,2}\d{6,8}\b")),
    ("penalty_amount", re.compile(r"penalt\w*\s+(?:of\s+)?(?:AED\s*)?\d|fine\w*\s+of\s+\d", _I)),
    ("penalty_claim", re.compile(r"penalty applies|you will be fined|avoid penalties|penalty charged", _I)),
    ("debt_claim", re.compile(r"\byou owe\b|\byou are overdue\b", _I)),
    ("instruction", re.compile(r"\byou must file\b|\bshould elect\b|\byou should elect relief\b", _I)),
    ("status_judgement", re.compile(r"\b(?:you are|you're|company is|is)\s+(?:registered|exempt|eligible)\b|\bSBR[- ]eligible\b|\bnot required to\b", _I)),
    ("approval_or_filing_implied", re.compile(r"\b(?:you|owner)\s+(?:have\s+|has\s+)?approved\b|\b(?:has been|was)\s+(?:filed|submitted)\b|\bFiled\b")),
    ("promotional", re.compile(r"\b(?:upgrade|discount|special offer|promo\w*|subscribe now)\b", _I)),
    ("audit_or_risk", re.compile(r"\baudit (?:finding|report|certificate)\w*|\bAML\b|money laundering|risk flag", _I)),
    ("legal_matter", re.compile(r"\blawsuit|court case|legal action\b", _I)),
]
TAX_TYPE_PATTERN = re.compile(r"\bVAT\b|value added tax|corporate tax|ضريبة القيمة المضافة|ضريبة الشركات", _I)
URL_PATTERN = re.compile(r"https?://\S+")
ALLOWED_PARAMS = {"trade_name", "category", "due_date", "status", "source_tag", "action_line", "portal_link"}


def portal_link() -> str:
    """Sign-in-only portal link: no token, no identifiers, no query string."""
    return f"{get_settings().frontend_base_url.rstrip('/')}/deadlines"


def validate_content(text: str, *, channel_class: str, generic: bool, trade_name: str | None = None) -> list[str]:
    """Return the forbidden-content codes found in a rendered reminder (empty list = allowed)."""
    found = [code for code, pat in FORBIDDEN_PATTERNS if pat.search(text)]
    if (generic or channel_class in ("outbound", "sms")) and TAX_TYPE_PATTERN.search(text):
        found.append("tax_type_named")
    base = get_settings().frontend_base_url.rstrip("/")
    for url in URL_PATTERN.findall(text):
        if not url.startswith(base) or "?" in url or "#" in url or "token" in url.lower():
            found.append("link_not_sign_in_only")
    if channel_class == "sms" and trade_name and trade_name in text:
        found.append("company_name_in_sms")
    return found


# --- policy / switches --------------------------------------------------------------------------------------------


def policy(db: Session) -> dict:
    p = get_config(db, "reminders.policy.v1", POLICY_DEFAULT) or POLICY_DEFAULT
    return {**POLICY_DEFAULT, **p}


def channel_enabled(db: Session, channel: str) -> bool:
    if channel == "portal":
        return True
    if channel in ("push",):
        return False
    if not bool(get_config(db, f"reminders.channel.{channel}.enabled", False)):
        return False
    callbacks = get_config(db, "reminders.provider.callbacks", {"email": True, "sms": False}) or {}
    return bool(callbacks.get(channel, False))  # provider without callbacks -> channel not enabled


def channel_states(db: Session) -> dict:
    out = {}
    for ch in ("portal", "email", "sms", "whatsapp", "push"):
        enabled = channel_enabled(db, ch)
        reason = None
        if not enabled:
            reason = {"email": "phase_1b_switch_off", "sms": "phase_1c_switch_off", "whatsapp": "disabled_by_configuration", "push": "not_in_phase_1"}.get(ch)
        out[ch] = {"enabled": enabled, "reason": reason, "mandatory": ch == "portal"}
    return out


# --- calendar helpers (shared Rule and Calendar Reference) -------------------------------------------------------


def _dl():
    from app.modules.deadlines import service as dl

    return dl


def _jurisdiction(db: Session, obligation_type: str) -> str:
    return _dl().calendar_for_authority(db, "FTA" if obligation_type in ("vat_return", "ct_return") else "DET")


def _working(db: Session, d: date, jurisdiction: str) -> bool:
    return _dl().is_working_day(db, d, jurisdiction)  # weekend and confirmed public holidays are never send days


def _earlier_working(db: Session, d: date, jurisdiction: str) -> date:
    for _ in range(30):
        if _working(db, d, jurisdiction):
            return d
        d -= timedelta(days=1)
    return d


def _later_working(db: Session, d: date, jurisdiction: str) -> date:
    for _ in range(30):
        if _working(db, d, jurisdiction):
            return d
        d += timedelta(days=1)
    return d


def _window(db: Session) -> tuple[time, time]:
    w = policy(db)["send_window"]
    a, b = (time.fromisoformat(w["start"]), time.fromisoformat(w["end"]))
    return a, b


def _at_dubai(d: date, t: time) -> datetime:
    """Naive UTC instant of a Dubai local date and time (UTC+4, no DST)."""
    return datetime.combine(d, t) - timedelta(hours=4)


def _dubai_now(now: datetime) -> datetime:
    return to_dubai(now).replace(tzinfo=None)


# --- recipients and preferences -----------------------------------------------------------------------------------


def _has_owner_level(db: Session, company_id: str) -> bool:
    try:
        from app.modules.delegates.models import CompanyHold

        hold = db.get(CompanyHold, company_id)
        if hold is not None and hold.hold_state == "no_owner":
            return False
    except ImportError:  # pragma: no cover
        pass
    from app.modules.licences.models import Licence, LicencePerson

    lic = db.scalar(select(Licence).where(Licence.company_id == company_id))
    if lic is not None:
        persons = list(db.scalars(select(LicencePerson).where(LicencePerson.licence_id == lic.id)))
        if persons and not any(p.emirates_id_hash for p in persons):
            return False  # no Emirates ID on the DET record: nobody can hold an owner role
    return db.scalar(select(CompanyRole).where(CompanyRole.company_id == company_id, CompanyRole.role.in_(OWNER_LEVEL), CompanyRole.status == "active", CompanyRole.identity_uuid.is_not(None)).limit(1)) is not None


def recipients(db: Session, company_id: str, obligation_type: str, *, overdue: bool = False) -> tuple[list[dict], list[str]]:
    """Owner-level users get every reminder; delegates get copies only for assigned functions. No owner-level user ->
    in-portal to delegates with the deadlines function, labelled; none -> held."""
    fm = _dl().function_map(db)
    needed = set(fm.get(obligation_type, ["all"]))
    roles = list(db.scalars(select(CompanyRole).where(CompanyRole.company_id == company_id, CompanyRole.status == "active", CompanyRole.identity_uuid.is_not(None))))
    owner_level = _has_owner_level(db, company_id)
    out, flags = [], []
    if owner_level:
        out += [{"uuid": r.identity_uuid, "role": r.role, "remote": r.role == "remote_owner"} for r in roles if r.role in OWNER_LEVEL]
    delegates = [r for r in roles if r.role == "delegate" and set(r.functions or []) & needed]
    if owner_level:
        out += [{"uuid": r.identity_uuid, "role": "delegate", "remote": False, "copy": True} for r in delegates]
    else:
        flags.append("no_owner_level_user")
        out += [{"uuid": r.identity_uuid, "role": "delegate", "remote": False, "portal_only": True} for r in delegates]
    seen, uniq = set(), []
    for rec in out:
        if rec["uuid"] not in seen:
            seen.add(rec["uuid"])
            uniq.append(rec)
    return uniq, flags


def get_preference(db: Session, company_id: str, identity_uuid: str) -> ReminderPreference:
    p = db.scalar(select(ReminderPreference).where(ReminderPreference.company_id == company_id, ReminderPreference.identity_uuid == identity_uuid))
    if p is None:
        p = ReminderPreference(company_id=company_id, identity_uuid=identity_uuid)
        db.add(p)
        db.flush()
    return p


def _language(db: Session, pref: ReminderPreference) -> str:
    if pref.language in ("ar", "en"):
        return pref.language
    return "ar+en"  # no preference: Arabic and English together


def _channels_for(db: Session, pref: ReminderPreference, rec: dict) -> list[str]:
    chans = ["portal"]
    if rec.get("portal_only"):
        return chans
    if channel_enabled(db, "email") and pref.email_enabled and pref.email_verified and pref.email_state == "ok":
        chans.append("email")
    if channel_enabled(db, "sms") and pref.sms_enabled and pref.sms_opt_in_at and pref.mobile_verified:
        chans.append("sms")
    if channel_enabled(db, "whatsapp") and pref.whatsapp_enabled:
        chans.append("whatsapp")
    return chans


def preferences_view(db: Session, principal, company_id: str) -> dict:
    pref = get_preference(db, company_id, principal.identity_uuid)
    is_owner = any(r.role in OWNER_LEVEL for r in principal.roles_for(company_id))
    return {
        "language": pref.language,
        "channels": {"portal": True, "email": pref.email_enabled, "sms": pref.sms_enabled, "whatsapp": False},
        "sms_opt_in_at": pref.sms_opt_in_at.isoformat() if pref.sms_opt_in_at else None,
        "contacts": {"email": pref.email_masked, "email_verified": pref.email_verified, "email_state": pref.email_state, "mobile": pref.mobile_masked, "mobile_verified": pref.mobile_verified},
        "channel_states": channel_states(db),
        "mandatory_types": policy(db)["mandatory_types"],
        "locked_note": {"en": s("settings.locked", "en"), "ar": s("settings.locked", "ar")},
        "phase_note": {"en": s("settings.phase_note", "en"), "ar": s("settings.phase_note", "ar")},
        "role": "owner" if is_owner else "delegate",
        "policy_version": policy(db)["version"],
        "lead_times": policy(db)["lead_times"],
        "send_window": policy(db)["send_window"],
    }


def set_preferences(db: Session, principal, company_id: str, payload: dict) -> dict:
    """Each person edits only their own channels and language. Portal is mandatory; WhatsApp is disabled by
    configuration; SMS (Phase 1C) is stored as a recorded opt-in and stays inactive while its switch is off."""
    pref = get_preference(db, company_id, principal.identity_uuid)
    ch = payload.get("channels") or {}
    if ch.get("portal") is False:
        raise ValidationFailed("in-portal deadline reminders are always on; you can choose extra channels but not turn them off", reason_code="MANDATORY_REMINDER")
    if ch.get("whatsapp"):
        raise SwitchedOff("WhatsApp reminders are disabled by configuration", reason_code="WHATSAPP_DISABLED")
    if "language" in payload:
        if payload["language"] not in (None, "ar", "en"):
            raise ValidationFailed("language must be ar or en", reason_code="LANGUAGE_INVALID")
        pref.language = payload["language"]
    if "email" in ch:
        pref.email_enabled = bool(ch["email"])
    if "sms" in ch:
        pref.sms_enabled = bool(ch["sms"])
        pref.sms_opt_in_at = utcnow() if ch["sms"] else None
    pref.updated_at = utcnow()
    db.flush()
    record_event(db, event_type="REMINDER_PREFERENCES_CHANGED", category="reminder", actor_key=principal.actor_key, actor_role=principal.primary_role(), company_id=company_id, details={"email": pref.email_enabled, "sms": pref.sms_enabled, "sms_active": pref.sms_enabled and channel_enabled(db, "sms"), "language": pref.language})
    return preferences_view(db, principal, company_id)


# --- template registry ----------------------------------------------------------------------------------------------


def template(db: Session, template_id: str, locale: str) -> ReminderTemplate | None:
    return db.scalar(select(ReminderTemplate).where(ReminderTemplate.template_id == template_id, ReminderTemplate.locale == locale, ReminderTemplate.is_current.is_(True)))


def register_template(db: Session, template_id: str, *, kind: str, channel_class: str, locale: str, text: str, version: str, approver: str | None, status: str = "approved", actor_key: str | None = None) -> ReminderTemplate:
    """Stories consume templates, never define text. Every version is checked against the forbidden-content rules."""
    probe = text
    for p in ALLOWED_PARAMS:
        probe = probe.replace("{" + p + "}", "x")
    if re.search(r"\{[a-z_]+\}", probe):
        raise ValidationFailed("template uses a parameter that is not allowed", reason_code="TEMPLATE_PARAM_NOT_ALLOWED")
    bad = validate_content(probe, channel_class=channel_class, generic=channel_class != "portal")
    if bad:
        raise ValidationFailed("template contains forbidden content", reason_code="TEMPLATE_FORBIDDEN_CONTENT", details={"codes": bad})
    cur = template(db, template_id, locale)
    if cur is not None:
        cur.is_current = False
    row = ReminderTemplate(template_id=template_id, kind=kind, channel_class=channel_class, locale=locale, text=text, version=version, status=status, approver=approver)
    db.add(row)
    db.flush()
    record_event(db, event_type="REMINDER_TEMPLATE_CHANGED", category="config", actor_key=actor_key, subject_type="reminder_template", subject_id=f"{template_id}:{locale}", details={"version": version, "status": status})
    return row


def _fmt_date(d: date, lang: str) -> str:
    from app.modules.deadlines.strings import s as _  # noqa: F401  (keeps the deadlines catalogue loaded)

    months_en = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"]
    months_ar = ["يناير", "فبراير", "مارس", "أبريل", "مايو", "يونيو", "يوليو", "أغسطس", "سبتمبر", "أكتوبر", "نوفمبر", "ديسمبر"]
    return f"{d.day} {(months_ar if lang == 'ar' else months_en)[d.month - 1]} {d.year}"


def render(db: Session, template_id: str, locale: str, params: dict) -> str:
    """Render an approved template with enumerated parameters only (no free text, no AI output)."""
    unknown = set(params) - ALLOWED_PARAMS
    if unknown:
        raise ValidationFailed("parameter not allowed in reminders", reason_code="TEMPLATE_PARAM_NOT_ALLOWED", details={"params": sorted(unknown)})
    t = template(db, template_id, locale)
    if t is None or t.status != "approved":
        raise NotFound("no approved template for this language", reason_code="TEMPLATE_MISSING_LOCALE")
    values = {
        "trade_name": str(params.get("trade_name", "")),
        "category": CATEGORY_LABELS[params["category"]][locale] if params.get("category") else "",
        "due_date": _fmt_date(params["due_date"], locale) if isinstance(params.get("due_date"), date) else "",
        "status": STATUS_LABELS[params["status"]][locale] if params.get("status") else "",
        "source_tag": SOURCE_TAGS[params["source_tag"]][locale] if params.get("source_tag") else "",
        "action_line": ACTION_LINES[params["action_line"]][locale] if params.get("action_line") else "",
        "portal_link": portal_link(),
    }
    text = t.text
    for k, v in values.items():
        text = text.replace("{" + k + "}", v)
    return re.sub(r"\s{2,}", " ", text).strip()


# --- scheduling ---------------------------------------------------------------------------------------------------


def category_for(obligation_type: str, subtype: str | None, *, generic: bool) -> str:
    if obligation_type == "vat_return":
        return "tax_return" if generic else "vat_return"
    if obligation_type == "ct_return":
        return "tax_return" if generic else "corporate_tax_return"
    if obligation_type == "licence_renewal":
        return "licence_renewal"
    if obligation_type == "ejari_renewal":
        return "tenancy_renewal"
    if subtype == "chambers_membership":
        return "chamber_membership"
    return "licence_requirement"


def _source_tag(ob: dict) -> str:
    if ob["obligation_type"] in ("vat_return", "ct_return"):
        if ob["is_stated"]:
            return "fta_data"
        return "company_entered" if ob.get("deadline_source") == "OWNER_ENTERED" else "computed_not_confirmed"
    if ob.get("deadline_source") == "OWNER_ENTERED":
        return "company_entered"
    return "licence_record"


def _pd(v: str | None) -> date | None:
    return date.fromisoformat(v) if v else None


def _slots(db: Session, ob: dict, today: date, already_sent: bool) -> list[dict]:
    """Planned dates for one obligation: lead times moved earlier to valid working days; merge; catch-up; overdue."""
    pol = policy(db)
    due = _pd(ob.get("date_used")) or _pd(ob.get("provisional_date")) or _pd(ob.get("last_confirmed_date"))
    if due is None:
        return []
    anchor = _pd(ob.get("recommended_submit_by")) or due  # reminders driven from the earlier recommended date
    jur = _jurisdiction(db, ob["obligation_type"])
    leads = pol["lead_times"].get(ob["obligation_type"], pol["lead_times"].get("other", [30, 14, 7]))
    by_day: dict[date, dict] = {}
    passed = []
    for lead in sorted(leads, reverse=True):
        d = _earlier_working(db, anchor - timedelta(days=lead), jur)  # earlier only, never later
        if d < today:
            passed.append(lead)
            continue
        if d > due:
            continue
        if d in by_day:  # same deadline + recipient + same day: one reminder with the shorter-lead template
            by_day[d] = {**by_day[d], "lead": min(by_day[d]["lead"], lead), "merged": True}
        else:
            by_day[d] = {"date": d, "lead": lead, "kind": "standard", "merged": False}
    slots = sorted(by_day.values(), key=lambda x: x["date"])
    if due >= today and not slots and passed and not already_sent:
        d = _later_working(db, today, jur)
        catch = {"date": d if d <= due else today, "lead": min(passed), "kind": "catch_up", "merged": False, "immediate_portal": d > due}
        slots.append(catch)
    if due < today:
        d = _later_working(db, due + timedelta(days=1), jur)
        if d < today:
            d = _later_working(db, today, jur)
        slots.append({"date": d, "lead": None, "kind": "overdue", "merged": False})
    return slots


def _key(company_id: str, ob: dict, slot: dict, rec_uuid: str, channel: str) -> tuple[str, str]:
    lead = slot["lead"] if slot["lead"] is not None else "overdue"
    cancel = f"{company_id}|{ob['obligation_id']}|{ob.get('rule_version') or '-'}|{slot['kind']}:{lead}"
    return f"{cancel}|{rec_uuid}|{channel}", cancel


def schedule_for_company(db: Session, company_id: str, now: datetime | None = None) -> dict:
    """Build (or rebuild) the reminder set of a company. Sent reminders are never changed; unsent ones that are no
    longer wanted are cancelled ('deadline_superseded'); revived rows keep their idempotency key."""
    now = now or utcnow()
    today = _dubai_now(now).date()
    company = db.get(Company, company_id)
    if company is None:
        return {"planned": 0}
    obligations = _dl().obligations_for(db, company_id)
    pol = policy(db)
    window_minutes = int(pol["k30_window_minutes"])
    start, _end = _window(db)
    desired: set[str] = set()
    created = 0
    for ob in obligations:
        if ob["done"]:
            cancel_for_obligation(db, company_id, ob["obligation_id"], "filed_evidence_recorded" if ob.get("filed_state") else "task_completed")
            continue
        sent_before = db.scalar(select(Reminder).where(Reminder.company_id == company_id, Reminder.deadline_id == ob["obligation_id"], Reminder.status == "sent").limit(1)) is not None
        recs, flags = recipients(db, company_id, ob["obligation_type"])
        for slot in _slots(db, ob, today, sent_before):
            for rec in recs:
                if slot["kind"] == "overdue" and rec["role"] == "delegate" and not rec.get("copy") and not rec.get("portal_only"):
                    continue
                pref = get_preference(db, company_id, rec["uuid"])
                chans = ["portal"] if slot.get("immediate_portal") else _channels_for(db, pref, rec)
                for ch in chans:
                    if ch == "sms" and slot["kind"] != "standard":
                        continue  # SMS carries only the standard minimal template
                    idem, cancel = _key(company_id, ob, slot, rec["uuid"], ch)
                    desired.add(idem)
                    generic = ch != "portal" or rec.get("remote", False)
                    planned = _at_dubai(slot["date"], start if ch != "portal" else time(0, 0))  # in-portal: any hour of a working day
                    if slot["kind"] == "catch_up" and slot["date"] == today:
                        planned = max(now, planned) if ch != "portal" else now
                    row_flags = [f for f in flags] + (["merged"] if slot["merged"] else []) + (["catch-up"] if slot["kind"] == "catch_up" else []) + (["overdue notice"] if slot["kind"] == "overdue" else [])
                    if not ob.get("holiday_calendar_confirmed", True) or "holiday calendar not confirmed" in str(ob.get("notes")):
                        row_flags.append("holiday_calendar_not_confirmed")
                    existing = db.scalar(select(Reminder).where(Reminder.idempotency_key == idem))
                    values = {
                        "deadline_id": ob["obligation_id"], "recipient_role": rec["role"], "language": _language(db, pref), "channel": ch,
                        "kind": slot["kind"], "template_id": f"{slot['kind']}.{'portal' if ch == 'portal' else ('sms' if ch == 'sms' and slot['kind'] == 'standard' else 'outbound')}",
                        "deadline_category": category_for(ob["obligation_type"], ob.get("subtype"), generic=generic), "lead_time_days": slot["lead"], "planned_date": slot["date"],
                        "planned_send_at": planned, "window_minutes": window_minutes, "calendar_version": ob.get("calendar_version"), "rule_version": ob.get("rule_version"),
                        "due_date_stated": _pd(ob.get("date_used")) or _pd(ob.get("provisional_date")) or _pd(ob.get("last_confirmed_date")), "source_label": _source_tag(ob),
                        "computed_only_flag": not ob["is_stated"], "flags": row_flags, "cancellation_key": cancel,
                    }
                    if existing is None:
                        db.add(Reminder(company_id=company_id, recipient_uuid=rec["uuid"], idempotency_key=idem, **values))
                        created += 1
                    elif existing.status in ("planned", "held") or (existing.status == "cancelled" and existing.cancel_event == "deadline_superseded"):
                        for k, v in values.items():
                            setattr(existing, k, v)
                        if existing.status == "cancelled":
                            existing.status, existing.cancel_event, existing.cancelled_at = "planned", None, None
    # unsent reminders that are no longer wanted
    for r in db.scalars(select(Reminder).where(Reminder.company_id == company_id, Reminder.status.in_(("planned", "held", "retry_wait")), Reminder.kind.in_(("standard", "catch_up", "overdue")))):
        if r.idempotency_key not in desired:
            _cancel(db, r, "deadline_superseded")
    db.flush()
    return {"planned": created, "desired": len(desired)}


def _cancel(db: Session, r: Reminder, reason: str) -> None:
    r.status, r.cancel_event, r.cancelled_at = "cancelled", reason, utcnow()
    db.add(K30Event(reminder_id=r.reminder_id, company_id=r.company_id, channel=r.channel, planned_send_at=r.planned_send_at, window_minutes=r.window_minutes, cancel_event=reason, excluded=True, calendar_version=r.calendar_version))
    record_event(db, event_type="REMINDER_CANCELLED", category="reminder", reason_code=reason.upper(), company_id=r.company_id, subject_type="reminder", subject_id=r.reminder_id, details={"cancel_event": reason, "channel": r.channel, "excluded_from_k30": True})


def cancel_for_obligation(db: Session, company_id: str, obligation_id_or_key: str, reason: str) -> int:
    from app.modules.deadlines.models import Obligation

    ob = db.get(Obligation, obligation_id_or_key) or db.scalar(select(Obligation).where(Obligation.company_id == company_id, Obligation.obligation_key == obligation_id_or_key))
    if ob is None:
        return 0
    n = 0
    for r in db.scalars(select(Reminder).where(Reminder.company_id == company_id, Reminder.deadline_id == ob.obligation_id, Reminder.status.in_(("planned", "held", "retry_wait")))):
        _cancel(db, r, reason)
        n += 1
    db.flush()
    return n


def cancel_unsent_for_company(db: Session, company_id: str, reason: str = "deadline_superseded") -> int:
    """Batch step 1 (idempotent): cancel unsent deadline reminders before new deadlines are written."""
    n = 0
    for r in db.scalars(select(Reminder).where(Reminder.company_id == company_id, Reminder.status.in_(("planned", "retry_wait")), Reminder.kind.in_(("standard", "catch_up", "overdue")))):
        _cancel(db, r, reason)
        n += 1
    db.flush()
    return n


def on_access_lost(db: Session, company_id: str, identity_uuid: str) -> dict:
    """Delegate rights removed: their reminders are cancelled (access_lost, excluded from K30); the same deadlines
    stay with the owner-level users without duplicates."""
    n = 0
    for r in db.scalars(select(Reminder).where(Reminder.company_id == company_id, Reminder.recipient_uuid == identity_uuid, Reminder.status.in_(("planned", "held", "retry_wait")))):
        _cancel(db, r, "access_lost")
        n += 1
    res = schedule_for_company(db, company_id)
    return {"cancelled": n, **res}


def notice_dates_changed(db: Session, company_id: str, changed: list[dict]) -> int:
    """One consolidated 'dates changed' in-portal notice per company to owner-level users."""
    if not changed:
        return 0
    digest = hashlib.sha256(repr(sorted(c["obligation_key"] + c["new"] for c in changed)).encode()).hexdigest()[:16]
    recs, _ = recipients(db, company_id, "other")
    now = utcnow()
    n = 0
    for rec in recs:
        if rec["role"] not in OWNER_LEVEL:
            continue
        idem = f"{company_id}|dates_changed|{digest}|{rec['uuid']}"
        if db.scalar(select(Reminder).where(Reminder.idempotency_key == idem)) is not None:
            continue
        pref = get_preference(db, company_id, rec["uuid"])
        db.add(Reminder(company_id=company_id, recipient_uuid=rec["uuid"], recipient_role=rec["role"], language=_language(db, pref), channel="portal", kind="dates_changed", template_id="dates_changed.portal",
                        deadline_category="licence_requirement", planned_date=_dubai_now(now).date(), planned_send_at=now, window_minutes=int(policy(db)["k30_window_minutes"]), idempotency_key=idem, cancellation_key=f"{company_id}|dates_changed|{digest}", flags=["dates changed"]))
        n += 1
    db.flush()
    return n


# --- delivery -----------------------------------------------------------------------------------------------------


class AdapterError(RuntimeError):
    pass


def _deliver(db: Session, r: Reminder, body: str, subject: str | None, now: datetime) -> ReminderOutbox:
    """Channel adapters. Portal: visible in the reminder centre. Email/SMS: write to the outbox only (no real send)."""
    if r.channel in ("email", "sms") and bool(get_config(db, f"reminders.{r.channel}.adapter.simulate_failure", False)):
        raise AdapterError("provider did not accept the message")
    status = "visible" if r.channel == "portal" else "accepted"
    msg_id = None if r.channel == "portal" else f"outbox-{hashlib.sha256((r.idempotency_key + str(r.attempt)).encode()).hexdigest()[:12]}"
    row = ReminderOutbox(reminder_id=r.reminder_id, company_id=r.company_id, channel=r.channel, recipient_ref=r.recipient_uuid[:8] + "…", template_id=r.template_id, template_version=r.template_version, language=r.language, subject=subject, body=body, idempotency_key=r.idempotency_key, attempt=r.attempt, status=status, provider_message_id=msg_id, is_demo=r.is_demo)
    db.add(row)
    return row


def _compose(db: Session, r: Reminder, company: Company, ob) -> dict[str, str]:
    """Render in the recipient language(s); ar+en renders both. Raises when a locale is missing (held)."""
    locales = ["ar", "en"] if r.language == "ar+en" else [r.language]
    channel_class = "portal" if r.channel == "portal" else ("sms" if r.channel == "sms" else "outbound")
    tax = ob is not None and ob.obligation_type in ("vat_return", "ct_return")
    status = None
    if r.due_date_stated:
        n = (r.due_date_stated - _dubai_now(utcnow()).date()).days
        status = "overdue" if n < 0 else ("due_soon" if n <= 30 else "upcoming")
    action = "upload_receipt" if tax and status == "overdue" else ("confirm_authority" if r.computed_only_flag else "track")
    out = {}
    for loc in locales:
        params = {"trade_name": company.trade_name_ar if loc == "ar" else company.trade_name_en, "category": r.deadline_category, "due_date": r.due_date_stated, "status": status, "source_tag": r.source_label, "action_line": action}
        if channel_class == "sms":
            params.pop("trade_name")
            params.pop("source_tag")
            params.pop("action_line")
        if r.kind in ("dates_changed", "quarantine_decision_needed"):
            params = {"trade_name": params.get("trade_name", "")}
        text = render(db, r.template_id, loc, params)
        extra = [FLAG_LINES[f][loc] for f in ("date_under_review", "holiday_calendar_not_confirmed", "no_owner_level_user") if f in (r.flags or [])]
        if tax and r.kind in ("standard", "catch_up", "requested") and r.due_date_stated:
            extra.append(DISCLAIMER[loc].replace("{due_date}", _fmt_date(r.due_date_stated, loc)))
        if extra:
            text = text + " " + " ".join(extra)
        bad = validate_content(text, channel_class=channel_class, generic=channel_class != "portal" or r.recipient_role == "remote_owner", trade_name=company.trade_name_en)
        if bad:
            raise ValidationFailed("rendered reminder contains forbidden content", reason_code="FORBIDDEN_CONTENT", details={"codes": bad})
        out[loc] = text
    return out


def _k30(db: Session, r: Reminder, sent_at: datetime, *, held_delay: int | None = None) -> None:
    on_time = r.planned_send_at <= sent_at <= r.planned_send_at + timedelta(minutes=r.window_minutes)
    db.add(K30Event(reminder_id=r.reminder_id, company_id=r.company_id, channel=r.channel, planned_send_at=r.planned_send_at, window_minutes=r.window_minutes, sent_at=sent_at, on_time=on_time, catch_up=r.kind == "catch_up", held_delay_minutes=held_delay, calendar_version=r.calendar_version))
    delay = (sent_at - r.planned_send_at).total_seconds() / 60
    pol = policy(db)
    if delay > pol["delay"]["pilot_manager_summary_minutes"]:
        record_event(db, event_type="REMINDER_DELAY_PILOT_SUMMARY", category="reminder", company_id=r.company_id, subject_type="reminder", subject_id=r.reminder_id, details={"delay_minutes": int(delay)})
    elif delay > pol["delay"]["ops_alert_minutes"]:
        record_event(db, event_type="REMINDER_DELAY_OPS_ALERT", category="reminder", company_id=r.company_id, subject_type="reminder", subject_id=r.reminder_id, details={"delay_minutes": int(delay)})


def _recipient_has_access(db: Session, r: Reminder) -> bool:
    return db.scalar(select(CompanyRole).where(CompanyRole.company_id == r.company_id, CompanyRole.identity_uuid == r.recipient_uuid, CompanyRole.status == "active").limit(1)) is not None


def run_due(db: Session, now: datetime | None = None, *, company_id: str | None = None) -> dict:
    """Job function: send every reminder whose planned time has come (and retries whose backoff has elapsed)."""
    from app.modules.deadlines.models import Obligation

    now = now or utcnow()
    pol = policy(db)
    w_start, w_end = _window(db)
    counts = {"sent": 0, "cancelled": 0, "held": 0, "deferred": 0, "retry": 0, "fallback": 0}
    stmt = select(Reminder).where(Reminder.status.in_(("planned", "held", "retry_wait")), Reminder.planned_send_at <= now)
    if company_id:
        stmt = stmt.where(Reminder.company_id == company_id)
    due_rows = list(db.scalars(stmt.order_by(Reminder.planned_send_at)))
    for r in due_rows:
        if r.status == "retry_wait" and r.next_attempt_at and r.next_attempt_at > now:
            continue
        ob = db.get(Obligation, r.deadline_id) if r.deadline_id else None
        if r.deadline_id and (ob is None or ob.superseded and not ob.done):
            _cancel(db, r, "deadline_superseded")
            counts["cancelled"] += 1
            continue
        if ob is not None and ob.done:
            _cancel(db, r, "filed_evidence_recorded" if ob.filed_state else "task_completed")
            counts["cancelled"] += 1
            continue
        if not _recipient_has_access(db, r):
            _cancel(db, r, "access_lost")
            counts["cancelled"] += 1
            continue
        flags = list(r.flags or [])
        if ob is not None and ob.recalc_state == "recalculation_pending":
            within = r.due_date_stated is not None and (datetime.combine(r.due_date_stated, time(23, 59)) - timedelta(hours=4) - now) <= timedelta(hours=int(pol["held_send_within_hours"]))
            if not within:
                if r.status != "held":
                    r.status, r.hold_reason = "held", "batch_running"
                    record_event(db, event_type="REMINDER_HELD", category="reminder", reason_code="BATCH_RUNNING", company_id=r.company_id, subject_type="reminder", subject_id=r.reminder_id)
                counts["held"] += 1
                continue
            flags.append("date_under_review")  # sent on the old schedule, labelled
            r.flags = flags
        if r.channel in ("email", "sms"):
            local = _dubai_now(now).time()
            if not (w_start <= local < w_end):
                r.next_attempt_at = _at_dubai(_dubai_now(now).date() + (timedelta(days=1) if local >= w_end else timedelta()), w_start)
                r.status = "retry_wait"
                counts["deferred"] += 1
                continue
        company = db.get(Company, r.company_id)
        try:
            bodies = _compose(db, r, company, ob)
        except NotFound:
            if r.status != "held" or r.hold_reason != "missing_translation":
                r.status, r.hold_reason = "held", "missing_translation"
                record_event(db, event_type="REMINDER_HELD_MISSING_TRANSLATION", category="reminder", reason_code="TEMPLATE_MISSING_LOCALE", company_id=r.company_id, subject_type="reminder", subject_id=r.reminder_id, details={"template_id": r.template_id, "language": r.language, "reviewer_alert": True, "held_since": now.isoformat()})
            counts["held"] += 1
            continue
        except ValidationFailed as exc:
            r.status, r.hold_reason = "held", "blocked_content"
            record_event(db, event_type="REMINDER_BLOCKED_CONTENT", category="reminder", outcome="blocked", reason_code="FORBIDDEN_CONTENT", company_id=r.company_id, subject_type="reminder", subject_id=r.reminder_id, details={"codes": exc.details.get("codes", [])})
            counts["held"] += 1
            continue
        r.body_en, r.body_ar = bodies.get("en"), bodies.get("ar")
        body = "\n\n".join(bodies[k] for k in ("ar", "en") if k in bodies)
        held_delay = int((now - r.planned_send_at).total_seconds() / 60) if r.hold_reason == "batch_running" else None
        r.attempt += 1
        try:
            out = _deliver(db, r, body, "Qeonix deadline reminder" if r.channel == "email" else None, now)
        except AdapterError:
            retries = list(pol["remote"]["bounce_retry_minutes"] if r.recipient_role == "remote_owner" else pol["retry_minutes"])
            if r.attempt < int(pol["attempts"]):
                r.status, r.next_attempt_at, r.delivery_status = "retry_wait", now + timedelta(minutes=int(retries[min(r.attempt - 1, len(retries) - 1)])), "failed"
                counts["retry"] += 1
            else:
                r.status, r.delivery_status = "failed_fallback", "failed"
                _ensure_portal_copy(db, r, bodies, now)
                db.add(K30Event(reminder_id=r.reminder_id, company_id=r.company_id, channel=r.channel, planned_send_at=r.planned_send_at, window_minutes=r.window_minutes, sent_at=None, on_time=False, calendar_version=r.calendar_version))
                record_event(db, event_type="REMINDER_FALLBACK_PORTAL", category="reminder", outcome="failure", company_id=r.company_id, subject_type="reminder", subject_id=r.reminder_id, details={"channel": r.channel, "attempts": r.attempt})
                counts["fallback"] += 1
            continue
        r.status, r.hold_reason, r.delivery_status, r.provider_message_id = "sent", None, out.status if out.status != "visible" else "delivered", out.provider_message_id
        if r.channel == "portal":
            r.reminder_visible_at = now
        else:
            r.provider_accepted_at = now
        _k30(db, r, now, held_delay=held_delay)
        record_event(db, event_type="REMINDER_SENT", category="reminder", company_id=r.company_id, subject_type="reminder", subject_id=r.reminder_id, details={"channel": r.channel, "template_id": r.template_id, "kind": r.kind, "language": r.language})
        counts["sent"] += 1
    db.flush()
    return counts


def _ensure_portal_copy(db: Session, r: Reminder, bodies: dict, now: datetime) -> None:
    idem = r.idempotency_key.rsplit("|", 1)[0] + "|portal"
    portal = db.scalar(select(Reminder).where(Reminder.idempotency_key == idem))
    if portal is not None and portal.status == "sent":
        return
    if portal is None:
        portal = Reminder(company_id=r.company_id, deadline_id=r.deadline_id, recipient_uuid=r.recipient_uuid, recipient_role=r.recipient_role, language=r.language, channel="portal", kind=r.kind, template_id=r.template_id.replace(".outbound", ".portal").replace(".sms", ".portal"), deadline_category=r.deadline_category, lead_time_days=r.lead_time_days, planned_date=r.planned_date, planned_send_at=r.planned_send_at, window_minutes=r.window_minutes, calendar_version=r.calendar_version, rule_version=r.rule_version, due_date_stated=r.due_date_stated, source_label=r.source_label, computed_only_flag=r.computed_only_flag, flags=(r.flags or []) + ["fallback"], idempotency_key=idem, cancellation_key=r.cancellation_key)
        db.add(portal)
        db.flush()
    portal.body_en, portal.body_ar = bodies.get("en"), bodies.get("ar")
    portal.attempt += 1
    _deliver(db, portal, "\n\n".join(bodies[k] for k in ("ar", "en") if k in bodies), None, now)
    portal.status, portal.reminder_visible_at, portal.delivery_status = "sent", now, "delivered"
    _k30(db, portal, now)


def record_bounce(db: Session, company_id: str, identity_uuid: str, *, hard: bool) -> ReminderPreference:
    """1 hard bounce -> unverified; 3 consecutive soft bounces -> undeliverable; sending stops, portal prompt."""
    pref = get_preference(db, company_id, identity_uuid)
    b = policy(db)["bounce"]
    if hard:
        pref.email_verified, pref.email_state = False, "unverified" if b["hard_to_unverified"] <= 1 else pref.email_state
    else:
        pref.soft_bounces += 1
        if pref.soft_bounces >= int(b["soft_consecutive_to_undeliverable"]):
            pref.email_state = "undeliverable"
    db.flush()
    return pref


# --- reminder requests from the compliance cards ------------------------------------------------------------------


def request_reminder(db: Session, principal, company_id: str, *, requirement_type: str, due_date: date | None, reminder_date: date | None = None, channel: str = "portal") -> dict:
    roles = principal.roles_for(company_id)
    is_owner = any(r.role in OWNER_LEVEL for r in roles)
    if not is_owner:
        owner_pref_right = True
        for r in roles:
            if r.role == "delegate":
                pref = get_preference(db, company_id, principal.identity_uuid)
                owner_pref_right = pref.delegate_reminder_right
        if not owner_pref_right or not any(r.role == "delegate" for r in roles):
            raise Forbidden(s("request.no_right", "en"), reason_code="REMINDER_RIGHT_OFF")
    if bool(get_config(db, "reminders.service.unavailable", False)):
        raise SwitchedOff(s("request.failed", "en"), reason_code="REMINDER_SERVICE_UNAVAILABLE", details={"ics_fallback": True})
    if channel != "portal" and not channel_enabled(db, channel):
        channel = "portal"
    default_lead = int(get_config(db, "compliance.reminder.default_lead_days", 7) or 7)
    today = _dubai_now(utcnow()).date()
    when = reminder_date or (max(today, due_date - timedelta(days=default_lead)) if due_date else today + timedelta(days=int(get_config(db, "compliance.reminder.overdue_repeat_days", 3) or 3)))
    if due_date and due_date < today and reminder_date is None:
        when = today + timedelta(days=int(get_config(db, "compliance.reminder.overdue_repeat_days", 3) or 3))
    req = ReminderRequest(company_id=company_id, requirement_type=requirement_type, requested_by_uuid=principal.identity_uuid, requested_by_role=principal.primary_role(), reminder_date=when, channel=channel)
    db.add(req)
    db.flush()
    start, _ = _window(db)
    pref = get_preference(db, company_id, principal.identity_uuid)
    cat = {"licence_expiry": "licence_renewal", "ejari_expiry": "tenancy_renewal", "chambers_membership": "chamber_membership"}.get(requirement_type, "licence_requirement")
    rem = Reminder(company_id=company_id, recipient_uuid=principal.identity_uuid, recipient_role=principal.primary_role(), language=_language(db, pref), channel=channel, kind="requested",
                   template_id="requested.portal" if channel == "portal" else "requested.outbound", deadline_category=cat, planned_date=when, planned_send_at=_at_dubai(when, start),
                   window_minutes=int(policy(db)["k30_window_minutes"]), due_date_stated=due_date, source_label="licence_record", idempotency_key=f"{company_id}|request|{req.id}", cancellation_key=f"{company_id}|request|{req.id}", flags=["requested"])
    db.add(rem)
    db.flush()
    req.reminder_id = rem.reminder_id
    record_event(db, event_type="REMINDER_REQUESTED", category="reminder", actor_key=principal.actor_key, actor_role=principal.primary_role(), company_id=company_id, subject_type="reminder_request", subject_id=req.id, details={"requirement_type": requirement_type, "channel": channel})
    return request_dict(req)


def cancel_request(db: Session, principal, company_id: str, request_id: str) -> dict:
    req = db.get(ReminderRequest, request_id)
    if req is None or req.company_id != company_id or req.requested_by_uuid != principal.identity_uuid:
        raise NotFound("reminder request not found", reason_code="NOT_FOUND")
    req.status = "cancelled"
    rem = db.get(Reminder, req.reminder_id) if req.reminder_id else None
    if rem is not None and rem.status in ("planned", "held", "retry_wait"):
        _cancel(db, rem, "task_completed")
    db.flush()
    return {**request_dict(req), "message": {"en": s("request.cancelled", "en"), "ar": s("request.cancelled", "ar")}}


def request_dict(req: ReminderRequest) -> dict:
    return {"id": req.id, "requirement_type": req.requirement_type, "reminder_date": req.reminder_date.isoformat(), "channel": req.channel, "status": req.status,
            "message": {"en": s("request.set", "en", date=req.reminder_date.isoformat(), channel=req.channel), "ar": s("request.set", "ar", date=req.reminder_date.isoformat(), channel=req.channel)}}


def requests_for(db: Session, company_id: str, identity_uuid: str) -> list[dict]:
    return [request_dict(r) for r in db.scalars(select(ReminderRequest).where(ReminderRequest.company_id == company_id, ReminderRequest.requested_by_uuid == identity_uuid, ReminderRequest.status == "scheduled"))]


# --- reads -------------------------------------------------------------------------------------------------------


def reminder_dict(r: Reminder) -> dict:
    return {"reminder_id": r.reminder_id, "deadline_id": r.deadline_id, "channel": r.channel, "kind": r.kind, "language": r.language, "template_id": r.template_id, "deadline_category": r.deadline_category,
            "lead_time_days": r.lead_time_days, "planned_date": r.planned_date.isoformat(), "planned_send_at": r.planned_send_at.isoformat(), "status": r.status, "hold_reason": r.hold_reason,
            "flags": r.flags or [], "cancel_event": r.cancel_event, "inbox_state": r.inbox_state, "body": {"en": r.body_en, "ar": r.body_ar}, "sent_at": (r.reminder_visible_at or r.provider_accepted_at).isoformat() if (r.reminder_visible_at or r.provider_accepted_at) else None,
            "due_date": r.due_date_stated.isoformat() if r.due_date_stated else None, "source_label": r.source_label, "is_demo": r.is_demo}


def inbox(db: Session, company_id: str, identity_uuid: str) -> dict:
    sent = list(db.scalars(select(Reminder).where(Reminder.company_id == company_id, Reminder.recipient_uuid == identity_uuid, Reminder.channel == "portal", Reminder.status == "sent").order_by(Reminder.reminder_visible_at.desc())))
    held = list(db.scalars(select(Reminder).where(Reminder.company_id == company_id, Reminder.recipient_uuid == identity_uuid, Reminder.status == "held", Reminder.hold_reason == "missing_translation")))
    notices = []
    for r in held:
        n = (r.due_date_stated - _dubai_now(utcnow()).date()).days if r.due_date_stated else None
        cat = CATEGORY_LABELS.get(r.deadline_category, CATEGORY_LABELS["licence_requirement"])
        notices.append({"reminder_id": r.reminder_id, "text": {loc: s("inbox.held_notice", loc, obligation=cat[loc], date=_fmt_date(r.due_date_stated, loc) if r.due_date_stated else "-", n=str(n) if n is not None else "-") for loc in ("en", "ar")}})
    upcoming = list(db.scalars(select(Reminder).where(Reminder.company_id == company_id, Reminder.recipient_uuid == identity_uuid, Reminder.status == "planned").order_by(Reminder.planned_send_at).limit(10)))
    return {"items": [reminder_dict(r) for r in sent], "unread": sum(1 for r in sent if r.inbox_state == "unread"), "held_notices": notices, "upcoming": [reminder_dict(r) for r in upcoming],
            "empty_message": {"en": s("inbox.empty", "en"), "ar": s("inbox.empty", "ar")}, "requests": requests_for(db, company_id, identity_uuid)}


def acknowledge(db: Session, company_id: str, identity_uuid: str, reminder_id: str) -> dict:
    r = db.get(Reminder, reminder_id)
    if r is None or r.company_id != company_id or r.recipient_uuid != identity_uuid:
        raise NotFound("reminder not found", reason_code="NOT_FOUND")
    r.inbox_state = "acknowledged"
    db.flush()
    return reminder_dict(r)


def company_reminders(db: Session, company_id: str) -> list[dict]:
    return [reminder_dict(r) for r in db.scalars(select(Reminder).where(Reminder.company_id == company_id).order_by(Reminder.planned_send_at))]


def k30_summary(db: Session) -> dict:
    """DET admin: aggregated timeliness only (no individual data). Cancellations are excluded; catch-up separate."""
    rows = list(db.scalars(select(K30Event)))
    counted = [e for e in rows if not e.excluded and not e.catch_up]
    catch = [e for e in rows if e.catch_up and not e.excluded]
    on_time = sum(1 for e in counted if e.on_time)
    no_owner = sum(1 for cid in db.scalars(select(Company.id)) if not _has_owner_level(db, cid))
    return {"measured": len(counted), "on_time": on_time, "rate": round(on_time / len(counted), 3) if counted else None, "catch_up_count": len(catch), "excluded_cancellations": sum(1 for e in rows if e.excluded), "companies_without_reachable_owner": no_owner}


def outbox_rows(db: Session, company_id: str | None = None) -> list[dict]:
    stmt = select(ReminderOutbox).order_by(ReminderOutbox.created_at)
    if company_id:
        stmt = stmt.where(ReminderOutbox.company_id == company_id)
    return [{"id": o.id, "reminder_id": o.reminder_id, "channel": o.channel, "template_id": o.template_id, "language": o.language, "status": o.status, "body": o.body, "attempt": o.attempt, "created_at": o.created_at.isoformat()} for o in db.scalars(stmt)]
