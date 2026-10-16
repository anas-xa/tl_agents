import i18n from 'i18next'

/** SC12 Delegate portfolio (E3-S4; Phase 2 refinements later). Arabic is a draft pending native review. */
const en = {
  title: 'My companies',
  intro: 'Companies you act for, nearest deadline first. You see only the functions each owner assigned to you.',
  loading: 'Loading your companies',
  error: 'We could not load your companies. Try again.',
  try_again: 'Try again',
  empty: 'No companies linked to your sign-in.',
  nearest: 'Nearest deadline',
  none_dated: 'No confirmed date yet',
  missing: 'Missing',
  nothing_missing: 'Nothing missing',
  send_pack: 'Send pack to owner for approval',
  open_draft: 'Open the draft',
  open_dashboard: 'Open dashboard',
  access_limits: 'What you can do here',
  withheld: 'Some obligations are not shared with you.',
  undated: 'Date not confirmed',
  only_owner_approve: 'Only the owner can approve',
  search: 'Find a company',
  no_match: 'No company matches your search.',
  count: 'Companies: {{count}}',
}
const ar: typeof en = {
  title: 'شركاتي',
  intro: 'الشركات التي تعمل لصالحها، الأقرب موعدًا أولًا. تظهر لك فقط المهام التي أسندها إليك كل مالك.',
  loading: 'جارٍ تحميل شركاتك',
  error: 'تعذّر تحميل شركاتك. حاول مرة أخرى.',
  try_again: 'حاول مرة أخرى',
  empty: 'لا توجد شركات مرتبطة بحسابك.',
  nearest: 'أقرب موعد',
  none_dated: 'لا يوجد تاريخ مؤكد بعد',
  missing: 'ناقص',
  nothing_missing: 'لا شيء ناقص',
  send_pack: 'إرسال الحزمة إلى المالك للموافقة',
  open_draft: 'افتح المسودة',
  open_dashboard: 'افتح اللوحة',
  access_limits: 'ما يمكنك فعله هنا',
  withheld: 'بعض الالتزامات غير مشاركة معك.',
  undated: 'التاريخ غير مؤكد',
  only_owner_approve: 'يمكن للمالك فقط الموافقة',
  search: 'ابحث عن شركة',
  no_match: 'لا توجد شركة تطابق بحثك.',
  count: 'عدد الشركات: {{count}}',
}
i18n.addResourceBundle('en', 'portfolio', en, true, true)
i18n.addResourceBundle('ar', 'portfolio', ar, true, true)
