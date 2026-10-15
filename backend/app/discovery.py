"""Auto-discovery of feature modules.

Every package under ``app.modules`` may provide:
* ``models.py``  - ORM models (imported so ``Base.metadata`` knows them)
* ``api.py``     - a FastAPI ``router`` (APIRouter) mounted by the app
* ``seed.py``    - ``seed(db)`` for reference data and ``seed_demo(db)`` for demo data;
                   optional ``ORDER`` (int, default 100) controls the order across modules.
"""

from __future__ import annotations

import importlib
import pkgutil
from types import ModuleType

import app.modules as modules_pkg


def iter_module_names() -> list[str]:
    return sorted(m.name for m in pkgutil.iter_modules(modules_pkg.__path__) if m.ispkg)


def _import_optional(name: str, sub: str) -> ModuleType | None:
    try:
        return importlib.import_module(f"app.modules.{name}.{sub}")
    except ModuleNotFoundError as exc:
        if exc.name == f"app.modules.{name}.{sub}":
            return None
        raise


def import_all_models() -> None:
    for name in iter_module_names():
        _import_optional(name, "models")


def routers() -> list:
    out = []
    for name in iter_module_names():
        mod = _import_optional(name, "api")
        if mod is not None and hasattr(mod, "router"):
            out.append(mod.router)
        if mod is not None and hasattr(mod, "routers"):
            out.extend(mod.routers)
    return out


def seed_modules() -> list[ModuleType]:
    mods = [m for m in (_import_optional(n, "seed") for n in iter_module_names()) if m is not None]
    return sorted(mods, key=lambda m: (getattr(m, "ORDER", 100), m.__name__))


def run_seeds(db) -> None:
    for mod in seed_modules():
        fn = getattr(mod, "seed", None)
        if fn:
            fn(db)


def run_demo_seeds(db) -> None:
    for mod in seed_modules():
        fn = getattr(mod, "seed_demo", None)
        if fn:
            fn(db)
