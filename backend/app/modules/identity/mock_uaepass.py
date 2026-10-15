"""Mock UAE PASS OpenID Connect provider.

The platform integrates with UAE PASS through the OIDC authorisation-code flow with PKCE and validates
the ID token against the provider's JWKS (Q3). This mock issues valid and deliberately invalid tokens
so the same test-suite can later run against the UAE PASS staging environment. It is mounted only when
``QEONIX_UAEPASS_ISSUER`` points at it (development, test, demo).
"""

from __future__ import annotations

import hashlib
import secrets
import time
from dataclasses import dataclass
from functools import lru_cache

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from jose import jwk, jwt

MOCK_PREFIX = "/mock-uaepass"
KID = "mock-uaepass-key-1"


@dataclass(frozen=True)
class Persona:
    key: str
    sub: str
    name: str
    assurance_level: str
    profile_type: int
    idn: str | None  # Emirates ID in the mock only; the platform stores only its salted hash on DET persons
    description: str


PERSONAS: dict[str, Persona] = {
    p.key: p
    for p in [
        Persona("khalid", "uuid-khalid-owner", "Khalid Al Mansoori", "SOP3", 1, "784-1980-1234567-1", "Owner-manager of Al Noor Trading (UAE)"),
        Persona("priya", "uuid-priya-remote", "Priya Raman", "SOP2", 2, "784-1985-7654321-2", "Remote owner of Blue Dune Consultancy (abroad)"),
        Persona("omar", "uuid-omar-delegate", "Omar Haddad", "SOP2", 1, "784-1990-1111111-3", "PRO / accountant delegate for several companies"),
        Persona("layla", "uuid-layla-auditor", "Dr. Layla Haddad", "SOP3", 1, "784-1975-2222222-4", "Licensed auditor (Ministry of Economy register)"),
        Persona("sara", "uuid-sara-detadmin", "Sara Al Shamsi", "SOP3", 1, "784-1982-3333333-5", "DET administrator"),
        Persona("faisal", "uuid-faisal-pilot", "Faisal Al Marri", "SOP3", 1, "784-1983-4444444-6", "DET pilot manager"),
        Persona("noura", "uuid-noura-reviewer", "Noura Al Ketbi", "SOP3", 1, "784-1984-5555555-7", "Compliance and audit-trail reviewer"),
        Persona("hassan", "uuid-hassan-taxspec", "Hassan Qureshi", "SOP3", 1, "784-1979-6666666-8", "Tax specialist (human escalation)"),
        Persona("mariam", "uuid-mariam-legal", "Mariam Al Suwaidi", "SOP3", 1, "784-1981-7777777-9", "Legal specialist (licensed law firm)"),
        Persona("yusuf", "uuid-yusuf-escops", "Yusuf Karim", "SOP3", 1, "784-1988-8888888-0", "Escalation operations (Qeonix)"),
        Persona("adel", "uuid-adel-secadmin", "Adel Rahman", "SOP3", 1, "784-1977-9999999-1", "Platform security administrator (Qeonix)"),
        Persona("lina", "uuid-lina-po", "Lina Farah", "SOP3", 1, "784-1986-1212121-2", "Qeonix product owner"),
        Persona("ahmed", "uuid-ahmed-complaints", "Ahmed Saeed", "SOP3", 1, "784-1987-1313131-3", "DET complaint handler"),
        Persona("noroles", "uuid-no-roles", "Tariq Nobody", "SOP2", 1, "784-1995-1414141-4", "Verified identity with no company role"),
        Persona("sop1", "uuid-sop1-basic", "Basic Account", "SOP1", 1, "784-1996-1515151-5", "Unverified UAE PASS account (SOP1) - refused"),
        Persona("noeid", "uuid-no-eid-owner", "Owner Without Emirates ID", "SOP2", 2, None, "Owner abroad whose DET record has no Emirates ID - no owner role"),
    ]
}


@lru_cache
def _keypair():
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = private_key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    ).decode()
    pub = private_key.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    ).decode()
    return pem, pub


def jwks() -> dict:
    _, pub = _keypair()
    key = jwk.construct(pub, algorithm="RS256").to_dict()
    key.update({"kid": KID, "use": "sig", "alg": "RS256"})
    return {"keys": [key]}


# in-memory authorisation codes: code -> dict(persona, nonce, code_challenge, redirect_uri, issued)
_CODES: dict[str, dict] = {}


def issue_code(persona_key: str, nonce: str, code_challenge: str | None, redirect_uri: str) -> str:
    code = secrets.token_urlsafe(24)
    _CODES[code] = {
        "persona": persona_key,
        "nonce": nonce,
        "code_challenge": code_challenge,
        "redirect_uri": redirect_uri,
        "issued": time.time(),
    }
    return code


def mint_id_token(
    issuer: str,
    audience: str,
    persona: Persona,
    nonce: str,
    *,
    expired: bool = False,
    wrong_issuer: bool = False,
    wrong_audience: bool = False,
    bad_signature: bool = False,
) -> str:
    now = int(time.time())
    claims = {
        "iss": "https://evil.example" if wrong_issuer else issuer,
        "aud": "other-client" if wrong_audience else audience,
        "sub": persona.sub,
        "name": persona.name,
        "assurance_level": persona.assurance_level,
        "profile_type": persona.profile_type,
        "nonce": nonce,
        "iat": now - 3600 if expired else now,
        "exp": now - 60 if expired else now + 300,
    }
    if persona.idn:
        claims["idn"] = persona.idn
    pem, _ = _keypair()
    if bad_signature:
        other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        pem = other.private_bytes(
            serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
        ).decode()
    return jwt.encode(claims, pem, algorithm="RS256", headers={"kid": KID})


def exchange_code(issuer: str, audience: str, code: str, code_verifier: str | None) -> dict:
    data = _CODES.pop(code, None)
    if data is None:
        return {"error": "invalid_grant"}
    if data["code_challenge"]:
        if not code_verifier:
            return {"error": "invalid_grant", "error_description": "code_verifier required"}
        import base64

        digest = hashlib.sha256(code_verifier.encode()).digest()
        challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
        if challenge != data["code_challenge"]:
            return {"error": "invalid_grant", "error_description": "PKCE mismatch"}
    persona = PERSONAS[data["persona"]]
    variant = data.get("variant")
    token = mint_id_token(
        issuer,
        audience,
        persona,
        data["nonce"],
        expired=variant == "expired",
        wrong_issuer=variant == "wrong_issuer",
        wrong_audience=variant == "wrong_audience",
        bad_signature=variant == "bad_signature",
    )
    return {"id_token": token, "token_type": "Bearer", "access_token": secrets.token_urlsafe(16), "expires_in": 300}


router = APIRouter(prefix=MOCK_PREFIX, tags=["mock-uaepass"])


@router.get("/.well-known/openid-configuration")
def openid_configuration(request: Request):
    base = str(request.base_url).rstrip("/") + MOCK_PREFIX
    return {
        "issuer": base,
        "authorization_endpoint": f"{base}/authorize",
        "token_endpoint": f"{base}/token",
        "jwks_uri": f"{base}/.well-known/jwks.json",
        "response_types_supported": ["code"],
        "code_challenge_methods_supported": ["S256"],
        "id_token_signing_alg_values_supported": ["RS256"],
    }


@router.get("/.well-known/jwks.json")
def jwks_endpoint():
    return jwks()


@router.get("/authorize")
def authorize(
    request: Request,
    state: str,
    nonce: str,
    redirect_uri: str,
    code_challenge: str | None = None,
    persona: str | None = None,
    action: str | None = None,
    variant: str | None = None,
    ui_locale: str = "en",
):
    if action == "cancel":
        return RedirectResponse(f"{redirect_uri}?state={state}&error=access_denied", status_code=302)
    if persona:
        if persona not in PERSONAS:
            return JSONResponse({"error": "unknown persona"}, status_code=400)
        code = issue_code(persona, nonce, code_challenge, redirect_uri)
        if variant:
            _CODES[code]["variant"] = variant
        return RedirectResponse(f"{redirect_uri}?state={state}&code={code}", status_code=302)
    rtl = ui_locale.startswith("ar")
    rows = "".join(
        f'<li><a class="p" href="?state={state}&nonce={nonce}&redirect_uri={redirect_uri}'
        f'&code_challenge={code_challenge or ""}&persona={p.key}&ui_locale={ui_locale}">'
        f"<strong>{p.name}</strong> <span>{p.assurance_level} · profile {p.profile_type}</span><br><small>{p.description}</small></a></li>"
        for p in PERSONAS.values()
    )
    cancel = f'?state={state}&nonce={nonce}&redirect_uri={redirect_uri}&action=cancel'
    html = f"""<!doctype html><html lang="{ui_locale}" dir="{'rtl' if rtl else 'ltr'}"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>UAE PASS (mock)</title>
<style>body{{font-family:system-ui,sans-serif;background:#f4f6f8;margin:0;padding:24px;color:#1b2430}}
.card{{max-width:560px;margin:0 auto;background:#fff;border-radius:12px;padding:24px;box-shadow:0 2px 12px #0001}}
ul{{list-style:none;padding:0}} li{{margin:8px 0}} a.p{{display:block;padding:12px;border:1px solid #d7dde3;border-radius:8px;text-decoration:none;color:inherit;min-height:44px}}
a.p:hover{{border-color:#0f6e56}} small{{color:#5b6672}} .cancel{{display:inline-block;margin-top:16px;color:#8a1c1c}}
h1{{font-size:20px}} .banner{{background:#fff4d6;border:1px solid #e8c36a;padding:8px 12px;border-radius:8px;font-size:14px}}</style></head>
<body><div class="card"><h1>UAE PASS <span style="font-weight:normal">(mock identity provider)</span></h1>
<p class="banner">{'هذه بيئة تجريبية. اختر شخصية اختبار لتسجيل الدخول.' if rtl else 'Sandbox only. Choose a test persona to sign in as.'}</p>
<ul>{rows}</ul><a class="cancel" href="{cancel}">{'إلغاء' if rtl else 'Cancel sign-in'}</a></div></body></html>"""
    return HTMLResponse(html)


@router.post("/token")
def token(request: Request, grant_type: str = Form(...), code: str = Form(...), code_verifier: str | None = Form(None), client_id: str | None = Form(None)):
    base = str(request.base_url).rstrip("/") + MOCK_PREFIX
    if grant_type != "authorization_code":
        return JSONResponse({"error": "unsupported_grant_type"}, status_code=400)
    result = exchange_code(base, client_id or "qeonix-portal", code, code_verifier)
    status = 400 if "error" in result else 200
    return JSONResponse(result, status_code=status)
