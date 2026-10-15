"""Today-relative demo periods (app.demo) and one coherent demo story at any date."""

from __future__ import annotations

from datetime import date

from sqlalchemy import select

from app import demo
from app.demo import (
    CO_ALNOOR,
    CO_BLUEDUNE,
    CO_SAFWA,
    DemoPeriod,
    demo_ct_year,
    demo_quarter,
    demo_vat_quarters,
)


def test_demo_vat_quarters_open_is_the_latest_ended_quarter():
    q = demo_vat_quarters(date(2026, 10, 15))
    assert q.open == DemoPeriod("2026-Q3", date(2026, 7, 1), date(2026, 9, 30), date(2026, 10, 28))
    assert q.previous == DemoPeriod("2026-Q2", date(2026, 4, 1), date(2026, 6, 30), date(2026, 7, 28))
    assert q.current == DemoPeriod("2026-Q4", date(2026, 10, 1), date(2026, 12, 31), date(2027, 1, 28))
    q = demo_vat_quarters(date(2027, 2, 10))
    assert (q.previous.period_id, q.open.period_id, q.current.period_id) == ("2026-Q3", "2026-Q4", "2027-Q1")
    assert q.open.due == date(2027, 1, 28) and q.today == date(2027, 2, 10)
    # quarter boundaries and year wrap
    assert demo_vat_quarters(date(2026, 10, 1)).open.period_id == "2026-Q3"
    assert demo_vat_quarters(date(2026, 9, 30)).open.period_id == "2026-Q2"
    q = demo_vat_quarters(date(2026, 1, 1))
    assert (q.previous.period_id, q.open.period_id) == ("2025-Q3", "2025-Q4") and q.open.due == date(2026, 1, 28)
    assert demo_quarter(2028, 1) == DemoPeriod("2028-Q1", date(2028, 1, 1), date(2028, 3, 31), date(2028, 4, 28))


def test_demo_ct_year_is_the_latest_ended_financial_year():
    assert demo_ct_year(date(2026, 10, 15)) == DemoPeriod("FY2025", date(2025, 1, 1), date(2025, 12, 31), date(2026, 9, 30))
    assert demo_ct_year(date(2027, 2, 10)) == DemoPeriod("FY2026", date(2026, 1, 1), date(2026, 12, 31), date(2027, 9, 30))
    assert demo_ct_year(date(2027, 1, 1)).period_id == "FY2026"


def test_helpers_default_to_the_patchable_today(monkeypatch):
    monkeypatch.setattr(demo, "_default_today", lambda: date(2027, 2, 10))
    assert demo_vat_quarters().open.period_id == "2026-Q4" and demo_ct_year().period_id == "FY2026"


def test_seed_builds_a_coherent_demo_in_another_quarter(monkeypatch):
    """Freeze the demo 'today' to 10 Feb 2027 and rebuild the seeded database: every module follows the helpers."""
    from app.core.db import Base, SessionLocal, engine
    from app.modules.approvals.models import Approval, ApprovalRequest, ManualFilingRecord
    from app.modules.bookkeeping.models import Classification, Transaction
    from app.modules.datalinks.models import TaxProfile
    from app.modules.deadlines import service as dl
    from app.modules.deadlines.models import FiledEvidence, Obligation
    from app.modules.drafts.models import DraftPack
    from app.modules.escalation.models import EscalationCase
    from app.seed import seed_reference_data

    today = date(2027, 2, 10)
    monkeypatch.setattr(demo, "_default_today", lambda: today)
    q, ct = demo_vat_quarters(), demo_ct_year()
    assert (q.previous.period_id, q.open.period_id, q.open.due, ct.period_id) == ("2026-Q3", "2026-Q4", date(2027, 1, 28), "FY2026")
    engine.dispose()
    Base.metadata.drop_all(bind=engine)  # this test's own copy of the database; the next test gets a fresh one
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        seed_reference_data(db)
        demo.seed_demo(db)
        db.commit()

        # Bookkeeping: rows span the previous and open quarters (fully reviewed) plus the running quarter's queue.
        rows = db.execute(select(Classification, Transaction).join(Transaction, Transaction.id == Classification.txn_id).where(Classification.company_id == CO_ALNOOR)).all()
        assert rows and all(q.previous.start <= t.txn_date <= today for _, t in rows)
        assert any(t.txn_date < q.open.start for _, t in rows) and any(q.open.start <= t.txn_date <= q.open.end for _, t in rows)
        assert not [c for c, t in rows if t.txn_date <= q.open.end and c.status in ("proposed", "needs_review")]
        assert {c.status for c, t in rows if t.txn_date >= q.current.start} >= {"proposed", "needs_review"}
        quarantined = [c for c, t in rows if c.status == "quarantined"]
        assert quarantined and all(c.access_removed_on == date(2026, 12, 1) for c in quarantined)

        # Drafts: previous quarter filed (locked), open quarter ready for owner review, CT for the demo year.
        packs = {(p.company_id, p.tax_type, p.period_id): p for p in db.scalars(select(DraftPack))}
        prev, open_pack = packs[(CO_ALNOOR, "vat", "2026-Q3")], packs[(CO_ALNOOR, "vat", "2026-Q4")]
        assert prev.review_status == "filed_user_confirmed" and prev.locked and prev.created_at.date() > q.previous.end
        assert open_pack.review_status == "under_review" and not open_pack.locked
        assert (CO_ALNOOR, "ct", "FY2026") in packs and (CO_BLUEDUNE, "ct", "FY2026") in packs and (CO_SAFWA, "vat", "2026-Q4") in packs
        assert not [k for k in packs if "2026-Q2" in k[2] or k[2] == "FY2025"]

        # Approvals: the open request is on the open quarter's pack (sent by the delegate); history on the real
        # previous-quarter pack with a self-declared filing before its due date.
        reqs = list(db.scalars(select(ApprovalRequest).where(ApprovalRequest.company_id == CO_ALNOOR)))
        open_req = next(r for r in reqs if r.status == "open")
        assert open_req.pack_id == open_pack.id and open_req.period_id == "2026-Q4" and open_req.due_date == date(2027, 1, 28) and open_req.requested_by_role == "delegate"
        hist = next(r for r in reqs if r.status == "decided")
        assert hist.pack_id == prev.id and hist.period_id == "2026-Q3" and hist.due_date == date(2026, 10, 28)
        a = db.scalar(select(Approval).where(Approval.request_id == hist.id))
        mfr = db.scalar(select(ManualFilingRecord).where(ManualFilingRecord.pack_id == prev.id))
        assert a.decision == "approve" and mfr.state == "filed_outside_self_declared" and q.previous.end < mfr.filed_date <= q.previous.due

        # Deadlines: no readiness fixture; the open quarter's readiness comes from its real draft.
        assert db.scalar(select(Obligation).where(Obligation.readiness_fixture.is_not(None))) is None
        assert db.scalar(select(FiledEvidence).where(FiledEvidence.company_id == CO_SAFWA)).obligation_key == "ct_return:2026-01-01_2026-12-31"
        vat = next(o for o in dl.obligations_for(db, CO_ALNOOR, today=today) if o["obligation_type"] == "vat_return" and o["period_end"] == "2026-12-31")
        assert vat["due_date"] == "2027-01-28" and vat["readiness"] == "draft_ready" and vat["missing_items"] == [] and vat["draft_pack_id"] == open_pack.id

        # Data links and escalation follow the same periods.
        prof = db.scalar(select(TaxProfile).where(TaxProfile.company_id == CO_ALNOOR, TaxProfile.tax_type == "vat"))
        assert (prof.tax_period_start, prof.tax_period_end) == (date(2026, 10, 1), date(2026, 12, 31))
        keys = {c.matter_key for c in db.scalars(select(EscalationCase).where(EscalationCase.company_id == CO_ALNOOR, EscalationCase.is_demo.is_(True)))}
        assert {"item:vat_return_2026Q3", "DET-1023456|VAT_RETURN|2026Q4", "audit_file_2026|audit_required|FY2026"} <= keys
    engine.dispose()
