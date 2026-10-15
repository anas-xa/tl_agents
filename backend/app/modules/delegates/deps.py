"""Dependency wrapper other modules may adopt: the permission matrix check plus the company hold / stale-DET /
reconfirmation rules (E1-S2 Q12, E1-S6 Q5). ``api.deps.require`` itself is unchanged."""

from __future__ import annotations

from collections.abc import Callable

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from app.api.deps import get_principal
from app.core.db import get_db
from app.core.errors import PlatformError
from app.modules.access.service import Principal, authorize, require_company_access, require_step_up
from app.modules.delegates.service import require_not_on_hold


def require_company_action(permission: str, *, company_param: str = "company_id") -> Callable:
    """Like ``require(permission)`` and additionally refuses held functions while the company is on hold
    (signatory change / no owner) or while DET data is stale; reads are never blocked by the hold."""
    def _dep(request: Request, principal: Principal = Depends(get_principal), db: Session = Depends(get_db)) -> Principal:
        company_id = request.path_params.get(company_param) or request.query_params.get(company_param)
        try:
            if company_id:
                require_company_access(db, principal, company_id)
            authorize(db, principal, permission, company_id=company_id)
            require_step_up(db, principal, permission)
            if company_id:
                require_not_on_hold(db, company_id, permission, principal=principal)
        except PlatformError:
            db.commit()  # denials are fail-safe: the refusal is logged even though the action is refused
            raise
        db.commit()
        return principal

    return _dep
