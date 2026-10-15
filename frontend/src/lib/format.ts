/**
 * Platform formatter (E1-S5). Dates always carry the written month; AED with two decimals; identifiers
 * (TRN, licence numbers, references) always Western digits in bidi isolation. The numeral style is a
 * platform-wide versioned configuration value (default western), never a per-user switch in Phase 1.
 */
export type NumeralStyle = 'western' | 'arabic_indic' | 'by_locale'

let numeralStyle: NumeralStyle = 'western'
export function setNumeralStyle(style: NumeralStyle) {
  numeralStyle = style
}
export function getNumeralStyle() {
  return numeralStyle
}

const AR_DIGITS = '٠١٢٣٤٥٦٧٨٩'
export function digits(value: string, lang: string): string {
  const useArabic = numeralStyle === 'arabic_indic' || (numeralStyle === 'by_locale' && lang === 'ar')
  if (!useArabic) return value
  return value.replace(/[0-9]/g, (d) => AR_DIGITS[Number(d)])
}

const MONTHS_EN = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December']
const MONTHS_AR = ['يناير', 'فبراير', 'مارس', 'أبريل', 'مايو', 'يونيو', 'يوليو', 'أغسطس', 'سبتمبر', 'أكتوبر', 'نوفمبر', 'ديسمبر']

export function formatDate(value: string | Date | null | undefined, lang: string): string {
  if (!value) return ''
  const d = typeof value === 'string' ? new Date(value.length === 10 ? value + 'T00:00:00' : value) : value
  if (Number.isNaN(d.getTime())) return ''
  const day = d.getDate()
  const month = (lang === 'ar' ? MONTHS_AR : MONTHS_EN)[d.getMonth()]
  const year = d.getFullYear()
  return digits(`${day} ${month} ${year}`, lang)
}

export function formatDateTime(value: string | Date | null | undefined, lang: string): string {
  if (!value) return ''
  const d = typeof value === 'string' ? new Date(value.endsWith('Z') || value.includes('+') ? value : value + 'Z') : value
  if (Number.isNaN(d.getTime())) return ''
  const dubai = new Date(d.toLocaleString('en-US', { timeZone: 'Asia/Dubai' }))
  const hh = String(dubai.getHours()).padStart(2, '0')
  const mm = String(dubai.getMinutes()).padStart(2, '0')
  const suffix = lang === 'ar' ? 'بتوقيت دبي' : 'Dubai time'
  return `${formatDate(dubai, lang)}, ${digits(`${hh}:${mm}`, lang)} ${suffix}`
}

export function formatAED(fils: number | null | undefined, lang: string, opts: { fromFils?: boolean } = { fromFils: true }): string {
  if (fils === null || fils === undefined) return ''
  const amount = opts.fromFils === false ? fils : fils / 100
  const str = amount.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
  return `AED ${digits(str, lang)}`
}

export function formatNumber(n: number | null | undefined, lang: string, fraction = 0): string {
  if (n === null || n === undefined) return ''
  return digits(n.toLocaleString('en-US', { minimumFractionDigits: fraction, maximumFractionDigits: fraction }), lang)
}

export function formatPercent(n: number | null | undefined, lang: string, fraction = 1): string {
  if (n === null || n === undefined) return ''
  return digits(n.toFixed(fraction), lang) + '%'
}

/** Arabic day-count agreement: 1 = يوم واحد, 2 = يومان, 3-10 = أيام, 11+ = يومًا. */
export function daysLeftLabel(days: number, lang: string): string {
  if (lang === 'ar') {
    const n = Math.abs(days)
    const word = n === 1 ? 'يوم واحد' : n === 2 ? 'يومان' : n <= 10 ? `${digits(String(n), lang)} أيام` : `${digits(String(n), lang)} يومًا`
    if (days === 0) return 'مستحق اليوم'
    if (days < 0) return `متأخر منذ ${word}`
    return `مستحق خلال ${word}`
  }
  if (days === 0) return 'Due today'
  if (days < 0) return `Overdue by ${Math.abs(days)} day${Math.abs(days) === 1 ? '' : 's'}`
  return `Due in ${days} day${days === 1 ? '' : 's'}`
}

export function daysLeftTier(days: number | null): 'neutral' | 'attention' | 'urgent' | 'critical' | 'unknown' {
  if (days === null || days === undefined) return 'unknown'
  if (days < 0) return 'critical'
  if (days <= 7) return 'urgent'
  if (days <= 30) return 'attention'
  return 'neutral'
}
