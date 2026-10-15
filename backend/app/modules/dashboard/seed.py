"""SC3 dashboard configuration: per-panel TTL/limit, live timeout, panel functions, Remote Services Agent switch."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.modules.config.service import ensure_config
from app.modules.dashboard.service import FRESHNESS_DEFAULT, PANEL_FUNCTIONS_DEFAULT

ORDER = 46


def seed(db: Session) -> None:
    for key, value, status, label, unit in (
        ("dashboard.panel.live_timeout_seconds", 2, "provisional", "assumption (Q66): live call timeout then cache", "seconds"),
        ("dashboard.panel_freshness", FRESHNESS_DEFAULT, "provisional", "per-panel TTL / limit (Q66), versioned per panel", "minutes"),
        ("dashboard.panel_functions", PANEL_FUNCTIONS_DEFAULT, "provisional", "delegate functions that share each SC3 panel ('*' = always shared; rows still filtered)", None),
        ("dashboard.simulate_timeout_panels", [], "provisional", "test hook: panels whose live source times out", None),
        ("dashboard.p95_load_seconds", 3, "provisional", "target: shell + cached panels at pilot concurrency (p99 6 s)", "seconds"),
        ("dashboard.export.download_link_validity_hours", 24, "provisional", "production, configurable", "hours"),
        ("dashboard.delegate_access_log.retention_months", 12, "provisional", "production, configurable", "months"),
        ("remote_services_agent.enabled", False, "confirmed", "Remote Services Agent switch OFF by default (no control/menu item; API 403 FEATURE_DISABLED)", None),
        ("remote.assertion_max_age_minutes", 15, "provisional", "illustrative: approvals need an assertion no older than 15 minutes", "minutes"),
        ("remote.approval_expiry_hours", 72, "provisional", "illustrative, versioned per action type", "hours"),
        ("remote.ux_staleness_threshold_hours", 24, "provisional", "illustrative", "hours"),
        ("remote.loading", {"still_loading_seconds": 5, "give_up_seconds": 20}, "provisional", "configurable", "seconds"),
    ):
        ensure_config(db, key, value, status=status, label=label, unit=unit, owner="Tech Lead (E3-S1/E3-S5)")
    db.flush()


def seed_demo(db: Session) -> None:
    return None
