"""The guided demo journey: one coherent story across every role, told in chapters.

Each chapter names a persona, a starting screen, what to say (narration), what to click (steps) and what to
point out (points), in English and Arabic. The story follows the demo data seeded in app/demo.py, so every
step works on a fresh demo database. Arabic is a draft pending native review, like all product wording.
"""

from __future__ import annotations

PROLOGUE = {
    "title": {"en": "A year in the life of a Dubai licence holder", "ar": "عام في حياة صاحب رخصة تجارية في دبي"},
    "narration": {
        "en": (
            "Khalid owns Al Noor Trading, a mainland company licensed by DET. Every year he needs tax filings, "
            "deadline tracking, sometimes audit preparation, and the occasional legal question. Today he pays separate "
            "accountants, consultants and intermediaries (often AED 1,000 to 3,000 for a simple procedure), and a missed "
            "deadline means a penalty. Smart Licence Services adds one optional subscription to his licence: AI agents "
            "prepare the work, licensed humans step in where the law requires, and Khalid stays in control of every "
            "submission. Follow his year, and the people around him."
        ),
        "ar": (
            "خالد يملك شركة النور للتجارة، وهي شركة في البر الرئيسي مرخّصة من دائرة الاقتصاد والسياحة. يحتاج كل عام إلى تقديم "
            "الإقرارات الضريبية ومتابعة المواعيد، وأحياناً الإعداد للتدقيق، وأسئلة قانونية من حين لآخر. اليوم يدفع لمحاسبين "
            "ومستشارين ووسطاء منفصلين (غالباً من 1,000 إلى 3,000 درهم للإجراء البسيط)، وأي تأخير يعني غرامة. تضيف خدمات الرخصة "
            "الذكية اشتراكاً اختيارياً واحداً إلى رخصته: يُعدّ وكلاء الذكاء الاصطناعي العمل، ويتدخل مختصون مرخّصون حيث يشترط "
            "القانون، ويبقى خالد صاحب القرار في كل تقديم. تابع عامه ومن حوله."
        ),
    },
}

EPILOGUE = {
    "title": {"en": "What is live, and what waits for confirmation", "ar": "ما هو متاح الآن، وما ينتظر التأكيد"},
    "narration": {
        "en": (
            "Everything you saw runs on the pilot rules. Live tax-authority filing, bank links through a licensed Open "
            "Finance provider, delegate approval rights, auditor signing and lawyer routing are built and tested, but "
            "switched off until the FTA, the Central Bank route, DET and counsel confirm them. Every fee, threshold, window "
            "and wording sits in a versioned register with an owner and a 'to be confirmed' status, so confirming a rule "
            "is a recorded configuration change, not a code release."
        ),
        "ar": (
            "كل ما رأيته يعمل وفق قواعد البرنامج التجريبي. التقديم المباشر إلى الهيئة الاتحادية للضرائب، وربط الحسابات المصرفية "
            "عبر مزوّد مرخّص للتمويل المفتوح، وصلاحيات الموافقة للمفوَّضين، وتوقيع المدقق، والإحالة إلى المحامين، كلها مبنية "
            "ومختبرة لكنها متوقفة حتى تؤكدها الهيئة والمصرف المركزي والدائرة والمستشار القانوني. كل رسم وحد ومهلة وصياغة محفوظة "
            "في سجل بإصدارات ومالك وحالة 'رهن التأكيد'، فيصبح تأكيد القاعدة تغييراً موثقاً في الإعدادات لا إصداراً جديداً للبرنامج."
        ),
    },
}


def _ch(cid, persona, path, title_en, title_ar, narration_en, narration_ar, steps, points, company_id=None):
    return {
        "id": cid,
        "persona": persona,
        "path": path,
        "company_id": company_id,
        "title": {"en": title_en, "ar": title_ar},
        "narration": {"en": narration_en, "ar": narration_ar},
        "steps": [{"en": e, "ar": a} for e, a in steps],
        "points": [{"en": e, "ar": a} for e, a in points],
    }


CHAPTERS = [
    _ch(
        "renewal", "khalid", "/welcome",
        "The renewal brings a new service", "التجديد يأتي بخدمة جديدة",
        "Khalid has just renewed his licence. He signs in with UAE PASS for the first time and sees what the subscription is, what it costs, and what it does not cover.",
        "جدّد خالد رخصته للتو. يسجّل الدخول عبر الهوية الرقمية لأول مرة ويرى ما هو الاشتراك، وكم يكلّف، وما الذي لا يشمله.",
        [
            ("Sign in with UAE Pass: there is no password and no other sign-in route.", "سجّل الدخول عبر الهوية الرقمية: لا كلمة مرور ولا طريقة دخول أخرى."),
            ("Accept the one-time privacy notice.", "اقبل إشعار الخصوصية الذي يظهر مرة واحدة."),
            ("Walk down the welcome page: the fee line, what is covered, what is not included.", "تصفّح صفحة الترحيب: بند الرسوم، وما يشمله الاشتراك، وما لا يشمله."),
            ("Show the setup checklist, then press Done.", "اعرض قائمة الإعداد، ثم اضغط تم."),
        ],
        [
            ("The subscription is a separate line from the licence fee, and the licence never depends on it.", "الاشتراك بند منفصل عن رسوم الرخصة، والرخصة لا تتوقف عليه أبداً."),
            ("Fees are shown as an example; unconfirmed wording is labelled 'Proposed wording - pending confirmation'.", "تظهر الرسوم كمثال، والصياغة غير المؤكدة موسومة 'صياغة مقترحة - بانتظار التأكيد'."),
            ("The pilot is opt-in until DET and Qeonix sign the agreement; default-on billing stays switched off.", "البرنامج التجريبي بالاشتراك الطوعي حتى توقيع الاتفاقية، والفوترة التلقائية متوقفة."),
        ],
        company_id="co_alnoor",
    ),
    _ch(
        "dashboard", "khalid", "/dashboard",
        "One place for every deadline", "مكان واحد لكل المواعيد",
        "Instead of calendars and reminders from five providers, Khalid sees his VAT return, licence renewal, Ejari and corporate tax in one view, with what is ready and what is missing.",
        "بدلاً من تقاويم وتذكيرات من خمسة مزودين، يرى خالد إقرار ضريبة القيمة المضافة وتجديد الرخصة وإيجاري وضريبة الشركات في شاشة واحدة، مع ما هو جاهز وما هو ناقص.",
        [
            ("Read the four deadline cards: VAT is due soon and its draft is ready for review.", "اقرأ بطاقات المواعيد الأربع: ضريبة القيمة المضافة مستحقة قريباً ومسودتها جاهزة للمراجعة."),
            ("Point to the Ejari warning: the tenancy contract must be renewed before the licence can be.", "أشر إلى تنبيه إيجاري: يجب تجديد عقد الإيجار قبل تجديد الرخصة."),
            ("Scroll to Audit status: 'Likely not required', as an indicator only.", "انزل إلى حالة التدقيق: 'غير مطلوب على الأرجح'، كمؤشر فقط."),
            ("Open Deadlines in the menu to show the full list.", "افتح المواعيد من القائمة لعرض القائمة الكاملة."),
        ],
        [
            ("Statutory dates are never moved; computed dates are labelled 'calculated' with their source and rule version.", "لا تُنقل المواعيد القانونية أبداً، والمواعيد المحسوبة موسومة 'محسوب' مع مصدرها وإصدار القاعدة."),
            ("Every AI-prepared item says so and shows its review status.", "كل عنصر أعدّه الذكاء الاصطناعي يوضح ذلك ويعرض حالة مراجعته."),
            ("Audit is not presented as mandatory: most licence holders do not need audited statements.", "لا يُعرض التدقيق على أنه إلزامي: معظم أصحاب الرخص لا يحتاجون بيانات مدققة."),
        ],
        company_id="co_alnoor",
    ),
    _ch(
        "consent", "khalid", "/consent",
        "Data with consent, never by default", "البيانات بالموافقة، لا افتراضياً",
        "The agents need books and bank data. Khalid decides what is shared, for what purpose and for how long, and can withdraw in one step.",
        "يحتاج الوكلاء إلى الدفاتر والبيانات المصرفية. يقرر خالد ما يُشارك ولأي غرض ولأي مدة، ويمكنه السحب بخطوة واحدة.",
        [
            ("Show the active ledger and invoice authorisation and what it does not read.", "اعرض تفويض الدفاتر والفواتير النشط وما لا يقرؤه."),
            ("Show the bank card: banks connect only through a licensed Open Finance provider, not yet available in the pilot.", "اعرض بطاقة البنك: تتصل البنوك فقط عبر مزوّد مرخّص للتمويل المفتوح، وهو غير متاح بعد في البرنامج التجريبي."),
            ("Press Withdraw consent, read the dialog, then keep the consent.", "اضغط سحب الموافقة، واقرأ النافذة، ثم احتفظ بالموافقة."),
            ("Point to the manual uploads line, labelled 'manual, unverified'.", "أشر إلى سطر الملفات المرفوعة، الموسوم 'يدوي، غير متحقق منه'."),
        ],
        [
            ("No screen scraping and no bank credentials: the platform never logs into a bank.", "لا استخلاص من الشاشات ولا بيانات دخول مصرفية: المنصة لا تدخل إلى أي بنك."),
            ("Withdrawal stops data pulls at once and never promises deletion of records the law requires to keep.", "السحب يوقف سحب البيانات فوراً، ولا يعد بحذف السجلات التي يلزم القانون الاحتفاظ بها."),
            ("Uploaded statements count as data, never as a bank link.", "الكشوف المرفوعة تُعد بيانات، وليست ربطاً مصرفياً."),
        ],
        company_id="co_alnoor",
    ),
    _ch(
        "delegate", "omar", "/portfolio",
        "The accountant prepares the return", "المحاسب يُعدّ الإقرار",
        "Omar is the accountant Khalid nominated. He works across several companies, checks what the AI classified, fixes what it could not, and prepares the VAT return. He cannot approve it.",
        "عمر هو المحاسب الذي عيّنه خالد. يعمل لعدة شركات، ويتحقق مما صنّفه الذكاء الاصطناعي، ويصحح ما لم يستطع تصنيفه، ويُعدّ إقرار ضريبة القيمة المضافة. لا يستطيع اعتماده.",
        [
            ("Show My companies: sorted by nearest deadline, with what is missing per company.", "اعرض شركاتي: مرتبة حسب أقرب موعد، مع النواقص لكل شركة."),
            ("Open Tax workspace for Al Noor and filter to 'Needs review'.", "افتح مساحة العمل الضريبية لشركة النور واختر 'تحتاج مراجعة'."),
            ("Point to the row whose text tries to give instructions: it was treated as data only.", "أشر إلى السطر الذي يحاول نصه إعطاء تعليمات: عومل كبيانات فقط."),
            ("Correct 'Deposit K. Al Mansoori' to Owner drawings, VAT code Out of scope, and save.", "صحّح 'إيداع خ. المنصوري' إلى سحوبات المالك، برمز ضريبة خارج النطاق، واحفظ."),
            ("Open Draft returns, then the open quarter's VAT draft: show the watermark and the source and basis.", "افتح مسودات الإقرارات، ثم مسودة ضريبة القيمة المضافة للربع المفتوح: اعرض العلامة المائية والمصدر وأساس الحساب."),
            ("Open Return review: the return waits for the owner; Omar has no approve button.", "افتح مراجعة الإقرار: الإقرار بانتظار المالك، ولا يملك عمر زر الموافقة."),
        ],
        [
            ("Classification follows fixed rules with a stated basis; when there is none it says 'Needs review: no basis found'.", "التصنيف يتبع قواعد ثابتة بأساس معلن، وعند غيابه يقول 'تحتاج مراجعة: لا يوجد أساس'."),
            ("Text inside documents can never change what the agents do.", "النص داخل المستندات لا يمكنه تغيير ما يفعله الوكلاء."),
            ("Delegates prepare and review; consent, approval and subscription rights are switched off in the pilot.", "المفوَّضون يُعدّون ويراجعون، وصلاحيات الموافقة على البيانات والاعتماد والاشتراك متوقفة في البرنامج التجريبي."),
        ],
        company_id="co_alnoor",
    ),
    _ch(
        "approval", "khalid", "/returns",
        "The owner approves; nothing is filed automatically", "المالك يعتمد، ولا شيء يُقدَّم تلقائياً",
        "Khalid reviews the return Omar prepared, approves it with UAE PASS, files it himself on EmaraTax, and records the filing reference.",
        "يراجع خالد الإقرار الذي أعدّه عمر، ويعتمده عبر الهوية الرقمية، ثم يقدّمه بنفسه على إيماراتاكس ويسجّل مرجع التقديم.",
        [
            ("Open the VAT return waiting for approval.", "افتح إقرار ضريبة القيمة المضافة المنتظر للاعتماد."),
            ("Walk through the figures, source data and calculation basis.", "استعرض الأرقام وبيانات المصدر وأساس الحساب."),
            ("Tick that you reviewed the figures, press Approve, then Continue with UAE PASS.", "أشّر أنك راجعت الأرقام، واضغط موافقة، ثم المتابعة عبر الهوية الرقمية."),
            ("Read the approval record: who, when, on which data version, valid until when.", "اقرأ سجل الموافقة: من، ومتى، وعلى أي إصدار من البيانات، وحتى متى."),
            ("In Filing, enter today's date and reference FTA2026Q3B4410, confirm you filed it yourself, and record it.", "في قسم التقديم، أدخل تاريخ اليوم والمرجع FTA2026Q3B4410، وأكّد أنك قدّمته بنفسك، وسجّله."),
        ],
        [
            ("The approval is bound to a hash of the draft: any change to the data voids it.", "الموافقة مرتبطة ببصمة المسودة: أي تغيير في البيانات يلغيها."),
            ("Approved by and Submitted by are always shown separately.", "يظهر 'اعتمدها' و'قدّمها' دائماً بشكل منفصل."),
            ("The filing is recorded as self-declared and 'not verified by the authority' until the FTA agrees a channel.", "يُسجَّل التقديم كإقرار ذاتي 'لم تتحقق منه الجهة' حتى تتفق الهيئة على قناة."),
        ],
        company_id="co_alnoor",
    ),
    _ch(
        "help", "khalid", "/help",
        "Information, not advice, and a human when it matters", "معلومات لا استشارة، ومختص عند الحاجة",
        "Khalid has questions. General ones are answered from the cited law. Questions about his own company's position go to a licensed human.",
        "لدى خالد أسئلة. يُجاب عن العامة منها من القانون المُستشهد به، وتُحال الأسئلة عن وضع شركته إلى مختص مرخّص.",
        [
            ("Ask: 'What is the VAT return deadline after the end of a tax period?'", "اسأل: 'ما موعد إقرار ضريبة القيمة المضافة بعد نهاية الفترة الضريبية؟'"),
            ("Show the cited instrument and article, the authoritative Arabic text and the 'General information, not legal or tax advice' label.", "اعرض الأداة القانونية والمادة المُستشهد بهما، والنص العربي المعتمد، ووسم 'معلومات عامة، وليست استشارة قانونية أو ضريبية'."),
            ("Ask: 'Should my company elect Small Business Relief this year?'", "اسأل: 'هل يجب أن تختار شركتي إعفاء الأعمال الصغيرة هذا العام؟'"),
            ("Show that it is routed to a human tax specialist, then show the case list.", "اعرض أنه أُحيل إلى مختص ضرائب، ثم اعرض قائمة الحالات."),
        ],
        [
            ("Answers come only from a curated, versioned legal corpus, never from the open internet.", "تأتي الإجابات فقط من مجموعة نصوص قانونية منتقاة وبإصدارات، لا من الإنترنت المفتوح."),
            ("Questions about the company's own position are refused and routed, not guessed.", "الأسئلة عن وضع الشركة نفسها تُرفض وتُحال، ولا تُخمَّن."),
            ("Legal questions get a neutral message only until a licensed law firm route is agreed.", "الأسئلة القانونية تتلقى رسالة محايدة فقط حتى الاتفاق على مسار مع مكتب محاماة مرخّص."),
        ],
        company_id="co_alnoor",
    ),
    _ch(
        "specialist", "hassan", "/cases",
        "The specialist works only on what was shared", "المختص يعمل فقط على ما شُورك",
        "Hassan is a tax specialist. He sees only the cases assigned to him, and only the data the owner consented to share for that case.",
        "حسن مختص ضرائب. يرى فقط الحالات المسندة إليه، وفقط البيانات التي وافق المالك على مشاركتها لتلك الحالة.",
        [
            ("Show My cases: status, priority, and active versus raw working days.", "اعرض حالاتي: الحالة والأولوية وأيام العمل الفعلية مقابل الإجمالية."),
            ("Open a resolved case and show the coded outcome.", "افتح حالة منتهية واعرض نتيجتها المرمّزة."),
            ("Open the closed-without-consent case: work stopped because the owner did not consent.", "افتح الحالة المغلقة دون موافقة: توقف العمل لأن المالك لم يوافق."),
        ],
        [
            ("Every specialist access needs a valid licence on a register and a case-specific grant from the owner.", "كل وصول للمختص يتطلب ترخيصاً سارياً في سجل، وتفويضاً خاصاً بالحالة من المالك."),
            ("The turnaround clock pauses while waiting for the owner.", "تتوقف ساعة المعالجة أثناء انتظار المالك."),
            ("Specialists never see other companies or DET data.", "لا يرى المختصون أي شركات أخرى أو بيانات الدائرة."),
        ],
    ),
    _ch(
        "auditor", "layla", "/auditor",
        "Audit readiness, honestly labelled", "الجاهزية للتدقيق، بتسمية صادقة",
        "Gulf Tech belongs to a corporate tax group, so an audit is likely required. The AI prepared a draft working file. Dr. Layla, a licensed auditor, reviews it.",
        "تنتمي شركة جلف تك إلى مجموعة ضريبية، لذا يُرجّح أن التدقيق مطلوب. أعدّ الذكاء الاصطناعي ملف عمل مسودة، وتراجعه الدكتورة ليلى، المدققة المرخّصة.",
        [
            ("Open the Gulf Tech engagement from the queue.", "افتح تكليف جلف تك من قائمة الانتظار."),
            ("Show Register check and Firewall and independence.", "اعرض التحقق من السجل والفصل والاستقلالية."),
            ("Press Start review, open Exceptions, add a note to each and confirm one, dismiss the other.", "اضغط بدء المراجعة، وافتح الاستثناءات، وأضف ملاحظة لكل منها، وأكّد أحدها وارفض الآخر."),
            ("Press Record my review and confirm.", "اضغط تسجيل مراجعتي وأكّد."),
        ],
        [
            ("Nothing unsigned is ever called an audit report or certificate; drafts carry 'DRAFT - NOT AN AUDIT REPORT'.", "لا يُسمّى أي شيء غير موقّع تقرير تدقيق أو شهادة، وتحمل المسودات 'مسودة - ليست تقرير تدقيق'."),
            ("Signing stays off until the audit service model is agreed; the auditor records a review instead.", "يبقى التوقيع متوقفاً حتى الاتفاق على نموذج خدمة التدقيق، وتسجّل المدققة مراجعة بدلاً منه."),
            ("The firewall says 'no conflict found in DET records', never 'independent'.", "يقول الفصل 'لم يُعثر على تعارض في سجلات الدائرة'، ولا يقول 'مستقل' أبداً."),
        ],
    ),
    _ch(
        "documents", "khalid", "/documents",
        "Documents anyone can verify", "مستندات يمكن لأي أحد التحقق منها",
        "Khalid's documents are issued in Arabic and English from one record. A bank or landlord can check one without signing in.",
        "تصدر مستندات خالد بالعربية والإنجليزية من سجل واحد، ويمكن لبنك أو مؤجّر التحقق منها دون تسجيل دخول.",
        [
            ("Show the document list with status and verification codes.", "اعرض قائمة المستندات مع حالاتها ورموز التحقق."),
            ("Open the public verification page (link below) in a new tab.", "افتح صفحة التحقق العامة (الرابط أدناه) في تبويب جديد."),
        ],
        [
            ("The verification page shows status, type and reference only, never figures.", "تعرض صفحة التحقق الحالة والنوع والمرجع فقط، دون أي أرقام."),
            ("Arabic and English versions are checked against each other; a mismatch blocks issue.", "تُطابق النسختان العربية والإنجليزية، وأي اختلاف يمنع الإصدار."),
        ],
        company_id="co_alnoor",
    ),
    _ch(
        "det", "sara", "/det",
        "DET sees the whole pilot, never a company's books", "الدائرة ترى البرنامج كله، لا دفاتر أي شركة",
        "Sara at DET follows the pilot: subscriptions, collections, opt-outs, residency and phase gates. She never sees a company's financial detail.",
        "تتابع سارة في الدائرة البرنامج التجريبي: الاشتراكات والتحصيل وطلبات الإلغاء وموقع البيانات ومراحل الإطلاق، ولا ترى أي تفاصيل مالية لشركة.",
        [
            ("Pilot KPIs: active licences, revenue billed, collection rate, opt-out and complaint rate.", "مؤشرات البرنامج: الرخص النشطة، والإيرادات المفوترة، ونسبة التحصيل، ونسبة الإلغاء والشكاوى."),
            ("Show a breakdown where small groups read 'Fewer than 10'.", "اعرض تفصيلاً تظهر فيه المجموعات الصغيرة 'أقل من 10'."),
            ("Data residency and security: the release is blocked because one backup's location is unknown.", "موقع البيانات والأمان: الإطلاق محظور لأن موقع نسخة احتياطية واحدة غير معروف."),
            ("Phase map and gates: what is open, what waits for evidence.", "خريطة المراحل والبوابات: ما هو مفتوح، وما ينتظر الأدلة."),
        ],
        [
            ("Aggregates only, with one platform-wide minimum group size and complementary suppression.", "بيانات مجمّعة فقط، بحد أدنى موحد لحجم المجموعة وإخفاء تكميلي."),
            ("The owner's footer reads 'Residency under review' until every component is UAE-hosted.", "يقرأ تذييل المالك 'موقع البيانات قيد المراجعة' حتى تُستضاف كل المكونات في الإمارات."),
            ("Figures are labelled demo data in this environment and are not forecasts.", "الأرقام موسومة كبيانات تجريبية في هذه البيئة، وليست توقعات."),
        ],
    ),
    _ch(
        "complaints", "ahmed", "/det/requests",
        "Complaints are handled on the record", "الشكاوى تُعالج وتُوثّق",
        "Ahmed handles subscription complaints for DET, against a reply target the pilot manager can configure.",
        "يعالج أحمد شكاوى الاشتراك لصالح الدائرة، وفق مهلة رد يضبطها مدير البرنامج التجريبي.",
        [
            ("Show the complaint, its reply-by date and status.", "اعرض الشكوى وتاريخ الرد المطلوب وحالتها."),
            ("Update the status to Replied with a reason code.", "حدّث الحالة إلى 'تم الرد' مع رمز سبب."),
        ],
        [
            ("Complaints and opt-outs feed the K4 indicator DET sees from day one.", "تغذي الشكاوى وطلبات الإلغاء مؤشر K4 الذي تراه الدائرة من اليوم الأول."),
            ("The owner sees a neutral 'request received, DET decides' status, never an outcome promise.", "يرى المالك حالة محايدة 'تم استلام الطلب، والقرار للدائرة'، دون وعد بنتيجة."),
        ],
    ),
    _ch(
        "oversight", "noura", "/admin/audit-trail",
        "Every action is on the record", "كل إجراء موثّق",
        "Noura reviews oversight for DET and Qeonix. Everything from this story, every sign-in, consent, approval and review, is in one tamper-evident trail.",
        "تراجع نورة الرقابة لصالح الدائرة وكيونكس. كل ما في هذه القصة، من تسجيل دخول وموافقة واعتماد ومراجعة، موجود في سجل واحد مقاوم للتلاعب.",
        [
            ("Point to 'Integrity check passed' at the top.", "أشر إلى 'اجتاز فحص السلامة' في الأعلى."),
            ("Filter Category to approval: find Khalid's approval from earlier.", "اختر الفئة 'اعتماد': ابحث عن اعتماد خالد السابق."),
            ("Open a record's details: actors are pseudonymous keys, with no figures or identity numbers.", "افتح تفاصيل سجل: الأطراف بمفاتيح مستعارة، دون أرقام مالية أو أرقام هوية."),
        ],
        [
            ("The trail is append-only and hash-chained; any edit or gap fails the integrity check.", "السجل للإضافة فقط ومتسلسل بالبصمات، وأي تعديل أو فجوة يُفشل فحص السلامة."),
            ("Exports need a reason code and a second approver, and are themselves logged.", "يتطلب التصدير رمز سبب وموافقاً ثانياً، ويُسجَّل هو نفسه."),
        ],
    ),
]

PERSONA_ROLES = {
    "khalid": {"en": "Owner, Al Noor Trading", "ar": "المالك، النور للتجارة"},
    "omar": {"en": "Accountant (delegate)", "ar": "محاسب (مفوَّض)"},
    "hassan": {"en": "Tax specialist", "ar": "مختص ضرائب"},
    "layla": {"en": "Licensed auditor", "ar": "مدققة مرخّصة"},
    "sara": {"en": "DET administrator", "ar": "مسؤولة في دائرة الاقتصاد والسياحة"},
    "ahmed": {"en": "DET complaint handler", "ar": "معالج الشكاوى في الدائرة"},
    "noura": {"en": "Compliance and audit-trail reviewer", "ar": "مراجعة الامتثال وسجل التدقيق"},
}
