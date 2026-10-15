from __future__ import annotations

from sqlalchemy.orm import Session

from app.modules.catalogue.service import sync_catalogue

ORDER = 5


def seed(db: Session) -> None:
    # Import every module's strings.py so registrations exist before syncing.
    import importlib

    from app.discovery import iter_module_names

    for name in iter_module_names():
        try:
            importlib.import_module(f"app.modules.{name}.strings")
        except ModuleNotFoundError as exc:
            if exc.name != f"app.modules.{name}.strings":
                raise
    sync_catalogue(db)
