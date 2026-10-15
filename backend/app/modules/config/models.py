"""Versioned configuration and rule registers.

The R&D package insists that thresholds, windows, wording and switches are configuration, not code,
each carrying an owner, an effective date and a confirmation status ("confirmed", "provisional",
"to_be_confirmed"). Two registers exist:

* ``config_entries`` - product configuration values (JSON), versioned per key.
* ``rule_register`` - the rule-version register (instrument, effective date, source, confirmed-by)
  for legal and calculation rules such as vat-tp-v1, ac-v1, k4-v1, audit-required thresholds.
"""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import JSON, Boolean, Date, DateTime, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.core.time import utcnow

STATUS_VALUES = ("confirmed", "provisional", "to_be_confirmed")


class ConfigEntry(Base):
    __tablename__ = "config_entries"
    __table_args__ = (UniqueConstraint("key", "version", name="uq_config_key_version"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    key: Mapped[str] = mapped_column(String(120), index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    value: Mapped[dict | list | str | int | float | bool | None] = mapped_column(JSON)
    unit: Mapped[str | None] = mapped_column(String(40))
    owner: Mapped[str] = mapped_column(String(120), default="Qeonix product owner")
    status: Mapped[str] = mapped_column(String(20), default="provisional")  # STATUS_VALUES
    label: Mapped[str | None] = mapped_column(String(255))  # e.g. "to be confirmed with DET"
    description: Mapped[str | None] = mapped_column(Text)
    effective_from: Mapped[date] = mapped_column(Date, default=date(2025, 1, 1))
    is_current: Mapped[bool] = mapped_column(Boolean, default=True)
    changed_by: Mapped[str | None] = mapped_column(String(120))
    approved_by: Mapped[str | None] = mapped_column(String(120))
    change_reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class RuleRegisterEntry(Base):
    """Rule-version register: one row per rule id and version."""

    __tablename__ = "rule_register"
    __table_args__ = (UniqueConstraint("rule_id", "version", name="uq_rule_id_version"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    rule_id: Mapped[str] = mapped_column(String(80), index=True)  # e.g. vat-tp-v1
    version: Mapped[str] = mapped_column(String(20), default="v1")
    title: Mapped[str] = mapped_column(String(255))
    instrument: Mapped[str | None] = mapped_column(String(255))  # legal instrument / source
    source: Mapped[str | None] = mapped_column(String(255))
    effective_from: Mapped[date | None] = mapped_column(Date)
    effective_to: Mapped[date | None] = mapped_column(Date)
    confirmed_by: Mapped[str | None] = mapped_column(String(120))
    status: Mapped[str] = mapped_column(String(20), default="provisional")
    owner_role: Mapped[str | None] = mapped_column(String(120))
    parameters: Mapped[dict | None] = mapped_column(JSON)
    is_current: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
