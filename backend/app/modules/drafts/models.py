"""Filing-ready draft packs (E5-S3): versioned records with a non-removable AI label and a role-bound status model."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.core.ids import new_id
from app.core.time import utcnow

# Review-status values (Q100). Humans set review/acceptance statuses; the system sets only
# not_reviewed, superseded and stale. approved_for_submission / filed_user_confirmed are written by the
# approvals module (E6-S1) through drafts.service.set_approval_status.
DRAFT_STATUSES = (
    "not_reviewed",
    "under_review",
    "reviewed_with_changes",
    "accepted_by_reviewer",
    "superseded",
    "stale",
    "prepared",
    "approved_for_submission",
    "filed_user_confirmed",
    "reviewed_by_specialist",
    "signed",
    "accepted_by_owner_no_independent_review",
    "reviewed_by_owner_after_hold",
)
SYSTEM_ONLY_STATUSES = ("not_reviewed", "superseded", "stale")
STATUS_LABELS = {
    "not_reviewed": {"en": "Not reviewed", "ar": "لم تتم المراجعة"},
    "under_review": {"en": "Under review", "ar": "قيد المراجعة"},
    "reviewed_with_changes": {"en": "Reviewed with changes", "ar": "رُوجعت مع تعديلات"},
    "accepted_by_reviewer": {"en": "Accepted by reviewer", "ar": "قبلها المراجع"},
    "superseded": {"en": "Superseded", "ar": "مستبدلة"},
    "stale": {"en": "Stale (source data changed)", "ar": "قديمة (تغيّرت بيانات المصدر)"},
    "prepared": {"en": "prepared", "ar": "مُعدّة"},
    "approved_for_submission": {"en": "approved for submission", "ar": "معتمدة للتقديم"},
    "filed_user_confirmed": {"en": "Filed (user-confirmed)", "ar": "قُدّمت (بتأكيد المستخدم)"},
    "reviewed_by_specialist": {"en": "reviewed by specialist", "ar": "راجعها مختص"},
    "signed": {"en": "signed", "ar": "موقّعة"},
    "accepted_by_owner_no_independent_review": {"en": "Accepted by owner, no independent review", "ar": "قبلها المالك، دون مراجعة مستقلة"},
    "reviewed_by_owner_after_hold": {"en": "Reviewed by owner after hold, no independent review", "ar": "راجعها المالك بعد الإيقاف، دون مراجعة مستقلة"},
}
LINE_CLASSES = ("calculated", "flagged", "person_entered")
AI_LABEL = {"en": "AI-generated draft: not a filed return", "ar": "مسودة مُعدّة بالذكاء الاصطناعي: ليست إقرارًا مقدَّمًا"}
WATERMARK = {"en": "Draft working figures arranged to follow the FTA return layout. Not a tax return. Not filed. Not tax advice.", "ar": "أرقام عمل أولية مرتبة وفق تخطيط إقرار الهيئة الاتحادية للضرائب. ليست إقرارًا ضريبيًا. غير مقدَّمة. ليست استشارة ضريبية."}
EMARATAX_SENTENCE = {"en": "Submission to the FTA is made only by you or your authorised person through EmaraTax", "ar": "يتم التقديم إلى الهيئة الاتحادية للضرائب من قِبلك أو من قِبل الشخص المفوَّض عنك فقط عبر إمارات تاكس"}
PRODUCT_NAME = {"en": "Tax preparation assistant", "ar": "مساعد إعداد الضرائب"}


class DraftPack(Base):
    __tablename__ = "draft_packs"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("pack"))
    company_id: Mapped[str] = mapped_column(String(40), index=True)
    tax_type: Mapped[str] = mapped_column(String(5))
    period_id: Mapped[str] = mapped_column(String(40), index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    ai_label_en: Mapped[str] = mapped_column(String(120), default=AI_LABEL["en"])  # cannot be removed
    ai_label_ar: Mapped[str] = mapped_column(String(120), default=AI_LABEL["ar"])
    review_status: Mapped[str] = mapped_column(String(50), default="not_reviewed")
    data_version: Mapped[str] = mapped_column(String(40))
    rule_version: Mapped[str | None] = mapped_column(String(120))
    calculation_id: Mapped[str | None] = mapped_column(String(40))
    assumptions: Mapped[list | None] = mapped_column(JSON)
    lines: Mapped[list] = mapped_column(JSON, default=list)  # figures (one source record, both languages)
    ai_lines: Mapped[list | None] = mapped_column(JSON)  # the AI version kept after a human edit
    sources: Mapped[list | None] = mapped_column(JSON)
    basis: Mapped[dict | None] = mapped_column(JSON)
    human_edited: Mapped[bool] = mapped_column(Boolean, default=False)
    edited_by_uuid: Mapped[str | None] = mapped_column(String(64))
    last_human_change_by: Mapped[str | None] = mapped_column(String(120))
    last_human_change_role: Mapped[str | None] = mapped_column(String(40))
    last_human_change_at: Mapped[datetime | None] = mapped_column(DateTime)
    on_hold: Mapped[bool] = mapped_column(Boolean, default=False)
    held_delegate_uuid: Mapped[str | None] = mapped_column(String(64))
    held_delegate_name: Mapped[str | None] = mapped_column(String(120))
    held_changes: Mapped[list | None] = mapped_column(JSON)
    superseded: Mapped[bool] = mapped_column(Boolean, default=False)
    superseded_by: Mapped[str | None] = mapped_column(String(40))
    what_changed: Mapped[str | None] = mapped_column(Text)
    locked: Mapped[bool] = mapped_column(Boolean, default=False)  # Filed (user-confirmed)
    filing_reference: Mapped[str | None] = mapped_column(String(80))
    created_by_uuid: Mapped[str | None] = mapped_column(String(64))
    created_by_name: Mapped[str | None] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)


class DraftStatusHistory(Base):
    """Append-only status history; earlier statuses are never deleted."""

    __tablename__ = "draft_status_history"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("dsh"))
    pack_id: Mapped[str] = mapped_column(String(40), index=True)
    from_status: Mapped[str | None] = mapped_column(String(50))
    to_status: Mapped[str] = mapped_column(String(50))
    actor_uuid: Mapped[str | None] = mapped_column(String(64))
    actor_name: Mapped[str | None] = mapped_column(String(120))
    actor_role: Mapped[str | None] = mapped_column(String(40))
    system: Mapped[bool] = mapped_column(Boolean, default=False)
    reason_code: Mapped[str | None] = mapped_column(String(40))
    reason_text: Mapped[str | None] = mapped_column(Text)
    changed_fields: Mapped[list | None] = mapped_column(JSON)
    material: Mapped[bool | None] = mapped_column(Boolean)
    at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class DraftExport(Base):
    __tablename__ = "draft_exports"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("exp"))
    pack_id: Mapped[str] = mapped_column(String(40), index=True)
    language: Mapped[str] = mapped_column(String(2))
    format: Mapped[str] = mapped_column(String(10), default="json")
    exported_by_uuid: Mapped[str | None] = mapped_column(String(64))
    exported_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    retention_class: Mapped[int] = mapped_column(Integer, default=3)
