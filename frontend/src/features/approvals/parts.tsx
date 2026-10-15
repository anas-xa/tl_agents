import { useTranslation } from 'react-i18next'
import { Chip, Ident } from '../../components/ui'
import { ApiError } from '../../lib/api'
import { formatDate, formatDateTime } from '../../lib/format'
import type { RequestRow } from './types'

export function useLang(): 'ar' | 'en' {
  const { i18n } = useTranslation()
  return i18n.language.startsWith('ar') ? 'ar' : 'en'
}

export function returnTitle(t: (k: string, o?: Record<string, unknown>) => string, r: { return_type: string; period_id: string }) {
  return `${t(r.return_type === 'ct' ? 'ct' : 'vat')} · ${t('period', { period: r.period_id })}`
}

/** Request status chip: icon + text, never colour alone. */
export function RequestChip({ r }: { r: RequestRow }) {
  const { t } = useTranslation('approvals')
  if (r.status === 'decided' && r.approval_valid) return <Chip tone="ok">{t('st_approved')}</Chip>
  if (r.status === 'decided') return <Chip tone="attention">{t('st_approval_expired')}</Chip>
  if (r.status === 'superseded') return <Chip tone="neutral" icon="↺">{t('st_superseded')}</Chip>
  if (r.status === 'expired') return <Chip tone="attention" icon="⌛">{t('st_expired')}</Chip>
  if (r.status === 'blocked') return <Chip tone="critical">{t('st_blocked')}</Chip>
  if (r.status === 'in_preparation') return <Chip tone="draft">{t('st_in_preparation')}</Chip>
  if (r.joint_collected > 0) return <Chip tone="info">{t('st_pending_joint')}</Chip>
  return <Chip tone="info" icon="◔">{t('st_ready')}</Chip>
}

/** Due date: GST first (no clock time unless the source states one); local time second only when different. */
export function DueDate({ date }: { date: string | null }) {
  const { t } = useTranslation('approvals')
  const lang = useLang()
  if (!date) return null
  const offsetMin = -new Date().getTimezoneOffset()
  const differs = offsetMin !== 240
  const end = new Date(`${date}T23:59:59+04:00`)
  const sign = offsetMin >= 0 ? '+' : '-'
  const offset = `UTC${sign}${Math.floor(Math.abs(offsetMin) / 60)}${Math.abs(offsetMin) % 60 ? `:${String(Math.abs(offsetMin) % 60).padStart(2, '0')}` : ''}`
  return (
    <div className="due-block">
      <strong>{t('due', { date: formatDate(date, lang) })}</strong>
      {differs && <div className="hint">{t('your_time', { when: `${formatDate(end, lang)}, ${end.toLocaleTimeString(lang === 'ar' ? 'ar-AE-u-nu-latn' : 'en-GB', { hour: '2-digit', minute: '2-digit' })}`, offset })}</div>}
    </div>
  )
}

export function Hash({ value }: { value: string | null | undefined }) {
  return <Ident>{(value || '').slice(0, 8)}</Ident>
}

export function when(value: string | null | undefined, lang: string) {
  return value ? formatDateTime(value, lang) : ''
}

/** Map a backend reason code to the spec's refusal wording (falls back to the generic line + reference). */
export function refusalText(t: (k: string, o?: Record<string, unknown>) => string, e: unknown): string {
  const code = e instanceof ApiError ? e.code : ''
  const map: Record<string, string> = {
    LEVEL_TOO_LOW_FOR_ACTION: 'level_too_low',
    RIGHT_SWITCHED_OFF: 'right_switched_off',
    REAUTH_FAILED: 'uaepass_failed',
    UAEPASS_CANCELLED: 'uaepass_cancelled',
    REQUEST_EXPIRED: 'request_expired',
    AUTHORITY_UNCLEAR: 'authority_unclear',
    ALREADY_APPROVED_BY_YOU: 'already_you',
    NO_PERMISSION: 'view_only',
    NO_APPROVAL_RIGHT: 'view_only',
    GRANT_SUSPENDED: 'view_only',
    GRANT_EXPIRED: 'view_only',
    GRANT_REVOKED: 'view_only',
    NOT_AUTHORITY_HOLDER: 'view_only',
    ON_HOLD: 'on_hold',
    APPROVAL_FLOW_SWITCHED_OFF: 'flow_off',
    REMINDER_RATE_LIMITED: 'reminder_limited',
    NO_OWNER_ROLE: 'ref_NO_OWNER_ROLE',
    NOT_OWNER_DELEGATE: 'ref_NOT_OWNER_DELEGATE',
    STALE_DATA: 'ref_STALE_DATA',
    DET_DATA_STALE: 'ref_STALE_DATA',
  }
  if (map[code]) return t(map[code])
  const ref = e instanceof ApiError && e.reference ? ` ${t('reference_id', { ref: e.reference })}` : ''
  return t('generic_error') + ref
}
