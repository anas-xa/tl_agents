from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import require_staff
from app.core.db import get_db
from app.modules.access.service import Principal
from app.modules.audit.service import record_event
from app.modules.catalogue.models import CatalogueString
from app.modules.catalogue.service import mark_reviewed, release_check, sync_catalogue

router = APIRouter(prefix="/api/catalogue", tags=["catalogue"])


@router.get("/strings")
def strings(lang: str = "en", module: str | None = None, db: Session = Depends(get_db)):
    """Public read of the catalogue in one language (used by documents/notifications previews)."""
    stmt = select(CatalogueString)
    if module:
        stmt = stmt.where(CatalogueString.module == module)
    return {r.key: (r.text_ar if lang == "ar" else r.text_en) for r in db.scalars(stmt)}


@router.get("/release-check")
def get_release_check(principal: Principal = Depends(require_staff("catalogue.manage")), db: Session = Depends(get_db)):
    sync_catalogue(db)
    db.commit()
    return release_check(db)


@router.get("/admin")
def admin_list(principal: Principal = Depends(require_staff("catalogue.manage")), db: Session = Depends(get_db)):
    sync_catalogue(db)
    db.commit()
    return [
        {"key": r.key, "module": r.module, "en": r.text_en, "ar": r.text_ar, "audience_class": r.audience_class, "review_ar": r.review_status_ar, "review_en": r.review_status_en, "legal_review": r.legal_review_status, "version": r.version, "reviewed_by": r.reviewed_by}
        for r in db.scalars(select(CatalogueString).order_by(CatalogueString.key))
    ]


class ReviewIn(BaseModel):
    lang: str = "ar"
    legal: bool = False


@router.post("/admin/{key}/review")
def review(key: str, body: ReviewIn, principal: Principal = Depends(require_staff("catalogue.manage")), db: Session = Depends(get_db)):
    row = mark_reviewed(db, key, body.lang, principal.identity_uuid, legal=body.legal)
    record_event(db, event_type="CATALOGUE_STRING_REVIEWED", category="config", actor_key=principal.actor_key, subject_type="catalogue_string", subject_id=key, details={"lang": body.lang, "legal": body.legal, "version": row.version})
    db.commit()
    return {"key": key, "review_ar": row.review_status_ar, "review_en": row.review_status_en}
