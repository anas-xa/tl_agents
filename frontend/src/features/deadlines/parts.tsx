import { useTranslation } from 'react-i18next'
import { Chip, Ident, Skeleton } from '../../components/ui'
import { daysLeftLabel, formatDate, formatDateTime } from '../../lib/format'
import { tierTone, useBi, useFetch, type Obligation } from './lib'

const CHIP_TONE: Record<string, { tone: 'neutral' | 'attention' | 'urgent' | 'critical' | 'info' | 'ok'; icon: string }> = {
  upcoming: { tone: 'neutral', icon: '○' },
  due_soon: { tone: 'attention', icon: '◔' },
  overdue: { tone: 'critical', icon: '✕' },
  overdue_status_unconfirmed: { tone: 'critical', icon: '✕' },
  date_not_confirmed: { tone: 'info', icon: '?' },
  date_being_updated: { tone: 'info', icon: '↻' },
  falls_on_weekend: { tone: 'info', icon: 'i' },
  falls_on_public_holiday: { tone: 'info', icon: 'i' },
  date_may_change: { tone: 'attention', icon: '!' },
  filed_outside_platform: { tone: 'neutral', icon: '✓' },
  status_unconfirmed: { tone: 'info', icon: '?' },
}

/** Days-left badge: icon + text from the platform formatter; no badge when the date is not confirmed. */
export function DaysBadge({ o }: { o: Obligation }) {
  const { t, i18n } = useTranslation('deadlines')
  if (o.done) return null
  if (o.days_left === null || o.due_date === null) return <Chip tone="info" icon="?">{t('undated')}</Chip>
  const tt = tierTone(o.days_left_tier)
  return <Chip tone={tt.tone} icon={tt.icon}>{daysLeftLabel(o.days_left, i18n.language)}</Chip>
}

export function StatusChips({ o }: { o: Obligation }) {
  const { t } = useTranslation('deadlines')
  return (
    <span style={{ display: 'inline-flex', gap: 6, flexWrap: 'wrap' }}>
      {o.status_chips.filter((c) => c !== 'moved_to_next_working_day').map((c) => {
        const ct = CHIP_TONE[c] ?? { tone: 'neutral', icon: '○' }
        return <Chip key={c} tone={ct.tone} icon={ct.icon}>{t(`chip.${c}`)}</Chip>
      })}
    </span>
  )
}

export function ReadinessChip({ o }: { o: Obligation }) {
  const { tx } = useBi()
  const tone = o.readiness === 'data_missing' ? 'attention' : o.readiness === 'draft_ready' ? 'draft' : o.readiness === 'owner_approved' || o.readiness === 'receipt_recorded' ? 'ok' : 'neutral'
  const icon = o.readiness === 'data_missing' ? '!' : o.readiness === 'draft_ready' ? '✎' : o.readiness === 'not_started' ? '○' : '✓'
  return <Chip tone={tone} icon={icon}>{tx(o.readiness_label)}</Chip>
}

/** Shown date or 'Date not confirmed' (with last confirmed / owner-entered dates labelled, never shown as current). */
export function ShownDate({ o }: { o: Obligation }) {
  const { t, i18n } = useTranslation('deadlines')
  if (o.due_date) return <span>{formatDate(o.due_date, i18n.language)}</span>
  return (
    <span>
      <strong>{t('undated')}</strong>
      {o.last_confirmed_date && <span className="helper"> · {t('last_confirmed', { date: formatDate(o.last_confirmed_date, i18n.language) })}</span>}
      {!o.last_confirmed_date && o.provisional_date && <span className="helper"> · {t('provisional', { date: formatDate(o.provisional_date, i18n.language) })}</span>}
    </span>
  )
}

export function SourceLine({ o }: { o: Obligation }) {
  const { t } = useTranslation('deadlines')
  const basis = o.input_source === 'delegate_entered' ? t('basis_delegate') : o.data_basis === 'based_on_verified_details' ? t('basis_verified') : t('basis_entered')
  return (
    <span className="helper" style={{ display: 'inline-flex', gap: 8, flexWrap: 'wrap', alignItems: 'center' }}>
      <Chip tone="info" icon={o.is_stated ? '⚑' : '∑'}>{o.is_stated ? t('source_stated') : t('source_computed')}</Chip>
      <span>{basis}</span>
      {o.calculated && o.due_date && <span>· {t('calculated')}</span>}
      {o.calendar_version && <span>· {t('calendar_version', { v: o.calendar_version })}</span>}
      {o.rule_version && <span>· {t('rule_version', { v: o.rule_version })}</span>}
    </span>
  )
}

export function MissingList({ o }: { o: Obligation }) {
  const { t } = useTranslation('deadlines')
  const { lang } = useBi()
  if (!o.missing_items.length) return null
  return (
    <div>
      <span className="helper">{t('missing_items')}:</span>
      <ul style={{ margin: '4px 0', paddingInlineStart: 20 }}>
        {o.missing_items.map((m) => <li key={m.code}><Chip tone="attention" icon="!">{t('missing')}</Chip> {lang === 'ar' ? m.label_ar : m.label_en}</li>)}
      </ul>
    </div>
  )
}

export function DateUpdatedChip({ o }: { o: Obligation }) {
  const { t, i18n } = useTranslation('deadlines')
  if (!o.date_updated) return null
  const d = o.date_updated
  return (
    <span>
      <Chip tone="info" icon="↻">{t('date_updated')}</Chip>{' '}
      <span className="helper">
        <s>{formatDate(d.old_date, i18n.language)}</s> → {formatDate(d.new_date, i18n.language)} · {formatDateTime(d.change_time, i18n.language)} · {d.source_tag}
      </span>
    </span>
  )
}

interface Detail extends Obligation {
  history: { at: string; statutory_date: string | null; due_date_used: string | null; source: string; rule_version: string | null; calendar_version: string | null }[]
  how_worked_out: { rule: { key: string; value: unknown; legal_instrument: string; version: string; last_checked: string | null } | null; working_day_treatment: { value: string; confirmation_status: string; instrument: string | null }; source: string; statutory_label: { en: string; ar: string }; wording: { en: string; ar: string } | null; nonworking_note: { en: string; ar: string } | null }
}

/** Detail sheet: statutory date beside the date used, working-day treatment, rule version, date history. */
export function ObligationDetail({ o }: { o: Obligation }) {
  const { t, i18n } = useTranslation('deadlines')
  const { tx } = useBi()
  const { data, loading } = useFetch<Detail>(`/api/companies/${o.company_id}/obligations/${o.obligation_id}`)
  if (loading && !data) return <Skeleton rows={3} />
  if (!data) return null
  const h = data.how_worked_out
  return (
    <div style={{ padding: '8px 0' }}>
      <dl className="kv">
        <dt>{t('statutory_date')}</dt><dd>{data.statutory_date ? formatDate(data.statutory_date, i18n.language) : t('undated')}</dd>
        <dt>{t('date_used')}</dt><dd>{data.date_used ? formatDate(data.date_used, i18n.language) : t('undated')}</dd>
        {data.recommended_submit_by && <><dt>{t('recommended_submit_by')}</dt><dd>{formatDate(data.recommended_submit_by, i18n.language)}</dd></>}
        <dt>{t('working_day_treatment')}</dt><dd>{h.working_day_treatment.value === 'no_roll' ? t('no_roll') : h.working_day_treatment.value}</dd>
        <dt>{t('source')}</dt><dd><Ident>{data.deadline_source}</Ident></dd>
        {data.licence_number && <><dt>DET</dt><dd><Ident>{data.licence_number}</Ident></dd></>}
      </dl>
      <details>
        <summary>{t('how_worked_out')}</summary>
        {h.rule && <p>{h.rule.legal_instrument} · <Ident>{h.rule.key}</Ident> = <Ident>{String(h.rule.value)}</Ident> · {t('rule_version', { v: h.rule.version })}</p>}
        <p>{tx(h.statutory_label)}</p>
        {h.wording && <p>{tx(h.wording)}</p>}
        {h.nonworking_note && <p>{tx(h.nonworking_note)}</p>}
        {data.period_start && <p>{t('period', { start: formatDate(data.period_start, i18n.language), end: formatDate(data.period_end, i18n.language) })}</p>}
      </details>
      {data.history.length > 0 && (
        <details>
          <summary>{t('history')}</summary>
          <ul className="timeline">
            {data.history.map((x, i) => (
              <li key={i}><span>{formatDateTime(x.at, i18n.language)}</span><span>{x.due_date_used ? formatDate(x.due_date_used, i18n.language) : t('undated')}</span><span className="helper"><Ident>{x.source}</Ident></span></li>
            ))}
          </ul>
        </details>
      )}
    </div>
  )
}
