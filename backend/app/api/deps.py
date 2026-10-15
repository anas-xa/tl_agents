"""FastAPI dependencies: database session, principal resolution and permission guards."""

from __future__ import annotations

from collections.abc import Callable

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.errors import PlatformError, Unauthenticated
from app.modules.access.service import Principal, authorize, require_company_access, require_step_up
from app.modules.audit.service import ensure_identity_mapping
from app.modules.identity.models import Identity
from app.modules.identity.service import get_active_session, resolve_roles

SESSION_COOKIE = "qx_session"


def _session_id_from(request: Request) -> str | None:
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return request.cookies.get(SESSION_COOKIE)


def get_principal(request: Request, db: Session = Depends(get_db)) -> Principal:
    session = get_active_session(db, _session_id_from(request))
    identity = db.get(Identity, session.identity_uuid)
    if identity is None:
        raise Unauthenticated("identity missing")
    roles = resolve_roles(db, identity.uuid)
    principal = Principal(
        identity_uuid=identity.uuid,
        actor_key=ensure_identity_mapping(db, identity.uuid),
        display_name=identity.display_name,
        assurance_level=session.assurance_level,
        profile_type=identity.profile_type,
        language=session.language,
        session_id=session.session_id,
        company_roles=roles["company_roles"],
        staff_roles=roles["staff_roles"],
        det_match_result=identity.det_match_result,
    )
    request.state.principal = principal
    db.commit()
    return principal


def client_ip(request: Request) -> str | None:
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else None


def browser_family(request: Request) -> str | None:
    ua = request.headers.get("user-agent", "").lower()
    for name in ("edg", "chrome", "safari", "firefox", "opera"):
        if name in ua:
            return {"edg": "edge"}.get(name, name)
    return "other" if ua else None


def require(permission: str, *, company_param: str = "company_id") -> Callable:
    """Dependency factory: checks a company-scoped permission taken from the path/query parameter."""

    def _dep(request: Request, principal: Principal = Depends(get_principal), db: Session = Depends(get_db)) -> Principal:
        company_id = request.path_params.get(company_param) or request.query_params.get(company_param)
        try:
            if company_id:
                require_company_access(db, principal, company_id)
            authorize(db, principal, permission, company_id=company_id)
            require_step_up(db, principal, permission)
        except PlatformError:
            db.commit()  # keep the ACCESS_REFUSED audit event before the refusal propagates
            raise
        db.commit()
        return principal

    return _dep


def require_staff(permission: str) -> Callable:
    def _dep(principal: Principal = Depends(get_principal), db: Session = Depends(get_db)) -> Principal:
        try:
            authorize(db, principal, permission, company_id=None)
        except PlatformError:
            db.commit()  # keep the ACCESS_REFUSED audit event before the refusal propagates
            raise
        db.commit()
        return principal

    return _dep
