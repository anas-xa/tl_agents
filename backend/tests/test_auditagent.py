"""E7-S1..E7-S4: exception rules and flags, audit-required indicator, draft audit working file, licensed-auditor review."""

from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.errors import Conflict, Forbidden, PlatformError
from app.core.time import utcnow
from app.demo import CO_ALNOOR, CO_BLUEDUNE, CO_GULFTECH, CO_SAFWA, PERSONA_UUIDS
from app.main import app
from app.modules.audit.models import AuditEvent
from app.modules.audit.service import actor_key_for
from app.modules.auditagent import engagement as eng_svc
from app.modules.auditagent import indicator as ind
from app.modules.auditagent import review as rv
from app.modules.auditagent import workfile as wf
from app.modules.auditagent.models import (
    AuditCriteriaVersion,
    AuditRequiredResult,
    AuditWorkingFile,
    Engagement,
    ExceptionFlag,
    ExceptionRule,
    RecomputeJob,
    RegisterSnapshot,
)
from app.modules.auditagent.strings import STRINGS, WATERMARK
from app.modules.companies.models import CompanyRole
from app.modules.config.service import set_config
from app.modules.identity.models import StaffRole
from tests.conftest import sign_in

AED = 100


class P:
    """Minimal principal for service-level calls."""

    def __init__(self, persona: str, name: str, staff: list[str] | None = None):
        self.identity_uuid = PERSONA_UUIDS.get(persona, persona)
        self.display_name = name
        self.actor_key = actor_key_for(self.identity_uuid)
        self.staff_roles = staff or []

    def roles_for(self, company_id):
        return []

    def has_staff(self, *roles):
        return any(r in self.staff_roles for r in roles)

    def primary_role(self):
        return self.staff_roles[0] if self.staff_roles else "none"


LAYLA = P("layla", "Layla Haddad", ["licensed_auditor"])


def _events(db, event_type, reason=None):
    stmt = select(AuditEvent).where(AuditEvent.event_type == event_type)
    if reason:
        stmt = stmt.where(AuditEvent.reason_code == reason)
    return list(db.scalars(stmt))


def _client(persona: str) -> TestClient:
    c = TestClient(app, follow_redirects=False)
    sign_in(c, persona)
    return c


def _rule(db, rule_id):
    return db.scalar(select(ExceptionRule).where(ExceptionRule.rule_id == rule_id, ExceptionRule.is_current.is_(True)))


def _rec(rid, d, amount, cp="Gulf Supplies LLC", **kw):
    base = {"record_id": rid, "record_version": 1, "source": kw.pop("source", "ledger"), "date": d, "posted_date": kw.pop("posted_date", d), "amount_fils": amount, "direction": kw.pop("direction", "out"), "vat_fils": None, "vat_code": None, "account_code": None, "counterparty": cp, "invoice_number": None, "currency": "AED", "description": "x", "manual": True, "trn": None, "has_trn_field": False}
    base.update(kw)
    return base


# --- E7-S1 rule register and rules ------------------------------------------------------------------------------


def test_rule_register_r1_and_cash_rule_off(db):
    rules = {r.rule_id: r for r in rv.current_rules(db)}
    assert {"AX01", "AX01b", "AX02", "AX03", "AX04", "AX05", "AX06", "AX07", "AX08", rv.CASH_RULE_ID} <= set(rules)
    assert all(r.rule_version == "r1" for r in rules.values())
    assert rules["AX01"].default_severity == "High" and rules["AX01b"].default_severity == "Low" and rules["AX02"].default_severity == "Medium"
    assert rules["AX04"].bank_dependent and rules["AX05"].bank_dependent and rules["AX08"].bank_dependent and not rules["AX01"].bank_dependent
    cash = rules[rv.CASH_RULE_ID]
    assert cash.enabled is False and cash.label == "internal review threshold, not a legal limit" and cash.parameters["threshold_fils"] is None
    assert cash.legal_anchor == "heuristic" and cash.instrument is None
    # AED 55,000 is never held or shown as a legal limit anywhere in the register or the strings.
    blob = str([rv.rule_row(r) for r in rules.values()]) + str(STRINGS)
    assert "55,000" not in blob and "5500000" not in blob and "55000" not in blob
    # Even a cash-like row above 55,000 never raises a flag with the pilot rule set (rule OFF, no value chosen).
    big = [_rec("c1", date(2026, 5, 3), 6_000_000, cp="Walk-in", description="Cash deposit")]
    assert rv.RULE_FUNCS[rv.CASH_RULE_ID](cash, cash.parameters, big, [], {}) == []
    cyc = rv.run_review_cycle(db, CO_ALNOOR)
    db.commit()
    assert cyc.status == "completed" and rv.CASH_RULE_ID not in cyc.rule_versions
    assert db.scalar(select(ExceptionFlag).where(ExceptionFlag.rule_id == rv.CASH_RULE_ID)) is None
    # Per-company tuning is possible (internal analytical rule) and still labelled as not a legal limit.
    rv.set_company_override(db, CO_ALNOOR, rv.CASH_RULE_ID, enabled=True, parameters={"threshold_fils": 1_000_000}, set_by="test")
    enabled, params = rv.effective_rule(db, CO_ALNOOR, cash)
    out = rv.RULE_FUNCS[rv.CASH_RULE_ID](cash, params, big, [], {})
    assert enabled and out and out[0]["basis"]["label"] == "internal review threshold, not a legal limit"


def test_rule_functions_fire_as_specified(db):
    f = rv.RULE_FUNCS
    ctx = {"today": date(2026, 10, 15), "period": (date(2026, 1, 1), date(2026, 12, 31)), "vat_rate": lambda code, on, p: 5.0 if code == "SR" else None}
    p = lambda rid: _rule(db, rid).parameters  # noqa: E731
    led = [_rec("a", date(2026, 5, 1), 105_000, invoice_number="INV-0099"), _rec("b", date(2026, 5, 20), 105_000, invoice_number=" inv-99 ")]
    assert len(f["AX01"](_rule(db, "AX01"), p("AX01"), led, [], ctx)) == 1  # trim, case-fold, strip leading zeros, same fils
    led2 = [_rec("a", date(2026, 5, 1), 105_000, invoice_number="A1"), _rec("b", date(2026, 5, 6), 105_000, invoice_number="A2"), _rec("c", date(2026, 5, 30), 105_000, invoice_number="A3")]
    assert [x["anchors"] for x in f["AX01b"](_rule(db, "AX01b"), p("AX01b"), led2, [], ctx)] == [["a", "b"]]  # within 7 days only
    vat = [_rec("v1", date(2026, 5, 1), 105_000, vat_code="SR", vat_fils=5_000), _rec("v2", date(2026, 5, 1), 105_000, vat_code="SR", vat_fils=5_200)]
    assert [x["anchors"] for x in f["AX02"](_rule(db, "AX02"), p("AX02"), vat, [], ctx)] == [["v2"]]  # AED 1.00 tolerance per line
    trn = [_rec("t1", date(2026, 5, 1), 1_200_000, vat_code="SR", trn="1234", has_trn_field=True), _rec("t2", date(2026, 5, 1), 1_200_000, vat_code="SR", has_trn_field=False)]
    assert [x["anchors"] for x in f["AX03"](_rule(db, "AX03"), p("AX03"), trn, [], ctx)] == [["t1"]]  # missing field = unable to assess
    bank = [_rec("s1", date(2026, 9, 1), 900_000, source="bank"), _rec("s2", date(2026, 10, 10), 900_000, source="bank")]
    assert [x["anchors"] for x in f["AX04"](_rule(db, "AX04"), p("AX04"), [], bank, ctx)] == [["s1"]]  # 14-day age rule
    edge = [_rec("e1", date(2026, 6, 30), 2_000_000), _rec("e2", date(2026, 6, 15), 2_000_000)]
    assert [x["anchors"] for x in f["AX06"](_rule(db, "AX06"), p("AX06"), edge, [], ctx)] == [["e1"]]
    dated = [_rec("f1", date(2026, 11, 1), 100, posted_date=date(2026, 10, 1)), _rec("f2", date(2025, 12, 20), 100, posted_date=date(2026, 1, 5))]
    assert sorted(x["reason_code"] for x in f["AX07"](_rule(db, "AX07"), p("AX07"), dated, [], ctx)) == ["dated_outside_period_posted_inside", "future_dated"]
    short = [_rec(f"h{i}", date(2026, 8, 1) + timedelta(days=i), 100_000, source="bank") for i in range(30)] + [_rec("big", date(2026, 9, 5), 90_000_000, source="bank")]
    assert f["AX08"](_rule(db, "AX08"), p("AX08"), [], short, ctx) == []  # suppressed without 6 months of history


def test_flag_lineage_revisions_and_k16(db):
    rule = _rule(db, "AX02")
    rows = [rv._evidence_row(_rec("r1", date(2026, 5, 1), 105_000, vat_code="SR"))]
    finding = {"rule": rule, "anchors": ["r1"], "rows": rows, "reason_code": "vat_amount_mismatch", "flag_type": "vat_check", "basis": {}, "severity": "Medium", "amount": 105_000}
    assert rv.upsert_flag(db, CO_SAFWA, "FY2026", finding) == (True, False)
    assert rv.upsert_flag(db, CO_SAFWA, "FY2026", finding) == (False, False)  # equal hash: nothing written
    fl = db.scalar(select(ExceptionFlag).where(ExceptionFlag.company_id == CO_SAFWA))
    assert fl.status == "New" and fl.rule_version == "r1" and rv.flag_dict(db, fl)["ai_label"]["en"] == "AI-generated, pending human review"
    with pytest.raises(PlatformError):
        rv.decide(db, fl, decision="dismiss", reason="too short", decided_by_uuid="u", decided_by_name="Khalid", actor_role="owner", role_label=None, actor_key=None)
    rv.decide(db, fl, decision="confirm", reason="Checked against the supplier invoice copy.", decided_by_uuid="u", decided_by_name="Khalid", actor_role="owner", role_label=None, actor_key=None)
    # Non-material change (description only) -> no revision; decision stands.
    rows_desc = [{**rows[0], "description": "renamed"}]
    assert rv.upsert_flag(db, CO_SAFWA, "FY2026", {**finding, "rows": rows_desc}) == (False, False)
    assert fl.status == "Confirmed"
    # Material change on a shared anchor -> same lineage, new revision, status back to New, decision kept.
    rows2 = [{**rows[0], "amount_fils": 106_000}, rv._evidence_row(_rec("r2", date(2026, 5, 2), 50_000))]
    assert rv.upsert_flag(db, CO_SAFWA, "FY2026", {**finding, "anchors": ["r1", "r2"], "rows": rows2}) == (False, True)
    db.refresh(fl)
    d = rv.flag_dict(db, fl)
    assert fl.current_revision_no == 2 and fl.status == "New" and fl.evidence_changed_since is not None
    assert len(d["decisions"]) == 1 and d["decisions"][0]["revision_no"] == 1
    # Revision 2: dismiss then change to confirm (replaces the earlier count on the same revision).
    rv.decide(db, fl, decision="dismiss", reason="Not relevant for this period.", decided_by_uuid="u", decided_by_name="Khalid", actor_role="owner", role_label=None, actor_key=None)
    rv.decide(db, fl, decision="confirm", reason="Second look: the VAT line is wrong.", decided_by_uuid="u", decided_by_name="Khalid", actor_role="owner", role_label=None, actor_key=None)
    # Revision 3 superseded before any decision -> not counted.
    rv.upsert_flag(db, CO_SAFWA, "FY2026", {**finding, "anchors": ["r1"], "rows": [{**rows[0], "amount_fils": 107_000}]})
    rv.upsert_flag(db, CO_SAFWA, "FY2026", {**finding, "anchors": ["r1"], "rows": [{**rows[0], "amount_fils": 108_000}]})
    db.commit()
    cells = [c for c in rv.k16(db, CO_SAFWA) if c["rule_id"] == "AX02"]
    assert sum(c["confirmed"] for c in cells) == 2 and sum(c["dismissed"] for c in cells) == 0
    assert rv.k16_by_rule_version(db, CO_SAFWA)[("AX02", "r1")] == 1.0
    # A rule version change with the same outcome writes nothing; old flags keep their version.
    new = rv.new_rule_version(db, "AX06", parameters={"last_days_of_period": 3}, change_reason="pilot tuning", owner="PO")
    assert new.rule_version == "r2" and _rule(db, "AX06").rule_version == "r2"
    with pytest.raises(PlatformError):
        rv.new_rule_version(db, "AX02", parameters={"tolerance_fils_per_line": 200}, change_reason="x", owner="PO")  # VAT rule needs tax specialist


def test_k16_counts_demo_decisions_by_rule_and_version(db):
    rows = {(c["rule_id"], c["rule_version"]): c for c in rv.k16(db, CO_ALNOOR)}
    assert rows[("AX01b", "r1")]["confirmed"] == 1 and rows[("AX06", "r1")]["dismissed"] == 1
    flags = {f.rule_id: f for f in rv.list_flags(db, CO_ALNOOR)}
    assert {f.status for f in flags.values()} == {"New", "Confirmed", "Dismissed"}


def test_decision_api_permissions(client, db):
    sign_in(client, "khalid")
    data = client.get(f"/api/companies/{CO_ALNOOR}/audit").json()
    new = next(e for e in data["exceptions"] if e["status"] == "New")
    url = f"/api/companies/{CO_ALNOOR}/audit/exceptions/{new['id']}/decide"
    r = client.post(url, json={"decision": "explain", "reason": "short"})
    assert r.status_code == 422 and r.json()["error"] == "REASON_TOO_SHORT"
    r = client.post(url, json={"decision": "explain", "reason": "Supplier issued a corrected invoice."})
    assert r.status_code == 200 and r.json()["status"] == "Explained" and r.json()["decisions"][0]["by"]
    detail = client.get(f"/api/companies/{CO_ALNOOR}/audit/exceptions/{new['id']}").json()
    assert detail["rule_version"] == "r1" and detail["evidence"] and detail["ai_label"]["en"].startswith("AI-generated, reviewed by")
    with _client("omar") as omar:  # delegate without the audit function: can view, cannot decide
        view = omar.get(f"/api/companies/{CO_ALNOOR}/audit").json()
        assert view["exceptions"] and view["decide_disabled_reason"]["en"] == "You can view this flag. Ask the owner to give you the right to decide."
        assert view["working_file"] is None and view["working_file_hidden"]["en"].startswith("You do not have access to audit status")
        r = omar.post(url, json={"decision": "confirm", "reason": "I think this is right."})
        assert r.status_code == 403 and r.json()["error"] == "NO_DECIDE_RIGHT"
    with _client("priya") as priya:  # remote owner: summary only
        view = priya.get(f"/api/companies/{CO_BLUEDUNE}/audit").json()
        assert view["exceptions"] is None and view["exceptions_hidden_reason"]["en"] == "Flag details are available to owners in the UAE and their delegates."
    with _client("layla") as layla:  # auditor without an engagement on Al Noor
        r = layla.post(url, json={"decision": "confirm", "reason": "Looks right to me here."})
        assert r.status_code == 403 and r.json()["error"] == "NOT_ASSIGNED"
    with _client("noroles") as other:
        r = other.get(f"/api/companies/{CO_ALNOOR}/audit")
        assert r.status_code == 403


def test_consent_gate_stops_reading_on_withdrawal_and_masks(db):
    from app.modules.consent.models import Consent
    from app.modules.consent.service import invalidate_gate

    set_config(db, "auditagent.consent_gate.batch_max_records", 10, changed_by="test")
    db.commit()

    def withdraw(_db, company_id, source, batch_no):
        if source == "ledger" and batch_no == 1:
            for c in _db.scalars(select(Consent).where(Consent.company_id == company_id, Consent.consent_type == "ledger_invoice_authorisation")):
                c.status, c.withdrawn_at = "withdrawn_on_platform", utcnow()
                invalidate_gate(c.consent_id)
            _db.flush()

    rv.BATCH_HOOK = withdraw
    try:
        cyc = rv.run_review_cycle(db, CO_ALNOOR)
    finally:
        rv.BATCH_HOOK = None
    db.commit()
    assert cyc.status == "cancelled_on_withdrawal" and cyc.batches_saved == 1 and cyc.batches_discarded == 1
    assert "ledger" not in cyc.sources_read and cyc.sources_refused["ledger"] == "withdrawn"
    assert _events(db, "CYCLE_CANCELLED_ON_WITHDRAWAL")
    flags = rv.list_flags(db, CO_ALNOOR)
    assert flags and all(f.source_withdrawn for f in flags if f.source == "ledger")
    d = rv.flag_dict(db, flags[0])
    assert all(r.get("masked") and "amount_fils" not in r and "counterparty" not in r for r in d["evidence"])
    assert d["rule_id"] and d["severity"] and d["period"]  # type, severity, rule and period remain
    # Next cycle: source not read; deletion of stored copies within the schedule (assumed 24 h).
    cyc2 = rv.run_review_cycle(db, CO_ALNOOR)
    assert "ledger" not in cyc2.sources_read
    assert rv.run_evidence_deletion(db, now=utcnow() + timedelta(hours=25)) >= 1


def test_bank_rules_hidden_without_bank_consent(db):
    cyc = rv.run_review_cycle(db, CO_SAFWA)
    assert all(rid not in cyc.rule_versions for rid in ("AX04", "AX05", "AX08"))
    assert rv.bank_rules_visible(db, CO_SAFWA) is False


# --- E7-S2 audit-required indicator ----------------------------------------------------------------------------


def _inputs(net_fils, *, tg="no", qfzp="not_applicable", months=12, full=True, src="ledger", vat=0, others=(), as_of=None, confirmed=True):
    ps = date(2025, 1, 1)
    pe = (ps + timedelta(days=round(months * 30.4375) - 1)) if months != 12 else date(2025, 12, 31)
    figs = [{"source": src, "amount_fils": net_fils + vat, "vat_fils": vat, "net_fils": net_fils, "covers_full_period": full, "owner_confirmed": confirmed, "as_of": (as_of or utcnow()).isoformat()}]
    for s_, v in others:
        figs.append({"source": s_, "amount_fils": v, "vat_fils": 0, "net_fils": v, "covers_full_period": True, "owner_confirmed": True, "as_of": utcnow().isoformat()})
    return {"has_profile": True, "period_start": ps, "period_end": pe, "period_confirmed": True, "tax_group": tg, "qfzp": qfzp, "figures": figs if net_fils is not None else [], "notes": []}


def _eval(db, inputs):
    return ind.compute(db, "co_x", inputs, db.get(AuditCriteriaVersion, "v1"))


def test_indicator_threshold_band_edges_and_strictly_above(db):
    cases = {
        44_999_999_99: ("likely_not_required", []),
        45_000_000_00: ("cannot_determine", ["near_threshold"]),
        49_999_999_99: ("cannot_determine", ["near_threshold"]),
        50_000_000_00: ("cannot_determine", ["near_threshold", "at_threshold"]),
        50_000_000_01: ("cannot_determine", ["near_threshold"]),
        55_000_000_00: ("cannot_determine", ["near_threshold"]),
        55_000_000_01: ("likely_required", []),
        90_000_000_00: ("likely_required", []),
    }
    for net, (result, reasons) in cases.items():
        out = _eval(db, _inputs(net))
        assert out["result"] == result, (net, out)
        assert out["cannot_determine_reasons"] == reasons, (net, out)
    assert _eval(db, _inputs(90_000_000_00))["reasons"] == ["revenue_threshold"]
    # Strictly above: with the band set to 0, exactly 50m is not above; 50m + 1 fils is.
    set_config(db, "auditagent.criteria.near_threshold_band_pct", 0, changed_by="test")
    assert _eval(db, _inputs(50_000_000_00))["result"] == "cannot_determine"
    assert "at_threshold" in _eval(db, _inputs(50_000_000_00))["cannot_determine_reasons"]
    assert _eval(db, _inputs(50_000_000_01))["result"] == "likely_required"
    assert _eval(db, _inputs(49_999_999_99))["result"] == "likely_not_required"
    # VAT-inclusive 52.5m -> net 50m -> at the threshold.
    set_config(db, "auditagent.criteria.near_threshold_band_pct", 10, changed_by="test")
    out = _eval(db, _inputs(50_000_000_00, vat=2_500_000_00))
    assert out["governing_revenue_fils"] == 50_000_000_00 and "at_threshold" in out["cannot_determine_reasons"]


def test_indicator_every_cannot_determine_reason(db):
    no_profile = {"has_profile": False, "period_start": None, "period_end": None, "period_confirmed": False, "tax_group": "unknown", "qfzp": "not_applicable", "figures": [], "notes": []}
    out = _eval(db, no_profile)
    assert out["result"] == "cannot_determine" and out["cannot_determine_reasons"] == ["missing_profile"] and {"legal_form", "tax_period", "annual_revenue"} <= set(out["checklist"])
    out = _eval(db, _inputs(30_000_000_00, full=False))
    assert out["cannot_determine_reasons"] == ["coverage_failure"]  # partial period = missing, not prorated
    out = _eval(db, _inputs(52_000_000_00, others=[("owner_declared", 47_000_000_00)]))
    assert "source_conflict" in out["cannot_determine_reasons"]
    out = _eval(db, _inputs(80_000_000_00, others=[("owner_declared", 30_000_000_00)]))
    assert out["result"] == "cannot_determine" and out["cannot_determine_reasons"] == ["source_conflict"]
    out = _eval(db, _inputs(80_000_000_00, others=[("owner_declared", 70_000_000_00)]))
    assert out["result"] == "likely_required" and "source_discrepancy_same_result" in out["caveats"]  # same result either way
    out = _eval(db, _inputs(20_000_000_00, as_of=utcnow() - timedelta(days=400)))
    assert out["cannot_determine_reasons"] == ["stale_data"]
    out = _eval(db, _inputs(20_000_000_00, confirmed=False))
    assert out["cannot_determine_reasons"] == ["missing_profile"] and "revenue_confirmation" in out["checklist"]
    # Owner-declared only (ledger absent) is accepted as 'declared, unverified'; e-invoice alone is never primary.
    assert _eval(db, _inputs(10_000_000_00, src="owner_declared"))["revenue_source"] == "owner_declared"
    assert _eval(db, _inputs(10_000_000_00, src="e_invoice"))["cannot_determine_reasons"] == ["missing_profile"]


def test_indicator_twelve_month_equivalent_split(db):
    out = _eval(db, _inputs(20_000_000_00, months=4))
    assert out["period_months"] == 4 and out["twelve_month_equivalent_fils"] == 60_000_000_00
    assert out["result"] == "cannot_determine" and "non_standard_period" in out["cannot_determine_reasons"]
    out = _eval(db, _inputs(10_000_000_00, months=6))
    assert out["result"] == "likely_not_required" and out["twelve_month_equivalent_fils"] == 20_000_000_00
    out = _eval(db, _inputs(70_000_000_00, months=6))
    assert out["result"] == "likely_required"  # actual and equivalent both above


def test_indicator_tax_group_qfzp_and_unknowns(db):
    assert _eval(db, _inputs(1_000_000_00, tg="yes"))["result"] == "likely_required"  # regardless of revenue
    assert _eval(db, _inputs(48_000_000_00, tg="yes"))["result"] == "likely_required"  # even inside the band
    assert _eval(db, _inputs(2_000_000_00, qfzp="yes"))["reasons"] == ["qualifying_free_zone_person"]
    out = _eval(db, _inputs(2_000_000_00, tg="unknown"))
    assert out["result"] == "cannot_determine" and "tax_group_status" in out["checklist"] and "revenue_only" in out["caveats"]  # never 'likely not required'
    assert _eval(db, _inputs(2_000_000_00))["result"] == "likely_not_required"
    assert ind.resolve_inputs(db, CO_ALNOOR)["qfzp"] == "not_applicable"  # QFZP defaults to not applicable for mainland


def test_indicator_demo_states_and_summary(db):
    s = {c: ind.audit_flag_summary(db, c) for c in (CO_ALNOOR, CO_GULFTECH, CO_BLUEDUNE, CO_SAFWA)}
    assert s[CO_ALNOOR]["state"] == "likely_not_required"
    assert s[CO_GULFTECH]["state"] == "likely_required" and s[CO_GULFTECH]["reason_codes"] == ["tax_group"]
    assert s[CO_BLUEDUNE]["state"] == "cannot_determine" and s[CO_BLUEDUNE]["reason_codes"] == ["near_threshold"] and s[CO_BLUEDUNE]["case_id"]
    assert s[CO_SAFWA]["state"] == "not_yet_assessed" and s[CO_SAFWA]["evaluated_at"] is None
    assert set(s[CO_ALNOOR]) >= {"state", "reason_codes", "wording_keys", "evaluated_at"}
    from app.modules.escalation.models import EscalationCase

    case = db.get(EscalationCase, s[CO_BLUEDUNE]["case_id"])
    assert case.module == "audit" and case.status not in ("closed", "resolved")


def test_indicator_wording_never_mandatory_or_sales(db):
    banned = ("mandatory", "compulsory", "is required", "must", "you need", "exempt", "audit certificate", "price", "buy", "recommended", "penalty", "certified")
    rows = [ind.latest_result(db, c) for c in (CO_ALNOOR, CO_GULFTECH, CO_BLUEDUNE)] + [None]
    for row in rows:
        d = ind.result_dict(db, row)
        for lang in ("en", "ar"):
            text = " ".join(d["text"][lang].values()).casefold()
            for word in banned:
                assert word not in text, (word, d["state"], lang)
    gt = ind.result_dict(db, ind.latest_result(db, CO_GULFTECH))
    assert gt["text"]["en"]["may_be_required"].startswith("Audited financial statements may be required for corporate tax")
    assert gt["text"]["en"]["badge_indicative"] == "Indicative, pending expert confirmation" and gt["ask_auditor_enabled"] is False
    an = ind.result_dict(db, ind.latest_result(db, CO_ALNOOR))
    assert an["text"]["en"]["headline_likely_not_required"] == "Likely not required: the current criteria do not indicate an audit for your company. This is not advice."
    assert an["text"]["ar"]["headline_likely_not_required"] == "غير مطلوب على الأرجح: المعايير الحالية لا تشير إلى حاجة شركتك إلى تدقيق. هذا ليس استشارة."
    assert "disclaimer" in an["text"]["en"] and "Federal Tax Authority" in an["text"]["en"]["disclaimer"]


def test_owner_actions_cannot_override(client, db):
    sign_in(client, "khalid")
    base = f"/api/companies/{CO_ALNOOR}/audit/flag/actions"
    before = ind.latest_result(db, CO_ALNOOR).result
    for bad in ("override", "dismiss", "set_result"):
        r = client.post(base, json={"action": bad})
        assert r.status_code == 422 and r.json()["error"] == "OWNER_CANNOT_OVERRIDE"
    assert client.post(base, json={"action": "acknowledge"}).status_code == 200
    assert client.post(base, json={"action": "hide_banner"}).status_code == 200
    r = client.post(base, json={"action": "dispute"})
    assert r.status_code == 422 and r.json()["error"] == "DISPUTE_CODE_REQUIRED"
    assert client.post(base, json={"action": "dispute", "reason_code": "revenue_wrong", "reason": "Revenue includes a one-off asset sale."}).status_code == 200
    r = client.post(base, json={"action": "request_review"})
    assert r.status_code == 200 and r.json()["case_id"] and r.json()["target_working_days"] == 3 and "not a commitment" in r.json()["target_label"]["en"]
    r = client.post(base, json={"action": "ask_auditor"})
    assert r.status_code == 403 and r.json()["error"] == "FEATURE_SWITCHED_OFF"
    db.expire_all()
    after = ind.latest_result(db, CO_ALNOOR)
    assert after.result == before and after.acknowledged_by and after.banner_hidden_at
    assert _events(db, "DISPUTE_OPENED") and _events(db, "OVERRIDE_REFUSED", "OWNER_CANNOT_OVERRIDE")
    with _client("priya") as priya:  # remote owner: read-only, cannot dismiss the notice
        r = priya.post(f"/api/companies/{CO_BLUEDUNE}/audit/flag/actions", json={"action": "acknowledge"})
        assert r.status_code == 403


def test_recompute_on_input_change_idempotent_and_retries(client, db):
    n0 = len(list(db.scalars(select(AuditRequiredResult).where(AuditRequiredResult.company_id == CO_ALNOOR))))
    ind.evaluate(db, CO_ALNOOR)
    db.commit()
    assert len(list(db.scalars(select(AuditRequiredResult).where(AuditRequiredResult.company_id == CO_ALNOOR)))) == n0  # same run key
    sign_in(client, "khalid")
    r = client.post(f"/api/companies/{CO_ALNOOR}/audit/inputs", json={"tax_group_member": "yes"})
    assert r.status_code == 200 and r.json()["state"] == "likely_required" and r.json()["change_notice"] is True and r.json()["previous_result"] == "likely_not_required"
    db.expire_all()
    assert _events(db, "FLAG_CHANGED") and _events(db, "NOTIFICATION_SENT")

    def boom(company_id):
        raise ind.InjectedFailure("source did not respond")

    ind.FAIL_HOOK = boom
    try:
        t0 = utcnow()
        job = ind.request_recompute(db, CO_ALNOOR, "ledger_sync", now=t0)
        assert job.status == "retrying" and job.attempts == 1 and job.next_attempt_at == t0 + timedelta(minutes=1)
        for minutes in (2, 8, 40, 200):
            ind.run_recompute_jobs(db, now=t0 + timedelta(minutes=minutes))
    finally:
        ind.FAIL_HOOK = None
    db.commit()
    job = db.get(RecomputeJob, job.id)
    assert job.status == "dead_letter" and job.attempts == 5
    assert ind.latest_result(db, CO_ALNOOR).not_refreshed is True and _events(db, "DEAD_LETTER_ALERT")


def test_criteria_four_eyes(db):
    with pytest.raises(Forbidden):
        ind.confirm_criteria(db, "v1", confirmer="Tax specialist (seed proposal)", confirmer_role="licensed_auditor")
    with pytest.raises(Forbidden):
        ind.confirm_criteria(db, "v1", confirmer="Hassan", confirmer_role="tax_specialist")
    with pytest.raises(PlatformError):
        ind.publish_criteria(db, "v1", publisher_role="qeonix_product_owner")  # not yet confirmed
    ind.confirm_criteria(db, "v1", confirmer="Layla Haddad", confirmer_role="licensed_auditor")
    with pytest.raises(Forbidden):
        ind.publish_criteria(db, "v1", publisher_role="owner")
    with pytest.raises(Forbidden):
        ind.publish_criteria(db, "v1", publisher_role="det_admin")
    assert ind.publish_criteria(db, "v1", publisher_role="qeonix_product_owner").status == "published"
    assert ind.evaluate(db, CO_ALNOOR).confirmation_state == "confirmed"
    assert _events(db, "CRITERIA_CONFIRMED") and _events(db, "CRITERIA_PUBLISHED")


def test_det_k20_aggregates_with_suppression(client):
    with _client("sara") as sara:
        r = sara.get("/api/det/audit-flags")
        assert r.status_code == 200
        k20 = r.json()["k20"]
        assert k20["min_cell_size"] == 10 and all(c["value"] is None and c["suppressed"] for c in k20["cells"].values() if c["suppressed"])
        assert k20["denominator"] is None and k20["denominator_suppressed"] is True  # 3 evaluated licences < 10
        assert "exceptions" not in r.json() and "evidence" not in str(r.json()).lower().replace("no individual flags or evidence", "")
    sign_in(client, "khalid")
    assert client.get("/api/det/audit-flags").status_code == 403


def test_k20_complementary_suppression():
    cells = ind._suppress({"likely_required": 3, "likely_not_required": 40, "cannot_determine": 12}, 10)
    assert cells["likely_required"]["suppressed"] and cells["cannot_determine"]["suppressed"] and not cells["likely_not_required"]["suppressed"]


# --- E7-S3 draft audit working file -----------------------------------------------------------------------------


BANNED_TERMS = ("audit report", "audit certificate", "certified")


def _banned(text: str) -> list[str]:
    low = text.casefold().replace("not an audit report", "").replace("it is not an audit report or certificate", "")
    return [t for t in BANNED_TERMS if t in low]


def test_working_file_states_labels_and_watermark(client, db):
    al = wf.current_file(db, CO_ALNOOR)
    gt = wf.current_file(db, CO_GULFTECH)
    assert al.completeness_state == "incomplete" and al.status == "draft" and wf.status_label(db, al)["en"] == "Draft, no auditor assigned"
    assert gt.completeness_state == "complete_with_exceptions" and wf.status_label(db, gt)["en"] == "Draft, awaiting licensed auditor"
    assert wf.status_label(db, gt)["ar"] == "مسودة، بانتظار مدقق مرخّص"
    d = wf.file_dict(db, al)
    assert d["sign_off_status"] == "not_ready" and d["gaps"] and d["gaps_summary"]["total"] >= 1 and d["watermark"] == {"en": "DRAFT - NOT AN AUDIT REPORT", "ar": "مسودة أعمال تدقيق - ليست تقرير تدقيق"}
    assert d["name"] == {"en": "audit work draft", "ar": "مسودة أعمال تدقيق"} and d["signing_available"] is False
    sign_in(client, "khalid")
    r = client.get(f"/api/companies/{CO_ALNOOR}/audit/working-file/export?lang=en")
    assert r.status_code == 200
    html = r.text
    assert WATERMARK["en"] in html and WATERMARK["ar"] in html and "Not an audit opinion. Not for submission to any authority." in html
    assert "Data gaps" in html and "فجوات البيانات" in html and "INCOMPLETE" in html and "No verification code" in html
    # Banned terms never appear in titles, file names, watermarks (negation 'not an audit report' allowed).
    for text in (d["title"]["en"], d["name"]["en"], d["watermark"]["en"], d["header"]["en"], html.split("<title>")[1].split("</title>")[0]):
        assert _banned(text) == [], text
    with _client("priya") as priya:  # remote owner: download hidden with the fixed text
        r = priya.get(f"/api/companies/{CO_BLUEDUNE}/audit/working-file/export")
        assert r.status_code == 403 and r.json()["error"] == "DOWNLOAD_NOT_AVAILABLE_FOR_ROLE"


def test_release_blocked_and_status_machine(client, db):
    sign_in(client, "khalid")
    r = client.post(f"/api/companies/{CO_ALNOOR}/audit/working-file/release")
    assert r.status_code == 403 and r.json()["error"] == "RELEASE_BLOCKED"
    db.expire_all()
    assert _events(db, "RELEASE_BLOCKED") and wf.current_file(db, CO_ALNOOR).release_blocked
    f = wf.current_file(db, CO_ALNOOR)
    for bad in ("signed", "issued", "rejected"):
        with pytest.raises(Conflict):
            wf.transition(db, f, bad, who="x", role="owner")
    assert f.status == "draft"


def test_k18_first_complete_date_is_immutable(db):
    f = wf.current_file(db, CO_GULFTECH)
    first = f.first_complete_draft_ready_at
    assert first is not None
    wf.prepare_working_file(db, CO_GULFTECH, period=(f.period_start, f.period_end), completeness_override="incomplete")
    f = wf.current_file(db, CO_GULFTECH)
    assert f.completeness_state == "incomplete" and f.first_complete_draft_ready_at == first and f.reopen_count == 1
    k = wf.k18(db)
    assert k["n"] >= 1


def test_refused_run_reads_no_data(db):
    out = wf.prepare_working_file(db, CO_GULFTECH)  # no ledger authorisation for Gulf Tech
    assert out["refused"] and out["no_data_read"]["en"] == "No data was read"
    assert _events(db, "RUN_REFUSED")


def test_data_gap_requests_and_reminders(db):
    f = wf.current_file(db, CO_ALNOOR)
    g = wf.gaps_for(db, f)[0]
    wf.gap_action(db, g, action="request", actor_name="Khalid", actor_role="owner", actor_key=None, assignee_uuid=PERSONA_UUIDS["omar"], assignee_name="Omar", due_date=date(2026, 1, 10))
    assert g.status == "requested"
    assert wf.run_gap_reminders(db, today=date(2026, 1, 10)) == 1
    assert wf.run_gap_reminders(db, today=date(2026, 1, 14)) == 1 and g.status == "overdue"
    assert wf.run_gap_reminders(db, today=date(2026, 2, 1)) == 0  # nothing further automatic
    with pytest.raises(PlatformError):
        wf.gap_action(db, g, action="reopen", actor_name="Khalid", actor_role="owner", actor_key=None, reason="no")


# --- E7-S4 licensed-auditor review ---------------------------------------------------------------------------------


def test_auditor_queue_shows_assigned_engagements_only(db):
    with _client("layla") as layla:
        q = layla.get("/api/auditor/engagements").json()["engagements"]
        assert [e["company_id"] for e in q] == [CO_GULFTECH]
        detail = layla.get(f"/api/auditor/engagements/{q[0]['id']}").json()
        assert detail["firewall"]["result"] == "no_conflict_found_in_det_records" and detail["independence_declared"]
        assert detail["register_check"]["outcome"] == "allowed" and detail["register_check"]["text"]["en"].startswith("Register check: matched on")
        assert detail["primary_action"] == "record_review" and detail["signing_enabled"] is False
        assert detail["evidence_mode"] == "supplied_documents_only" and detail["supplied_documents_text"]["en"] == "Based only on supplied documents, not an audit opinion."
        assert detail["badge"]["en"] == "Draft audit working file, unsigned" and len(detail["exceptions"]) == 2
        other = Engagement(company_id=CO_ALNOOR, auditor_identity_uuid="uuid-other-auditor", auditor_name="Other", engagement_manager="DET pilot manager queue", assigned_by="t", status="awaiting_review")
        db.add(other)
        db.commit()
        r = layla.get(f"/api/auditor/engagements/{other.id}")
        assert r.status_code == 403 and r.json()["error"] == "NOT_ASSIGNED"
    db.expire_all()
    assert _events(db, "UNASSIGNED_ACCESS_DENIED")
    with _client("khalid") as khalid:
        assert khalid.get("/api/auditor/engagements").status_code == 403


def test_engagement_firewall_independence_and_register_freshness(db):
    # Firewall: a related-entity / same-company role is a hit -> assignment refused.
    db.add(CompanyRole(identity_uuid=PERSONA_UUIDS["layla"], company_id=CO_SAFWA, role="delegate", capacity="delegate", status="active", granted_by_uuid="test"))
    db.commit()
    with pytest.raises(Forbidden) as exc:
        eng_svc.create_engagement(db, company_id=CO_SAFWA, auditor_uuid=PERSONA_UUIDS["layla"], assigned_by="ops")
    assert exc.value.reason_code == "FIREWALL_CONFLICT"
    # Independence declaration required before activation.
    eng = eng_svc.create_engagement(db, company_id=CO_BLUEDUNE, auditor_uuid=PERSONA_UUIDS["layla"], assigned_by="ops")
    with pytest.raises(Conflict) as exc:
        eng_svc.activate_engagement(db, eng)
    assert exc.value.reason_code == "INDEPENDENCE_DECLARATION_REQUIRED"
    eng_svc.declare_independence(db, LAYLA, eng)
    # Register snapshot older than 24 h and the register unreachable -> blocked (stale snapshot), with retries.
    for snap in db.scalars(select(RegisterSnapshot)):
        snap.loaded_at = utcnow() - timedelta(hours=30)
    set_config(db, "auditagent.register.simulate_unreachable", True, changed_by="test")
    with pytest.raises(Forbidden) as exc:
        eng_svc.activate_engagement(db, eng)
    assert exc.value.reason_code == "BLOCKED_STALE_SNAPSHOT"
    set_config(db, "auditagent.register.simulate_unreachable", False, changed_by="test")
    assert eng_svc.activate_engagement(db, eng).status == "awaiting_review"  # fresh snapshot fetched
    # Every register outcome has a seeded snapshot entry.
    outcomes = {}
    for ref in ("AUD-9001", "AUD-9002", "AUD-9003", "AUD-9004", "AUD-9005", "AUD-0000"):
        uuid = f"uuid-test-{ref}"
        db.add(StaffRole(identity_uuid=uuid, role="licensed_auditor", work_email="t@example.ae", status="active", requester="t", approver="t2", entitlement_ref=f"MoE auditor register ref {ref}"))
        db.flush()
        outcomes[ref] = eng_svc.check_register(db, uuid, purpose="sign").outcome
    assert outcomes == {"AUD-9001": "blocked_suspended", "AUD-9002": "blocked_expired", "AUD-9003": "blocked_struck_off", "AUD-9004": "blocked_ambiguous", "AUD-9005": "blocked_no_signing_authority", "AUD-0000": "blocked_unlisted"}
    for snap in db.scalars(select(RegisterSnapshot)):
        db.delete(snap)
    db.flush()
    set_config(db, "auditagent.register.simulate_unreachable", True, changed_by="test")
    assert eng_svc.check_register(db, PERSONA_UUIDS["layla"]).outcome == "blocked_unreachable"


def test_record_review_only_while_signing_off(db):
    eng = db.scalar(select(Engagement).where(Engagement.company_id == CO_GULFTECH))
    with _client("layla") as layla:
        base = f"/api/auditor/engagements/{eng.id}"
        r = layla.post(f"{base}/review", json={"action": "sign"})
        assert r.status_code == 403 and r.json()["error"] == "FEATURE_SWITCHED_OFF"
        r = layla.post(f"{base}/review", json={"action": "record_review"})
        assert r.status_code == 403 and r.json()["error"] == "REAUTH_REQUIRED"
        assert layla.post(f"{base}/review", json={"action": "start_review"}).status_code == 200
        ref = layla.post("/api/auditor/reauth").json()["reauth_ref"]
        r = layla.post(f"{base}/review", json={"action": "record_review", "reauth_ref": ref})
        assert r.status_code == 409 and r.json()["error"] == "EXCEPTIONS_OPEN" and r.json()["details"]["open"] == 2
        for fl in layla.get(base).json()["exceptions"]:
            r = layla.post(f"{base}/exceptions/{fl['id']}/decide", json={"decision": "dismiss", "reason": "Agreed to the supplied trial balance."})
            assert r.status_code == 200 and r.json()["status"] == "Dismissed"
    db.expire_all()
    assert all(f.status == "Dismissed" for f in rv.list_flags(db, CO_GULFTECH))


def test_record_review_flow_and_signature_void(db):
    eng = db.scalar(select(Engagement).where(Engagement.company_id == CO_GULFTECH))
    with _client("layla") as layla:
        base = f"/api/auditor/engagements/{eng.id}"
        layla.post(f"{base}/review", json={"action": "start_review"})
        for fl in layla.get(base).json()["exceptions"]:
            layla.post(f"{base}/exceptions/{fl['id']}/decide", json={"decision": "confirm", "reason": "Confirmed against the supplied ledger."})
        # An old re-auth (> 5 minutes) is refused.
        from app.modules.auditagent.models import ReauthAssertion

        old = ReauthAssertion(identity_uuid=PERSONA_UUIDS["layla"], at=utcnow() - timedelta(minutes=6))
        db.add(old)
        db.commit()
        r = layla.post(f"{base}/review", json={"action": "record_review", "reauth_ref": old.id})
        assert r.status_code == 403 and r.json()["error"] == "REAUTH_REQUIRED"
        ref = layla.post("/api/auditor/reauth").json()["reauth_ref"]
        r = layla.post(f"{base}/review", json={"action": "record_review", "reauth_ref": ref})
        assert r.status_code == 200, r.text
        out = r.json()
        assert out["status"] == "review_recorded"
        assert out["review_recorded"]["en"].startswith("Review recorded by ") and "Layla Haddad" in out["review_recorded"]["en"] and "Not an audit report, not an opinion." in out["review_recorded"]["en"]
        assert "sign" not in out["review_recorded"]["en"].casefold().replace("unsigned", "")
    db.expire_all()
    rr = _events(db, "REVIEW_RECORDED")[-1]
    assert rr.details["reauth_ref"] == ref and rr.details["version_hash"] and rr.details["supplied_documents_only"] is True
    k = {(c["rule_id"]): c for c in rv.k16(db, CO_GULFTECH)}
    assert k["AX02"]["confirmed"] == 1 and k["AX06"]["confirmed"] == 1
    # Content edit after the recorded review -> new unsigned version, signature void, back to review.
    f = wf.current_file(db, CO_GULFTECH)
    nf = wf.edit_content(db, f, content={"figures": [], "changed": True}, who="Qeonix audit operations", role="qeonix_audit_ops")
    db.commit()
    assert nf.id != f.id and nf.version_no == f.version_no + 1 and nf.signature_void and nf.status == "draft"
    db.refresh(eng)
    assert eng.status == "awaiting_review" and _events(db, "SIGNATURE_VOID")
    assert db.get(AuditWorkingFile, f.id).is_current is False


def test_coded_rejection_and_return_to_preparation(db):
    eng = db.scalar(select(Engagement).where(Engagement.company_id == CO_GULFTECH))
    with _client("layla") as layla:
        base = f"/api/auditor/engagements/{eng.id}"
        layla.post(f"{base}/review", json={"action": "start_review"})
        ref = layla.post("/api/auditor/reauth").json()["reauth_ref"]
        r = layla.post(f"{base}/review", json={"action": "reject", "reauth_ref": ref, "reason_code": "looks_bad"})
        assert r.status_code == 422 and r.json()["error"] == "REASON_CODE_REQUIRED"
        r = layla.post(f"{base}/review", json={"action": "reject", "reauth_ref": ref, "reason_code": "data_missing", "free_text": "short"})
        assert r.status_code == 422 and r.json()["error"] == "REASON_TOO_SHORT"
        r = layla.post(f"{base}/review", json={"action": "request_changes", "reauth_ref": ref, "reason_code": "data_inconsistent", "free_text": "Trial balance does not agree to the ledger totals.", "release_free_text": False})
        assert r.status_code == 200 and r.json()["status"] == "returned_to_preparation"
    db.expire_all()
    f = wf.current_file(db, CO_GULFTECH)
    assert f.status == "draft"
    owner_view = wf.file_dict(db, f, role="owner")
    assert owner_view["return"]["reason_code"] == "data_inconsistent" and owner_view["return"]["free_text"] is None  # coded category only
    assert wf.file_dict(db, f, role="qeonix_audit_ops")["return"]["free_text"].startswith("Trial balance")
    assert owner_view["engagement"]["auditor_name"] is None and owner_view["engagement"]["preparing_team_role"] == "Qeonix audit operations"


def test_signed_outside_platform_and_reminders(db):
    eng = db.scalar(select(Engagement).where(Engagement.company_id == CO_GULFTECH))
    with pytest.raises(PlatformError):
        eng_svc.record_signed_outside(db, LAYLA, eng, signer_name="Layla Haddad", register_number="AUD-2201", date_signed=date(2026, 10, 1), document_reference="HP-2026-117", confirmed=False)
    # Reminders at 14/7/2 days and escalation after 3 working days of inactivity.
    eng.review_deadline = date(2026, 11, 1)
    eng.last_activity_at = datetime(2026, 10, 5, 8, 0)
    out = eng_svc.run_engagement_reminders(db, today=date(2026, 10, 18), now=datetime(2026, 10, 18, 8, 0))
    assert out["reminders"] == 1 and "d-14" in eng.reminders_sent
    assert any(k.startswith("idle-") for k in eng.escalations_sent)
    out = eng_svc.run_engagement_reminders(db, today=date(2026, 10, 30), now=datetime(2026, 10, 30, 8, 0))
    assert {"d-7", "d-2"} <= set(eng.reminders_sent) and {"not_under_review_7", "unsigned_2"} <= set(eng.escalations_sent)
    rec = eng_svc.record_signed_outside(db, LAYLA, eng, signer_name="Layla Haddad", register_number="AUD-2201", date_signed=date(2026, 10, 1), document_reference="HP-2026-117", confirmed=True)
    assert rec.version == 1 and eng.status == "signed_outside_platform"
    d = eng_svc.engagement_dict(db, eng)
    assert "Not verified by the platform or by any authority." in d["signed_outside"]["text"]["en"]
    rec2 = eng_svc.record_signed_outside(db, LAYLA, eng, signer_name="Layla Haddad", register_number="AUD-2201", date_signed=date(2026, 10, 2), document_reference="HP-2026-117", confirmed=True)
    assert rec2.version == 2  # every edit versioned
