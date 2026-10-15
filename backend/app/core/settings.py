"""Platform settings.

Every value that the R&D package marks as configurable lives either here (deployment-level)
or in the versioned configuration register (``app.modules.config``) for product rules.
Deployment-level values are read from the environment (prefix ``QEONIX_``).
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="QEONIX_", env_file=BASE_DIR / ".env", extra="ignore")

    app_name: str = "Qeonix Smart Licence Services"
    environment: str = "dev"  # dev | test | pilot | production
    database_url: str = Field(default=f"sqlite:///{BASE_DIR / 'data' / 'qeonix.db'}")
    secret_key: str = "change-me-in-production"
    upload_dir: str = Field(default=str(BASE_DIR / "data" / "uploads"))
    # Session rules (Q3, E1-S1): illustrative, configurable for production.
    session_idle_timeout_minutes: int = 15
    session_max_length_hours: int = 8
    session_warning_minutes: int = 2
    pending_signin_expiry_minutes: int = 5
    # UAE PASS (OIDC authorisation-code flow with PKCE). Defaults point at the bundled mock provider.
    uaepass_issuer: str = "http://localhost:8000/mock-uaepass"
    uaepass_client_id: str = "qeonix-portal"
    uaepass_redirect_uri: str = "http://localhost:8000/api/auth/callback"
    uaepass_jwks_url: str | None = None  # derived from issuer when unset
    frontend_base_url: str = "http://localhost:5173"
    # One-port mode: when the built portal exists, the API serves it (set by the start scripts and Docker).
    static_dir: str = Field(default=str(BASE_DIR.parent / "frontend" / "dist"))
    serve_frontend: bool = False
    seed_demo_on_start: bool = False
    # Guided demo journey (/demo page, story bar, data reset). Never on in pilot or production.
    demo_mode: bool = False
    # Hosting and residency guardrails (E1-S4): outbound hosts that are permitted (UAE-located).
    outbound_allowlist: list[str] = Field(default_factory=lambda: ["localhost", "127.0.0.1"])
    hosting_region: str = "uae-dubai-1"
    # Local model (no external model calls). Adapter 'rules' is deterministic; 'ollama' calls a local URL.
    local_model_adapter: str = "rules"
    local_model_url: str = "http://127.0.0.1:11434"
    local_model_name: str = "local-model"
    # Operational alert thresholds (Q3): failures per identity in 10 min / platform-wide in 5 min.
    signin_failure_alert_per_identity: int = 5
    signin_failure_alert_platform: int = 20
    # Notification channels (decision: portal baseline, minimal email, optional SMS, WhatsApp off).
    email_enabled: bool = True
    sms_enabled: bool = False
    whatsapp_enabled: bool = False

    @property
    def jwks_url(self) -> str:
        return self.uaepass_jwks_url or f"{self.uaepass_issuer}/.well-known/jwks.json"


@lru_cache
def get_settings() -> Settings:
    return Settings()
