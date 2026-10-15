"""SC3 company dashboard (E3-S1) and remote-owner view (E3-S5).

* ``RememberedCompany``        last selected company per UAE PASS identity (kept after sign-out, re-validated).
* ``PanelCache``                last good payload per company and panel (TTL / limit freshness, 2 s live timeout).
* ``AccessRequest``             delegate 'Request access' to an unshared panel (in-portal, logged, once).
* ``DelegatePanelVisibility``   owner switch per delegate and panel (default on).
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.core.time import utcnow

PANELS = ("tax_status", "audit_status", "deadlines", "documents", "compliance")
FRESHNESS_STATES = ("fresh", "last_known", "cannot_be_confirmed", "not_available", "could_not_be_loaded", "not_linked_yet", "not_shared")


class RememberedCompany(Base):
    __tablename__ = "dashboard_remembered_company"

    identity_uuid: Mapped[str] = mapped_column(String(64), primary_key=True)
    company_id: Mapped[str] = mapped_column(String(40))
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class PanelCache(Base):
    __tablename__ = "dashboard_panel_cache"
    __table_args__ = (UniqueConstraint("company_id", "panel", name="uq_dashboard_panel_cache"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    company_id: Mapped[str] = mapped_column(String(40), index=True)
    panel: Mapped[str] = mapped_column(String(30))
    payload: Mapped[dict] = mapped_column(JSON)
    source: Mapped[str] = mapped_column(String(30))
    data_as_of: Mapped[datetime] = mapped_column(DateTime)
    cached_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class AccessRequest(Base):
    __tablename__ = "dashboard_access_requests"
    __table_args__ = (UniqueConstraint("company_id", "identity_uuid", "panel", name="uq_dashboard_access_request"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    company_id: Mapped[str] = mapped_column(String(40), index=True)
    identity_uuid: Mapped[str] = mapped_column(String(64))
    panel: Mapped[str] = mapped_column(String(30))
    sent_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class DelegatePanelVisibility(Base):
    __tablename__ = "dashboard_delegate_panel_visibility"
    __table_args__ = (UniqueConstraint("company_id", "identity_uuid", "panel", name="uq_dashboard_delegate_panel"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    company_id: Mapped[str] = mapped_column(String(40), index=True)
    identity_uuid: Mapped[str] = mapped_column(String(64))
    panel: Mapped[str] = mapped_column(String(30))
    visible: Mapped[bool] = mapped_column(Boolean, default=True)
    changed_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    changes: Mapped[list | None] = mapped_column(JSON)
