import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'
import { useAuth } from '../../app/auth'
import { Icon } from '../../components/Icon'
import { Button, Chip, Dialog, Empty, Field, Ident, Message, PageHeader, Panel, Skeleton } from '../../components/ui'
import { ApiError, post } from '../../lib/api'
import { formatAED, formatDate } from '../../lib/format'
import { bl, newRequestId, useFetch, type CaseRow, type LicenceRow, type Sub, type SubscriptionView } from './lib'
import { FeeCard, ParametersList, Proposed, StatusBadge, StatusMessage, TermsSheet } from './parts'

const CASE_CHIP_TONE: Record<string, 'ok' | 'attention' | 'info' | 'neutral' | 'critical'> = { received: 'info', pending: 'attention', with_det: 'attention', applied: 'ok', refused: 'critical', cancelled: 'neutral', draft: 'neutral' }

/** Owner Subscription screen (SC2 card repeated under SC11). Delegates and remote owners read it read-only. */
export default function SubscriptionPage() {
  const { t } = useTranslation('subscription')
  const { companyId, can } = useAuth()
  const { data, error, loading, slow, reload } = useFetch<SubscriptionView>(companyId ? `/api/companies/${companyId}/subscription` : null, [companyId])
  const [termsOpen, setTermsOpen] = useState(false)
  const [complaintOpen, setComplaintOpen] = useState(false)
  const [notice, setNotice] = useState<string | null>(null)

  if (!companyId) return null
  if (loading && !data) {
    return (
      <div className="page" aria-busy="true">
        <h1>{t('screen.title')}</h1>
        <p role="status">{t('screen.loading')}</p>
        <Skeleton rows={6} />
        {slow && <Message kind="info">{t('screen.still_loading')} <Button variant="link" onClick={reload}>{t('screen.try_again')}</Button></Message>}
      </div>
    )
  }
  if (error && !data) {
    const ref = error instanceof ApiError ? error.reference : undefined
    return (
      <div className="page">
        <h1>{t('screen.title')}</h1>
        <Message kind="error">
          {t('screen.error')} {ref && <span>{t('screen.error_ref', { code: '' })}<Ident>{ref}</Ident></span>}
          <div className="actions"><Button onClick={reload}>{t('screen.try_again')}</Button></div>
        </Message>
      </div>
    )
  }
  if (!data) return null
  const canComplain = can('complaints.open', companyId)
  return (
    <div className="sub-page">
      <PageHeader
        title={t('screen.title')}
        subtitle={t('screen.subtitle')}
        actions={
          <>
            <Button variant="secondary" onClick={() => setTermsOpen(true)}><Icon name="file" size={18} />{t('screen.see_terms')}</Button>
            <Link className="btn btn-secondary" to="/welcome">{t('screen.open_welcome')}</Link>
          </>
        }
      />
      {!data.can_change && <Message kind="info">{t('screen.only_owner')}</Message>}
      {notice && <Message kind="success">{notice}</Message>}
      {data.licences.length === 0 && <Empty icon="card" title={t('screen.no_licence')} />}
      {data.licences.map((row) => (
        <LicenceSection key={row.licence_number} row={row} view={data} onChanged={(msg) => { setNotice(msg); reload() }} />
      ))}
      <div className="sub-grid">
        <ParametersList parameters={data.parameters} />
        <section className="card sub-complaints" aria-labelledby="sub-complaints-title" id="sub-complaints">
          <header className="sub-card-head">
            <h3 id="sub-complaints-title">{t('screen.complaints')}</h3>
            {canComplain && <Button variant="secondary" className="btn-sm" onClick={() => setComplaintOpen(true)}>{t('screen.complaint')}</Button>}
          </header>
          {data.complaints.length === 0 ? (
            <p className="hint">{t('screen.no_requests')}</p>
          ) : (
            <ul className="sub-rows">
              {data.complaints.map((c) => (
                <li key={c.id}>
                  <div className="sub-row-main">
                    <span className="sub-row-title">{bl(data.complaint_categories.find((x) => x.code === c.category), document.documentElement.lang) || c.category}</span>
                    <span className="sub-row-meta"><Ident>{c.reference}</Ident> · <span className="nowrap">{t('screen.reply_by', { date: formatDate(c.reply_by, document.documentElement.lang) })}</span></span>
                  </div>
                  <Chip tone={c.status === 'resolved' || c.status === 'refunded' || c.status === 'replied' ? 'ok' : c.status === 'rejected' ? 'neutral' : 'info'}>{t(`complaint_status.${c.status}`, { defaultValue: c.status })}</Chip>
                </li>
              ))}
            </ul>
          )}
        </section>
      </div>
      <p className="hint">{t('screen.questions')}<Proposed /></p>
      <TermsSheet companyId={companyId} open={termsOpen} onClose={() => setTermsOpen(false)} />
      {complaintOpen && <ComplaintDialog view={data} onClose={() => setComplaintOpen(false)} onDone={(msg) => { setComplaintOpen(false); setNotice(msg); reload() }} />}
    </div>
  )
}

function LicenceSection({ row, view, onChanged }: { row: LicenceRow; view: SubscriptionView; onChanged: (msg: string) => void }) {
  const { t, i18n } = useTranslation('subscription')
  const { companyId, can } = useAuth()
  const [busy, setBusy] = useState(false)
  const sub = row.subscription
  const pilotKey = `screen.pilot_${row.pilot?.pilot_status ?? 'not_in_pilot'}`
  const registerInterest = async () => {
    setBusy(true)
    try {
      await post(`/api/companies/${companyId}/cohort/interest`, { licence_number: row.licence_number })
      onChanged(t('screen.interest_registered'))
    } finally {
      setBusy(false)
    }
  }
  return (
    <Panel className="sub-licence" title={<>{t('screen.licence')} <Ident>{row.licence_number}</Ident></>} id={`lic-${row.licence_number}`} actions={<span className="sub-pilot">{t('screen.pilot_status')}: <Chip tone={row.pilot?.pilot_status === 'active' ? 'ok' : 'neutral'}>{t(pilotKey)}</Chip></span>}>
      {row.empty_state === 'not_in_pilot' && (
        <Message kind="info">
          {t('screen.empty_not_in_pilot')}
          {row.pilot?.interest_status ? <p>{t('screen.interest_registered')}</p> : can('settings.manage', companyId) && (
            <div className="actions"><Button variant="secondary" disabled={busy} onClick={registerInterest}>{t('screen.register_interest')}</Button></div>
          )}
        </Message>
      )}
      {row.empty_state === 'in_cohort_no_event' && <Message kind="info">{t('screen.empty_in_cohort')}</Message>}
      {row.empty_state === 'opted_out' && <Message kind="info">{t('screen.empty_opted_out')}</Message>}
      {sub && <SubscriptionCard sub={sub} view={view} onChanged={onChanged} />}
      {row.past.length > 0 && (
        <details>
          <summary>{t('screen.badge_ended')}</summary>
          <ul className="timeline">
            {row.past.map((p) => (
              <li key={p.id}><StatusBadge badge={p.badge} /> {t('screen.term', { start: formatDate(p.start_date, i18n.language), end: formatDate(p.end_date, i18n.language) })}</li>
            ))}
          </ul>
        </details>
      )}
    </Panel>
  )
}

function SubscriptionCard({ sub, view, onChanged }: { sub: Sub; view: SubscriptionView; onChanged: (msg: string) => void }) {
  const { t, i18n } = useTranslation('subscription')
  const { companyId } = useAuth()
  const lang = i18n.language
  const [dialog, setDialog] = useState<'opt_out' | 'refund' | null>(null)
  const stopped = ['opted_out', 'cancelled_by_opt_out', 'ended', 'cancelled'].includes(sub.status)
  const openCase = (action: string) => sub.cases.find((c) => c.action === action && c.can_cancel)
  const cancel = async (c: CaseRow) => {
    await post(`/api/companies/${companyId}/subscription/${sub.id}/cases/${c.id}/cancel`)
    onChanged(t('screen.chip_cancelled'))
  }
  return (
    <div className="sub-licence-grid">
      <div className="sub-col">
        <div className="sub-status">
          <span className="sub-status-chips">
            <StatusBadge badge={sub.badge} />
            <Chip tone="neutral" icon={sub.enrolment_basis === 'opted_in' ? '✓' : 'i'}>{sub.enrolment_basis === 'opted_in' ? t('screen.you_chose') : t('screen.default_on_tag')}</Chip>
            {sub.is_demo && <Chip tone="draft" icon="✎">{t('demo')}</Chip>}
          </span>
          <StatusMessage sub={sub} />
        </div>
        {openCase('opt_out') && <Message kind="info">{t('screen.pending_banner')}</Message>}
        {sub.service_mode === 'read_only' && (
          <Message kind="warning">{t('screen.read_only_mode')} {sub.grace_until && <span className="hint">{t('screen.grace_until', { date: formatDate(sub.grace_until, lang) })}</span>}</Message>
        )}
        <FeeCard sub={sub} />
      </div>
      <div className="sub-col">
        <div className="card sub-term">
          <span className="sub-term-icon" aria-hidden="true"><Icon name="calendar" size={18} /></span>
          <span>{t('screen.term', { start: formatDate(sub.start_date, lang), end: formatDate(sub.end_date, lang) })}</span>
        </div>
        {sub.billing && sub.fee && <BillingLine sub={sub} />}
        <section className="card sub-requests" aria-labelledby={`actions-${sub.id}`}>
          <h3 id={`actions-${sub.id}`}>{t('screen.actions')}</h3>
          {view.can_change ? (
            <div className="actions">
              {!stopped && !openCase('opt_out') && <Button variant="secondary" onClick={() => setDialog('opt_out')}>{t('screen.opt_out')}</Button>}
              {sub.billing && !openCase('refund') && <Button variant="secondary" onClick={() => setDialog('refund')}>{t('screen.refund')}</Button>}
            </div>
          ) : (
            <div className="actions">
              <Button variant="secondary" disabled aria-describedby={`owner-only-${sub.id}`}>{t('screen.opt_out')}</Button>
              <span id={`owner-only-${sub.id}`} className="hint">{t('screen.only_owner_action')}</span>
            </div>
          )}
          {sub.cases.length === 0 ? <p className="hint sub-none">{t('screen.no_requests')}</p> : (
            <ul className="sub-rows">
              {sub.cases.map((c) => (
                <li key={c.id}>
                  <div className="sub-row-main">
                    <span className="sub-row-title">{c.action === 'opt_out' ? t('screen.opt_out') : t('screen.refund')}</span>
                    <span className="sub-row-meta"><Ident>{c.reference_code}</Ident> · <span className="nowrap">{formatDate(c.received_at, lang)}</span></span>
                    {c.state === 'needs_DET_action' && <span className="hint">{t('screen.needs_det', { code: c.reference_code })}</span>}
                    {c.action === 'refund' && c.can_cancel && <span className="hint">{t('screen.request_received')}</span>}
                    {c.action === 'opt_out' && c.can_cancel && <span className="hint">{t('screen.window_not_set')}</span>}
                  </div>
                  <span className="sub-row-end">
                    <Chip tone={CASE_CHIP_TONE[c.chip] ?? 'neutral'}>{t(`screen.chip_${c.chip}`)}</Chip>
                    {view.can_change && c.can_cancel && <Button variant="link" onClick={() => cancel(c)}>{t('screen.cancel_request')}</Button>}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </section>
      </div>
      {dialog === 'opt_out' && <OptOutDialog sub={sub} view={view} onClose={() => setDialog(null)} onDone={(m) => { setDialog(null); onChanged(m) }} />}
      {dialog === 'refund' && <RefundDialog sub={sub} view={view} onClose={() => setDialog(null)} onDone={(m) => { setDialog(null); onChanged(m) }} />}
    </div>
  )
}

/** Owner fee-line state: collection status, payment reference, paid / outstanding for partial payments. */
function BillingLine({ sub }: { sub: Sub }) {
  const { t, i18n } = useTranslation('subscription')
  const lang = i18n.language
  const b = sub.billing!
  const unallocated = sub.payments.some((p) => p.status === 'received_unallocated') || b.collection_status === 'received_unallocated'
  return (
    <section className="card sub-billing" aria-labelledby={`billing-${sub.id}`}>
      <header className="sub-card-head">
        <h3 id={`billing-${sub.id}`}>{t('screen.payment')}</h3>
        <span className="sub-status-chips">
          <Chip tone={b.collection_status === 'collected' ? 'ok' : b.collection_status === 'failed' ? 'urgent' : 'info'}>{t(`screen.status_${b.collection_status}`)}</Chip>
          {b.provisional && <Chip tone="draft">{t('screen.provisional')}</Chip>}
        </span>
      </header>
      <dl className="kv sub-billing-kv">
        <dt>{t('screen.payment_reference')}</dt>
        <dd>{b.payment_reference ? <Ident>{b.payment_reference}</Ident> : '–'}</dd>
        {b.collected_fils !== undefined && (b.collected_fils > 0 || b.collection_status === 'partially_collected') && (
          <>
            <dt>{t('screen.paid')}</dt>
            <dd><bdi dir="ltr">{formatAED(b.collected_fils, lang)}</bdi></dd>
            <dt>{t('screen.outstanding')}</dt>
            <dd><bdi dir="ltr">{formatAED(b.outstanding_fils ?? 0, lang)}</bdi></dd>
          </>
        )}
        {!!b.refunded_fils && (
          <>
            <dt>{t('screen.refunded')}</dt>
            <dd><bdi dir="ltr">{formatAED(b.refunded_fils, lang)}</bdi></dd>
          </>
        )}
      </dl>
      {b.collection_status === 'partially_collected' && <Message kind="warning">{t('screen.notice_partly', { paid: formatAED(b.collected_fils, lang).replace('AED ', ''), amount: formatAED(b.gross_fils, lang).replace('AED ', ''), remaining: formatAED(b.outstanding_fils, lang).replace('AED ', '') })}</Message>}
      {b.collection_status === 'failed' && <Message kind="warning">{t('screen.notice_failed')}</Message>}
      {unallocated && <Message kind="info">{t('screen.received_unallocated')}. {t('screen.we_are_confirming')}</Message>}
      {b.status === 'mismatch' && <Message kind="info">{t('screen.notice_mismatch')}</Message>}
      {b.status === 'pending_confirmation' && <Message kind="info">{t('screen.we_are_confirming')}</Message>}
      <p className="hint">{t('screen.footer_not_affected')}</p>
    </section>
  )
}

function useSubmit() {
  const { t } = useTranslation('subscription')
  const [sending, setSending] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const run = async (fn: () => Promise<void>) => {
    setSending(true)
    setErr(null)
    try {
      await fn()
    } catch (e) {
      const code = e instanceof ApiError ? e.code : ''
      setErr(code === 'NO_PERMISSION' || code === 'RIGHT_SWITCHED_OFF' ? t('screen.only_owner_action') : `${t('screen.error')}${e instanceof ApiError && e.reference ? ` (${e.reference})` : ''}`)
    } finally {
      setSending(false)
    }
  }
  return { sending, err, run }
}

/** Opt-out: consequences, reason, understanding checkbox; "Keep my services" holds default focus. */
function OptOutDialog({ sub, view, onClose, onDone }: { sub: Sub; view: SubscriptionView; onClose: () => void; onDone: (m: string) => void }) {
  const { t, i18n } = useTranslation('subscription')
  const { companyId } = useAuth()
  const [requestId] = useState(newRequestId)
  const [reason, setReason] = useState('')
  const [understood, setUnderstood] = useState(false)
  const { sending, err, run } = useSubmit()
  const reasons = view.reasons.opt_out ?? []
  const submit = () => run(async () => {
    const r = await post<{ already_requested: boolean }>(`/api/companies/${companyId}/subscription/${sub.id}/opt-out`, { request_id: requestId, reason_code: reason, understood })
    onDone(r.already_requested ? t('screen.already_requested') : t('screen.pending_banner'))
  })
  return (
    <Dialog open title={t('screen.opt_out_title')} onClose={onClose} labelledBy="optout-title">
      <h3>{t('screen.consequences_title')}<Proposed /></h3>
      <ul>
        {['cons_stops', 'cons_unchanged', 'cons_when', 'cons_fee', 'cons_data', 'cons_back', 'cons_complain'].map((k) => <li key={k}>{t(`screen.${k}`)}</li>)}
      </ul>
      <p>{t('screen.window_not_set')}</p>
      <Field label={t('screen.reason')} id="optout-reason" required>
        <select id="optout-reason" value={reason} onChange={(e) => setReason(e.target.value)}>
          <option value="" />
          {reasons.map((r) => <option key={r.code} value={r.code}>{bl(r, i18n.language)}</option>)}
        </select>
      </Field>
      <label style={{ display: 'flex', gap: 8, alignItems: 'center', minHeight: 44 }}>
        <input type="checkbox" checked={understood} onChange={(e) => setUnderstood(e.target.checked)} /> {t('screen.understand')}
      </label>
      {err && <Message kind="error">{err}</Message>}
      <div className="actions">
        <Button autoFocus variant="primary" onClick={onClose}>{t('screen.keep')}</Button>
        <Button variant="secondary" disabled={!reason || !understood || sending} onClick={submit}>{sending ? t('screen.sending') : t('screen.stop')}</Button>
      </div>
    </Dialog>
  )
}

/** Refund request: neutral status only, no eligibility, outcome or amount before DET decides. */
function RefundDialog({ sub, view, onClose, onDone }: { sub: Sub; view: SubscriptionView; onClose: () => void; onDone: (m: string) => void }) {
  const { t, i18n } = useTranslation('subscription')
  const { companyId } = useAuth()
  const [requestId] = useState(newRequestId)
  const [reason, setReason] = useState('')
  const { sending, err, run } = useSubmit()
  const submit = () => run(async () => {
    const r = await post<{ already_requested: boolean }>(`/api/companies/${companyId}/subscription/${sub.id}/refund-request`, { request_id: requestId, reason_code: reason })
    onDone(r.already_requested ? t('screen.already_requested') : t('screen.refund_received', { days: view.refund_response_time_working_days }))
  })
  return (
    <Dialog open title={t('screen.refund')} onClose={onClose} labelledBy="refund-title">
      <p>{t('screen.refund_placeholder')}<Proposed /></p>
      <Field label={t('screen.reason')} id="refund-reason" required>
        <select id="refund-reason" value={reason} onChange={(e) => setReason(e.target.value)}>
          <option value="" />
          {(view.reasons.refund ?? []).map((r) => <option key={r.code} value={r.code}>{bl(r, i18n.language)}</option>)}
        </select>
      </Field>
      {err && <Message kind="error">{err}</Message>}
      <div className="actions">
        <Button variant="secondary" onClick={onClose}>{t('translation:common.cancel')}</Button>
        <Button disabled={!reason || sending} onClick={submit}>{sending ? t('screen.sending') : t('screen.send')}</Button>
      </div>
    </Dialog>
  )
}

/** Complaint form (1A: no attachments); the confirmation shows the reference and the computed reply-by date. */
function ComplaintDialog({ view, onClose, onDone }: { view: SubscriptionView; onClose: () => void; onDone: (m: string) => void }) {
  const { t, i18n } = useTranslation('subscription')
  const { companyId } = useAuth()
  const [category, setCategory] = useState('')
  const [description, setDescription] = useState('')
  const [language, setLanguage] = useState(i18n.language.startsWith('ar') ? 'ar' : 'en')
  const [licence, setLicence] = useState(view.licences[0]?.licence_number ?? '')
  const { sending, err, run } = useSubmit()
  const submit = () => run(async () => {
    const sub = view.licences.find((l) => l.licence_number === licence)?.subscription
    const r = await post<{ complaint: { reference: string }; reply_by: string }>(`/api/companies/${companyId}/complaints`, { licence_number: licence || null, subscription_id: sub?.id ?? null, category, description, preferred_language: language, contact_channel: 'portal' })
    onDone(`${t('screen.complaint_sent', { ref: r.complaint.reference })} ${t('screen.reply_by', { date: formatDate(r.reply_by, i18n.language) })}`)
  })
  return (
    <Dialog open title={t('screen.complaint_title')} onClose={onClose} labelledBy="complaint-title">
      <Field label={t('screen.licence')} id="cmp-licence" required>
        <select id="cmp-licence" value={licence} onChange={(e) => setLicence(e.target.value)}>
          {view.licences.map((l) => <option key={l.licence_number} value={l.licence_number}>{l.licence_number}</option>)}
        </select>
      </Field>
      <Field label={t('screen.category')} id="cmp-category" required>
        <select id="cmp-category" value={category} onChange={(e) => setCategory(e.target.value)}>
          <option value="" />
          {view.complaint_categories.map((c) => <option key={c.code} value={c.code}>{bl(c, i18n.language)}</option>)}
        </select>
      </Field>
      <Field label={t('screen.description')} id="cmp-desc" required>
        <textarea id="cmp-desc" rows={4} maxLength={2000} value={description} onChange={(e) => setDescription(e.target.value)} />
      </Field>
      <Field label={t('screen.preferred_language')} id="cmp-lang">
        <select id="cmp-lang" value={language} onChange={(e) => setLanguage(e.target.value)}>
          <option value="ar">العربية</option>
          <option value="en">English</option>
        </select>
      </Field>
      {err && <Message kind="error">{err}</Message>}
      <div className="actions">
        <Button variant="secondary" onClick={onClose}>{t('translation:common.cancel')}</Button>
        <Button disabled={!category || !description.trim() || sending} onClick={submit}>{sending ? t('screen.sending') : t('screen.send')}</Button>
      </div>
    </Dialog>
  )
}
