import { useCallback, useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, useParams } from 'react-router-dom'
import { useAuth } from '../../app/auth'
import { Icon } from '../../components/Icon'
import { Button, Chip, Dialog, Disclosure, Field, Message, PageHeader, Panel, Skeleton, StatCard } from '../../components/ui'
import { get, post } from '../../lib/api'
import { formatAED, formatDateTime, iso } from '../../lib/format'
import { SR_ONLY, errorKey, type Pack, type PackLine } from './types'
import './tax.css'

const REOPEN_NEEDS_REASON = ['accepted_by_reviewer', 'accepted_by_owner_no_independent_review']

/**
 * Draft pack viewer (E5-S3), independent of the owner approval screen (E6-S1 at /returns).
 * Watermark, line marks, source data, calculation basis, review status and role-bound transitions.
 */
export default function DraftViewer() {
  const { t, i18n } = useTranslation('tax')
  const lang: 'en' | 'ar' = i18n.language.startsWith('ar') ? 'ar' : 'en'
  const { packId } = useParams()
  const { companyId, can } = useAuth()
  const [pack, setPack] = useState<Pack | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [actionError, setActionError] = useState<string | null>(null)
  const [announce, setAnnounce] = useState('')
  const [figure, setFigure] = useState<PackLine | null>(null)
  const [pending, setPending] = useState<string | null>(null)
  const [rubric, setRubric] = useState<string[]>([])
  const [reason, setReason] = useState({ code: '', text: '' })
  const triggerRef = useRef<HTMLButtonElement | null>(null)
  const base = `/api/companies/${companyId}/drafts`

  const load = useCallback(async () => {
    setError(null)
    try {
      setPack(await get<Pack>(`${base}/${packId}`))
    } catch (e) {
      const k = errorKey(e)
      setError(t(k.key, k.values))
    }
  }, [base, packId, t])

  useEffect(() => { load() }, [load])
  useEffect(() => { get<{ rubric: string[] }>(`${base}/reference/rubric`).then((r) => setRubric(r.rubric)).catch(() => setRubric([])) }, [base])

  if (error) return <div className="page"><Message kind="info">{error}</Message></div>
  if (!pack) return <div className="page" aria-busy="true"><Skeleton rows={6} /></div>

  const status = t(`st_${pack.review_status}`)
  const isDelegate = pack.role === 'delegate'
  const readOnly = pack.superseded || pack.review_status === 'stale' || pack.on_hold || pack.locked

  const setStatus = async (to: string, withReason: boolean) => {
    setActionError(null)
    try {
      const out = await post<Pack>(`${base}/${pack.id}/record-review`, { to_status: to, reason_code: withReason ? reason.code : undefined, reason_text: withReason ? reason.text || undefined : undefined })
      setPack({ ...out, role: pack.role })
      setPending(null)
      setReason({ code: '', text: '' })
      setAnnounce(t('status_label', { status: t(`st_${out.review_status}`) }))
    } catch (e) {
      const k = errorKey(e)
      setActionError(t(k.key, k.values))
    }
  }

  const sendForApproval = async () => {
    setActionError(null)
    try {
      const out = await post<Pack>(`${base}/${pack.id}/send-for-review`)
      setPack({ ...out, role: pack.role })
      setAnnounce(t('sent_for_approval'))
    } catch (e) {
      const k = errorKey(e)
      setActionError(t(k.key, k.values))
    }
  }

  const exportPack = async (l: 'en' | 'ar') => {
    try {
      const doc = await get<Record<string, unknown>>(`${base}/${pack.id}/export?lang=${l}`)
      const blob = new Blob([JSON.stringify(doc, null, 2)], { type: 'application/json' })
      const a = document.createElement('a')
      a.href = URL.createObjectURL(blob)
      a.download = `draft-${pack.tax_type}-${pack.period_id}-v${pack.version}-${l}.json`
      a.click()
      URL.revokeObjectURL(a.href)
    } catch (e) {
      setActionError(t(errorKey(e).key))
    }
  }

  const value = (ln: PackLine) => (ln.value_fils === null ? ln.text ?? '—' : formatAED(ln.value_fils, lang))

  const keyLine = pack.tax_type === 'ct' ? 'tax' : 'net_vat'
  const totals = pack.lines.filter((ln) => ln.value_fils !== null)

  return (
    <div className="page tax-page tax-draft">
      <div role="status" aria-live="polite" style={SR_ONLY}>{announce}</div>
      <Link className="tax-back" to="/tax?tab=drafts">
        <Icon name="chevron-start" size={18} className="flip-rtl" />
        {t('tab_drafts')}
      </Link>
      <div className="tax-watermark" role="note" aria-label={t('watermark')}>
        <span aria-hidden="true"><Icon name="alert" size={18} /></span>
        <span>{t('watermark')}</span>
      </div>
      <PageHeader
        eyebrow={t('product_name')}
        title={t('draft_for', { type: t(pack.tax_type === 'vat' ? 'tax_type_vat' : 'tax_type_ct'), period: iso(pack.period_id) })}
        subtitle={pack.last_human_change.by ? t('last_human_change', { by: pack.last_human_change.by, role: pack.last_human_change.role, datetime: formatDateTime(pack.last_human_change.at, lang) }) : t('no_human_change')}
        meta={
          <>
            <Chip tone={pack.superseded ? 'neutral' : 'info'}>{t('status_label', { status })}</Chip>
            <Chip tone="draft" icon="✎">{t('ai_label')}</Chip>
            {pack.not_reviewed_by_human && <Chip tone="attention">{t('not_reviewed_by_human')}</Chip>}
            {pack.is_demo && <Chip tone="neutral">{t('demo')}</Chip>}
            <span><bdi dir="ltr">{t('version_n', { n: pack.version })}</bdi></span>
          </>
        }
      />

      {(pack.superseded || pack.review_status === 'stale') && (
        <Message kind="warning">
          {t('out_of_date')}
          {pack.what_changed && <div>{t('what_changed', { description: pack.what_changed })}</div>}
          {pack.current_pack_id !== pack.id && <div><Link to={`/returns/${pack.current_pack_id}`} aria-label={t('open_version_name', { n: pack.current_version })}>{t('open_version', { n: pack.current_version })}</Link></div>}
          <div><Chip tone="neutral">{t('superseded')}</Chip> {t('approval_current_only')}</div>
        </Message>
      )}
      {pack.on_hold && pack.held && <Message kind="warning"><Chip tone="critical" icon="⏸">{t('on_hold')}</Chip> {t('held_intro', { name: pack.held.delegate })}</Message>}
      {pack.no_source_count > 0 && <Message kind="info">{t('contains_no_source', { n: pack.no_source_count })}</Message>}
      {actionError && <Message kind="error">{actionError}</Message>}

      <h2 className="visually-hidden">{t('key_figures')}</h2>
      <div className="stat-grid tax-figs">
        {totals.map((ln) => (
          <StatCard key={ln.key} className={ln.key === keyLine ? 'tax-key' : undefined} label={ln.term[lang]} value={<bdi dir="ltr">{value(ln)}</bdi>} status={<Chip tone={ln.line_class === 'flagged' ? 'attention' : ln.line_class === 'person_entered' ? 'info' : 'neutral'}>{t(`line_${ln.line_class}`)}</Chip>} />
        ))}
      </div>

      <div className="tax-dv-layout">
        <div>
          <Panel title={t('line_items')} className="tax-table-panel">
            <div className="table-wrap">
              <table className="table-compact tax-lines">
                <thead>
                  <tr>
                    <th scope="col">{t('col_item')}</th>
                    <th scope="col" className="num">{t('col_amount')}</th>
                    <th scope="col">{t('col_status')}</th>
                    <th scope="col">{t('source_data')}</th>
                  </tr>
                </thead>
                <tbody>
                  {pack.lines.map((ln) => (
                    <tr key={ln.key}>
                      <td>
                        <div className="tax-line-term">{ln.term[lang]}</div>
                        <div className="hint">{ln.gloss[lang]}</div>
                        {ln.return_box_ref && <div className="hint"><bdi dir="ltr">{ln.return_box_ref}</bdi> · {t('configured_pending')}</div>}
                        {ln.sbr && <div className="hint">{ln.sbr.indicator === 'may be eligible' ? t('sbr_eligible') : t('sbr_not_eligible')}{ln.sbr.reason ? ` · ${t('sbr_reason', { reason: ln.sbr.reason })}` : ''}</div>}
                      </td>
                      <td className="num"><bdi dir="ltr">{value(ln)}</bdi></td>
                      <td>
                        <Chip tone={ln.line_class === 'flagged' ? 'attention' : ln.line_class === 'person_entered' ? 'info' : 'neutral'}>{t(`line_${ln.line_class}`)}</Chip>
                        {ln.line_class === 'person_entered' && <div className="hint">{t('person_entered')}</div>}
                        {ln.held_for_specialist && <div className="hint">{t('escalated')}</div>}
                      </td>
                      <td>
                        <Button
                          variant="link"
                          className="tax-src-btn"
                          aria-label={`${ln.term[lang]}, ${value(ln)}, ${ln.no_source ? t('no_source') : t('source_data')}, ${t('figure_source')}`}
                          onClick={(e) => { triggerRef.current = e.currentTarget; setFigure(ln) }}
                        >
                          {ln.no_source ? <><span aria-hidden="true">⚠ </span>{t('no_source')}</> : t('figure_source')}
                        </Button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Panel>

          <Panel title={t('calculation_basis')} className="tax-basis">
            <Disclosure summary={t('basis_and_rules')}>
              <dl className="kv">
                {Object.entries(pack.basis ?? {}).map(([k, v]) => (
                  <div key={k} style={{ display: 'contents' }}>
                    <dt>{k.replace(/_/g, ' ')}</dt>
                    <dd><BasisValue name={k} value={v} /></dd>
                  </div>
                ))}
              </dl>
              <h3 className="tax-sub">{t('assumptions')}</h3>
              <ul>{pack.assumptions.map((a, i) => <li key={i}>{a.text} <span className="hint">({a.citation})</span></li>)}</ul>
            </Disclosure>
            <Disclosure summary={t('source_records', { n: pack.sources.length })}>
              {pack.sources.length === 0 ? <p>{t('no_source')}</p> : (
                <ul className="tax-sources">
                  {pack.sources.slice(0, 50).map((s, i) => (
                    <li key={i}><code dir="ltr" className="hint">{Object.entries(s).filter(([, v]) => v !== null && typeof v !== 'object').map(([k, v]) => `${k}: ${v}`).join(' · ')}</code></li>
                  ))}
                </ul>
              )}
            </Disclosure>
          </Panel>
        </div>

        <div>
          <Panel title={t('review_actions')}>
            <p><Chip tone={pack.superseded ? 'neutral' : 'info'}>{t('status_label', { status })}</Chip></p>
            <div className="tax-dv-actions">
              {!readOnly && pack.allowed_transitions.map((s) => (
                <Button key={s} variant="secondary" onClick={() => (REOPEN_NEEDS_REASON.includes(pack.review_status) || (s === 'accepted_by_reviewer' && pack.no_source_count > 0) ? setPending(s) : setStatus(s, false))}>
                  {t('set_status', { status: t(`st_${s}`) })}
                </Button>
              ))}
              {isDelegate && can('returns.send_for_approval') && !readOnly && !['under_review', 'accepted_by_reviewer'].includes(pack.review_status) && (
                <Button onClick={sendForApproval}>{t('send_for_approval')}</Button>
              )}
            </div>
            {pack.role === 'owner' ? <p className="hint">{t('owner_approves_in_return_review')}</p> : <p className="hint">{t('only_owner_approves')}</p>}
            {!pack.can_approve && pack.approve_disabled_reason && <p className="hint">{pack.superseded || pack.review_status === 'stale' ? t('approval_current_only') : pack.approve_disabled_reason}</p>}
            <div className="tax-dv-actions tax-dv-export">
              <div className="tax-dv-row">
                <Button variant="secondary" className="btn-sm" disabled={pack.on_hold} onClick={() => exportPack('en')}><Icon name="download" size={16} />{t('export_en')}</Button>
                <Button variant="secondary" className="btn-sm" disabled={pack.on_hold} onClick={() => exportPack('ar')}><Icon name="download" size={16} />{t('export_ar')}</Button>
              </div>
              <Link className="btn btn-ghost btn-sm" to="/help"><Icon name="help" size={16} />{t('ask_a_human')}</Link>
            </div>
          </Panel>

          <Panel title={t('history_and_versions')}>
            <h3 className="tax-sub">{t('versions')}</h3>
            <ul className="tax-versions">
              {pack.versions.map((v) => (
                <li key={v.id}>
                  {v.id === pack.id ? <strong>{t('version_n', { n: v.version })}</strong> : <Link to={`/returns/${v.id}`}>{t('version_n', { n: v.version })}</Link>} <span className="muted">· {t(`st_${v.review_status}`)}</span>
                </li>
              ))}
            </ul>
            <h3 className="tax-sub">{t('history')}</h3>
            <ol className="tax-history">
              {pack.history.map((h, i) => (
                <li key={i}>
                  <span>{t(`st_${h.to}`)}{h.reason_code ? ` · ${t(`rubric_${h.reason_code}`, { defaultValue: h.reason_code })}` : ''}</span>
                  <span className="hint">{h.system ? 'system' : `${h.by ?? ''}, ${h.role ?? ''}`} · <span className="nowrap">{formatDateTime(h.at, lang)}</span></span>
                </li>
              ))}
            </ol>
          </Panel>
        </div>
      </div>

      <div className="tax-legal">
        <p>{t('emaratax_sentence')}</p>
        <p className="hint">{t('retention_note')}</p>
      </div>

      <Dialog open={!!figure} title={figure ? figure.term[lang] : ''} onClose={() => { setFigure(null); triggerRef.current?.focus() }} labelledBy="fig-title">
        {figure && (
          <>
            <p><bdi dir="ltr">{value(figure)}</bdi> · {t(`line_${figure.line_class}`)}</p>
            {figure.no_source ? (
              <>
                <p>{t('no_source_panel')}</p>
                {figure.no_source_reason && <p>{t('reason_recorded', { reason: figure.no_source_reason })}</p>}
                <div className="actions"><Link className="btn btn-secondary" to="/help">{t('ask_human_check')}</Link></div>
              </>
            ) : (
              <ul>{figure.source_refs.map((s, i) => <li key={i}><code dir="ltr" className="hint">{JSON.stringify(s)}</code></li>)}</ul>
            )}
            <div className="actions"><Button autoFocus onClick={() => { setFigure(null); triggerRef.current?.focus() }}>{t('close')}</Button></div>
          </>
        )}
      </Dialog>

      <Dialog open={!!pending} title={t('why_changing')} onClose={() => setPending(null)} labelledBy="reason-title">
        <Field label={t('why_changing')} id="reason-code" hint={t('reason_saved')} required>
          <select id="reason-code" value={reason.code} onChange={(e) => setReason({ ...reason, code: e.target.value })}>
            <option value="" />
            {rubric.map((r) => <option key={r} value={r}>{t(`rubric_${r}`, { defaultValue: r })}</option>)}
          </select>
        </Field>
        <Field label={t('reason_free_text')} id="reason-text">
          <textarea id="reason-text" value={reason.text} onChange={(e) => setReason({ ...reason, text: e.target.value })} />
        </Field>
        {!reason.code && <p className="hint">{t('choose_reason')}</p>}
        <div className="actions">
          <Button variant="secondary" onClick={() => setPending(null)}>{t('cancel')}</Button>
          <Button disabled={!reason.code} onClick={() => pending && setStatus(pending, true)}>{t('save')}</Button>
        </div>
      </Dialog>
    </div>
  )
}


/** Readable calculation basis: rule references show id, version, instrument and confirmation status. */
function BasisValue({ name, value }: { name: string; value: unknown }) {
  if (typeof value === 'string' || typeof value === 'number') return <span>{String(value)}</span>
  if (name === 'rule_refs' && value && typeof value === 'object') {
    return (
      <ul>
        {Object.values(value as Record<string, { rule_id?: string; version?: string; instrument?: string; status?: string }>).map((r, i) => (
          <li key={i}>
            <bdi dir="ltr">{r.rule_id}</bdi> · {r.instrument} <span className="notice-tbc">({(r.status || '').replace(/_/g, ' ')})</span>
          </li>
        ))}
      </ul>
    )
  }
  if (value && typeof value === 'object') {
    return (
      <span>
        {Object.entries(value as Record<string, unknown>)
          .map(([k, v]) => `${k.replace(/_/g, ' ')}: ${typeof v === 'object' ? JSON.stringify(v) : String(v)}`)
          .join(' · ')}
      </span>
    )
  }
  return null
}
