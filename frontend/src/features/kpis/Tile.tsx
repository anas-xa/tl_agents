import { useId, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Button, Chip } from '../../components/ui'
import { formatDateTime, formatPercent } from '../../lib/format'
import { CellView, SupTableView, type Bi, type Cell, type KpiRecord, useLang } from './parts'

const TILE_CLASS = 'card'

/** One SC14 KPI tile: value (or a state with icon + text), state chips, target, definition on demand. */
export default function Tile({ k, n, dataAsOf, onRetry, retrying }: { k: KpiRecord; n: number; dataAsOf: string; onRetry: (id: string) => void; retrying?: boolean }) {
  const { t } = useTranslation('kpis')
  const { lang, tx } = useLang()
  const [open, setOpen] = useState(false)
  const [showMissing, setShowMissing] = useState(false)
  const defId = useId()
  const name = tx(k.name)
  const flags = k.flags || {}
  const later = k.state === 'not_yet_available'
  const stateWords: string[] = []
  if (later) stateWords.push(t('not_yet_short'))
  if (flags.partial) stateWords.push(t('partial_chip'))
  if (flags.provisional) stateWords.push(t('provisional'))
  if (flags.stale) stateWords.push(t('stale', { when: '' }).trim())
  if (k.value && k.value.suppressed) stateWords.push(t('fewer_than', { n }))
  const accessibleName = [name, ...stateWords].join(', ')
  const unit = k.unit

  const definition = (
    <div id={defId} className="hint" style={{ marginTop: 8 }}>
      <p>{tx(k.definition)}</p>
      <dl className="kv">
        {k.formula_text && (<><dt>{t('formula')}</dt><dd>{k.formula_text}</dd></>)}
        {unit && (<><dt>{t('unit')}</dt><dd>{unit}</dd></>)}
        {k.refresh_period && (<><dt>{t('refresh')}</dt><dd>{t(k.refresh_period === 'monthly' ? 'refresh_monthly' : 'refresh_daily')}</dd></>)}
        {!later && (<><dt>{t('data_as_of')}</dt><dd>{formatDateTime(dataAsOf, lang)}</dd></>)}
        {k.sources && (<><dt>{t('sources')}</dt><dd>{k.sources.join(' · ')}</dd></>)}
        {k.rule_version_id && (<><dt>{t('rule_version')}</dt><dd><bdi dir="ltr">{k.rule_version_id}</bdi></dd></>)}
        {typeof k.extra?.config_version === 'string' && (<><dt>{t('config_version')}</dt><dd><bdi dir="ltr">{k.extra.config_version as string}</bdi></dd></>)}
      </dl>
    </div>
  )
  const defButton = (
    <Button variant="link" aria-expanded={open} aria-controls={defId} onClick={() => setOpen(!open)}>
      {open ? t('hide_definition') : t('show_definition', { name })}
    </Button>
  )

  if (later) {
    return (
      <article className={TILE_CLASS} aria-label={accessibleName} style={{ borderStyle: 'dashed', color: 'var(--muted)', background: 'transparent' }}>
        <h3 style={{ marginTop: 0 }}>{name} <span className="muted">(<bdi dir="ltr">{k.kpi_id}</bdi>)</span></h3>
        <p><span aria-hidden="true">○ </span>{t('not_yet', { x: k.planned_phase_label || '—' })}</p>
        {defButton}
        {open && definition}
      </article>
    )
  }

  let body: React.ReactNode
  if (k.state === 'error') {
    body = (
      <div role="alert">
        <p><span aria-hidden="true">✕ </span>{t('error_kpi', { name })}</p>
        <Button variant="secondary" onClick={() => onRetry(k.kpi_id)} disabled={retrying}>{t('try_again')}</Button>
      </div>
    )
  } else if (k.state === 'blocked') {
    body = <p><span aria-hidden="true">◌ </span>{t('fewer_than', { n })}</p>
  } else if (k.state === 'no_data') {
    body = <p><span className="stat" aria-hidden="true">—</span> <span>{t('no_data')}</span></p>
  } else if (k.state === 'not_applicable') {
    body = (
      <div>
        <p><Chip tone="neutral" icon="⊘">{t('not_applicable')}</Chip></p>
        {k.na_reason_text && <p className="hint">{tx(k.na_reason_text)}</p>}
        {typeof k.extra?.first_due_date === 'string' && <p className="hint"><bdi dir="ltr">{k.extra.first_due_date as string}</bdi></p>}
      </div>
    )
  } else {
    body = (
      <div>
        <p className="stat" style={{ margin: '4px 0', color: flags.stale ? 'var(--muted)' : undefined }}>
          {k.counts_only ? <span className="muted">—</span> : <CellView cell={k.value} unit={unit} n={n} />}
        </p>
        {k.value && k.value.suppressed && <p className="hint">{t('fewer_than', { n })}</p>}
        {k.trend && <Trend cell={k.trend} unit={unit} n={n} />}
      </div>
    )
  }

  const counts = Object.entries(k.counts || {}).filter(([, c]) => c)
  return (
    <article className={TILE_CLASS} aria-label={accessibleName}>
      <h3 style={{ marginTop: 0 }}>{name} <span className="muted">(<bdi dir="ltr">{k.kpi_id}</bdi>)</span></h3>
      {body}
      <div className="actions" style={{ flexWrap: 'wrap', gap: 6 }}>
        {flags.provisional ? <Chip tone="attention" icon="◌">{t('provisional')}</Chip> : k.state === 'value' && flags.final ? <Chip tone="ok">{t('final')}</Chip> : null}
        {flags.partial && (
          <Button variant="link" aria-expanded={showMissing} onClick={() => setShowMissing(!showMissing)}>
            <Chip tone="attention" icon="◐">{t('partial_chip')}</Chip>
          </Button>
        )}
        {flags.stale && <Chip tone="neutral" icon="🕒">{t('stale', { when: '' })}</Chip>}
        {flags.restated && <Chip tone="info" icon="↺">{t('restated')}</Chip>}
        {flags.window_state === 'open' && <Chip tone="neutral" icon="◷">{t('window_open')}</Chip>}
        {Boolean(flags.vat_treatment_unconfirmed) && <Chip tone="neutral" icon="i">{t('vat_unconfirmed')}</Chip>}
      </div>
      {flags.partial && k.partial_message && <p className="hint">{tx(k.partial_message)}</p>}
      {showMissing && flags.missing_sources && (
        <div className="hint"><strong>{t('missing_sources')}:</strong> {flags.missing_sources.join(', ')}</div>
      )}
      {k.provisional_message && <p className="hint">{tx(k.provisional_message)}</p>}
      {k.window_message && <p className="hint">{tx(k.window_message)}</p>}
      {k.restatement_note && <p className="hint">{tx(k.restatement_note)}</p>}
      {k.alert && <p role="alert"><Chip tone="critical">{tx(k.alert)}</Chip></p>}
      {k.kpi_id === 'K3' && k.state === 'value' && <K3Lines k={k} n={n} />}
      {(k.kpi_id === 'K7' || k.kpi_id === 'K8') && k.state === 'value' && (
        <div className="hint">
          {k.source_label && <p><Chip tone="neutral" icon="i">{tx(k.source_label)}</Chip></p>}
          {k.coverage_message && <p>{t('coverage')}: {tx(k.coverage_message)}</p>}
          {k.counts_only && <p>{t('counts_only', { share: k.extra?.min_measurable_share as number, min: k.extra?.min_returns as number })}</p>}
        </div>
      )}
      {k.kpi_id === 'K2' && k.amounts_fils && (
        <dl className="kv hint">
          <dt>{t('credit_notes')}</dt><dd><CellView cell={k.amounts_fils.credit_notes_fils} unit="AED" n={n} /></dd>
          <dt>{t('recognised')}</dt><dd><CellView cell={k.amounts_fils.recognised_fils} unit="AED" n={n} /></dd>
          <dt>{t('normalised_annual')}</dt><dd><CellView cell={k.amounts_fils.normalised_annual_fils} unit="AED" n={n} /> <span className="muted">({t('arithmetic')})</span></dd>
        </dl>
      )}
      {k.default_on_message && <p className="hint">{tx(k.default_on_message)}</p>}
      <p className="hint">
        {t('target')}: {k.target?.en ? (lang === 'ar' && k.target.ar ? k.target.ar : k.target.en) : t('to_be_confirmed')}
      </p>
      {(counts.length > 0 || (k.breakdowns && Object.keys(k.breakdowns).length > 0)) && (
        <details>
          <summary style={{ minHeight: 44, display: 'flex', alignItems: 'center', cursor: 'pointer' }}>{t('details')}</summary>
          {counts.length > 0 && (
            <dl className="kv hint">
              {counts.map(([key, c]) => (
                <div key={key} style={{ display: 'contents' }}>
                  <dt>{t(`cnt.${key}`, { defaultValue: key })}</dt>
                  <dd><CellView cell={c as Cell} n={n} /></dd>
                </div>
              ))}
            </dl>
          )}
          {Object.entries(k.breakdowns || {}).map(([id, table]) => (
            <SupTableView key={id} table={table} n={n} ctx={id} countLabel={['enrolment_split', 'subscription_status_counts', 'by_enrolment_mode', 'by_enrolment_basis', 'by_renewal_choice_marker', 'bands', 'by_result'].includes(id) ? 'licences' : 'count'} caption={t(`tbl.${id}`, { defaultValue: id })} />
          ))}
        </details>
      )}
      {defButton}
      {open && definition}
    </article>
  )
}

function Trend({ cell, unit, n }: { cell: Cell; unit?: string; n: number }) {
  const { t } = useTranslation('kpis')
  const { lang } = useLang()
  if (cell.suppressed) return <p className="hint"><span aria-hidden="true">◌ </span>{t('trend_hidden')}</p>
  const v = Number(cell.value)
  if (!v) return <p className="hint"><span aria-hidden="true">→ </span>{t('trend_same')}</p>
  const shown = unit === '%' ? `${Math.abs(v).toFixed(1)} pp` : unit === 'AED' ? `AED ${(Math.abs(v) / 100).toLocaleString('en-US', { minimumFractionDigits: 2 })}` : String(Math.abs(v))
  void n
  void lang
  return (
    <p className="hint">
      <span aria-hidden="true">{v > 0 ? '▲ ' : '▼ '}</span>
      {t(v > 0 ? 'trend_up' : 'trend_down', { d: shown })}
    </p>
  )
}

function K3Lines({ k, n }: { k: KpiRecord; n: number }) {
  const { t } = useTranslation('kpis')
  const { lang } = useLang()
  const ex = (k.extra || {}) as Record<string, Cell>
  const share = k.flags?.platform_derived_share
  const pct = (c: Cell | undefined) => (c && !c.suppressed ? formatPercent(c.value as number, lang) : '—')
  return (
    <div className="hint">
      <p>{t('final_rate')}: <CellView cell={k.value} unit="%" n={n} /></p>
      <p>{t('provisional_rate')}: <CellView cell={ex.provisional_rate_incl_platform_derived} unit="%" n={n} /></p>
      <p>{t('gross_net', { gross: pct(ex.gross_collection_rate), net: pct(ex.net_collection_rate) })}</p>
      {typeof share === 'number' && share > 0 && (
        <p><Chip tone="attention" icon="◌">{t('platform_share', { pct: formatPercent(share, lang) })}</Chip> {t('platform_note')}</p>
      )}
    </div>
  )
}

export type { Bi }
