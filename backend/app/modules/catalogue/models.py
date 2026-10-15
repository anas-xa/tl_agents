"""Bilingual string catalogue (E1-S5) with audience class and reviewer status per language."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.core.time import utcnow

AUDIENCE_CLASSES = ("official", "other")
REVIEW_STATUSES = ("unreviewed", "reviewed")


class CatalogueString(Base):
    __tablename__ = "catalogue_strings"

    key: Mapped[str] = mapped_column(String(160), primary_key=True)
    module: Mapped[str] = mapped_column(String(60), index=True)
    text_en: Mapped[str] = mapped_column(Text)
    text_ar: Mapped[str] = mapped_column(Text)
    audience_class: Mapped[str] = mapped_column(String(20), default="official")
    review_status_en: Mapped[str] = mapped_column(String(20), default="unreviewed")
    review_status_ar: Mapped[str] = mapped_column(String(20), default="unreviewed")
    legal_review_status: Mapped[str | None] = mapped_column(String(20))  # for legal-commitment strings
    reviewed_by: Mapped[str | None] = mapped_column(String(120))
    reviewed_on: Mapped[datetime | None] = mapped_column(DateTime)
    version: Mapped[int] = mapped_column(Integer, default=1)
    plural_forms: Mapped[dict | None] = mapped_column(JSON)  # Arabic: zero/one/two/few/many/other
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
