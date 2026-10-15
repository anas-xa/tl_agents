from app.modules.localmodel.client import RulesAdapter, language_class
from tests.conftest import sign_in


def test_rules_adapter_classifies_and_reports_no_basis():
    m = RulesAdapter()
    r = m.classify("DEWA bill March", candidates=["utilities", "rent"])
    assert r.output["category"] == "utilities" and r.basis == "rule"
    r2 = m.classify("Unknown counterparty XYZ", candidates=["utilities", "rent"])
    assert r2.output["category"] is None and "Needs review: no basis found" in r2.notes
    r3 = m.classify("Unknown counterparty XYZ", candidates=["utilities", "rent"], context={"prior_choices": {"xyz": "rent"}})
    assert r3.output["category"] == "rent" and "Matches your earlier choices" in r3.notes
    assert language_class("تحويل من Emirates NBD") == "mixed" and language_class("إيجار") == "ar"


def test_release_check_blocks_unreviewed_official(client):
    sign_in(client, "lina")
    r = client.get("/api/catalogue/release-check")
    assert r.status_code == 200
    body = r.json()
    assert "official_release_blocked" in body and "unreviewed_other_warning" in body
