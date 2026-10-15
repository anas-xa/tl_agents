import { useTranslation } from 'react-i18next'
import { Button, Chip, Dialog } from '../../components/ui'
import { formatDate, formatDateTime } from '../../lib/format'
import type { LinkRow, ReceiptOut, Timeline } from './types'

type Tone = 'neutral' | 'ok' | 'attention' | 'urgent' | 'critical' | 'info' | 'draft'

export function useLang() {
  const { i18n } = useTranslation()
  return i18n.language.startsWith('ar') ? 'ar' : 'en'
}

const CONSENT_TONE: Record<string, [Tone, string]> = {
  active: ['ok', '✓'],
  pending: ['info', '◷'],
  expired: ['critical', '⌛'],
  withdrawn_on_platform: ['neutral', '⏹'],
  revocation_confirmed_by_provider: ['neutral', '⏹'],
  superseded: ['neutral', '⇄'],
  paused: ['attention', '⏸'],
  paused_licence_expired: ['attention', '⏸'],
  paused_subscription_ended: ['attention', '⏸'],
}

export function ConsentChip({ status }: { status: string }) {
  const { t } = useTranslation('consent')
  const [tone, icon] = CONSENT_TONE[status] ?? ['neutral', '○']
  return <Chip tone={tone} icon={icon}>{t(`chip.${status}`)}</Chip>
}

const BADGE: Record<string, [Tone, string]> = {
  failed: ['critical', '✕'],
  consent_expired: ['critical', '⌛'],
  consent_withdrawn: ['neutral', '⏹'],
  stale: ['attention', '◷'],
  status_check_delayed: ['neutral', '◷!'],
  partial: ['attention', '◑'],
  connecting: ['info', '⟳'],
  not_available_yet: ['neutral', '◌'],
  active: ['ok', '✓'],
}

export function LinkBadge({ badge }: { badge: string }) {
  const { t } = useTranslation('consent')
  const [tone, icon] = BADGE[badge] ?? ['neutral', '○']
  return <Chip tone={tone} icon={icon}>{t(`badge.${badge}`)}</Chip>
}

export function MaskedAccount({ value }: { value: string | null | undefined }) {
  const { t } = useTranslation('consent')
  if (!value) return null
  const last = value.replace(/[^0-9A-Za-z]/g, '').slice(-4)
  return (
    <bdi dir="ltr" className="ident" aria-label={t('account_ending', { n: last })}>
      {value}
    </bdi>
  )
}

export function linkLine(t: (k: string, o?: Record<string, unknown>) => string, row: LinkRow, lang: string): string {
  const time = row.last_successful_refresh_at ? formatDateTime(row.last_successful_refresh_at, lang) : t('never')
  const source = row.source_name
  switch (row.badge) {
    case 'active':
      return t('line.active', { time })
    case 'stale':
      return t('line.stale', { n: Math.round(row.data_age_days ?? 0), date: time })
    case 'status_check_delayed':
      return t('line.status_check_delayed', { status: row.last_known?.status ?? '', time: row.last_known?.at ? formatDateTime(row.last_known.at, lang) : '' })
    case 'connecting':
      return t('line.connecting', { source })
    case 'not_available_yet':
      return t('line.not_available_yet', { source })
    case 'partial':
      return t('line.partial', { n: row.partial?.refreshed ?? 0, m: row.partial?.total ?? 0, names: (row.partial?.missing ?? []).join(', ') })
    case 'consent_withdrawn':
      return t('line.consent_withdrawn')
    case 'consent_expired':
      return t('line.consent_expired', { date: row.reason_line ? formatDate(row.reason_line.slice(0, 10), lang) : '' })
    case 'failed':
      return t('line.failed', { id: row.reference_id ?? '' })
    default:
      return ''
  }
}

export function TimelineList({ timeline, source }: { timeline: Timeline; source: string }) {
  const { t } = useTranslation('consent')
  const lang = useLang()
  return (
    <div>
      <h4 style={{ margin: '8px 0 4px' }}>{t('timeline')}</h4>
      <ol className="timeline" aria-live="polite">
        {timeline.steps.map((s, i) => (
          <li key={s.key}>
            <span aria-hidden="true">{s.state === 'done' ? '✓' : s.state === 'failed' ? '✕' : '◷'}</span>
            <span>
              {i + 1}. {t(`tl.${s.key}`, { bank: s.source ?? source })} · <strong>{t(`tl_state.${s.state}`)}</strong>
              {s.at && <span className="muted"> · {formatDateTime(s.at, lang)}</span>}
            </span>
          </li>
        ))}
      </ol>
    </div>
  )
}

export function ReceiptDialog({ receipt, onClose }: { receipt: ReceiptOut | null; onClose: () => void }) {
  const { t } = useTranslation('consent')
  const lang = useLang()
  if (!receipt) return null
  const body = lang === 'ar' ? receipt.ar : receipt.en
  const rows = body.rows ?? []
  const extra = Object.entries(body).filter(([k, v]) => !['title', 'rows', 'footer', 'reference', 'scope', 'retention', 'effects'].includes(k) && typeof v === 'string') as [string, string][]
  const effects = (body.effects as string[] | undefined) ?? []
  const retention = (body.retention as string[] | undefined) ?? []
  return (
    <Dialog open title={body.title} onClose={onClose} labelledBy="receipt-title">
      <p className="muted">
        <bdi dir="ltr">{receipt.receipt_number}</bdi>
      </p>
      {rows.length > 0 && (
        <dl className="kv">
          {rows.map((r) => (
            <div key={r.label} style={{ display: 'contents' }}>
              <dt>{r.label}</dt>
              <dd>{r.value}</dd>
            </div>
          ))}
        </dl>
      )}
      {effects.length > 0 && (
        <ul>
          {effects.map((e) => (
            <li key={e}>{e}</li>
          ))}
        </ul>
      )}
      {retention.length > 0 && (
        <>
          <h3 style={{ fontSize: '1rem' }}>{t('retention_title')}</h3>
          <ul>
            {retention.map((e) => (
              <li key={e}>{e}</li>
            ))}
          </ul>
        </>
      )}
      {extra.map(([k, v]) => (
        <p key={k}>{v}</p>
      ))}
      {body.footer && <p><strong>{body.footer}</strong></p>}
      <div className="actions">
        <Button variant="secondary" onClick={() => window.print()}>{t('print')}</Button>
        <Button autoFocus onClick={onClose}>{t('translation:common.close')}</Button>
      </div>
    </Dialog>
  )
}
