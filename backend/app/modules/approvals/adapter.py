"""EmaraTax send-adapter interface (E6-S3). Phase 1 has NO live adapter: only this stub exists, and it refuses
unless `filing.live_adapter.enabled` is ON, the FTA integration-checklist row is confirmed_live (E1-S8) AND the
pre-submission gate passes with a valid approval. The stub never makes a network call and holds no
credentials. Idempotent send keyed by approval id + pack hash; read-back match rules; versioned status map.
"""

from __future__ import annotations

import hashlib
from typing import Any, Protocol

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import NotFound
from app.modules.approvals.models import SubmissionAttempt
from app.modules.audit.service import record_event
from app.modules.config.service import get_config
from app.modules.drafts import service as drafts

# Versioned authority status mapping table (product control, to be confirmed with the FTA). Unknown -> mismatch.
STATUS_MAP = {"version": "asm-v1", "status": "to_be_confirmed", "map": {"submitted": "match_if_fields_match", "received": "match_if_fields_match"}}


class SendAdapter(Protocol):
    name: str

    def transmit(self, attempt: SubmissionAttempt) -> dict: ...

    def fetch_status(self, attempt: SubmissionAttempt) -> dict | None: ...


class EmaraTaxStubAdapter:
    """Stub only. Records that a send would happen; never sends. Real adapter only after FTA written confirmation
    of channel, format, authentication and liability."""

    name = "emaratax-stub"

    def transmit(self, attempt: SubmissionAttempt) -> dict:
        return {"accepted": None, "note": "stub: nothing transmitted"}

    def fetch_status(self, attempt: SubmissionAttempt) -> dict | None:
        return None


def idempotency_key(approval_id: str, pack_hash: str) -> str:
    return hashlib.sha256(f"{approval_id}|{pack_hash}".encode()).hexdigest()[:48]


def switch_state(db: Session) -> tuple[bool, bool]:
    from app.modules.phases.service import integration_live

    return bool(get_config(db, "filing.live_adapter.enabled", False)), bool(integration_live(db, "fta"))


def submit(db: Session, *, company_id: str, pack_id: str, approval_id: str | None, caller_type: str = "user", caller_key: str | None = None, adapter: SendAdapter | None = None) -> SubmissionAttempt:
    """The only send path. The gate runs first on every call (blocked attempts are logged and counted)."""
    from app.modules.approvals.service import gate

    pack = drafts.get_pack(db, pack_id)
    if pack.company_id != company_id:
        raise NotFound("draft not found", reason_code="NOT_FOUND")
    enabled, live = switch_state(db)
    block = None if enabled and live else ("SEND_SWITCHED_OFF" if not enabled else "INTEGRATION_NOT_LIVE")
    approval = gate(db, company_id=company_id, pack=pack, approval_id=approval_id, path="adapter_send", caller_type=caller_type, caller_key=caller_key, switch_state="ON" if enabled and live else "OFF", switch_block=block)
    key = idempotency_key(approval.id, drafts.pack_hash(pack))
    existing = db.scalar(select(SubmissionAttempt).where(SubmissionAttempt.idempotency_key == key))
    if existing is not None:
        record_event(db, event_type="SEND_RETRIED", category="approval", company_id=company_id, subject_type="submission_attempt", subject_id=existing.id, details={"same_key": True})
        return existing  # one active submission per key; repeated triggers return the existing attempt
    attempt = SubmissionAttempt(company_id=company_id, pack_id=pack.id, approval_id=approval.id, data_version_hash=drafts.pack_hash(pack), idempotency_key=key, tax_type=pack.tax_type, period_id=pack.period_id, status="sending", status_map_version=STATUS_MAP["version"])
    db.add(attempt)
    db.flush()
    (adapter or EmaraTaxStubAdapter()).transmit(attempt)  # the send response is never treated as success alone
    record_event(db, event_type="SEND_ATTEMPTED", category="approval", actor_key=caller_key, company_id=company_id, subject_type="submission_attempt", subject_id=attempt.id, details={"approval_id": approval.id, "adapter": (adapter or EmaraTaxStubAdapter()).name})
    db.flush()
    return attempt


def match_read_back(expected: dict[str, Any], record: dict[str, Any] | None, status_map: dict | None = None) -> tuple[bool, list[str]]:
    """Exact match, no tolerance: TRN (trimmed), return type, period start/end, authority reference, every
    amount in AED at the form's precision, and a mapped status. Unknown status or unreadable record = mismatch."""
    if not record:
        return False, ["record_unreadable"]
    smap = (status_map or STATUS_MAP)["map"]
    mism = []
    if str(expected.get("trn", "")).strip() != str(record.get("trn", "")).strip():
        mism.append("trn")
    for f in ("return_type", "period_start", "period_end", "reference"):
        if expected.get(f) != record.get(f):
            mism.append(f)
    exp_amounts, rec_amounts = expected.get("amounts") or {}, record.get("amounts") or {}
    for k, v in exp_amounts.items():
        if rec_amounts.get(k) != v:
            mism.append(f"amount:{k}")
    if smap.get(str(record.get("status", "")).lower()) != "match_if_fields_match":
        mism.append("status")
    return not mism, mism


def read_back(db: Session, attempt: SubmissionAttempt, *, expected: dict, record: dict | None) -> SubmissionAttempt:
    """'filed' only on a full match; otherwise 'unconfirmed', escalation to a human specialist and an owner
    alert. Never resends, never auto-corrects."""
    ok, mism = match_read_back(expected, record)
    attempt.read_back_results = [*(attempt.read_back_results or []), {"matched": ok, "mismatches": mism}]
    record_event(db, event_type="READ_BACK_MATCHED" if ok else "READ_BACK_MISMATCH", category="approval", company_id=attempt.company_id, subject_type="submission_attempt", subject_id=attempt.id, details={"mismatches": mism})
    if ok:
        attempt.status, attempt.authority_reference = "filed", (record or {}).get("reference")
    else:
        attempt.status = "unconfirmed"
        try:
            from app.modules.escalation.service import open_case

            case = open_case(db, company_id=attempt.company_id, module="tax", reason_code="data_conflict", matter_key=f"read_back:{attempt.id}", event_id=f"rb:{attempt.id}:{len(attempt.read_back_results)}", opened_by="system", trigger_source="agent_output", trigger_rule_id="read_back_mismatch", linked_item_id=attempt.id)
            attempt.escalation_case_id = case.case_id
        except Exception:
            pass
        record_event(db, event_type="NOTIFICATION_SENT", category="reminder", company_id=attempt.company_id, subject_type="submission_attempt", subject_id=attempt.id, details={"to": "owner", "kind": "read_back_mismatch"})
    db.flush()
    return attempt
