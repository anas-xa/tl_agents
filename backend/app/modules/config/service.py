from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import NotFound, ValidationFailed
from app.modules.config.models import STATUS_VALUES, ConfigEntry, RuleRegisterEntry


def get_config(db: Session, key: str, default: Any = None) -> Any:
    row = db.scalar(select(ConfigEntry).where(ConfigEntry.key == key, ConfigEntry.is_current.is_(True)))
    return default if row is None else row.value


def get_config_entry(db: Session, key: str) -> ConfigEntry:
    row = db.scalar(select(ConfigEntry).where(ConfigEntry.key == key, ConfigEntry.is_current.is_(True)))
    if row is None:
        raise NotFound(f"config key {key} not found", reason_code="CONFIG_NOT_FOUND")
    return row


def list_config(db: Session, prefix: str | None = None) -> list[ConfigEntry]:
    stmt = select(ConfigEntry).where(ConfigEntry.is_current.is_(True)).order_by(ConfigEntry.key)
    if prefix:
        stmt = stmt.where(ConfigEntry.key.like(f"{prefix}%"))
    return list(db.scalars(stmt))


def config_history(db: Session, key: str) -> list[ConfigEntry]:
    return list(db.scalars(select(ConfigEntry).where(ConfigEntry.key == key).order_by(ConfigEntry.version)))


def set_config(
    db: Session,
    key: str,
    value: Any,
    *,
    changed_by: str,
    approved_by: str | None = None,
    change_reason: str | None = None,
    status: str | None = None,
    label: str | None = None,
    effective_from: date | None = None,
    owner: str | None = None,
    unit: str | None = None,
    description: str | None = None,
    require_second_approver: bool = False,
) -> ConfigEntry:
    """Create a new version of a configuration key. Earlier versions stay as history (never edited)."""
    if status and status not in STATUS_VALUES:
        raise ValidationFailed(f"status must be one of {STATUS_VALUES}")
    if require_second_approver and (not approved_by or approved_by == changed_by):
        raise ValidationFailed("this change needs a second, different approver", reason_code="SECOND_APPROVER_REQUIRED")
    current = db.scalar(select(ConfigEntry).where(ConfigEntry.key == key, ConfigEntry.is_current.is_(True)))
    version = 1
    if current is not None:
        current.is_current = False
        version = current.version + 1
    entry = ConfigEntry(
        key=key,
        version=version,
        value=value,
        unit=unit if unit is not None else (current.unit if current else None),
        owner=owner or (current.owner if current else "Qeonix product owner"),
        status=status or (current.status if current else "provisional"),
        label=label if label is not None else (current.label if current else None),
        description=description if description is not None else (current.description if current else None),
        effective_from=effective_from or date.today(),
        changed_by=changed_by,
        approved_by=approved_by,
        change_reason=change_reason,
    )
    db.add(entry)
    db.flush()
    return entry


def ensure_config(db: Session, key: str, value: Any, **kwargs: Any) -> ConfigEntry:
    """Seed helper: create the key only if it does not exist yet."""
    current = db.scalar(select(ConfigEntry).where(ConfigEntry.key == key, ConfigEntry.is_current.is_(True)))
    if current is not None:
        return current
    kwargs.setdefault("changed_by", "seed")
    return set_config(db, key, value, **kwargs)


# --- rule register -------------------------------------------------------------------------


def get_rule(db: Session, rule_id: str) -> RuleRegisterEntry:
    row = db.scalar(
        select(RuleRegisterEntry).where(RuleRegisterEntry.rule_id == rule_id, RuleRegisterEntry.is_current.is_(True))
    )
    if row is None:
        raise NotFound(f"rule {rule_id} not found", reason_code="RULE_NOT_FOUND")
    return row


def rule_params(db: Session, rule_id: str, default: dict | None = None) -> dict:
    try:
        return dict(get_rule(db, rule_id).parameters or {})
    except NotFound:
        return dict(default or {})


def list_rules(db: Session) -> list[RuleRegisterEntry]:
    return list(db.scalars(select(RuleRegisterEntry).where(RuleRegisterEntry.is_current.is_(True)).order_by(RuleRegisterEntry.rule_id)))


def ensure_rule(db: Session, rule_id: str, title: str, **kwargs: Any) -> RuleRegisterEntry:
    row = db.scalar(
        select(RuleRegisterEntry).where(RuleRegisterEntry.rule_id == rule_id, RuleRegisterEntry.is_current.is_(True))
    )
    if row is not None:
        return row
    row = RuleRegisterEntry(rule_id=rule_id, title=title, **kwargs)
    db.add(row)
    db.flush()
    return row


def register_rule_version(db: Session, rule_id: str, title: str, *, version: str, **kwargs: Any) -> RuleRegisterEntry:
    """Add a new version of a rule; the previous version is kept with is_current=False."""
    current = db.scalar(
        select(RuleRegisterEntry).where(RuleRegisterEntry.rule_id == rule_id, RuleRegisterEntry.is_current.is_(True))
    )
    if current is not None:
        current.is_current = False
    row = RuleRegisterEntry(rule_id=rule_id, title=title, version=version, **kwargs)
    db.add(row)
    db.flush()
    return row
