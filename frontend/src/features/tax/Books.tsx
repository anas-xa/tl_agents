import { useCallback, useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'
import { Icon } from '../../components/Icon'
import { Button, Chip, Dialog, Empty, Field, Message, Skeleton, Toolbar } from '../../components/ui'
import { get, post } from '../../lib/api'
import { formatAED, formatDate, formatDateTime } from '../../lib/format'
import { SR_ONLY, errorKey, type Reference, type TxnList, type TxnRow } from './types'

const FILTERS = ['needs_review', 'proposed', 'posted', 'rejected', 'quarantined', 'all'] as const

interface BulkPreview { count: number; total_fils: number; income_fils: number; expenses_fils: number; ids: string[] }

/** SC6 classification queue (E5-S1): fixed-rule routing, no confidence numbers, AI label on every row. */
export default function Books({ companyId }: { companyId: string }) {
  const { t, i18n } = useTranslation('tax')
  const lang = i18n.language.startsWith('ar') ? 'ar' : 'en'
  const base = `/api/companies/${companyId}`
  const [data, setData] = useState<TxnList | null>(null)
  const [ref, setRef] = useState<Reference | null>(null)
  const [filter, setFilter] = useState<(typeof FILTERS)[number]>('needs_review')
  const [error, setError] = useState<string | null>(null)
  const [rowError, setRowError] = useState<{ id: string; text: string } | null>(null)
  const [busyRow, setBusyRow] = useState<string | null>(null)
  const [announce, setAnnounce] = useState('')
  const [correcting, setCorrecting] = useState<TxnRow | null>(null)
  const [form, setForm] = useState({ category: '', vat_code: '', ledger_account: '' })
  const [bulk, setBulk] = useState<BulkPreview | null>(null)
  const [quarantine, setQuarantine] = useState<{ decision: 'keep_and_review' | 'discard'; ids?: string[] } | null>(null)
  const [reason, setReason] = useState('')
  const [preparing, setPreparing] = useState<{ done: number; total: number } | null>(null)
  const cancelRef = useRef<HTMLButtonElement>(null)
  const bulkTrigger = useRef<HTMLButtonElement>(null)
  const retryRef = useRef<HTMLButtonElement>(null)

  const load = useCallback(async () => {
    setError(null)
    try {
      const qs = filter === 'all' ? '' : `?status=${filter}`
      setData(await get<TxnList>(`${base}/transactions${qs}`))
    } catch (e) {
      setError(t(errorKey(e).key))
    }
  }, [base, filter, t])

  useEffect(() => { load() }, [load])
  useEffect(() => { get<Reference>(`${base}/bookkeeping/reference`).then(setRef).catch(() => setRef(null)) }, [base])
  useEffect(() => { if (bulk) cancelRef.current?.focus() }, [bulk])
  useEffect(() => { if (rowError) retryRef.current?.focus() }, [rowError])

  const act = async (row: TxnRow, path: string, body?: unknown) => {
    setBusyRow(row.id)
    setRowError(null)
    try {
      const out = await post<TxnRow>(`${base}/transactions/${row.id}/${path}`, body)
      if (out.status === 'draft_not_posted') setRowError({ id: row.id, text: t('post_failed') })
      else setAnnounce(out.reviewer ? t('posted_by', { name: out.reviewer.name, role: out.reviewer.role, datetime: formatDateTime(out.reviewer.at, lang) }) : t(`status_${out.status === 'needs_review' || out.status === 'proposed' ? 'draft' : out.status}`))
      await load()
    } catch (e) {
      setRowError({ id: row.id, text: t(errorKey(e).key) })
    } finally {
      setBusyRow(null)
    }
  }

  const classifyAll = async () => {
    setPreparing({ done: 0, total: 0 })
    try {
      const out = await post<{ total: number; done: number }>(`${base}/transactions/classify-all`)
      setPreparing({ done: out.done, total: out.total })
      setAnnounce(t('preparing', { done: out.done, total: out.total }))
      await load()
    } catch (e) {
      setError(t(errorKey(e).key))
    } finally {
      setTimeout(() => setPreparing(null), 1500)
    }
  }

  const openBulk = async () => {
    try {
      setBulk(await post<BulkPreview>(`${base}/transactions/bulk-accept`, { confirm: false }))
    } catch (e) {
      setError(t(errorKey(e).key))
    }
  }

  const confirmBulk = async () => {
    if (!bulk) return
    try {
      const out = await post<BulkPreview & { accepted_by: string; role: string }>(`${base}/transactions/bulk-accept`, { confirm: true, ids: bulk.ids })
      setAnnounce(t('bulk_done', { count: out.count, name: out.accepted_by, role: out.role }))
      setBulk(null)
      bulkTrigger.current?.focus()
      await load()
    } catch (e) {
      setError(t(errorKey(e).key))
    }
  }

  const decideQuarantine = async () => {
    if (!quarantine || !reason.trim()) return
    try {
      await post(`${base}/transactions/quarantine-decision`, { decision: quarantine.decision, reason, ids: quarantine.ids })
      setQuarantine(null)
      setReason('')
      await load()
    } catch (e) {
      setError(t(errorKey(e).key))
    }
  }

  if (error && !data) return <Message kind="error">{error}</Message>
  if (!data) return <div aria-busy="true"><Skeleton rows={6} /><p role="status">{t('loading')}</p></div>

  if (data.view === 'no_function') {
    return (
      <Empty icon="lock" title={t('no_function')} action={<Button variant="secondary">{t('ask_owner')}</Button>} />
    )
  }

  const counts = data.counts
  const isOwner = data.role === 'owner'
  const bank = data.consent.bank
  const latest = typeof counts.latest_data_at === 'string' ? counts.latest_data_at : null
  const staleData = latest ? Date.now() - new Date(latest + 'Z').getTime() > 24 * 3600 * 1000 : false

  const banners = (
    <>
      {bank.state === 'awaiting_consent' && !data.consent.ledger.allowed && <Message kind="info">{t('awaiting_consent')}</Message>}
      {(bank.state === 'withdrawn' || bank.state === 'expired') && (
        <Message kind="warning">
          {t('consent_ended', { date: formatDate(bank.ended_on ?? null, lang) })}{' '}
          {isOwner ? <Link to="/consent">{t('renew')}</Link> : <span>{t('ask_owner_renew')}</span>}
        </Message>
      )}
      {staleData && latest && (
        <Message kind="warning">
          {t('stale_data', { datetime: formatDateTime(latest, lang) })} <Button variant="link" onClick={load}>{t('refresh')}</Button>
        </Message>
      )}
    </>
  )

  if (data.view === 'summary') {
    return (
      <div>
        {banners}
        <p>{t('summary_counts', { needs: counts.needs_review ?? 0, proposed: counts.proposed ?? 0, posted: counts.posted ?? 0 })}</p>
        <p className="hint">{t('summary_view')}</p>
      </div>
    )
  }

  if (!counts.has_transactions) {
    return (
      <>
        {banners}
        <Empty
          icon="inbox"
          title={t('empty_queue')}
          action={
            <div className="actions" style={{ justifyContent: 'center' }}>
              <Link className="btn btn-secondary" to="/consent">{t('upload_statement')} <Chip tone="neutral">{t('manual_unverified')}</Chip></Link>
              <Link className="btn btn-secondary" to="/consent">{t('open_consent_centre')}</Link>
            </div>
          }
        />
      </>
    )
  }

  const canAct = data.view === 'full'
  const bulkCount = data.rows.filter((r) => r.bulk_eligible).length
  const statusChip = (r: TxnRow) => {
    if (r.status === 'posted') return <Chip tone="ok">{r.reviewer ? t('status_reviewed_by', { role: r.reviewer.role }) : t('status_posted')}</Chip>
    if (r.status === 'quarantined') return <Chip tone="critical" icon="⏸">{t('status_quarantined')}</Chip>
    if (r.status === 'rejected') return <Chip tone="neutral">{t('status_rejected')}</Chip>
    if (r.status === 'draft_not_posted') return <Chip tone="urgent">{t('draft_not_posted')}</Chip>
    return <Chip tone="draft">{t('status_draft')}</Chip>
  }
  const catLabel = (c: string | null) => (c ? t(`cat_${c}`) : '—')

  return (
    <div>
      {banners}
      <div role="status" aria-live="polite" style={SR_ONLY}>{announce}</div>
      <Toolbar label={t('filter')}>
        <Field label={t('filter')} id="tax-filter">
          <select id="tax-filter" value={filter} onChange={(e) => setFilter(e.target.value as (typeof FILTERS)[number])}>
            {FILTERS.filter((f) => f !== 'quarantined' || isOwner).map((f) => (
              <option key={f} value={f}>{t(`filter_${f}`)}</option>
            ))}
          </select>
        </Field>
        <span className="tax-counts hint">{t('summary_counts', { needs: counts.needs_review ?? 0, proposed: counts.proposed ?? 0, posted: counts.posted ?? 0 })}</span>
        {canAct && (
          <div className="toolbar-end">
            {canAct && <Button variant="secondary" onClick={classifyAll}><Icon name="sparkle" size={18} />{t('classify_all')}</Button>}
            {canAct && bulkCount > 0 && (
              <Button ref={bulkTrigger} onClick={openBulk} aria-label={t('bulk_open', { count: bulkCount })}>{t('bulk_open', { count: bulkCount })}</Button>
            )}
          </div>
        )}
      </Toolbar>
      {preparing && <p role="status">{t('preparing', { done: preparing.done, total: preparing.total })}</p>}
      {error && <Message kind="error">{error}</Message>}
      {filter === 'needs_review' && data.rows.length === 0 && <Message kind="success">{t('all_reviewed')}</Message>}
      {filter === 'quarantined' && data.rows.length > 0 && (
        <Message kind="warning">
          {t('nothing_posted_until_decide')}
          <div className="actions">
            <Button variant="secondary" onClick={() => setQuarantine({ decision: 'keep_and_review' })}>{t('keep_and_review_all')}</Button>
            <Button variant="danger" onClick={() => setQuarantine({ decision: 'discard' })}>{t('discard_all')}</Button>
          </div>
        </Message>
      )}
      {data.rows.length > 0 && (
        <div className="tax-table card">
          <p className="tax-table-note"><Chip tone="draft" icon="✎">{t('ai_prepared_draft')}</Chip> <span className="hint">{t('codes_pending')}</span></p>
          <div className="table-wrap">
            <table className="table-compact tax-books">
              <thead>
                <tr>
                  <th scope="col">{t('col_date')}</th>
                  <th scope="col">{t('col_description')}</th>
                  <th scope="col" className="num">{t('col_amount')}</th>
                  <th scope="col">{t('col_proposal')}</th>
                  <th scope="col">{t('col_status')}</th>
                  <th scope="col">{t('col_actions')}</th>
                </tr>
              </thead>
              <tbody>
                {data.rows.map((r) => (
                  <tr key={r.id} aria-busy={busyRow === r.id}>
                    <td className="date-cell"><bdi dir="ltr">{formatDate(r.txn_date, lang)}</bdi></td>
                    <td className="tax-desc">
                      <bdi dir="auto">{r.description}</bdi>
                      <div className="hint">
                        {t('lang_label', { lang: t(`lang_${r.description_language}`) })}
                        {r.manual_unverified && <> · <Chip tone="neutral">{t('manual_unverified')}</Chip></>}
                        {r.treated_as_data && <> · <span>{t('treated_as_data')}</span></>}
                        {r.consent_withdrawn && <> · <span>{t('consent_withdrawn_row')}</span></>}
                      </div>
                      <div className="hint">{t('source_ref', { system: r.source_system, id: '' })}<bdi dir="ltr">{r.source_id}</bdi></div>
                    </td>
                    <td className="num tax-amount">
                      <bdi dir="ltr" className={r.direction === 'out' ? 'tax-out' : undefined}>{r.direction === 'out' ? '−' : ''}{formatAED(r.aed_amount_fils, lang)}</bdi>
                      {r.fx && (
                        <div className="hint tax-fx">
                          {r.fx.missing ? t('fx_missing') : t('fx_line', { amount: (r.original_amount_fils / 100).toFixed(2), currency: r.original_currency, rate: r.fx.rate, source: r.fx.source, date: formatDate(r.fx.rate_date, lang) })}
                          {r.fx.carried && <> · {t('fx_carried')}</>}
                        </div>
                      )}
                    </td>
                    <td className="tax-proposal">
                      <span className="visually-hidden">{t('ai_prepared_draft')}. </span>
                      <div className="tax-proposal-main">{catLabel(r.final.category ?? r.proposed.category)} · <bdi dir="ltr">{r.final.vat_code ?? r.proposed.vat_code ?? '—'}</bdi> · <bdi dir="ltr">{r.final.ledger_account ?? r.proposed.ledger_account ?? '—'}</bdi></div>
                      {r.review_reason && (
                        <div className="hint">
                          <span aria-hidden="true">{r.review_reason === 'Matches your earlier choices' ? '↺ ' : '? '}</span>
                          {r.review_reason === 'Matches your earlier choices' ? t('reason_matches') : t('reason_no_basis')}
                        </div>
                      )}
                    </td>
                    <td>
                      {statusChip(r)}
                      {r.reviewer && r.status === 'posted' && <div className="hint">{t('posted_by', { name: r.reviewer.name, role: r.reviewer.role, datetime: formatDateTime(r.reviewer.at, lang) })}</div>}
                      {r.quarantine && <div className="hint">{t('quarantined', { name: r.quarantine.made_by, date: formatDate(r.quarantine.access_removed_on, lang) })}</div>}
                    </td>
                    <td className="tax-actions">
                      {canAct && (r.status === 'proposed' || r.status === 'needs_review') && (
                        <div className="tax-row-actions">
                          {r.proposed.category && <Button className="btn-sm" onClick={() => act(r, 'accept')} disabled={busyRow === r.id}>{t('accept')}</Button>}
                          <Button variant="secondary" className="btn-sm" onClick={() => { setCorrecting(r); setForm({ category: r.proposed.category ?? '', vat_code: r.proposed.vat_code ?? '', ledger_account: r.proposed.ledger_account ?? '' }) }}>{t('correct')}</Button>
                          <Button variant="secondary" className="btn-sm tax-reject" onClick={() => act(r, 'reject')}>{t('reject')}</Button>
                        </div>
                      )}
                      {canAct && r.status === 'quarantined' && isOwner && (
                        <div className="tax-row-actions">
                          <Button variant="secondary" className="btn-sm" onClick={() => setQuarantine({ decision: 'keep_and_review', ids: [r.id] })}>{t('keep_and_review')}</Button>
                          <Button variant="danger" className="btn-sm" onClick={() => setQuarantine({ decision: 'discard', ids: [r.id] })}>{t('discard')}</Button>
                        </div>
                      )}
                      {canAct && r.can_undo && <Button variant="link" onClick={() => act(r, 'undo')}>{t('undo')}</Button>}
                      {rowError?.id === r.id && (
                        <div role="alert">
                          <p>{rowError.text}</p>
                          {r.status === 'draft_not_posted' && (
                            <div className="tax-row-actions">
                              <Button ref={retryRef} className="btn-sm" onClick={() => act(r, 'post')}>{t('retry')}</Button>
                              <Link className="btn btn-secondary btn-sm" to="/help">{t('contact_support')}</Link>
                            </div>
                          )}
                        </div>
                      )}
                      {canAct && r.status === 'draft_not_posted' && rowError?.id !== r.id && <Button className="btn-sm" onClick={() => act(r, 'post')}>{t('retry')}</Button>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      <Dialog open={!!bulk} title={t('bulk_title', { count: bulk?.count ?? 0 })} onClose={() => setBulk(null)} labelledBy="bulk-title">
        {bulk && (
          <>
            <p>{t('bulk_body', { total: formatAED(bulk.total_fils, lang), income: formatAED(bulk.income_fils, lang), expenses: formatAED(bulk.expenses_fils, lang) })}</p>
            <Button variant="link" onClick={() => { setBulk(null); setFilter('proposed') }}>{t('review_list_first')}</Button>
            <div className="actions">
              <Button ref={cancelRef} variant="secondary" onClick={() => { setBulk(null); bulkTrigger.current?.focus() }}>{t('cancel')}</Button>
              <Button onClick={confirmBulk}>{t('bulk_button', { count: bulk.count })}</Button>
            </div>
          </>
        )}
      </Dialog>

      <Dialog open={!!correcting} title={t('correct_title')} onClose={() => setCorrecting(null)} labelledBy="correct-title">
        {correcting && ref && (
          <form onSubmit={(e) => { e.preventDefault(); const r = correcting; setCorrecting(null); act(r, 'correct', { category: form.category, vat_code: form.vat_code, ledger_account: form.ledger_account || null }) }}>
            <p><bdi dir="auto">{correcting.description}</bdi></p>
            <Field label={t('category')} id="fix-cat">
              <select id="fix-cat" required value={form.category} onChange={(e) => setForm({ ...form, category: e.target.value })}>
                <option value="" />
                {ref.categories.map((c) => <option key={c} value={c}>{t(`cat_${c}`)}</option>)}
              </select>
            </Field>
            <Field label={t('vat_code')} id="fix-vat" hint={t('configured_pending')}>
              <select id="fix-vat" required value={form.vat_code} onChange={(e) => setForm({ ...form, vat_code: e.target.value })}>
                <option value="" />
                {ref.vat_codes.map((v) => <option key={v.code} value={v.code}>{(lang === 'ar' ? v.name_ar : v.name_en)} ({v.code}): {lang === 'ar' ? v.gloss_ar : v.gloss_en}</option>)}
              </select>
            </Field>
            <Field label={t('ledger_account')} id="fix-acct">
              <select id="fix-acct" value={form.ledger_account} onChange={(e) => setForm({ ...form, ledger_account: e.target.value })}>
                <option value="" />
                {ref.accounts.map((a) => <option key={a.code} value={a.code}>{a.code} {lang === 'ar' ? a.name_ar : a.name_en}</option>)}
              </select>
            </Field>
            <div className="actions">
              <Button type="button" variant="secondary" onClick={() => setCorrecting(null)}>{t('cancel')}</Button>
              <Button type="submit">{t('save')}</Button>
            </div>
          </form>
        )}
      </Dialog>

      <Dialog open={!!quarantine} title={quarantine?.decision === 'discard' ? t('discard') : t('keep_and_review')} onClose={() => setQuarantine(null)} labelledBy="q-title">
        <Field label={t('reason_prompt')} id="q-reason" hint={t('reason_saved')} required>
          <textarea id="q-reason" value={reason} onChange={(e) => setReason(e.target.value)} />
        </Field>
        {!reason.trim() && <p className="hint">{t('choose_reason')}</p>}
        <div className="actions">
          <Button variant="secondary" onClick={() => setQuarantine(null)}>{t('cancel')}</Button>
          <Button disabled={!reason.trim()} onClick={decideQuarantine}>{t('save')}</Button>
        </div>
      </Dialog>
    </div>
  )
}
