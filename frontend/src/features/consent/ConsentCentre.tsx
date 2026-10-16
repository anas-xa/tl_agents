import { useCallback, useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../../app/auth'
import { Icon } from '../../components/Icon'
import { Button, Chip, Dialog, Disclosure, Empty, Field, Message, PageHeader, Panel, Skeleton } from '../../components/ui'
import { ApiError, get, post } from '../../lib/api'
import { formatDate, formatDateTime } from '../../lib/format'
import LinkStatusList, { useLinks } from './LinkStatusList'
import TaxLinkCard from './TaxLinkCard'
import { ConsentChip, MaskedAccount, ReceiptDialog, TimelineList, useLang } from './parts'
import type { ConsentList, ConsentRow, ReceiptOut } from './types'
import './consent.css'

const LIVE = ['active', 'pending', 'paused']

/** SC5 Consent Centre (E4-S1, E4-S2, E4-S3 bank list, E4-S5 tax card, E4-S6 link status). */
export default function ConsentCentre() {
  const { t } = useTranslation('consent')
  const lang = useLang()
  const { me, companyId, company } = useAuth()
  const [data, setData] = useState<ConsentList | null>(null)
  const [error, setError] = useState<ApiError | Error | null>(null)
  const [slow, setSlow] = useState(false)
  const [granting, setGranting] = useState(false)
  const [withdrawing, setWithdrawing] = useState<ConsentRow | null>(null)
  const [receipt, setReceipt] = useState<ReceiptOut | null>(null)
  const [notice, setNotice] = useState<{ kind: 'info' | 'error' | 'success' | 'warning'; text: string } | null>(null)

  const load = useCallback(async () => {
    if (!companyId) return
    setError(null)
    setSlow(false)
    const timer = setTimeout(() => setSlow(true), 10000)
    try {
      setData(await get<ConsentList>(`/api/companies/${companyId}/consents`))
    } catch (e) {
      setError(e as Error)
    } finally {
      clearTimeout(timer)
      setSlow(false)
    }
  }, [companyId])
  useEffect(() => {
    load()
  }, [load])

  if (!me || !companyId) return null
  const companyName = company ? (lang === 'ar' ? company.trade_name_ar : company.trade_name_en) : ''
  const rights = data?.rights
  const actingAs = rights?.is_delegate ? t('acting_as_delegate', { name: me.display_name, company: companyName }) : t('acting_as_owner', { name: me.display_name, company: companyName })

  const showReceipt = async (c: ConsentRow, kind: 'grant' | 'withdrawal' = 'grant') => {
    try {
      setReceipt(await get<ReceiptOut>(`/api/companies/${companyId}/consents/${c.consent_id}/receipt?kind=${kind}`))
    } catch {
      setNotice({ kind: 'error', text: t('status_load_failed') })
    }
  }
  const act = async (c: ConsentRow, action: 'cancel' | 'resume') => {
    try {
      await post(`/api/companies/${companyId}/consents/${c.consent_id}/${action}`)
      await load()
    } catch (e) {
      setNotice({ kind: 'error', text: refusal(t, e) })
    }
  }
  const askOwner = async (consentType: string) => {
    try {
      const r = await post<{ expires_at: string }>(`/api/companies/${companyId}/consents/requests`, { consent_type: consentType })
      setNotice({ kind: 'success', text: t('request_sent', { date: formatDate(r.expires_at.slice(0, 10), lang) }) })
      await load()
    } catch (e) {
      setNotice({ kind: e instanceof ApiError && e.code === 'RATE_LIMITED' ? 'info' : 'error', text: e instanceof ApiError && e.code === 'RATE_LIMITED' ? t('request_limited') : t('save_failed') })
    }
  }

  const live = data?.consents.filter((c) => LIVE.includes(c.status)) ?? []
  const past = data?.consents.filter((c) => !LIVE.includes(c.status)) ?? []
  return (
    <div className="consent-centre">
      <PageHeader
        title={t('title')}
        subtitle={t('subtitle')}
        meta={<span className="consent-acting"><Icon name="user" size={16} />{actingAs}</span>}
        actions={rights?.can_grant ? <Button onClick={() => setGranting(true)}>{live.length ? t('add') : t('add_first')}</Button> : undefined}
      />
      {notice && <Message kind={notice.kind}>{notice.text}</Message>}
      {!data && !error && (
        <div>
          <p className="muted" role="status" aria-live="polite">{t('loading')}</p>
          <div className="consent-grid">
            {[0, 1, 2].map((i) => (
              <div className="card" key={i}><Skeleton rows={3} /></div>
            ))}
          </div>
          {slow && (
            <Message kind="info">
              {t('slow')} <Button variant="link" onClick={load}>{t('retry')}</Button>
            </Message>
          )}
        </div>
      )}
      {error && !data && (
        error instanceof ApiError && error.status === 403 ? (
          <Message kind="error">{error.code === 'NOT_YOUR_COMPANY' ? t('access_ended') : t('no_access')}</Message>
        ) : (
          <Message kind="error">
            {t('load_failed')} <Button variant="link" onClick={load}>{t('retry')}</Button>
          </Message>
        )
      )}
      {data && rights && (
        <>
          {!rights.can_grant && rights.is_delegate && (
            <Message kind="info">
              {t('view_only')} {rights.refusal_code === 'RIGHT_SWITCHED_OFF' && <span className="muted">({t('right_off')})</span>}{' '}
              <Button variant="link" onClick={() => askOwner('ledger_invoice_authorisation')}>{t('ask_owner')}</Button>
            </Message>
          )}
          {rights.is_remote_owner && <Message kind="info">{t('remote_tax')}</Message>}
          {rights.can_grant && rights.assurance_level !== rights.step_up_required && rights.assurance_level < rights.step_up_required && (
            <Message kind="warning">{t('step_up', { level: rights.step_up_required, current: rights.assurance_level })}</Message>
          )}
          <div className="consent-section-head">
            <h2>{t('your_consents')}</h2>
            <Disclosure summary={t('what_is')} className="consent-what">
              <p>{t('what_is_body')}</p>
            </Disclosure>
          </div>
          {data.consents.length === 0 ? (
            <Empty
              icon="shield"
              title={t('empty_title')}
              body={t('empty_body')}
              action={rights.can_grant ? <Button onClick={() => setGranting(true)}>{t('add_first')}</Button> : rights.can_request ? <Button variant="secondary" onClick={() => askOwner('ledger_invoice_authorisation')}>{t('ask_owner')}</Button> : undefined}
            />
          ) : (
            <>
              {live.length === 0 && <p>{t('no_active')}</p>}
              <div className="consent-grid">
                {live.map((c) => (
                  <ConsentCard key={c.consent_id} c={c} data={data} onWithdraw={() => setWithdrawing(c)} onReceipt={() => showReceipt(c)} onCancel={() => act(c, 'cancel')} onResume={() => act(c, 'resume')} onAsk={() => askOwner(c.consent_type)} />
                ))}
              </div>
              {past.length > 0 && (
                <>
                  <div className="section-title"><h2>{t('past')}</h2></div>
                  <div className="consent-grid">
                    {past.map((c) => (
                      <ConsentCard key={c.consent_id} c={c} data={data} onWithdraw={() => undefined} onReceipt={() => showReceipt(c, c.timeline ? 'withdrawal' : 'grant')} onAsk={() => askOwner(c.consent_type)} />
                    ))}
                  </div>
                </>
              )}
            </>
          )}
          <div className="consent-two">
          <BankSection />
          <section className="consent-retention" aria-labelledby="consent-retention-title">
            <span className="consent-retention-icon" aria-hidden="true"><Icon name="lock" size={18} /></span>
            <div>
              <h2 id="consent-retention-title">{t('retention_title')}</h2>
              <p>{t('microcopy')}</p>
              <p className="muted">{t('retention_note')}</p>
            </div>
          </section>
          </div>
          <TaxLinkCard />
          <section id="data-links" aria-labelledby="data-links-title">
            <div className="section-title consent-links-title"><h2 id="data-links-title">{t('links_title')}</h2></div>
            <LinkStatusList />
          </section>
          {granting && <GrantDialog data={data} onClose={() => setGranting(false)} onDone={async (msg) => { setGranting(false); setNotice(msg); await load() }} />}
          {withdrawing && <WithdrawDialog c={withdrawing} onClose={() => setWithdrawing(null)} onDone={async (msg) => { setNotice(msg); await load() }} />}
          <ReceiptDialog receipt={receipt} onClose={() => setReceipt(null)} />
        </>
      )}
    </div>
  )
}

function refusal(t: (k: string, o?: Record<string, unknown>) => string, e: unknown): string {
  if (!(e instanceof ApiError)) return t('save_failed')
  switch (e.code) {
    case 'RIGHT_SWITCHED_OFF':
      return t('right_off')
    case 'REMOTE_OWNER_TAX_CONSENT_NOT_AVAILABLE':
      return t('remote_tax')
    case 'LEVEL_TOO_LOW_FOR_ACTION':
      return t('step_up', { level: String((e.details as { required_level?: string })?.required_level ?? 'SOP3'), current: '' })
    case 'NO_LICENSED_BANK_ROUTE':
      return t('no_bank_route')
    default:
      return e.message || t('save_failed')
  }
}

function ConsentCard({ c, data, onWithdraw, onReceipt, onCancel, onResume, onAsk }: { c: ConsentRow; data: ConsentList; onWithdraw: () => void; onReceipt: () => void; onCancel?: () => void; onResume?: () => void; onAsk: () => void }) {
  const { t } = useTranslation('consent')
  const lang = useLang()
  const rights = data.rights
  const source = c.provider_name || c.source
  const isTaxRemote = c.consent_type === 'tax_data' && rights.is_remote_owner && !rights.tax_consent_online
  const canWithdraw = rights.can_withdraw && !isTaxRemote
  const withdrawn = c.status === 'withdrawn_on_platform' || c.status === 'revocation_confirmed_by_provider'
  const list = c.data_types.map((d) => t(`dt.${d}`)).join(', ')
  const excluded = c.data_types_not_read.map((d) => t(`dt.${d}`)).join(', ') || '-'
  return (
    <article className="card consent-card" aria-labelledby={`c-${c.consent_id}`}>
      <header className="consent-card-head">
        <ConsentChip status={c.display_status} />
        {c.granted_by_removed_delegate && <Chip tone="attention" icon="!">{t('chip.removed_delegate')}</Chip>}
        {c.is_demo && <span className="tag">{t('demo')}</span>}
      </header>
      <h3 id={`c-${c.consent_id}`} className="consent-card-title">{t(`type.${c.consent_type}`)}</h3>
      <dl className="kv consent-kv">
        <dt>{t('source')}</dt>
        <dd><bdi dir="auto">{source}</bdi></dd>
        {c.accounts_masked.length > 0 && (
          <>
            <dt>{t('accounts')}</dt>
            <dd>{c.accounts_masked.map((a) => <MaskedAccount key={a} value={a} />)}</dd>
          </>
        )}
        <dt>{t('field_purpose')}</dt>
        <dd>{t(`purpose.${c.purpose}`)}</dd>
        <dt>{t('reads')}</dt>
        <dd>{list || '-'}</dd>
        <dt>{t('not_reads')}</dt>
        <dd>{excluded}</dd>
      </dl>
      {c.consent_type === 'bank_data_open_finance' && <p className="consent-note">{t('bank_read_only')} {t('through_provider')}</p>}
      {c.consent_type === 'tax_data' && <p className="consent-note">{t('tax.scope_note')}</p>}
      {c.status === 'pending' && <p className="consent-state"><Icon name="clock" size={16} /><strong>{t('pending_cause')}</strong></p>}
      {c.status === 'active' && <p className="consent-state"><Icon name="calendar" size={16} /><span>{t('valid_until', { date: formatDateTime(c.expires_at, lang) })}</span></p>}
      {c.status === 'active' && c.days_left !== null && c.days_left <= 30 && (
        <Message kind="warning">{t('ends_on', { what: source, date: formatDateTime(c.expires_at, lang) })}</Message>
      )}
      {c.status === 'paused' && <p>{t('paused_note')}</p>}
      {c.status === 'expired' && <p>{t('expired_on', { date: formatDate((c.expired_at ?? c.expires_at).slice(0, 10), lang) })}</p>}
      {withdrawn && c.withdrawn_at && (
        <p>
          {t('withdrawn_by', { date: formatDateTime(c.withdrawn_at, lang), name: c.timeline?.withdrawn_by ?? '-' })} · <span className="muted">{t(`sub.${c.status}`)}</span>
        </p>
      )}
      {withdrawn && c.timeline && <TimelineList timeline={c.timeline} source={source} />}
      {withdrawn && c.timeline?.provider_revocation_status === 'retrying' && <Message kind="info">{t('revocation_retrying', { bank: source })}</Message>}
      {withdrawn && c.timeline?.provider_revocation_status === 'failed' && <Message kind="warning">{t('revocation_failed', { bank: source })}</Message>}
      {c.granted_by_removed_delegate && canWithdraw && (
        <Message kind="warning">
          {t('removed_delegate_banner', { delegate: c.grantor_display_name ?? '-', date: '-' })}
          <div className="actions">
            <Button variant="secondary">{t('keep')}</Button>
            <Button variant="danger" onClick={onWithdraw}>{t('withdraw')}</Button>
          </div>
        </Message>
      )}
      <footer className="consent-card-foot">
        <p className="consent-granted">
          {t('granted_by', { name: c.grantor_display_name ?? '-' })}
          {c.delegation_id && <> · {t('delegation_id')}: <bdi dir="ltr">{c.delegation_id}</bdi></>}
        </p>
        {LIVE.includes(c.status) && !canWithdraw && (
          <p className="muted consent-granted">
            {isTaxRemote ? t('only_owner_tax') : t('only_owner_withdraw')}{' '}
            {rights.can_request && <Button variant="link" onClick={onAsk}>{rights.is_delegate ? t('request_consent') : t('ask_owner')}</Button>}
          </p>
        )}
        <div className="consent-card-actions">
          <Button variant="secondary" className="btn-sm" onClick={onReceipt}>{t('view_receipt')}</Button>
          {c.status === 'pending' && canWithdraw && onCancel && <Button variant="secondary" className="btn-sm" onClick={onCancel}>{t('cancel_request')}</Button>}
          {c.status === 'paused' && rights.can_grant && onResume && data.authority_rule !== 'unclear' && <Button className="btn-sm" onClick={onResume}>{t('resume')}</Button>}
          {c.status === 'active' && canWithdraw && <Button variant="danger" className="btn-sm" onClick={onWithdraw}>{t('withdraw_consent')}</Button>}
          {c.status === 'expired' && rights.can_grant && <Button variant="secondary" className="btn-sm">{t('review_renew')}</Button>}
        </div>
      </footer>
    </article>
  )
}

function WithdrawDialog({ c, onClose, onDone }: { c: ConsentRow; onClose: () => void; onDone: (m: { kind: 'success' | 'error' | 'info'; text: string }) => void }) {
  const { t } = useTranslation('consent')
  const lang = useLang()
  const { companyId } = useAuth()
  const [busy, setBusy] = useState(false)
  const [result, setResult] = useState<ConsentRow | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const keep = useRef<HTMLButtonElement>(null)
  const source = c.provider_name || c.source
  useEffect(() => {
    keep.current?.focus()
  }, [])
  const confirm = async () => {
    setBusy(true)
    setErr(null)
    try {
      const r = await post<ConsentRow>(`/api/companies/${companyId}/consents/${c.consent_id}/withdraw`, { confirm: true })
      setResult(r)
      onDone({ kind: 'success', text: t('withdrawn_by', { date: formatDateTime(r.withdrawn_at, lang), name: r.timeline?.withdrawn_by ?? '' }) })
    } catch (e) {
      setErr(e instanceof ApiError && e.status === 403 ? refusal(t, e) : t('withdraw_error'))
    } finally {
      setBusy(false)
    }
  }
  const receipt = result?.withdrawal_receipt
  const rbody = receipt ? ((lang === 'ar' ? receipt.ar : receipt.en) as Record<string, unknown>) : null
  return (
    <Dialog open title={result ? t('chip.withdrawn_on_platform') : t('withdraw_q', { bank: source })} onClose={onClose} labelledBy="withdraw-title">
      {!result ? (
        <>
          <p>{t('withdraw_body', { purposes: t(`purpose.${c.purpose}`) })}</p>
          <ul>
            <li>{t('withdraw_stops')}</li>
            <li>{t('withdraw_keeps')}</li>
            <li>{t('withdraw_drafts')}</li>
          </ul>
          <p className="muted">{t('microcopy')}</p>
          {busy && <p role="status" aria-live="polite">{t('stopping')}</p>}
          {err && <Message kind="error">{err} <Button variant="secondary">{t('contact_support')}</Button></Message>}
          <div className="actions">
            <Button ref={keep} variant="secondary" onClick={onClose}>{t('keep_consent')}</Button>
            <Button variant="danger" onClick={confirm} disabled={busy}>{t('withdraw_consent')}</Button>
          </div>
        </>
      ) : (
        <>
          <p role="status"><ConsentChip status="withdrawn_on_platform" /> {t('withdrawn_by', { date: formatDateTime(result.withdrawn_at, lang), name: result.timeline?.withdrawn_by ?? '' })}</p>
          {result.timeline && <TimelineList timeline={result.timeline} source={source} />}
          {result.timeline && !result.timeline.pulls_stopped_at && <Message kind="warning">{t('withdraw_failed_retrying')}</Message>}
          {rbody && (
            <div className="card">
              <h3 style={{ marginTop: 0 }}>{String(rbody.title)} · <bdi dir="ltr">{receipt?.receipt_number}</bdi></h3>
              <p>{String(rbody.withdrawn_line)}</p>
              <ul>
                {((rbody.effects as string[]) ?? []).map((x) => <li key={x}>{x}</li>)}
              </ul>
              <p className="muted">{String(rbody.not_legal)}</p>
              <p>{String(rbody.how_to_reconsent)}</p>
            </div>
          )}
          <div className="actions">
            <Button onClick={onClose} autoFocus>{t('translation:common.close')}</Button>
          </div>
        </>
      )}
    </Dialog>
  )
}

const DEFAULT_SOURCE: Record<string, string> = { bank_data_open_finance: 'bank', ledger_invoice_authorisation: 'erp', tax_data: 'tax_authority', auditor_specialist_evidence_access: 'erp' }

function GrantDialog({ data, onClose, onDone }: { data: ConsentList; onClose: () => void; onDone: (m: { kind: 'success' | 'info' | 'error'; text: string }) => void }) {
  const { t } = useTranslation('consent')
  const lang = useLang()
  const { companyId } = useAuth()
  const heading = useRef<HTMLHeadingElement>(null)
  const [step, setStep] = useState(1)
  const [type, setType] = useState('ledger_invoice_authorisation')
  const [dataTypes, setDataTypes] = useState<string[]>([])
  const [accounts, setAccounts] = useState('')
  const [provider, setProvider] = useState('')
  const [recipient, setRecipient] = useState('')
  const [purpose, setPurpose] = useState(data.controlled_lists.purposes[0] ?? '')
  const maxMonths = type === 'bank_data_open_finance' ? data.route.max_duration_months_bank : data.route.max_duration_months
  const [expiry, setExpiry] = useState(() => new Date(Date.now() + 180 * 864e5).toISOString().slice(0, 10))
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [idem] = useState(() => `grant-${Date.now()}-${Math.random().toString(36).slice(2)}`)
  const source = DEFAULT_SOURCE[type]
  const allowed = data.controlled_lists.data_types[source] ?? []
  const excluded = allowed.filter((d) => !dataTypes.includes(d))
  const remoteTaxBlocked = type === 'tax_data' && data.rights.is_remote_owner && !data.rights.tax_consent_online
  useEffect(() => {
    heading.current?.focus()
  }, [step])
  const toggle = (d: string) => setDataTypes((xs) => (xs.includes(d) ? xs.filter((x) => x !== d) : [...xs, d]))
  const valid = [true, dataTypes.length > 0 && (source !== 'bank' || accounts.trim().length > 0) && (type !== 'auditor_specialist_evidence_access' || recipient.trim().length > 0), !!purpose && !!expiry, true]
  const submit = async () => {
    setBusy(true)
    setErr(null)
    try {
      const r = await post<ConsentRow & { created: boolean }>(`/api/companies/${companyId}/consents`, {
        consent_type: type,
        source,
        data_types: dataTypes,
        account_ids: accounts.split(/\n|,/).map((x) => x.trim()).filter(Boolean),
        purpose,
        expires_at: `${expiry}T19:59:00`,
        recipient: recipient || null,
        provider_name: provider || null,
        idempotency_key: idem,
      })
      onDone({ kind: r.status === 'pending' ? 'info' : 'success', text: r.status === 'pending' ? `${t('chip.pending')}: ${t('pending_cause')}` : t('valid_until', { date: formatDateTime(r.expires_at, lang) }) })
    } catch (e) {
      setErr(refusal(t, e))
    } finally {
      setBusy(false)
    }
  }
  const titles = [t('step_source'), t('step_scope'), t('step_purpose'), t('step_review')]
  return (
    <Dialog open title={t('choose')} onClose={onClose} labelledBy="grant-title">
      <p className="stepper muted">{t('step', { n: step, total: 4 })}</p>
      <h3 ref={heading} tabIndex={-1}>{titles[step - 1]}</h3>
      {err && <Message kind="error" id="grant-error">{err}</Message>}
      {step === 1 && (
        <>
          <Field label={t('field_type')} id="g-type">
            <select id="g-type" value={type} onChange={(e) => { setType(e.target.value); setDataTypes([]) }}>
              {data.consent_types.map((ct) => (
                <option key={ct} value={ct}>{t(`type.${ct}`)}</option>
              ))}
            </select>
          </Field>
          {type === 'bank_data_open_finance' && <Message kind="info">{t('bank_note')} {t('through_provider')}</Message>}
          {remoteTaxBlocked && <Message kind="warning">{t('remote_tax')}</Message>}
          <Field label={t('field_provider')} id="g-prov">
            <input id="g-prov" dir="auto" value={provider} onChange={(e) => setProvider(e.target.value)} />
          </Field>
        </>
      )}
      {step === 2 && (
        <>
          <fieldset>
            <legend>{t('field_data')}</legend>
            {allowed.map((d) => (
              <label key={d} style={{ display: 'flex', gap: 8, minHeight: 44, alignItems: 'center' }}>
                <input type="checkbox" checked={dataTypes.includes(d)} onChange={() => toggle(d)} /> {t(`dt.${d}`)}
              </label>
            ))}
          </fieldset>
          {source === 'bank' && (
            <Field label={t('field_accounts')} id="g-acc" required>
              <textarea id="g-acc" dir="ltr" rows={2} value={accounts} onChange={(e) => setAccounts(e.target.value)} />
            </Field>
          )}
          {type === 'auditor_specialist_evidence_access' && (
            <Field label={t('field_recipient')} id="g-rec" required>
              <input id="g-rec" dir="ltr" value={recipient} onChange={(e) => setRecipient(e.target.value)} />
            </Field>
          )}
        </>
      )}
      {step === 3 && (
        <>
          <Field label={t('field_purpose')} id="g-purpose" required>
            <select id="g-purpose" value={purpose} onChange={(e) => setPurpose(e.target.value)}>
              {data.controlled_lists.purposes.map((p) => (
                <option key={p} value={p}>{t(`purpose.${p}`)}</option>
              ))}
            </select>
          </Field>
          <Field label={t('field_expiry')} id="g-exp" required hint={`≤ ${maxMonths}`}>
            <input id="g-exp" type="date" value={expiry} onChange={(e) => setExpiry(e.target.value)} />
          </Field>
        </>
      )}
      {step === 4 && (
        <div className="card">
          <p><strong>{t(`type.${type}`)}</strong> · <bdi dir="auto">{provider || source}</bdi></p>
          <p>{t('we_read', { list: dataTypes.map((d) => t(`dt.${d}`)).join(', '), excluded: excluded.map((d) => t(`dt.${d}`)).join(', ') || '-' })}</p>
          <p>{t(`purpose.${purpose}`)}</p>
          <p>{t('valid_until', { date: formatDate(expiry, lang) })}</p>
          <p className="muted">{t('receipt_footer')}</p>
        </div>
      )}
      <div className="actions">
        <Button variant="secondary" onClick={step === 1 ? onClose : () => setStep(step - 1)}>{step === 1 ? t('translation:common.cancel') : t('translation:common.back')}</Button>
        {step < 4 ? (
          <Button onClick={() => setStep(step + 1)} disabled={!valid[step - 1] || remoteTaxBlocked}>{t('translation:common.next')}</Button>
        ) : (
          <Button onClick={submit} disabled={busy || remoteTaxBlocked}>{t('confirm_grant')}</Button>
        )}
      </div>
    </Dialog>
  )
}

/** E4-S3 bank list: all 'Not yet available' in the pilot except fixture banks marked 'Demo'; upload instead. */
function BankSection() {
  const { t } = useTranslation('consent')
  const lang = useLang()
  const nav = useNavigate()
  const { companyId, can } = useAuth()
  const { data } = useLinks(companyId)
  const [saved, setSaved] = useState<string | null>(null)
  if (!data) return null
  const notify = async (bankId: string) => {
    try {
      await post(`/api/companies/${companyId}/links/bank/${bankId}/notify-me`)
      setSaved(bankId)
    } catch {
      /* preference only */
    }
  }
  const anyAvailable = data.banks.some((b) => b.availability === 'available')
  const availableCount = data.banks.filter((b) => b.availability === 'available').length
  const canManage = can('links.manage', companyId) && !data.remote_owner_read_only
  return (
    <Panel title={t('bank_title')} className="consent-bank" actions={can('uploads.manage', companyId) ? <Button variant="secondary" className="btn-sm" onClick={() => nav('/settings?tab=data-links')}><Icon name="upload" size={16} />{t('upload_statements')}</Button> : undefined}>
      <p>{t('bank_empty')}{!anyAvailable && <span className="muted"> {t('bank_nya')}</span>}</p>
      {saved && <Message kind="success">{t('notify_saved')}</Message>}
      <Disclosure className="consent-bank-disclosure" summary={<><Icon name="building" size={16} /> {anyAvailable ? t('banks_summary_some', { n: data.banks.length, m: availableCount }) : t('banks_summary_none', { n: data.banks.length })} <span className="consent-bank-more">· {t('show_banks')}</span></>}>
        <ul className="consent-bank-list">
          {data.banks.map((b) => (
            <li key={b.bank_id}>
              <span className="consent-bank-name">
                <bdi>{lang === 'ar' ? b.name_ar : b.name_en}</bdi>
                <span className="consent-bank-meta">
                  <Chip tone={b.availability === 'available' ? 'ok' : 'neutral'} icon={b.availability === 'available' ? '✓' : '◌'}>{t(`bank_chip.${b.availability}`)}</Chip>
                  {b.demo && <span className="tag">{t('demo')}</span>}
                </span>
              </span>
              {b.availability !== 'available' && (
                <Button variant="secondary" className="btn-sm" onClick={() => notify(b.bank_id)}>
                  {saved === b.bank_id && <Icon name="check" size={16} />}
                  <span>{t('notify_me')}</span>
                  <span className="visually-hidden"> <bdi>{lang === 'ar' ? b.name_ar : b.name_en}</bdi></span>
                </Button>
              )}
            </li>
          ))}
        </ul>
      </Disclosure>
      {!canManage && <p className="muted consent-bank-owner">{t('only_owner_bank')}</p>}
    </Panel>
  )
}
