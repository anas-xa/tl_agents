"""Registry of all ORM models so ``Base.metadata`` knows every table (auto-discovered)."""

from app.discovery import import_all_models

import_all_models()
