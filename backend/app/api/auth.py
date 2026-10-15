"""Sign-in endpoints (E1-S1): start, callback, cancel, me, sign-out, session timing."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import SESSION_COOKIE, browser_family, client_ip, get_principal
from app.core.db import get_db
from app.core.settings import get_settings
from app.modules.access.service import Principal, permissions_for
from app.modules.companies.models import Company
from app.modules.identity.models import Identity, UserSession
from app.modules.identity.service import (
    cancel_signin,
    complete_signin,
    end_session,
    session_timing,
    start_signin,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])


class StartResponse(BaseModel):
    redirect_url: str
    state: str


@router.post("/start", response_model=StartResponse)
def start(language: str = "en", return_to: str | None = None, invite: str | None = None, db: Session = Depends(get_db)):
    language = "ar" if language.startswith("ar") else "en"
    url, state = start_signin(db, language=language, return_to=return_to, invitation_token=invite)
    db.commit()
    return StartResponse(redirect_url=url, state=state)


@router.post("/cancel")
def cancel(state: str, request: Request, db: Session = Depends(get_db)):
    cancel_signin(db, state, ip=client_ip(request))
    db.commit()
    return {"ok": True}


@router.get("/callback")
def callback(request: Request, state: str = "", code: str | None = None, error: str | None = None, db: Session = Depends(get_db)):
    settings = get_settings()
    result = complete_signin(db, state=state, code=code, error=error, ip=client_ip(request), browser=browser_family(request))
    db.commit()
    front = settings.frontend_base_url.rstrip("/")
    if not result.ok:
        resp = RedirectResponse(f"{front}/signin?lang={result.language}&reason={result.reason_code}&ref={result.reference}", status_code=302)
        return resp
    target = f"{front}/auth/complete?lang={result.language}"
    if result.no_company_role:
        target += "&no_company=1"
    if result.return_to:
        target += f"&return_to={result.return_to}"
    resp = RedirectResponse(target, status_code=302)
    resp.set_cookie(SESSION_COOKIE, result.session_id or "", httponly=True, samesite="lax", secure=settings.environment == "production", path="/")
    return resp


@router.post("/signout")
def signout(response: Response, principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    end_session(db, principal.session_id)
    db.commit()
    response.delete_cookie(SESSION_COOKIE, path="/")
    return {"ok": True}


@router.post("/keepalive")
def keepalive(principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    session = db.get(UserSession, principal.session_id)
    db.commit()
    return session_timing(db, session)


class CompanySummary(BaseModel):
    company_id: str
    trade_name_en: str
    trade_name_ar: str
    roles: list[str]
    rights: list[str]
    functions: list[str]
    permissions: list[str]


class MeResponse(BaseModel):
    identity_uuid: str
    display_name: str
    assurance_level: str
    profile_type: int
    det_match_result: str
    language: str
    numerals: str
    staff_roles: list[str]
    companies: list[CompanySummary]
    staff_permissions: list[str]
    session: dict
    privacy_notice_seen: bool


@router.get("/me", response_model=MeResponse)
def me(principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    identity = db.get(Identity, principal.identity_uuid)
    session = db.get(UserSession, principal.session_id)
    companies = []
    for cid in principal.company_ids():
        company = db.get(Company, cid)
        roles = principal.roles_for(cid)
        rights: set[str] = set()
        functions: set[str] = set()
        for r in roles:
            rights |= set(r.rights or [])
            functions |= set(r.functions or [])
        companies.append(
            CompanySummary(
                company_id=cid,
                trade_name_en=company.trade_name_en if company else cid,
                trade_name_ar=company.trade_name_ar if company else cid,
                roles=[r.role for r in roles],
                rights=sorted(rights),
                functions=sorted(functions),
                permissions=sorted(permissions_for(db, principal, cid)),
            )
        )
    return MeResponse(
        identity_uuid=principal.identity_uuid,
        display_name=principal.display_name,
        assurance_level=principal.assurance_level,
        profile_type=principal.profile_type,
        det_match_result=principal.det_match_result,
        language=identity.language if identity else principal.language,
        numerals=identity.numerals if identity else "western",
        staff_roles=principal.staff_roles,
        companies=companies,
        staff_permissions=sorted(permissions_for(db, principal, None)),
        session=session_timing(db, session),
        privacy_notice_seen=bool(identity and identity.privacy_notice_seen_version),
    )


class PreferencesIn(BaseModel):
    language: str | None = None
    numerals: str | None = None
    privacy_notice_version: str | None = None
    contact_email: str | None = None
    contact_mobile: str | None = None


@router.patch("/me/preferences")
def preferences(body: PreferencesIn, principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    identity = db.get(Identity, principal.identity_uuid)
    session = db.get(UserSession, principal.session_id)
    if body.language in ("ar", "en"):
        identity.language = body.language
        session.language = body.language
    if body.numerals in ("western", "arabic_indic"):
        identity.numerals = body.numerals
    if body.privacy_notice_version:
        identity.privacy_notice_seen_version = body.privacy_notice_version
    if body.contact_email is not None:
        identity.contact_email = body.contact_email or None
    if body.contact_mobile is not None:
        identity.contact_mobile = body.contact_mobile or None
    db.commit()
    return {"ok": True, "language": identity.language, "numerals": identity.numerals}
