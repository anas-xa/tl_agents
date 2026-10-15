import type React from 'react'
import { useCallback, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Chip, Table } from '../../components/ui'
import { ApiError, get } from '../../lib/api'
import { formatAED, formatNumber, formatPercent } from '../../lib/format'

export type Bi = { en: string; ar: string }
/** A suppressed cell never carries a value: only its state and label. */
export type Cell = { suppressed: false; cell_state: 'shown'; value: number | string | null } | { suppressed: true; cell_state: string; label_en: string; label_ar: string }

export interface SupTable {
  n: number
  dims: string[]
  state: 'shown' | 'not_shown_group_too_small'
  rows: Array<Record<string, Cell | string | null | undefined> & { cell_state?: string; label_en?: string; label_ar?: string; state?: string; na_reason_text?: Bi }>
  total: (Record<string, Cell | string | null> & { cell_state?: string }) | null
  notice: boolean
  notice_key: 'suppressed' | 'merged' | 'combined_or_hidden' | null
  notice_en?: string
  notice_ar?: string
}

export interface KpiRecord {
  kpi_id: string
  name: Bi
  definition: Bi
  formula_text?: string
  unit?: string
  target?: { en: string | null; ar: string | null }
  refresh_period?: 'daily' | 'monthly'
  sources?: string[]
  rule_version_id?: string
  release_state: 'live' | 'not_yet_available'
  planned_phase_label?: string | null
  group: 'live' | 'later'
  is_fairness_indicator?: boolean
  dimensions?: string[]
  period_key?: string
  state: 'value' | 'no_data' | 'not_applicable' | 'not_yet_available' | 'blocked' | 'error'
  message?: Bi | null
  na_reason?: string
  na_reason_text?: Bi | null
  value?: Cell | null
  numerator?: Cell | null
  denominator?: Cell | null
  counts?: Record<string, Cell | null>
  amounts_fils?: Record<string, Cell>
  flags?: Record<string, unknown> & { stale?: boolean; partial?: boolean; provisional?: boolean; restated?: boolean; missing_sources?: string[]; sources_included_n?: number; sources_total_m?: number; platform_derived_share?: number; coverage_share?: number; window_state?: string }
  extra?: Record<string, unknown>
  breakdowns?: Record<string, SupTable>
  trend?: Cell
  partial_message?: Bi
  provisional_message?: Bi
  window_message?: Bi
  vat_message?: Bi
  coverage_message?: Bi
  source_label?: Bi
  default_on_message?: Bi
  restatement_note?: Bi
  alert?: Bi
  counts_only?: boolean
  error_code?: string
}

export interface Dashboard {
  data_source: 'platform' | 'demo_fixture'
  source_label: Bi
  demo_data: boolean
  refresh_time: string
  data_as_of: string
  data_version: string
  catalogue_version: string
  suppression: { min_group_size: number; label: Bi; status: string }
  banner: Bi
  revenue_note: Bi
  loading_slow_after_seconds: number
  filters: { period: string; cohort: string | null; payment_status: string | null }
  periods: string[]
  filter_options: { cohorts: string[]; payment_statuses: string[] }
  can_manage_n: boolean
  can_export: boolean
  state: 'ready' | 'empty' | 'blocked'
  blocked?: { notice_en: string; notice_ar: string }
  kpis: KpiRecord[]
}

export function useLang() {
  const { i18n } = useTranslation()
  const lang = i18n.language.startsWith('ar') ? 'ar' : 'en'
  return { lang, tx: (b: Bi | null | undefined) => (b ? b[lang as 'en' | 'ar'] || b.en : '') }
}

export function useFetch<T>(path: string | null) {
  const [data, setData] = useState<T | null>(null)
  const [error, setError] = useState<ApiError | Error | null>(null)
  const [loading, setLoading] = useState(!!path)
  const load = useCallback(async () => {
    if (!path) return
    setLoading(true)
    try {
      setData(await get<T>(path))
      setError(null)
    } catch (e) {
      setError(e as Error)
    } finally {
      setLoading(false)
    }
  }, [path])
  useEffect(() => {
    load()
  }, [load])
  return { data, error, loading, reload: load, setData }
}

/** Visually hidden style for live regions. */
export const srOnly: React.CSSProperties = { position: 'absolute', width: 1, height: 1, overflow: 'hidden', clip: 'rect(0 0 0 0)', whiteSpace: 'nowrap' }

/** Formats a shown value by unit; amounts are integer fils. */
export function formatValue(v: number | string | null | undefined, unit: string | undefined, lang: string): string {
  if (v === null || v === undefined) return '—'
  if (typeof v === 'string') return v
  if (unit === '%') return formatPercent(v, lang)
  if (unit === 'AED' || unit === 'fils') return formatAED(v, lang)
  return formatNumber(v, lang)
}

/** One cell: a value, or 'Fewer than N' with a neutral icon (icon + text, never colour alone). */
export function CellView({ cell, unit, n }: { cell: Cell | null | undefined; unit?: string; n: number }) {
  const { t } = useTranslation('kpis')
  const { lang } = useLang()
  if (!cell) return <span className="muted">—</span>
  if (cell.suppressed) {
    const label = cell.cell_state === 'not_shown_group_too_small' ? t('not_shown') : cell.cell_state === 'suppressed_dominance' ? t('dominance') : t('fewer_than_short', { n })
    return (
      <span title={t('fewer_than', { n })}>
        <span aria-hidden="true">◌ </span>
        {label}
      </span>
    )
  }
  return <bdi dir="ltr">{formatValue(cell.value, unit, lang)}</bdi>
}

const AMOUNT_KEYS = new Set(['net_billed_fils', 'billed_fils', 'collected_fils'])
const RATE_KEYS = new Set(['rate', 'share'])
const HIDDEN_KEYS = new Set(['cell_state', 'label_en', 'label_ar', 'state', 'na_reason_text'])

/** A breakdown table after suppression: 'Other (combined)' rows, hidden cells, notices; totals only when shown. */
export function SupTableView({ table, n, caption, ctx, countLabel }: { table: SupTable; n: number; caption?: React.ReactNode; ctx?: string; countLabel?: 'licences' | 'count' }) {
  const { t } = useTranslation('kpis')
  const { tx } = useLang()
  const dims = table.dims
  if (table.state === 'not_shown_group_too_small') {
    return (
      <div>
        {caption && <p className="stat-label">{caption}</p>}
        <Chip tone="neutral" icon="◌">{t('not_shown')}</Chip>
        <p className="hint" role="status">{t('combined_note')}</p>
      </div>
    )
  }
  const sample = table.rows[0] || table.total || {}
  const measures = Object.keys(sample).filter((k) => !dims.includes(k) && !HIDDEN_KEYS.has(k))
  const head = (k: string) => (k === 'count' ? t(countLabel === 'count' ? 'col_count' : 'col_licences') : k === 'net_billed_fils' || k === 'billed_fils' ? t('col_billed') : k === 'collected_fils' ? t('col_collected') : k === 'rate' ? t('col_rate') : k === 'share' ? t('col_share') : k === 'numerator' ? t('col_numerator') : k === 'denominator' ? t('col_denominator') : k === 'measured' ? t('col_measured') : k === 'flagged' ? t('col_numerator') : k === 'renewed' ? t('col_numerator') : k)
  const unitOf = (k: string) => (AMOUNT_KEYS.has(k) ? 'AED' : RATE_KEYS.has(k) ? '%' : undefined)
  const label = (row: Record<string, unknown>) => {
    if (row.cell_state === 'merged_other_combined') return t('other_combined')
    return dims
      .map((d) => {
        const v = String(row[d] ?? '')
        return d === 'month' ? v : t(ctx ? [`val.${ctx}.${v}`, `val.${v}`] : `val.${v}`, { defaultValue: v })
      })
      .join(' · ')
  }
  const notice = table.notice_key === 'merged' ? t('other_note', { n }) : table.notice_key === 'combined_or_hidden' ? t('combined_note') : table.notice ? t('fewer_than', { n }) : null
  return (
    <div>
      <Table caption={caption} headers={[dims.map((d) => t(`dim.${d}`, { defaultValue: t('col_group') })).join(' · '), ...measures.map(head)]}>
        {table.rows.map((row, i) => (
          <tr key={i}>
            <th scope="row">
              {row.cell_state === 'no_data' ? (
                <>{label(row)} <span className="muted">— {t('no_data')}</span></>
              ) : (
                label(row)
              )}
              {row.state === 'not_applicable' && <div className="hint">{t('not_applicable')}: {tx(row.na_reason_text as Bi)}</div>}
            </th>
            {measures.map((k) => (
              <td key={k}>{row.cell_state === 'no_data' ? '—' : <CellView cell={row[k] as Cell} unit={unitOf(k)} n={n} />}</td>
            ))}
          </tr>
        ))}
        {table.total && (
          <tr>
            <th scope="row">{t('total')}</th>
            {measures.map((k) => (
              <td key={k}><CellView cell={table.total?.[k] as Cell} unit={unitOf(k)} n={n} /></td>
            ))}
          </tr>
        )}
      </Table>
      {notice && (
        <p className="hint" role="status">
          <span aria-hidden="true">ⓘ </span>
          {notice}
        </p>
      )}
    </div>
  )
}
