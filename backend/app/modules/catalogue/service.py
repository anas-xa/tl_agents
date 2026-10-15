from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.time import utcnow
from app.modules.catalogue.models import CatalogueString

REGISTRY: dict[str, dict] = {}  # key -> {"en","ar","audience_class","module"}
ARABIC_PLURAL_FORMS = ("zero", "one", "two", "few", "many", "other")


def register_strings(module: str, strings: dict[str, dict[str, str]], audience: dict[str, str] | None = None) -> None:
    """Called at import time by feature modules' ``strings.py``; persisted by ``sync_catalogue``."""
    for key, texts in strings.items():
        REGISTRY[f"{module}.{key}"] = {
            "module": module,
            "en": texts.get("en", ""),
            "ar": texts.get("ar", ""),
            "audience_class": (audience or {}).get(key, "official"),
            "plural_forms": texts.get("plural_forms"),
        }


def sync_catalogue(db: Session) -> int:
    n = 0
    for key, item in REGISTRY.items():
        row = db.get(CatalogueString, key)
        if row is None:
            db.add(CatalogueString(key=key, module=item["module"], text_en=item["en"], text_ar=item["ar"], audience_class=item["audience_class"], plural_forms=item["plural_forms"]))
            n += 1
        elif row.text_en != item["en"] or row.text_ar != item["ar"]:
            row.text_en, row.text_ar = item["en"], item["ar"]
            row.review_status_en = row.review_status_ar = "unreviewed"  # any edit resets status
            row.version += 1
            row.updated_at = utcnow()
    db.flush()
    return n


def text(db: Session, key: str, lang: str, **params) -> str:
    row = db.get(CatalogueString, key)
    if row is None:
        item = REGISTRY.get(key)
        value = (item or {}).get(lang) or (item or {}).get("en") or key
    else:
        value = row.text_ar if lang == "ar" else row.text_en
    try:
        return value.format(**params) if params else value
    except (KeyError, IndexError):
        return value


def bilingual(db: Session, key: str, **params) -> dict[str, str]:
    return {"en": text(db, key, "en", **params), "ar": text(db, key, "ar", **params)}


def release_check(db: Session) -> dict:
    """Release gate: missing translation fails all; unreviewed Arabic fails official only; partial plurals fail."""
    rows = list(db.scalars(select(CatalogueString)))
    missing = [r.key for r in rows if not r.text_en.strip() or not r.text_ar.strip()]
    unreviewed_official = [r.key for r in rows if r.audience_class == "official" and r.review_status_ar != "reviewed"]
    unreviewed_other = [r.key for r in rows if r.audience_class == "other" and r.review_status_ar != "reviewed"]
    no_class = [r.key for r in rows if r.audience_class not in ("official", "other")]
    partial_plurals = [r.key for r in rows if r.plural_forms and set(ARABIC_PLURAL_FORMS) - set(r.plural_forms.keys())]
    passed = not missing and not unreviewed_official and not no_class and not partial_plurals
    return {
        "passed": passed,
        "official_release_blocked": bool(unreviewed_official or missing or no_class or partial_plurals),
        "missing_translation": missing,
        "unreviewed_official": unreviewed_official,
        "unreviewed_other_warning": {"count": len(unreviewed_other), "keys": unreviewed_other[:50]},
        "missing_audience_class": no_class,
        "partial_plural_forms": partial_plurals,
        "total": len(rows),
    }


def mark_reviewed(db: Session, key: str, lang: str, reviewer: str, *, legal: bool = False) -> CatalogueString:
    row = db.get(CatalogueString, key)
    if row is None:
        from app.core.errors import NotFound

        raise NotFound("string not found")
    if lang == "ar":
        row.review_status_ar = "reviewed"
    else:
        row.review_status_en = "reviewed"
    if legal:
        row.legal_review_status = "reviewed"
    row.reviewed_by = reviewer
    row.reviewed_on = utcnow()
    return row
