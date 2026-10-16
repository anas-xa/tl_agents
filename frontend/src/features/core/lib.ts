import { digits } from '../../lib/format'

const ACRONYMS = new Set(['DET', 'VAT', 'CT', 'AI', 'UAE', 'ID', 'KPI', 'SLA', 'FTA', 'TRN', 'PDF', 'API', 'SMS', 'URL', 'OTP', 'ESR', 'UBO', 'AML', 'IBAN'])

/** Humanise a raw code for display: AUDIT_TRAIL_VIEWED -> "Audit trail viewed", data_access -> "Data access". */
export function humanize(code: string | null | undefined): string {
  if (!code) return ''
  const words = code.replace(/[._-]+/g, ' ').trim().split(/\s+/)
  return words
    .map((w, i) => {
      const up = w.toUpperCase()
      if (ACRONYMS.has(up)) return up
      const low = w.toLowerCase()
      return i === 0 ? low.charAt(0).toUpperCase() + low.slice(1) : low
    })
    .join(' ')
}

const MONTHS_EN = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
const MONTHS_AR = ['يناير', 'فبراير', 'مارس', 'أبريل', 'مايو', 'يونيو', 'يوليو', 'أغسطس', 'سبتمبر', 'أكتوبر', 'نوفمبر', 'ديسمبر']

/** Short Dubai-time stamp for dense tables: "16 Oct 2026, 10:59" (the column header says "Dubai time"). */
export function shortDateTime(value: string | null | undefined, lang: string): string {
  if (!value) return ''
  const d = new Date(value.endsWith('Z') || value.includes('+') ? value : value + 'Z')
  if (Number.isNaN(d.getTime())) return ''
  const dubai = new Date(d.toLocaleString('en-US', { timeZone: 'Asia/Dubai' }))
  const month = (lang === 'ar' ? MONTHS_AR : MONTHS_EN)[dubai.getMonth()]
  const hh = String(dubai.getHours()).padStart(2, '0')
  const mm = String(dubai.getMinutes()).padStart(2, '0')
  return digits(`${dubai.getDate()} ${month} ${dubai.getFullYear()}${lang === 'ar' ? '،' : ','} ${hh}:${mm}`, lang)
}

/** Short date for dense tables: "16 Oct 2026". */
export function shortDate(value: string | null | undefined, lang: string): string {
  if (!value) return ''
  const d = new Date(value.length === 10 ? value + 'T00:00:00' : value)
  if (Number.isNaN(d.getTime())) return ''
  const month = (lang === 'ar' ? MONTHS_AR : MONTHS_EN)[d.getMonth()]
  return digits(`${d.getDate()} ${month} ${d.getFullYear()}`, lang)
}

/** Translated label for a known code, humanised fallback otherwise. */
export function labelFor(t: (k: string, o?: Record<string, unknown>) => string, group: string, code: string | null | undefined): string {
  if (!code) return ''
  return t(`core:${group}.${code}`, { defaultValue: humanize(code) })
}

/** One-line preview of a register value (strings without quotes, objects as compact JSON). */
export function preview(value: unknown): string {
  if (value === null || value === undefined) return '—'
  if (typeof value === 'string') return value
  return JSON.stringify(value)
}
