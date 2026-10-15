"""Guided demo journey endpoints: the story (chapters, personas, narration) and a data reset.

Active only when ``QEONIX_DEMO_MODE`` is on (the start scripts and Docker image switch it on) and never in
pilot or production: otherwise every endpoint answers 404 as if it did not exist.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import Base, get_db
from app.core.errors import NotFound
from app.core.settings import get_settings
from app.modules.demo.story import CHAPTERS, EPILOGUE, PERSONA_ROLES, PROLOGUE

router = APIRouter(prefix="/api/demo", tags=["demo"])


def demo_enabled() -> bool:
    s = get_settings()
    return s.demo_mode and s.environment not in ("pilot", "production")


def _require_demo() -> None:
    if not demo_enabled():
        raise NotFound("Not found.", reason_code="NOT_FOUND")


def _verification_code(db: Session) -> str | None:
    """An issued official Al Noor document, for the 'verify a document without signing in' moment."""
    from app.modules.documents.models import IssuedDocument

    return db.scalar(
        select(IssuedDocument.verification_code)
        .where(IssuedDocument.company_id == "co_alnoor", IssuedDocument.official.is_(True), IssuedDocument.verification_code.is_not(None), IssuedDocument.revoked_at.is_(None), IssuedDocument.superseded_by_id.is_(None))
        .order_by(IssuedDocument.issued_at.desc())
        .limit(1)
    )


@router.get("/story", dependencies=[Depends(_require_demo)])
def story(db: Session = Depends(get_db)):
    from app.modules.identity.mock_uaepass import PERSONAS

    personas = {
        key: {"key": key, "name": PERSONAS[key].name, "role": role}
        for key, role in PERSONA_ROLES.items()
        if key in PERSONAS
    }
    return {
        "prologue": PROLOGUE,
        "chapters": CHAPTERS,
        "epilogue": EPILOGUE,
        "personas": personas,
        "verification_code": _verification_code(db),
    }


@router.post("/reset", dependencies=[Depends(_require_demo)])
def reset(db: Session = Depends(get_db)):
    """Reload the demo data from scratch so the story can be told again. Everyone is signed out."""
    from app import models  # noqa: F401  (registers all ORM models)
    from app.demo import seed_demo
    from app.modules.consent import service as consent_service
    from app.seed import seed_reference_data

    bind = db.get_bind()
    db.close()
    Base.metadata.drop_all(bind=bind)
    Base.metadata.create_all(bind=bind)
    with Session(bind=bind, autoflush=False, expire_on_commit=False) as fresh:
        seed_reference_data(fresh)
        seed_demo(fresh)
        fresh.commit()
    consent_service._GATE_CACHE.clear()
    uploads = Path(get_settings().upload_dir)
    if uploads.is_dir():
        for child in uploads.iterdir():
            shutil.rmtree(child) if child.is_dir() else child.unlink(missing_ok=True)
    return {"status": "reset"}
