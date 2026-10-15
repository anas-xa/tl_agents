"""Seeds for the phase map, gate register and integration checklist (E1-S7, E1-S8)."""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.time import dubai_today, utcnow
from app.modules.config.service import ensure_config, ensure_rule
from app.modules.phases import service
from app.modules.phases.models import GateRegisterRow, Increment, IntegrationChecklistRow, IntegrationSwitch

ORDER = 9

INCREMENTS = [
    {"id": "1A", "order": 1, "name_en": "Foundations and licence/subscription", "name_ar": "الأساسيات والرخصة/الاشتراك", "entry_gate_en": "DET billing hook and fee model", "entry_gate_ar": "ربط فوترة دائرة الاقتصاد والسياحة ونموذج الرسوم", "manual_fallback_en": "your company is loaded manually by the pilot team", "manual_fallback_ar": "يتم تحميل بيانات شركتك يدويًا من قبل فريق التجربة", "demo_outcome_en": "A company signs in, sees licence and subscription status in Arabic and English, grants and withdraws a consent record.", "demo_outcome_ar": "تسجّل الشركة الدخول وترى حالة الرخصة والاشتراك بالعربية والإنجليزية وتمنح سجل موافقة وتسحبه.", "functions": ["all"], "build_state": "built",
     "stories": [{"order": 1, "story_id": "E1-S1", "title": "UAE PASS sign-in with Emirates ID match and owner-role refusal"}, {"order": 2, "story_id": "E1-S2", "title": "Role model and delegates with high-impact toggles built but off"}, {"order": 3, "story_id": "E1-S5", "title": "Safe states (no owner, stale data, re-auth failure, pending/removed chips)"}, {"order": 4, "story_id": "E1-S3", "title": "Audit trail"}, {"order": 5, "story_id": "E2-S1", "title": "Licence record view from DET data"}, {"order": 6, "story_id": "E2-S2", "title": "Subscription display and opt-out, refund and complaint configuration"}, {"order": 7, "story_id": "E2-S3", "title": "Live DET billing collection", "gated": True}, {"order": 8, "story_id": "E2-S5", "title": "Live DET integrations until each go-live checklist is complete", "gated": True}],
     "manual_path": ["Licence record entry/upload if the DET feed is not live", "Bilingual shell"], "gated": ["Live DET billing collection", "Any live DET integration until its go-live checklist is complete"]},
    {"id": "1B", "order": 2, "name_en": "Tax calculation and reminders", "name_ar": "حساب الضرائب والتذكيرات", "entry_gate_en": "FTA format agreement for any direct link only", "entry_gate_ar": "اتفاق تنسيق الهيئة الاتحادية للضرائب لأي ربط مباشر فقط", "manual_fallback_en": "all except live feeds: manual upload and consent notice", "manual_fallback_ar": "كل شيء عدا التغذيات المباشرة: الرفع اليدوي وإشعار الموافقة", "demo_outcome_en": "The owner sees correct deadlines and a prepared calculation with its source data.", "demo_outcome_ar": "يرى المالك المواعيد الصحيحة وحسابًا مُعدًّا مع بيانات المصدر.", "functions": ["bookkeeping", "tax_preparation", "uploads"], "build_state": "in_build",
     "stories": [{"order": 1, "story_id": "E3-S1", "title": "Deadline and reminder engine (VAT 28 days after period end, CT 9 months after period end, official holiday calendar)"}, {"order": 2, "story_id": "E4-S3", "title": "Manual upload and consent notice"}, {"order": 3, "story_id": "E5-S1", "title": "Classification and bookkeeping"}, {"order": 4, "story_id": "E5-S2", "title": "VAT and CT calculation"}, {"order": 5, "story_id": "E5-S5", "title": "E-invoicing readiness notice (exchange only via accredited service provider)"}, {"order": 6, "story_id": "E4-S1", "title": "Bank link", "gated": True}, {"order": 7, "story_id": "E4-S2", "title": "FTA data exchange", "gated": True}, {"order": 8, "story_id": "E4-S4", "title": "ERP connectors", "gated": True}],
     "manual_path": ["All except live feeds"], "gated": ["Bank link", "FTA data exchange", "ERP connectors"]},
    {"id": "1C", "order": 3, "name_en": "Drafts and approvals", "name_ar": "المسودات والموافقات", "entry_gate_en": "Bank and Open Finance agreements", "entry_gate_ar": "اتفاقيات البنوك والتمويل المفتوح", "manual_fallback_en": "manual statements", "manual_fallback_ar": "كشوف الحساب اليدوية", "demo_outcome_en": "The owner approves a prepared return; the trail shows approver, time and data.", "demo_outcome_ar": "يوافق المالك على إقرار مُعدّ؛ ويُظهر السجل الموافق والوقت والبيانات.", "functions": ["tax_preparation"], "build_state": "not_started",
     "stories": [{"order": 1, "story_id": "E6-S1", "title": "Draft reports with source, basis, review status"}, {"order": 2, "story_id": "E6-S2", "title": "Owner/signatory approval record (who, when, data, signed, time-stamped)"}, {"order": 3, "story_id": "E6-S3", "title": "Filing-ready export for the owner to file in EmaraTax"}, {"order": 4, "story_id": "E6-S4", "title": "Delegate review"}, {"order": 5, "story_id": "E6-S5", "title": "Any submission by the platform", "gated": True}, {"order": 6, "story_id": "E1-S2b", "title": "Delegate approval rights unless the owner enables per right", "gated": True}],
     "manual_path": ["All"], "gated": ["Any submission by the platform", "Delegate approval rights unless owner enables per right", "Automatic filing excluded"]},
    {"id": "1D", "order": 4, "name_en": "Audit and escalation", "name_ar": "التدقيق والتصعيد", "entry_gate_en": "Audit service model agreed with competent authorities and MoE auditor register route", "entry_gate_ar": "اعتماد نموذج خدمة التدقيق من الجهات المختصة ومسار سجل مدققي وزارة الاقتصاد", "manual_fallback_en": "draft working files and escalation queue by named humans", "manual_fallback_ar": "ملفات عمل مسودة وقائمة تصعيد يديرها أشخاص معيّنون", "demo_outcome_en": "A draft working file goes through auditor review to a signed audit report.", "demo_outcome_ar": "ينتقل ملف العمل المسودة عبر مراجعة المدقق إلى تقرير تدقيق موقّع.", "functions": ["audit"], "build_state": "not_started",
     "stories": [{"order": 1, "story_id": "E7-S1", "title": "Audit-required flag from owner-confirmed tax group and QFZP fields"}, {"order": 2, "story_id": "E7-S2", "title": "Draft audit working file, unsigned"}, {"order": 3, "story_id": "E8-S1", "title": "Escalation with deterministic placeholder rules and minimal reject flow"}, {"order": 4, "story_id": "E7-S3", "title": "Auditor assignment, independence declaration, sign-off recording"}, {"order": 5, "story_id": "E7-S4", "title": "Signed audit report and sign-off (MoE register; Federal Law 12/2014 confirm instrument)", "gated": True}, {"order": 6, "story_id": "E8-S3", "title": "All legal advice, lawyer routing, virtual lawyer", "gated": True}],
     "manual_path": ["Draft working files and escalation queue by named humans"], "gated": ["Signed audit report and sign-off", "All legal advice, lawyer routing, virtual lawyer OFF; only neutral states and information-versus-advice label ship"]},
]

GATES = [
    {"gate_id": "gate_1a_det_billing", "increment": "1A", "gate_type": "entry_gate", "integration_row": "DET_billing", "description_en": "DET billing hook and fee model", "description_ar": "ربط فوترة دائرة الاقتصاد والسياحة ونموذج الرسوم", "fallback_path": "Manually loaded cohort", "required_evidence_list": ["DET written confirmation of the fee model", "DET billing hook interface specification"]},
    {"gate_id": "gate_1a_manual_cohort", "increment": "1A", "gate_type": "fallback", "integration_row": "none", "description_en": "Manually loaded cohort (fallback)", "description_ar": "مجموعة محمّلة يدويًا (مسار بديل)", "fallback_path": "Manually loaded cohort", "required_evidence_list": []},
    {"gate_id": "gate_1b_fta_format", "increment": "1B", "gate_type": "entry_gate", "integration_row": "FTA", "description_en": "FTA format agreement for any direct link only", "description_ar": "اتفاق تنسيق الهيئة الاتحادية للضرائب لأي ربط مباشر فقط", "fallback_path": "Manual upload and consent notice", "required_evidence_list": ["Written agreement or published technical specification naming the channel", "Report / return format"]},
    {"gate_id": "gate_1c_bank_open_finance", "increment": "1C", "gate_type": "entry_gate", "integration_row": "bank", "description_en": "Bank and Open Finance agreements", "description_ar": "اتفاقيات البنوك والتمويل المفتوح", "fallback_path": "Manual statements", "required_evidence_list": ["Open Finance licence evidence (operator or licensed provider)", "Signed contract covering account-information service", "Per-bank live coverage record"]},
    {"gate_id": "gate_1d_audit_model", "increment": "1D", "gate_type": "entry_gate", "integration_row": "auditor_register", "description_en": "Audit service model agreed with competent authorities and MoE auditor register route", "description_ar": "اعتماد نموذج خدمة التدقيق من الجهات المختصة ومسار سجل مدققي وزارة الاقتصاد", "fallback_path": "Draft working files and escalation queue by named humans", "required_evidence_list": ["Audit service model acceptance", "MoE auditor register source and date checked"]},
]


def _item(item_id: str, en: str, ar: str, item_type: str = "go_live_evidence", tag: str | None = None) -> dict:
    return {"item_id": item_id, "text_en": en, "text_ar": ar, "item_type": item_type, "tag": tag, "owner_name": None, "owner_role": None, "evidence_reference": None, "evidence_date": None, "approver_identity": None, "approved_at": None, "evidence_expires_at": None}


def _done(item: dict, ref: str, owner: str = "Qeonix product owner", approver: str = "lina (product owner)") -> dict:
    item.update({"owner_name": owner, "owner_role": "qeonix_product_owner", "evidence_reference": ref, "evidence_date": dubai_today().isoformat(), "approver_identity": approver, "approved_at": utcnow().isoformat(), "tag": None})
    return item


def _bank_items(bank: str) -> list[dict]:
    return [
        _item("circular_7_2023", "CBUAE Open Finance Regulation Circular 7/2023 text confirmed (Nebras API hub, Al Tareq consent/authorisation)", "تأكيد نص تعميم المصرف المركزي 7/2023 للتمويل المفتوح", "precondition", "[REG]"),
        _item("licence_evidence", "Open Finance Licence document and scope (operator's own, or licensed provider's licence plus signed contract covering account-information service)", "مستند ترخيص التمويل المفتوح ونطاقه", "go_live_evidence", "[OPEN]"),
        _item("corporate_coverage", "Provider confirmation of corporate-account coverage", "تأكيد المزود لتغطية الحسابات التجارية", "go_live_evidence", "[OPEN]"),
        _item("consent_model", "Recorded granular, time-limited, revocable consent from the authorised signatory (account, data type, purpose, period)", "موافقة مسجّلة ومحددة وقابلة للإلغاء من المفوّض بالتوقيع", "precondition"),
        _item("bank_live_coverage", f"{bank}: live coverage recorded (corporate coverage OPEN); screen scraping is never evidence or fallback", f"{bank}: تسجيل التغطية الفعلية", "go_live_evidence", "[OPEN]"),
    ]


ROWS = [
    {"row_id": "manual_upload", "integration": "manual_upload", "name_en": "Manual statement and ledger upload", "name_ar": "الرفع اليدوي لكشوف الحساب ودفاتر الأستاذ", "switch_key": "manual_upload", "phase": 1, "fallback_path": "n/a (this is the fallback)", "status": "confirmed_live", "live": True,
     "items": [_done(_item("notice_consent", "Recorded notice and consent/purpose statement (purpose, scope, retention, withdrawal, uploader)", "إشعار موافقة وبيان غرض مسجّل"), "Notice-and-consent record template v1 (Demo data)"), _done(_item("uploader_right", "Uploader is the owner or a delegate with the assigned right; not bank-consent evidence", "الرافع هو المالك أو مفوّض بحق مُسند"), "Delegate rights matrix E1-S2 (Demo data)"), _done(_item("unverified_label", "Data labelled 'uploaded by the company, not verified at source'; never bank-sourced; withdrawal stops processing", "تُعلَّم البيانات كغير مدققة من المصدر"), "String catalogue hosting.manual_upload_label (Demo data)")]},
    {"row_id": "uae_pass", "integration": "uae_pass", "name_en": "UAE PASS sign-in (mock provider in the pilot build)", "name_ar": "تسجيل الدخول عبر الهوية الرقمية (مزوّد تجريبي)", "switch_key": "uae_pass", "phase": 1, "fallback_path": "none: sign-in requires UAE PASS", "status": "confirmed_live", "live": True, "mock": True,
     "items": [_done(_item("oidc_agreement", "UAE PASS service agreement and client registration", "اتفاقية خدمة الهوية الرقمية وتسجيل العميل"), "Mock provider (Demo data) - production agreement to be confirmed")]},
    {"row_id": "det_licence_feed", "integration": "det_licence_feed", "name_en": "DET licence record feed (mock in the pilot build)", "name_ar": "تغذية سجل الرخص من دائرة الاقتصاد والسياحة (تجريبي)", "switch_key": "det_licence_feed", "phase": 1, "fallback_path": "Licence record entry/upload marked 'not checked'", "status": "confirmed_live", "live": True, "mock": True,
     "items": [_done(_item("det_feed_spec", "DET licence record interface and data-sharing terms", "واجهة سجل الرخص وشروط مشاركة البيانات"), "Mock feed (Demo data) - DET interface type OPEN")]},
    {"row_id": "det_billing", "integration": "DET_billing", "name_en": "DET billing hook (subscription collection)", "name_ar": "ربط فوترة دائرة الاقتصاد والسياحة", "switch_key": "det_billing_hook", "phase": 1, "fallback_path": "Hook off or test mode with no live charges; manual cohort",
     "items": [_item("legal_basis", "DET written confirmation of the legal basis for subscription collection", "تأكيد كتابي من الدائرة للأساس القانوني للتحصيل", "precondition", "[OPEN]"), _item("fee_setting", "Fee-setting approval", "اعتماد تحديد الرسوم", "precondition", "[OPEN]"), _item("contracting_party", "Contracting party and liability for agent output", "الطرف المتعاقد والمسؤولية عن مخرجات الوكيل", "precondition", "[OPEN]"), _item("dsa", "Data-sharing / processing agreement DET-operator; Dubai data law and DESC check", "اتفاقية مشاركة ومعالجة البيانات", "go_live_evidence"), _item("never_blocks", "Subscription never blocks or delays issuance or renewal; no live charges until confirmed", "الاشتراك لا يعيق الإصدار أو التجديد", "precondition")]},
    {"row_id": "bank_demo_a", "integration": "bank", "bank_code": "Bank A (demo)", "name_en": "Open Finance bank link - Bank A (demo)", "name_ar": "الربط المصرفي بالتمويل المفتوح - البنك أ (تجريبي)", "switch_key": "bank_link.bank_demo_a", "phase": 2, "fallback_path": "Upload statements (manual, unverified)", "items": _bank_items("Bank A (demo)")},
    {"row_id": "bank_demo_b", "integration": "bank", "bank_code": "Bank B (demo)", "name_en": "Open Finance bank link - Bank B (demo)", "name_ar": "الربط المصرفي بالتمويل المفتوح - البنك ب (تجريبي)", "switch_key": "bank_link.bank_demo_b", "phase": 2, "fallback_path": "Upload statements (manual, unverified)", "items": _bank_items("Bank B (demo)")},
    {"row_id": "erp", "integration": "ERP", "name_en": "Accounting / ERP connector", "name_ar": "موصل برنامج المحاسبة", "switch_key": "erp_connector", "phase": 2, "fallback_path": "Enter figures or upload an accounting export",
     "items": [_item("company_auth_pdpl", "Per-connection company authorisation plus PDPL record (purpose, data categories, retention, withdrawal, processing record)", "تفويض الشركة لكل ربط مع سجل حماية البيانات", "go_live_evidence"), _item("processor_contract", "Processor / supplier contract", "عقد المعالج أو المورد", "go_live_evidence"), _item("vendor_terms", "ERP vendor API terms; token scope read-only", "شروط واجهة المورد؛ نطاق الرمز للقراءة فقط", "precondition")]},
    {"row_id": "fta", "integration": "FTA", "name_en": "FTA data exchange and submission", "name_ar": "تبادل البيانات والتقديم مع الهيئة الاتحادية للضرائب", "switch_key": "fta_link_submission", "phase": 3, "fallback_path": "Filing-ready reports; owner/signatory files in EmaraTax",
     "items": [_item("channel", "Written agreement/authorisation or published technical specification naming the channel (machine access or EmaraTax with company authorisation)", "اتفاق كتابي أو مواصفة تقنية منشورة تحدد القناة", "precondition", "[OPEN]"), _item("format", "Report / return format agreed; never 'agreed' on an email or verbal assurance", "تنسيق التقرير/الإقرار متفق عليه", "precondition", "[OPEN]"), _item("company_auth", "Signed company authorisation per company", "تفويض موقّع لكل شركة", "go_live_evidence"), _item("third_party_access", "Machine access to third parties", "الوصول الآلي لأطراف ثالثة", "precondition", "[OPEN]")]},
    {"row_id": "e_invoicing_provider", "integration": "e_invoicing_provider", "name_en": "E-invoicing (accredited Peppol service provider)", "name_ar": "الفوترة الإلكترونية (مزود خدمة Peppol معتمد)", "switch_key": "e_invoicing_provider", "phase": 3, "fallback_path": "Readiness notice only",
     "items": [_item("accreditation", "Accredited Peppol service provider accreditation", "اعتماد مزود خدمة Peppol", "precondition", "[OPEN]"), _item("contract", "Contract with the accredited provider", "عقد مع المزود المعتمد", "go_live_evidence")]},
    {"row_id": "auditor_register", "integration": "auditor_register", "name_en": "MoE auditor register check", "name_ar": "التحقق من سجل مدققي وزارة الاقتصاد", "switch_key": "auditor_register_check", "phase": 4, "fallback_path": "Manual check recorded with date; match is not an independence declaration",
     "items": [_item("register_source", "MoE auditor register source (public) and machine-readable feed availability", "مصدر سجل المدققين وتوافر تغذية آلية", "precondition", "[REG]"), _item("processing_note", "Record source, date checked, processing note for auditor personal data; stale check never stays green", "تسجيل المصدر وتاريخ التحقق وملاحظة المعالجة", "go_live_evidence"), _item("service_model", "Audit service model acceptance", "قبول نموذج خدمة التدقيق", "precondition", "[OPEN]")]},
    {"row_id": "signed_audit", "integration": "signed_audit", "name_en": "Signed audit report", "name_ar": "تقرير التدقيق الموقّع", "switch_key": "signed_audit", "phase": 4, "fallback_path": "Draft working file only",
     "items": [_item("service_model_accepted", "Accepted audit service model with a licensed auditor signing", "نموذج خدمة تدقيق معتمد يوقّعه مدقق مرخّص", "precondition", "[OPEN]"), _item("law_12_2014", "Federal Law 12/2014 instrument confirmed", "تأكيد سند القانون الاتحادي 12/2014", "precondition", "[REG]")]},
    {"row_id": "payment_channel", "integration": "payment_channel", "name_en": "Online payment channel", "name_ar": "قناة الدفع الإلكتروني", "switch_key": "payment_channel", "phase": 1, "fallback_path": "Usual government payment channel",
     "items": [_item("channel_agreement", "Payment channel agreement and PCI scope", "اتفاقية قناة الدفع ونطاق PCI", "go_live_evidence", "[OPEN]")]},
]


def seed(db: Session) -> None:
    ensure_config(db, "phases.waves", [{"id": "1a", "label": "Wave 1a: register entity, status rule, switch guard, read-only register table, owner availability notes"}, {"id": "1b", "label": "Wave 1b: row detail drawer with checklist items, switch history, K12 checklist"}, {"id": "1c", "label": "Wave 1c: expandable phase strip, switch-off confirmation detail, daily snapshot and ON-without-evidence check"}], owner="Qeonix product owner", status="provisional")
    for key in ("virtual_lawyer", "remote_owner_agent", "aml_monitoring", "other_emirates", "federal_level", "aml_channel", "remote_services_agent"):
        ensure_config(db, f"phases.switch.{key}.enabled", False, owner="PM", status="confirmed", label="outside the pilot increments; behind a switch")
    ensure_config(db, "phases.gate_change_roles", ["platform_security_admin", "qeonix_product_owner", "det_pilot_manager"], owner="Platform", status="to_be_confirmed", label="Q462 open: who may change a gate")
    ensure_config(db, "phases.switch_on_role", "authorised administrator (role TBC, Q469)", owner="Platform", status="to_be_confirmed", label="role TBC")
    ensure_config(db, "phases.on_without_evidence_check", "daily", owner="Platform", status="provisional", label="target 0")
    ensure_rule(db, "phase-map-v1", "Phase map 1A-1D with entry gates, fallbacks and demo outcomes", instrument="E1-S7 settled decisions", status="provisional", owner_role="Qeonix product owner", parameters={"increments": ["1A", "1B", "1C", "1D"], "demo_done_rule": ["a", "b", "c", "d"], "k29_unlinked": True})
    for inc in INCREMENTS:
        if db.get(Increment, inc["id"]) is None:
            db.add(Increment(**inc))
    db.flush()
    for g in GATES:
        if db.scalar(select(GateRegisterRow).where(GateRegisterRow.gate_id == g["gate_id"]).limit(1)) is None:
            db.add(GateRegisterRow(**g, status="not_yet_confirmed", evidence_refs=[], changed_by="seed", change_reason="initial register"))
    db.flush()
    for r in ROWS:
        if db.scalar(select(IntegrationChecklistRow).where(IntegrationChecklistRow.row_id == r["row_id"]).limit(1)) is None:
            live = bool(r.get("live", False))
            row = IntegrationChecklistRow(**{k: v for k, v in r.items() if k != "live"}, changed_by="seed", change_reason="initial register", evidence_expires_at=(utcnow() + timedelta(days=365)) if live else None)
            db.add(row)
            db.flush()
            if db.get(IntegrationSwitch, row.switch_key) is None:
                db.add(IntegrationSwitch(switch_key=row.switch_key, row_id=row.row_id, state="ON" if live else "OFF", changed_by="seed", change_reason="seed: confirmed_live row" if live else "default OFF", history=[{"state": "ON" if live else "OFF", "changed_by": "seed", "changed_at": utcnow().isoformat(), "reason": "seed"}]))
    db.flush()


def seed_demo(db: Session) -> None:
    """Gate statuses for the demo: 1A open (with evidence + owner approval), 1B evidence received, 1C/1D not yet confirmed."""
    g = db.scalar(select(GateRegisterRow).where(GateRegisterRow.gate_id == "gate_1a_det_billing", GateRegisterRow.is_current.is_(True)))
    if g is not None and g.status == "not_yet_confirmed":
        service.change_gate_status(db, "gate_1a_det_billing", "evidence_received", changed_by="seed:qeonix_product_owner", change_reason="Demo data: DET pilot letter received", evidence_ref="DET-PILOT-LETTER-2026-01 (Demo data)")
        service.change_gate_status(db, "gate_1a_det_billing", "open", changed_by="seed:qeonix_product_owner", change_reason="Demo data: owner approved opening for the manual cohort", approved_by="uuid-lina-po")
        service.change_gate_status(db, "gate_1a_manual_cohort", "fallback_active", changed_by="seed:qeonix_product_owner", change_reason="Demo data: manual cohort loaded")
        service.change_gate_status(db, "gate_1b_fta_format", "evidence_received", changed_by="seed:qeonix_product_owner", change_reason="Demo data: FTA published specification reference received", evidence_ref="FTA-SPEC-REF-2026 (Demo data)")
    db.flush()
