"""The app re-runs the reference seed at every start: seeding an already-seeded database must be a no-op."""

from sqlalchemy import func, select

from app.demo import seed_demo
from app.modules.config.models import ConfigEntry, RuleRegisterEntry
from app.seed import seed_reference_data


def test_reference_and_demo_seed_run_twice_without_error_or_duplicates(db):
    rules_before = db.scalar(select(func.count(RuleRegisterEntry.id)))
    config_before = db.scalar(select(func.count(ConfigEntry.id)))
    seed_reference_data(db)
    seed_demo(db)
    db.commit()
    assert db.scalar(select(func.count(RuleRegisterEntry.id))) == rules_before
    assert db.scalar(select(func.count(ConfigEntry.id))) == config_before
