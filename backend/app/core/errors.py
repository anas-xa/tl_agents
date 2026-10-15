"""Typed errors mapped to HTTP responses with a reference code and bilingual-ready message keys."""

from __future__ import annotations

from app.core.ids import reference_code


class PlatformError(Exception):
    status_code = 400
    reason_code = "ERROR"

    def __init__(self, message: str = "", *, reason_code: str | None = None, details: dict | None = None):
        super().__init__(message or self.reason_code)
        self.message = message or self.reason_code
        if reason_code:
            self.reason_code = reason_code
        self.details = details or {}
        self.reference = reference_code()


class NotFound(PlatformError):
    status_code = 404
    reason_code = "NOT_FOUND"


class Forbidden(PlatformError):
    """Fail-closed authorisation refusal."""

    status_code = 403
    reason_code = "FORBIDDEN"


class Unauthenticated(PlatformError):
    status_code = 401
    reason_code = "UNAUTHENTICATED"


class Conflict(PlatformError):
    status_code = 409
    reason_code = "CONFLICT"


class ValidationFailed(PlatformError):
    status_code = 422
    reason_code = "VALIDATION_FAILED"


class SwitchedOff(PlatformError):
    """A feature that is built but switched off until its gate evidence exists."""

    status_code = 403
    reason_code = "FEATURE_SWITCHED_OFF"
