"""Bilingual strings for SC2, the subscription badges, the fee-line notices, removal/pause notices and the
proposed subscription terms (E2-S2/S3/S4). Every commercial or legal sentence carries the label
'Proposed wording - pending confirmation'. Arabic is copied from the spec where supplied; the rest is a draft
pending native review."""

from __future__ import annotations

PROPOSED = {"en": "Proposed wording - pending confirmation", "ar": "صياغة مقترحة - بانتظار الاعتماد"}

STRINGS = {
    "proposed_wording": PROPOSED,
    # Lifecycle badges and messages (Q276)
    "badge_pending_billing": {"en": "Pending billing", "ar": "بانتظار الفوترة"},
    "msg_pending_billing": {"en": "Your subscription is set up. DET will collect it with your licence fee. Nothing is due from you here.", "ar": "تم إعداد اشتراكك. ستحصّله دائرة الاقتصاد والسياحة مع رسوم رخصتك. لا يوجد مبلغ مطلوب منك هنا."},
    "badge_billing_requested": {"en": "Billing requested", "ar": "تم طلب الفوترة"},
    "msg_billing_requested": {"en": "We have asked DET to add this to your licence fee. You will see it on your DET payment.", "ar": "طلبنا من الدائرة إضافة هذا المبلغ إلى رسوم رخصتك. سيظهر في دفعتك لدى الدائرة."},
    "badge_awaiting_det_confirmation": {"en": "Awaiting DET confirmation", "ar": "بانتظار تأكيد الدائرة"},
    "msg_awaiting_det_confirmation": {"en": "DET is confirming the payment. Your licence is not affected.", "ar": "تؤكد الدائرة الدفع الآن. رخصتك غير متأثرة."},
    "badge_active": {"en": "Active", "ar": "نشط"},
    "msg_active": {"en": "Your subscription is active. Term: {start} to {end}.", "ar": "اشتراكك نشط. المدة: {start} إلى {end}."},
    "badge_held_for_review": {"en": "Held for review", "ar": "قيد المراجعة"},
    "msg_held_for_review": {"en": "Your subscription is being checked with DET. You will not be charged until it is confirmed.", "ar": "يجري التحقق من اشتراكك مع الدائرة. لن يتم تحصيل أي مبلغ حتى يتم التأكيد."},
    "badge_ended": {"en": "Ended", "ar": "منتهٍ"},
    "msg_ended": {"en": "Your subscription ended on {date} because {cause}. Your licence is not affected.", "ar": "انتهى اشتراكك في {date} بسبب {cause}. رخصتك غير متأثرة."},
    "badge_cancelled": {"en": "Cancelled", "ar": "ملغى"},
    "msg_cancelled": {"en": "This subscription was cancelled on {date}. Any refund is decided by DET.", "ar": "أُلغي هذا الاشتراك في {date}. تقرر الدائرة أي استرداد."},
    "badge_opted_out": {"en": "Opted out", "ar": "غير مشترك"},
    "msg_opted_out": {"en": "You chose not to have this service. Your licence is not affected. You can ask to join again at any time.", "ar": "اخترتَ عدم الاشتراك في هذه الخدمة. رخصتك غير متأثرة. يمكنك طلب الاشتراك مجددًا في أي وقت."},
    "badge_billed": {"en": "Billed", "ar": "مفوترة"},
    "badge_paused": {"en": "Paused", "ar": "متوقف مؤقتاً"},
    "only_owner_changes": {"en": "Only the owner can change the subscription.", "ar": "المالك وحده يمكنه تغيير الاشتراك."},
    # SC2 wording list
    "you_chose": {"en": "You chose this service", "ar": "اخترت هذه الخدمة"},
    "optional_line": {"en": "Optional smart services subscription: AED {amount} per year. Added to your total. You can remove it now or cancel later.", "ar": "اشتراك اختياري في الخدمات الذكية: {amount} درهم سنويًا. يُضاف إلى إجمالي المبلغ. يمكنك إزالته الآن أو إلغاؤه لاحقًا."},
    "term": {"en": "Term: {start} to {end}", "ar": "المدة: {start} إلى {end}"},
    "licence_fee": {"en": "Licence fee: AED {amount}", "ar": "رسوم الرخصة: {amount} درهم"},
    "subscription_line": {"en": "Smart services subscription: AED {amount} per {period}", "ar": "اشتراك الخدمات الذكية: {amount} درهم لكل {period}"},
    "collected_by_det": {"en": "Collected by DET with your licence fee", "ar": "تحصّله الدائرة مع رسوم رخصتك"},
    "total_collected": {"en": "Total collected: AED {amount}", "ar": "إجمالي المحصّل: {amount} درهم"},
    "fee_schedule_line": {"en": "Fee schedule {version}, in force from {date}", "ar": "جدول الرسوم {version}، ساري من {date}"},
    "opt_out_settings_line": {"en": "Opt-out and refund settings {version}", "ar": "إعدادات إلغاء الاشتراك والاسترداد {version}"},
    "opt_out_settings_not_set": {"en": "Opt-out and refund settings: not set", "ar": "إعدادات إلغاء الاشتراك والاسترداد: غير محددة"},
    "example_fee": {"en": "Example fee (pilot only)", "ar": "رسوم مثال (للمرحلة التجريبية فقط)"},
    "example_banner": {"en": "Example fee. This amount is an example for the pilot. No live billing is running and nothing is being charged.", "ar": "رسوم مثال. هذا المبلغ مثال للمرحلة التجريبية. لا توجد فوترة فعلية ولا يتم تحصيل أي مبلغ."},
    "det_rule_not_set": {"en": "DET has not yet set the rules for opting out, refunds and complaints. Until it does, we show no dates or time limits for them.", "ar": "لم تحدد الدائرة بعد قواعد إلغاء الاشتراك والاسترداد والشكاوى. وحتى تفعل، لن نعرض أي تواريخ أو مهل زمنية لها."},
    "terms_tbc": {"en": "Some terms (opt-out, refund, notice period) are still to be confirmed with DET.", "ar": "بعض الشروط (إلغاء الاشتراك، الاسترداد، فترة الإشعار) لا تزال بانتظار التأكيد مع الدائرة."},
    "tbc_with_det": {"en": "to be confirmed with DET", "ar": "رهن التأكيد مع الدائرة"},
    "fixture_fee_label": {"en": "AED 600 (VAT treatment to be confirmed)", "ar": "600 درهم (معاملة ضريبة القيمة المضافة بانتظار التأكيد)"},
    "refund_placeholder": {"en": "Refund and cancellation terms: to be confirmed.", "ar": "شروط الاسترداد والإلغاء: بانتظار التأكيد."},
    "questions_fee": {"en": "Questions about this fee? See the terms.", "ar": "لديك أسئلة عن هذه الرسوم؟ راجع الشروط."},
    "separate_line": {"en": "The subscription is a separate line from your licence fee.", "ar": "الاشتراك بند منفصل عن رسوم رخصتك."},
    "not_dependent": {"en": "Your licence issuance or renewal does not depend on this subscription.", "ar": "لا يعتمد إصدار رخصتك أو تجديدها على هذا الاشتراك."},
    "can_opt_out": {"en": "You can ask to opt out.", "ar": "يمكنك طلب إلغاء الاشتراك."},
    "audit_not_required": {"en": "Most licence holders are not required to have audited financial statements for UAE corporate tax.", "ar": "لا يُلزم معظم أصحاب الرخص بتقديم بيانات مالية مدققة لأغراض ضريبة الشركات في الإمارات."},
    "audit_other_authorities": {"en": "Other authorities, banks or your licence activity may still require an audit.", "ar": "قد تظل جهات أخرى أو البنوك أو نشاط رخصتك تتطلب تدقيقًا."},
    # Empty states
    "empty_not_in_pilot": {"en": "No subscription on this licence. Smart licence services are in a pilot with selected companies. Your licence is not affected and nothing is due.", "ar": "لا يوجد اشتراك على هذه الرخصة. خدمات الرخصة الذكية في مرحلة تجريبية مع شركات مختارة. رخصتك غير متأثرة ولا يوجد مبلغ مستحق."},
    "empty_in_cohort": {"en": "Your subscription starts when your licence is issued or renewed. Nothing to pay now.", "ar": "يبدأ اشتراكك عند إصدار رخصتك أو تجديدها. لا يوجد ما تدفعه الآن."},
    "empty_not_found": {"en": "We could not find a subscription for this licence. Your licence is not affected. Contact support and we will check it for you.", "ar": "لم نجد اشتراكًا لهذه الرخصة. رخصتك لم تتأثر. تواصل مع الدعم وسنتحقق لك."},
    "error_load": {"en": "We could not load your subscription details. Your licence is not affected. Try again, or contact support.", "ar": "تعذّر تحميل تفاصيل اشتراكك. رخصتك لم تتأثر. حاول مرة أخرى أو تواصل مع الدعم."},
    # Fee-line notices (E2-S3)
    "notice_billed": {"en": "Your subscription fee of AED {amount} is on your licence invoice. Next step: pay with your licence fees.", "ar": "رسوم اشتراكك البالغة {amount} درهم مدرجة في فاتورة رخصتك. الخطوة التالية: السداد مع رسوم الرخصة."},
    "notice_pending_confirmation": {"en": "We sent your payment and are waiting for DET to confirm it. Nothing more is needed from you.", "ar": "أرسلنا دفعتك وننتظر تأكيد الدائرة. لا حاجة لأي إجراء منك."},
    "notice_on_hold": {"en": "Collection is paused. Reason: {reason}. Your licence is not affected.", "ar": "التحصيل متوقف مؤقتاً. السبب: {reason}. رخصتك غير متأثرة."},
    "notice_mismatch": {"en": "We are checking this fee with DET billing. Nothing more is needed from you.", "ar": "نتحقق من هذه الرسوم مع قسم الفوترة في الدائرة. لا حاجة لأي إجراء منك."},
    "notice_collected": {"en": "Paid on {date}. AED {amount}. Receipt", "ar": "تم السداد في {date}. {amount} درهم. الإيصال"},
    "notice_failed": {"en": "Your subscription fee of AED {amount} for {licence}, period {period}, was not paid. Cause: {cause}. Next step: pay through {channel}, or contact DET billing. Your licence issuance and renewal are not affected by this unpaid fee.", "ar": "لم يتم سداد رسوم الاشتراك البالغة {amount} درهم للرخصة رقم {licence} عن الفترة {period}. السبب: {cause}. الخطوة التالية: السداد عبر {channel} أو التواصل مع قسم الفوترة في الدائرة. لا يتأثر إصدار رخصتك أو تجديدها بهذه الرسوم غير المسددة."},
    "notice_partly_collected": {"en": "AED {paid} of AED {amount} received. AED {remaining} is still due. Next step: pay the remaining amount or contact DET billing.", "ar": "تم استلام {paid} درهم من {amount} درهم. المتبقي {remaining} درهم. الخطوة التالية: سداد المتبقي أو التواصل مع قسم الفوترة."},
    "notice_refunded": {"en": "AED {amount} was refunded on {date}. Reference {ref}.", "ar": "تم استرداد {amount} درهم في {date}. المرجع {ref}."},
    "notice_provisional": {"en": "Estimated by the platform (provisional)", "ar": "تقدير من المنصة (مؤقت)"},
    "notice_footer": {"en": "Your licence issuance and renewal are not affected.", "ar": "لا يتأثر إصدار رخصتك أو تجديدها."},
    "notice_unpaid": {"en": "We could not collect the Smart Licence Services subscription fee for licence {licence}. Your licence issuance and renewal are not affected by this. Until the fee is paid, the smart services for this licence may be paused. You can pay or update your payment method here: {link}. Your data stays protected, and any consent you gave is unchanged.", "ar": "لم نتمكن من تحصيل رسوم اشتراك الخدمات الذكية للرخصة رقم {licence}. لا يؤثر ذلك على إصدار رخصتك أو تجديدها. وإلى حين السداد قد يتم إيقاف الخدمات الذكية لهذه الرخصة مؤقتًا. يمكنك الدفع أو تحديث وسيلة الدفع هنا: {link}. تبقى بياناتك محمية، ولا يتغير أي موافقة منحتها."},
    "payment_reference": {"en": "payment reference", "ar": "مرجع الدفع"},
    "received_unallocated": {"en": "Payment received, not yet allocated to a line", "ar": "تم استلام الدفعة، ولم تُخصص بعد لبند"},
    "we_are_confirming": {"en": "We are confirming your payment. Nothing more is needed from you.", "ar": "نحن نؤكد دفعتك. لا حاجة لأي إجراء منك."},
    # Opt-out / request states (E2-S4)
    "request_received_det_decides": {"en": "Request received. DET decides.", "ar": "تم استلام الطلب. الدائرة تقرر."},
    "pending_banner": {"en": "Your request is received and waiting for DET to confirm. Your services continue until it is confirmed.", "ar": "استلمنا طلبك وهو بانتظار تأكيد دائرة الاقتصاد والسياحة. تستمر خدماتك إلى حين التأكيد."},
    "needs_det_action": {"en": "DET needs to take a step before this can go ahead. Your reference is {code}. Please keep it if you contact DET.", "ar": "تحتاج الدائرة إلى اتخاذ إجراء قبل المتابعة. رقمك المرجعي {code}. يرجى الاحتفاظ به عند التواصل مع الدائرة."},
    "refused_window_closed": {"en": "The period for stopping this service has ended, so this request cannot be accepted here. You can send a complaint or ask DET a question.", "ar": "انتهت المدة المتاحة لإيقاف هذه الخدمة، لذلك لا يمكن قبول الطلب هنا. يمكنك تقديم شكوى أو الاستفسار من الدائرة."},
    "already_stopped": {"en": "Smart services are already stopped for this licence.", "ar": "الخدمات الذكية متوقفة بالفعل لهذه الرخصة."},
    "window_not_set": {"en": "End of the stopping period: to be confirmed by DET", "ar": "نهاية مدة الإيقاف: سيتم تأكيدها من دائرة الاقتصاد والسياحة"},
    "understand_checkbox": {"en": "I understand what will stop.", "ar": "أفهم ما الذي سيتوقف."},
    "opt_out_requested_awaiting": {"en": "Opt-out requested, awaiting DET", "ar": "طُلب إلغاء الاشتراك، بانتظار الدائرة"},
    "chip_received": {"en": "Received", "ar": "مستلم"},
    "chip_pending": {"en": "Pending", "ar": "قيد التأكيد"},
    "chip_with_det": {"en": "With DET", "ar": "لدى الدائرة"},
    "chip_refused": {"en": "Refused", "ar": "مرفوض"},
    "chip_cancelled": {"en": "Cancelled", "ar": "ملغى"},
    "no_requests": {"en": "No requests or complaints yet.", "ar": "لا توجد طلبات أو شكاوى حتى الآن."},
    "only_owner_action": {"en": "Only the owner can do this. Ask the owner to act.", "ar": "هذا الإجراء للمالك فقط. يرجى مطالبة المالك بتنفيذه."},
    "no_emirates_id": {"en": "We could not match you to an Emirates ID on the licence record, so you cannot act as owner. You can view this page only. Next step: ask the owner or DET to correct the licence record, then sign in again.", "ar": "لم نتمكن من مطابقتك مع رقم هوية إماراتية في سجل الرخصة، لذلك لا يمكنك التصرف بصفة مالك. يمكنك الاطلاع على هذه الصفحة فقط. الخطوة التالية: اطلب من المالك أو من دائرة الاقتصاد والسياحة تصحيح سجل الرخصة، ثم سجّل الدخول مرة أخرى."},
    "complaint_reply_by": {"en": "We will reply by {date}", "ar": "سنرد بحلول {date}"},
    "complaint_contact_channel": {"en": "We will contact you through the channel you chose", "ar": "سنتواصل معك عبر القناة التي اخترتها"},
    "filed_by_for_owner": {"en": "Filed by {name}, for the owner", "ar": "قدّمها {name} نيابةً عن المالك"},
}
AUDIENCE = {k: ("other" if k.startswith("chip_") or k in ("payment_reference",) else "official") for k in STRINGS}

# Proposed subscription terms (versioned bilingual content store; version in config subscription.terms.version).
TERMS_SECTIONS = {
    "service": {"en": "Smart Licence Services subscription: AI agents prepare tax, audit-preparation and compliance work under human sign-off. Draft outputs are not signed audit reports or legal advice.", "ar": "اشتراك خدمات الرخصة الذكية: يعدّ وكلاء الذكاء الاصطناعي أعمال الضرائب والإعداد للتدقيق والامتثال تحت اعتماد بشري. المخرجات مسودات وليست تقارير تدقيق موقّعة ولا استشارة قانونية."},
    "optional": {"en": "The subscription is optional and can be declined. Your licence issuance or renewal does not depend on this subscription.", "ar": "الاشتراك اختياري ويمكن رفضه. لا يعتمد إصدار رخصتك أو تجديدها على هذا الاشتراك."},
    "price": {"en": "Example price: AED 600 a year (about AED 50 a month, display only). The subscription is a separate line from your licence fee. VAT treatment to be confirmed.", "ar": "سعر مثال: 600 درهم سنويًا (نحو 50 درهمًا شهريًا، للعرض فقط). الاشتراك بند منفصل عن رسوم رخصتك. معاملة ضريبة القيمة المضافة بانتظار التأكيد."},
    "cancel": {"en": "You can ask to opt out from the Subscription screen at any time. Refund and cancellation terms: to be confirmed.", "ar": "يمكنك طلب إلغاء الاشتراك من شاشة الاشتراك في أي وقت. شروط الاسترداد والإلغاء: بانتظار التأكيد."},
    "data": {"en": "Bank and financial data are read only with a separate, explicit consent. Paying for or keeping the subscription is never that consent.", "ar": "تُقرأ البيانات المصرفية والمالية فقط بموافقة منفصلة وصريحة. الدفع مقابل الاشتراك أو الاحتفاظ به ليس تلك الموافقة أبدًا."},
    "complaints": {"en": "Complaints are handled by DET within a configured period. Submit a complaint from the Subscription screen with your reference code.", "ar": "تتولى الدائرة معالجة الشكاوى خلال مدة محددة. قدّم شكواك من شاشة الاشتراك مع رمزك المرجعي."},
}

try:
    from app.modules.catalogue.service import register_strings

    register_strings("subscriptions", STRINGS, AUDIENCE)
    register_strings("subscriptions.terms", TERMS_SECTIONS, {k: "official" for k in TERMS_SECTIONS})
except ImportError:  # pragma: no cover
    pass
