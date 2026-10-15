import i18n from 'i18next'

/** SC15 owner/delegate activity list strings (E1-S3 wording verbatim; the row texts themselves come from the backend). */
const en = {
  nav: 'Activity',
  title: 'Activity',
  intro: 'What happened on this company, in plain language. No figures, identity numbers or bank details are shown here.',
  own_only: 'You see your own actions only, including refused and held ones.',
  col_time: 'When', col_actor: 'Who', col_action: 'What happened', col_company: 'Company', col_object: 'Reference', col_outcome: 'Outcome',
  filter_type: 'Action type', filter_outcome: 'Outcome', filter_from: 'From', filter_to: 'To', filter_actor: 'Person',
  all: 'All',
  outcome_done: 'Done', outcome_refused: 'Refused', outcome_quarantined: 'Quarantined',
  k1: 'Sign-in', k2: 'Data viewed', k3: 'Document uploaded', k4: 'AI draft prepared', k5: 'Return pack approved', k6: 'Approval voided', k7: 'Consent', k8: 'Delegate change', k9: 'Specialist request', k10: 'Audit working draft', k11: "Auditor's report signed", k12: 'Document issued or superseded', k13: 'Subscription', k14: 'Records exported',
  export: 'Export (PDF)', export_hint: 'In your language with the other language as a second page version. No hash columns.',
  export_ready: 'Export prepared. It was recorded in the activity list.',
  no_results: 'No results',
  retention: 'Kept for {{n}} months (illustrative, for production).',
  page: 'Page {{p}} of {{n}}', prev: 'Previous', next: 'Next',
  reason: 'Reason code',
}
const ar: typeof en = {
  nav: 'النشاط',
  title: 'النشاط',
  intro: 'ما حدث في هذه الشركة بلغة واضحة. لا تُعرض هنا أرقام مالية أو أرقام هوية أو تفاصيل مصرفية.',
  own_only: 'ترى إجراءاتك فقط، بما فيها المرفوضة والمحفوظة.',
  col_time: 'متى', col_actor: 'مَن', col_action: 'ما حدث', col_company: 'الشركة', col_object: 'المرجع', col_outcome: 'النتيجة',
  filter_type: 'نوع الإجراء', filter_outcome: 'النتيجة', filter_from: 'من', filter_to: 'إلى', filter_actor: 'الشخص',
  all: 'الكل',
  outcome_done: 'تم', outcome_refused: 'مرفوض', outcome_quarantined: 'قيد الحجر',
  k1: 'تسجيل الدخول', k2: 'الاطلاع على البيانات', k3: 'رفع مستند', k4: 'مسودة من الذكاء الاصطناعي', k5: 'اعتماد حزمة الإقرار', k6: 'إلغاء الموافقة', k7: 'الموافقة على مشاركة البيانات', k8: 'تغيير مفوَّض', k9: 'طلب مختص', k10: 'مسودة عمل التدقيق', k11: 'توقيع تقرير المدقق', k12: 'إصدار مستند أو استبداله', k13: 'الاشتراك', k14: 'تصدير السجلات',
  export: 'تصدير (PDF)', export_hint: 'بلغتك مع نسخة باللغة الأخرى كصفحة ثانية. بدون أعمدة تجزئة.',
  export_ready: 'تم تجهيز التصدير. سُجّل في قائمة النشاط.',
  no_results: 'لا توجد نتائج',
  retention: 'يُحتفظ به لمدة {{n}} شهراً (توضيحي، للإنتاج).',
  page: 'الصفحة {{p}} من {{n}}', prev: 'السابق', next: 'التالي',
  reason: 'رمز السبب',
}
i18n.addResourceBundle('en', 'activity', en)
i18n.addResourceBundle('ar', 'activity', ar)
