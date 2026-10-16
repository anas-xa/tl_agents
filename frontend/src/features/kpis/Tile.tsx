import { useId, useState, type ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import { Icon } from '../../components/Icon'
import { Button, Chip } from '../../components/ui'
import { formatDateTime, formatPercent } from '../../lib/format'
import { TrendArrow } from '../det/ui'
import { CellView, SupTableView, type Bi, type Cell, type KpiRecord, useLang } from './parts'

/**
 * One SC14 KPI tile, laid out like a stat card: label + KPI code, the figure as the dominant element, the trend
 * line, grouped state chips, quiet notes and target, and the definition / details toggles in a footer row.
 * Tiles in a row share a height (the grid stretches them and the footer sits at the bottom).
 */
export default function Tile({ k, n, dataAsOf, onRetry, retrying }: { k: KpiRecord; n: number; dataAsOf: string; onRetry: (id: string) => void; retrying?: boolean }) {
  const { t } = useTranslation('kpis')
  const { lang, tx } = useLang()
  const [panel, setPanel] = useState<null | 'definition' | 'details'>(null)
  const defId = useId()
  const detId = useId()
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
    <div id={defId} className="det-kpi-panel">
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
  const toggle = (which: 'definition' | 'details', id: string, label: ReactNode) => (
    <button type="button" className="det-linkbtn" aria-expanded={panel === which} aria-controls={id} onClick={() => setPanel(panel === which ? null : which)}>
      {label}
      <Icon name="chevron-down" size={16} />
    </button>
  )
  const defButton = toggle('definition', defId, <><span>{panel === 'definition' ? t('hide_definition') : t('definition')}</span>{panel !== 'definition' && <span className="visually-hidden">: {name}</span>}</>)
  const head = (
    <header className="det-kpi-head">
      <h3>{name}</h3>
      <span className="det-kpi-code"><bdi dir="ltr">{k.kpi_id}</bdi></span>
    </header>
  )

  if (later) {
    return (
      <article className="card det-kpi det-kpi-later" aria-label={accessibleName}>
        {head}
        <p className="det-kpi-state"><span aria-hidden="true">○</span>{t('not_yet', { x: k.planned_phase_label || '—' })}</p>
        <div className="det-kpi-foot">
          {defButton}
          {panel === 'definition' && definition}
        </div>
      </article>
    )
  }

  let body: ReactNode
  if (k.state === 'error') {
    body = (
      <div role="alert" className="det-kpi-error">
        <p className="det-kpi-state"><span aria-hidden="true">✕</span>{t('error_kpi', { name })}</p>
        <Button variant="secondary" className="btn-sm" onClick={() => onRetry(k.kpi_id)} disabled={retrying}>{t('try_again')}</Button>
      </div>
    )
  } else if (k.state === 'blocked') {
    body = <p className="det-kpi-state"><span aria-hidden="true">◌</span>{t('fewer_than', { n })}</p>
  } else if (k.state === 'no_data') {
    body = (
      <>
        <p className="det-kpi-value is-stale" aria-hidden="true">—</p>
        <p className="det-kpi-target">{t('no_data')}</p>
      </>
    )
  } else if (k.state === 'not_applicable') {
    body = (
      <div>
        <p className="det-kpi-state"><Chip tone="neutral" icon="⊘">{t('not_applicable')}</Chip></p>
        {k.na_reason_text && <p className="det-kpi-target">{tx(k.na_reason_text)}</p>}
        {typeof k.extra?.first_due_date === 'string' && <p className="det-kpi-target"><bdi dir="ltr">{k.extra.first_due_date as string}</bdi></p>}
      </div>
    )
  } else {
    const suppressed = !!k.value && k.value.suppressed
    body = (
      <>
        <p className={`det-kpi-value ${flags.stale || k.counts_only ? 'is-stale' : ''} ${suppressed ? 'det-kpi-value-sm' : ''}`}>
          {k.counts_only ? '—' : <CellView cell={k.value} unit={unit} n={n} />}
        </p>
        {suppressed && <p className="det-kpi-target">{t('fewer_than', { n })}</p>}
        {k.trend && <Trend cell={k.trend} unit={unit} />}
      </>
    )
  }

  const chips: ReactNode[] = []
  if (flags.provisional) chips.push(<Chip key="prov" tone="attention" icon="◌">{t('provisional')}</Chip>)
  else if (k.state === 'value' && flags.final) chips.push(<Chip key="final" tone="ok">{t('final')}</Chip>)
  if (flags.partial) chips.push(<Chip key="partial" tone="attention" icon="◐">{t('partial_chip')}</Chip>)
  if (flags.stale) chips.push(<Chip key="stale" tone="neutral" icon="◷">{t('stale', { when: '' })}</Chip>)
  if (flags.restated) chips.push(<Chip key="restated" tone="info" icon="↺">{t('restated')}</Chip>)
  if (flags.window_state === 'open') chips.push(<Chip key="window" tone="neutral" icon="◷">{t('window_open')}</Chip>)
  if (flags.vat_treatment_unconfirmed) chips.push(<Chip key="vat" tone="neutral" icon="i">{t('vat_unconfirmed')}</Chip>)
  if ((k.kpi_id === 'K7' || k.kpi_id === 'K8') && k.state === 'value' && k.source_label) chips.push(<Chip key="src" tone="neutral" icon="i">{tx(k.source_label)}</Chip>)

  const notes: ReactNode[] = []
  if (flags.partial && k.partial_message) notes.push(tx(k.partial_message))
  if (flags.partial && flags.missing_sources && flags.missing_sources.length > 0) notes.push(<><strong>{t('missing_sources')}:</strong> {flags.missing_sources.join(', ')}</>)
  if (k.provisional_message) notes.push(tx(k.provisional_message))
  if (k.window_message) notes.push(tx(k.window_message))
  if (k.restatement_note) notes.push(tx(k.restatement_note))
  if ((k.kpi_id === 'K7' || k.kpi_id === 'K8') && k.state === 'value') {
    if (k.coverage_message) notes.push(<>{t('coverage')}: {tx(k.coverage_message)}</>)
    if (k.counts_only) notes.push(t('counts_only', { share: k.extra?.min_measurable_share as number, min: k.extra?.min_returns as number }))
  }
  if (k.default_on_message) notes.push(tx(k.default_on_message))

  const counts = Object.entries(k.counts || {}).filter(([, c]) => c)
  const hasDetails = counts.length > 0 || (k.breakdowns && Object.keys(k.breakdowns).length > 0)
  const target = k.target?.en ? (lang === 'ar' && k.target.ar ? k.target.ar : k.target.en) : t('to_be_confirmed')

  return (
    <article className="card det-kpi" aria-label={accessibleName}>
      {head}
      {body}
      {chips.length > 0 && <div className="det-kpi-chips">{chips}</div>}
      {k.kpi_id === 'K3' && k.state === 'value' && <K3Lines k={k} n={n} />}
      {k.kpi_id === 'K2' && k.amounts_fils && (
        <dl className="det-kpi-kv">
          <dt>{t('credit_notes')}</dt><dd><CellView cell={k.amounts_fils.credit_notes_fils} unit="AED" n={n} /></dd>
          <dt>{t('recognised')}</dt><dd><CellView cell={k.amounts_fils.recognised_fils} unit="AED" n={n} /></dd>
          <dt>{t('normalised_annual')}</dt><dd><CellView cell={k.amounts_fils.normalised_annual_fils} unit="AED" n={n} /></dd>
          <dd className="det-kpi-kv-full">({t('arithmetic')})</dd>
        </dl>
      )}
      {notes.length > 0 && (
        <ul className="det-kpi-notes">
          {notes.map((x, i) => <li key={i}>{x}</li>)}
        </ul>
      )}
      {k.alert && <p role="alert" className="det-kpi-alert"><Chip tone="critical">{tx(k.alert)}</Chip></p>}
      <p className="det-kpi-target"><strong>{t('target')}:</strong> {target}</p>
      <div className="det-kpi-foot">
        {defButton}
        {hasDetails && toggle('details', detId, t('details'))}
        {panel === 'definition' && definition}
        {panel === 'details' && (
          <div id={detId} className="det-kpi-panel">
            {counts.length > 0 && (
              <dl className="det-kpi-kv">
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
          </div>
        )}
      </div>
    </article>
  )
}

function Trend({ cell, unit }: { cell: Cell; unit?: string }) {
  const { t } = useTranslation('kpis')
  if (cell.suppressed) {
    return <p className="det-trend det-trend-muted"><span className="det-trend-icon"><span aria-hidden="true">◌</span></span>{t('trend_hidden')}</p>
  }
  const v = Number(cell.value)
  if (!v) return <p className="det-trend det-trend-muted"><span className="det-trend-icon"><TrendArrow dir="flat" /></span>{t('trend_same')}</p>
  const shown = unit === '%' ? `${Math.abs(v).toFixed(1)} pp` : unit === 'AED' ? `AED ${(Math.abs(v) / 100).toLocaleString('en-US', { minimumFractionDigits: 2 })}` : String(Math.abs(v))
  return (
    <p className="det-trend">
      <span className="det-trend-icon"><TrendArrow dir={v > 0 ? 'up' : 'down'} /></span>
      <span>{t(v > 0 ? 'trend_up' : 'trend_down', { d: shown })}</span>
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
    <>
      <dl className="det-kpi-kv">
        <dt>{t('final_rate')}</dt><dd><CellView cell={k.value} unit="%" n={n} /></dd>
        <dt>{t('provisional_rate')}</dt><dd><CellView cell={ex.provisional_rate_incl_platform_derived} unit="%" n={n} /></dd>
        <dd className="det-kpi-kv-full">{t('gross_net', { gross: pct(ex.gross_collection_rate), net: pct(ex.net_collection_rate) })}</dd>
      </dl>
      {typeof share === 'number' && share > 0 && (
        <p className="det-kpi-target"><Chip tone="attention" icon="◌">{t('platform_share', { pct: formatPercent(share, lang) })}</Chip> {t('platform_note')}</p>
      )}
    </>
  )
}

export type { Bi }
