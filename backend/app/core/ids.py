from __future__ import annotations

import secrets
import uuid


def new_id(prefix: str = "") -> str:
    value = uuid.uuid4().hex
    return f"{prefix}_{value}" if prefix else value


def reference_code(length: int = 8) -> str:
    """Short, user-facing reference code shown with refusals and errors."""
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    return "".join(secrets.choice(alphabet) for _ in range(length))
