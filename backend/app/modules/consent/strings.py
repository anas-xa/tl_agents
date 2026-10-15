"""Bilingual strings that end up in receipts, notices and refusals (E4-S1/E4-S2). Arabic copied from the spec
verbatim where the spec gives it; other Arabic is a draft pending native review."""

from __future__ import annotations

STRINGS: dict[str, dict[str, str]] = {
    # Receipt (grant)
    "receipt.title": {"en": "Consent receipt", "ar": "إيصال الموافقة"},
    "receipt.footer": {"en": "You can withdraw at any time. Withdrawing stops new data pulls.", "ar": "يمكنك السحب في أي وقت. يوقف السحب أي سحب جديد للبيانات."},
    "receipt.row.company": {"en": "Company", "ar": "الشركة"},
    "receipt.row.purpose": {"en": "Purpose", "ar": "الغرض"},
    "receipt.row.data_source": {"en": "Data source", "ar": "مصدر البيانات"},
    "receipt.row.accounts": {"en": "Accounts", "ar": "الحسابات"},
    "receipt.row.data_we_read": {"en": "Data we read", "ar": "البيانات التي نقرؤها"},
    "receipt.row.data_we_do_not_read": {"en": "Data we do not read", "ar": "البيانات التي لا نقرؤها"},
    "receipt.row.valid_from": {"en": "Valid from", "ar": "صالحة من"},
    "receipt.row.valid_until": {"en": "Valid until", "ar": "صالحة حتى"},
    "receipt.row.granted_by": {"en": "Granted by", "ar": "منحها"},
    "receipt.row.acting_as": {"en": "Acting as", "ar": "بصفة"},
    "receipt.row.delegation_id": {"en": "Delegation ID", "ar": "معرّف التفويض"},
    "receipt.row.delegated_by": {"en": "Delegated by", "ar": "فوّضه"},
    "receipt.row.date_granted": {"en": "Date granted", "ar": "تاريخ المنح"},
    "receipt.row.status": {"en": "Status", "ar": "الحالة"},
    "receipt.row.how_to_withdraw": {"en": "How to withdraw", "ar": "كيفية السحب"},
    "receipt.how_to_withdraw": {"en": "Open Consent Centre and choose Withdraw consent on this card.", "ar": "افتح مركز الموافقات واختر سحب الموافقة في هذه البطاقة."},
    "receipt.delegate_granted_by": {"en": "Granted by {delegate}", "ar": "منحها {delegate}"},
    "receipt.delegate_on_behalf": {"en": "On behalf of {owner}, Delegation ID {delegation_id}", "ar": "نيابةً عن {owner}، معرّف التفويض {delegation_id}"},
    "receipt.valid_until_line": {"en": "Valid until {date}. You can withdraw at any time.", "ar": "صالحة حتى {date}. يمكنك السحب في أي وقت."},
    # Withdrawal receipt (Q52; no deletion promise, no legal-document claim)
    "withdrawal_receipt.title": {"en": "Withdrawal receipt", "ar": "إيصال سحب الموافقة"},
    "withdrawal_receipt.withdrawn_on": {"en": "Withdrawn on {date} by {name}", "ar": "تم السحب في {date} بواسطة {name}"},
    "withdrawal_receipt.pulls_stopped": {"en": "New data pulls have stopped. Data pulls are paused for this consent.", "ar": "توقف سحب أي بيانات جديدة. سحب البيانات متوقف لهذه الموافقة."},
    "withdrawal_receipt.effect_drafts": {"en": "Drafts built on this data are marked as affected and approval is blocked until they are prepared again.", "ar": "المسودات المبنية على هذه البيانات معلّمة كمتأثرة، والاعتماد موقوف حتى تتم إعادة إعدادها."},
    "withdrawal_receipt.data_held": {"en": "Data already held is handled under the retention rules. Bank data pulls have stopped; records required by law are kept.", "ar": "تُعالج البيانات المحفوظة بالفعل وفق قواعد الاحتفاظ. توقف سحب البيانات المصرفية؛ وتُحفظ السجلات التي يوجب القانون الاحتفاظ بها."},
    "withdrawal_receipt.microcopy": {"en": "Withdrawing consent stops new data being collected. Data already used in your tax or audit records may have to be kept for the period required by law.", "ar": "يوقف سحب الموافقة جمع أي بيانات جديدة. قد يلزم الاحتفاظ بالبيانات المستخدمة بالفعل في سجلاتك الضريبية أو سجلات التدقيق للمدة التي يوجبها القانون."},
    "withdrawal_receipt.how_to_reconsent": {"en": "You can give consent again at any time in Consent Centre.", "ar": "يمكنك منح الموافقة مرة أخرى في أي وقت من مركز الموافقات."},
    "withdrawal_receipt.support": {"en": "Need help? Contact support.", "ar": "هل تحتاج إلى مساعدة؟ تواصل مع الدعم."},
    "withdrawal_receipt.not_legal": {"en": "This receipt is a plain record of your action. It is not a legal document or a signature.", "ar": "هذا الإيصال سجل بسيط لإجرائك. وهو ليس مستنداً قانونياً ولا توقيعاً."},
    # Timeline
    "timeline.withdrawn": {"en": "Withdrawn", "ar": "تم سحب الموافقة"},
    "timeline.pulls_stopped": {"en": "Pulls stopped", "ar": "تم إيقاف قراءة البيانات"},
    "timeline.revoked_at": {"en": "Revoked at {source}", "ar": "تم إلغاء الوصول لدى {source}"},
    "timeline.state.done": {"en": "Done", "ar": "تم"},
    "timeline.state.in_progress": {"en": "In progress", "ar": "قيد التنفيذ"},
    "timeline.state.pending": {"en": "Pending", "ar": "قيد الانتظار"},
    "timeline.state.failed": {"en": "Failed", "ar": "فشل"},
    # Notices (minimal content: type, date, status, sign-in link)
    "notice.consent_withdrawn": {"en": "A consent for {company} was withdrawn on {date}. Data pulls are paused. Sign in to review.", "ar": "تم سحب موافقة خاصة بـ{company} في {date}. سحب البيانات متوقف. سجّل الدخول للمراجعة."},
    "notice.consent_withdrawn_delegate": {"en": "A consent was withdrawn on {date}. Effect: drafts marked stale, approval blocked. Sign in to review.", "ar": "تم سحب موافقة في {date}. الأثر: المسودات معلّمة كقديمة، والاعتماد موقوف. سجّل الدخول للمراجعة."},
    "notice.evidence_access_ended": {"en": "Your evidence access for an engagement ended on {date} because the underlying consent was withdrawn.", "ar": "انتهى وصولك إلى الأدلة الخاصة بارتباط في {date} بسبب سحب الموافقة الأساسية."},
    "notice.consent_expiry": {"en": "A consent for {company} ends on {date}. Sign in to review and renew.", "ar": "تنتهي موافقة خاصة بـ{company} في {date}. سجّل الدخول للمراجعة والتجديد."},
    "notice.licence_expiry": {"en": "The licence of {company} ends on {date}. Data pulls will pause on that day. Sign in to review.", "ar": "تنتهي رخصة {company} في {date}. سيتوقف سحب البيانات في ذلك اليوم. سجّل الدخول للمراجعة."},
    "notice.paused": {"en": "Consents for {company} were paused on {date} ({reason}). Data pulls are paused. Sign in to review.", "ar": "تم إيقاف موافقات {company} مؤقتاً في {date} ({reason}). سحب البيانات متوقف. سجّل الدخول للمراجعة."},
    "notice.pause_limit_expired": {"en": "A paused consent for {company} reached its pause limit on {date}. A fresh consent is needed to resume. Sign in to review.", "ar": "بلغت موافقة موقوفة مؤقتاً لـ{company} حد الإيقاف في {date}. يلزم منح موافقة جديدة للاستئناف. سجّل الدخول للمراجعة."},
    "notice.consent_request": {"en": "{requester} asked for a consent right for {company} on {date}. Nothing was granted. Sign in to decide.", "ar": "طلب {requester} صلاحية موافقة لـ{company} في {date}. لم يُمنح شيء. سجّل الدخول للبت."},
    "notice.list_value_removed": {"en": "A purpose or data type was removed from the controlled list on {date}. The gate now denies it. Sign in to review.", "ar": "أُزيل غرض أو نوع بيانات من القائمة المضبوطة في {date}. تمنعه البوابة الآن. سجّل الدخول للمراجعة."},
    "notice.removed_delegate_grant": {"en": "A consent granted by a removed delegate needs your review (Keep or Withdraw). Sign in to decide.", "ar": "موافقة منحها مفوَّض أُزيلت صلاحيته تحتاج مراجعتك (إبقاء أو سحب). سجّل الدخول للبت."},
    "pause.reason.licence_expired": {"en": "licence expired", "ar": "انتهت الرخصة"},
    "pause.reason.subscription_ended": {"en": "subscription ended", "ar": "انتهى الاشتراك"},
    # Refusals
    "refusal.remote_owner_tax_consent": {"en": "Tax-data consent cannot be given or withdrawn online by an owner abroad in this phase. Contact DET support (help line) to record your authority. Nothing was changed.", "ar": "لا يمكن للمالك المقيم خارج الدولة منح موافقة البيانات الضريبية أو سحبها عبر الإنترنت في هذه المرحلة. تواصل مع دعم دائرة الاقتصاد والسياحة (خط المساعدة) لتسجيل صلاحيتك. لم يتغيّر شيء."},
    "refusal.delegate_right_off": {"en": "Only the owner, or a delegate with this right, can give or withdraw consent.", "ar": "يمكن للمالك، أو لمفوض لديه هذه الصلاحية، فقط منح الموافقة أو سحبها."},
    "refusal.authority_unclear": {"en": "Signing authority on the licence record is unclear. Resume is blocked. Contact DET support.", "ar": "صلاحية التوقيع في سجل الرخصة غير واضحة. الاستئناف موقوف. تواصل مع دعم دائرة الاقتصاد والسياحة."},
    "refusal.no_licensed_bank_route": {"en": "This bank link can't be turned on yet. Nothing was stored. We can tell you when it is available.", "ar": "لا يمكن تفعيل الربط مع هذا البنك بعد. لم يتم حفظ أي شيء. يمكننا إبلاغك عند توفره."},
    # Retention notice (category reasons only; no date, no instrument until confirmed)
    "retention.class_a": {"en": "Raw data pulled or uploaded under this consent: restricted at once; purge scheduled under the retention rule (period to be confirmed).", "ar": "البيانات الخام المسحوبة أو المرفوعة بموجب هذه الموافقة: مقيّدة فوراً؛ ومُجدول إتلافها وفق قاعدة الاحتفاظ (المدة قيد التأكيد)."},
    "retention.class_b": {"en": "Records behind a filed return, a signed audit file or an open escalation: kept under legal hold for the statutory period, to be confirmed.", "ar": "السجلات المرتبطة بإقرار مقدَّم أو ملف تدقيق موقَّع أو تصعيد مفتوح: محفوظة بحكم القانون للمدة النظامية، قيد التأكيد."},
    "retention.class_c": {"en": "Audit trail and consent receipts: kept, with personal fields minimised.", "ar": "سجل التدقيق وإيصالات الموافقة: محفوظة مع تقليل الحقول الشخصية."},
}

AUDIENCE: dict[str, str] = {k: ("official" if k.startswith(("receipt", "withdrawal_receipt", "retention", "refusal")) else "other") for k in STRINGS}

try:  # the catalogue module registers strings for the release check; keep the dict usable without it
    from app.modules.catalogue.service import register_strings

    register_strings("consent", STRINGS, AUDIENCE)
except ImportError:  # pragma: no cover
    pass


def s(key: str, lang: str, **params: object) -> str:
    item = STRINGS.get(key, {})
    value = item.get(lang) or item.get("en") or key
    try:
        return value.format(**params) if params else value
    except (KeyError, IndexError):
        return value
