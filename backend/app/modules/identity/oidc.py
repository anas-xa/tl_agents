"""OIDC client for UAE PASS: code exchange and ID-token validation (signature, issuer, audience, nonce, expiry)."""

from __future__ import annotations

import base64
import hashlib
import secrets
from dataclasses import dataclass

import httpx
from jose import JWTError, jwt

from app.core.settings import Settings, get_settings


class AssertionInvalid(Exception):
    pass


class ProviderUnavailable(Exception):
    pass


@dataclass
class Assertion:
    sub: str
    name: str
    assurance_level: str
    profile_type: int
    idn: str | None
    raw: dict


def make_pkce() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    return verifier, challenge


def _uses_mock(settings: Settings) -> bool:
    return "/mock-uaepass" in settings.uaepass_issuer


def authorize_url(settings: Settings, *, state: str, nonce: str, code_challenge: str, language: str) -> str:
    base = settings.uaepass_issuer.rstrip("/")
    return (
        f"{base}/authorize?response_type=code&client_id={settings.uaepass_client_id}"
        f"&redirect_uri={settings.uaepass_redirect_uri}&scope=openid&state={state}&nonce={nonce}"
        f"&code_challenge={code_challenge}&code_challenge_method=S256&ui_locale={language}"
    )


def _validate(settings: Settings, id_token: str, keys: dict, expected_nonce: str) -> Assertion:
    try:
        claims = jwt.decode(
            id_token,
            keys,
            algorithms=["RS256"],
            audience=settings.uaepass_client_id,
            issuer=settings.uaepass_issuer.rstrip("/"),
            options={"require_exp": True, "require_iat": True},
        )
    except JWTError as exc:
        raise AssertionInvalid(f"token validation failed: {exc}") from exc
    if claims.get("nonce") != expected_nonce:
        raise AssertionInvalid("nonce mismatch")
    level = str(claims.get("assurance_level") or "")
    if level not in ("SOP1", "SOP2", "SOP3"):
        raise AssertionInvalid("missing or unknown assurance level")
    return Assertion(
        sub=str(claims["sub"]),
        name=str(claims.get("name") or "Unnamed"),
        assurance_level=level,
        profile_type=int(claims.get("profile_type") or 1),
        idn=claims.get("idn"),
        raw=claims,
    )


def exchange_and_validate(code: str, code_verifier: str, nonce: str, settings: Settings | None = None) -> Assertion:
    settings = settings or get_settings()
    if _uses_mock(settings):
        from app.modules.identity import mock_uaepass

        result = mock_uaepass.exchange_code(settings.uaepass_issuer.rstrip("/"), settings.uaepass_client_id, code, code_verifier)
        if "error" in result:
            raise AssertionInvalid(result.get("error_description") or result["error"])
        return _validate(settings, result["id_token"], mock_uaepass.jwks(), nonce)
    try:
        with httpx.Client(timeout=10) as client:
            token_resp = client.post(
                f"{settings.uaepass_issuer.rstrip('/')}/token",
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "code_verifier": code_verifier,
                    "client_id": settings.uaepass_client_id,
                    "redirect_uri": settings.uaepass_redirect_uri,
                },
            )
            keys = client.get(settings.jwks_url).json()
    except httpx.HTTPError as exc:
        raise ProviderUnavailable(str(exc)) from exc
    if token_resp.status_code != 200:
        raise AssertionInvalid(token_resp.text)
    return _validate(settings, token_resp.json()["id_token"], keys, nonce)
