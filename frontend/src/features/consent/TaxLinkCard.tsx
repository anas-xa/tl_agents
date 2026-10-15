import { useCallback, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useAuth } from '../../app/auth'
import { Button, Chip, Field, Message, Panel, Skeleton } from '../../components/ui'
import { ApiError, get, put } from '../../lib/api'
import { formatDate, formatDateTime } from '../../lib/format'
import { useLang } from './parts'
import type { TaxLinkOut, TaxProfile } from './types'

type Tone = 'neutral' | 'ok' | 'attention' | 'critical' | 'info' | 'draft'
/** The ten tax-link states (E4-S5 §6): icon, badge key, tone. Read-only and side-by-side are view variants. */
const STATE: Record<string, [string, string, Tone]> = {
  not_available: ['◷', 'tax.not_available', 'neutral'],
  not_linked: ['○', 'tax.not_linked', 'neutral'],
  loading: ['⟳', 'tax.reading', 'info'],
  error: ['⚠', 'tax.could_not_read', 'critical'],
  format_unrecognised: ['⚠', 'tax.format', 'critical'],
  consent_withdrawn: ['⏹', 'tax.withdrawn', 'neutral'],
  stale: ['◷', 'tax.out_of_date', 'attention'],
  mismatch: ['⇄', 'tax.mismatch', 'attention'],
  manual_unverified: ['✎', 'tax.manual_unverified', 'draft'],
  active: ['✓', 'tax.from_authority', 'ok'],
}

/** SC5 'Tax authority link' card: adapter OFF in Phase 1; manual entry 'Entered by hand / Unverified'. */
export default function TaxLinkCard() {
  const { t } = useTranslation('consent')
  const lang = useLang()
  const { companyId, can, company } = useAuth()
  const [data, setData] = useState<TaxLinkOut | null>(null)
  const [error, setError] = useState(false)
  const [editing, setEditing] = useState(false)
  const load = useCallback(async () => {
    if (!companyId) return
    try {
      setData(await get<TaxLinkOut>(`/api/companies/${companyId}/tax-link?lang=${lang}`))
      setError(false)
    } catch {
      setError(true)
    }
  }, [companyId, lang])
  useEffect(() => {
    load()
  }, [load])
  if (error) return <Panel title={t('tax.title')} id="tax-link"><Message kind="error">{t('status_load_failed')}</Message></Panel>
  if (!data) return <Panel title={t('tax.title')} id="tax-link"><Skeleton rows={3} /></Panel>
  const [icon, key, tone] = STATE[data.status] ?? STATE.not_available
  const canEnter = can('taxprofile.edit', companyId)
  const isDelegate = !!company?.roles.includes('delegate')
  const lastRead = data.last_good_read_at ? formatDateTime(data.last_good_read_at, lang) : '-'
  const old = ['error', 'format_unrecognised', 'consent_withdrawn', 'stale'].includes(data.status)
  const vat = data.profiles.find((p) => p.tax_type === 'vat')
  const ct = data.profiles.find((p) => p.tax_type === 'corporate_tax')
  return (
    <Panel title={t('tax.title')} id="tax-link">
      <p>
        <Chip tone={tone} icon={icon}>{t(key)}</Chip>
        {data.demo_data && <span className="tag"> {t('demo')}</span>}
      </p>
      <div aria-busy={data.status === 'loading'}>
        {data.status === 'not_available' && <p>{t('tax.not_available_body')}</p>}
        {data.status === 'manual_unverified' && <p>{t('tax.not_available_body')}</p>}
        {data.status === 'not_linked' && <p>{t('tax.not_linked_body')}</p>}
        {data.status === 'loading' && <p role="status">{t('tax.reading_body')}</p>}
        {data.status === 'error' && <Message kind="error">{t('tax.error_body', { cause: data.error_cause === 'consent_expired' ? t('tax.cause_consent') : t('tax.cause_authority'), date: lastRead })}</Message>}
        {data.status === 'format_unrecognised' && <Message kind="warning">{t('tax.format_body', { date: lastRead })}</Message>}
        {data.status === 'consent_withdrawn' && <p>{data.last_good_read_at ? t('tax.withdrawn_values', { date: lastRead }) : t('tax.withdrawn_body')}</p>}
        {data.status === 'stale' && <p>{t('tax.may_not_match', { date: lastRead })}</p>}
        {data.status === 'mismatch' && <Message kind="warning">{t('tax.mismatch_body', { a: '-', b: '-' })}</Message>}
      </div>
      <ValueRows vat={vat} ct={ct} old={old} lang={lang} />
      <p className="muted">{t('tax.scope_note')} {t('tax.never_credentials')}</p>
      {data.remote_owner && (
        <Message kind="info">
          {t('remote_tax')} <span className="muted">({t('remote_tax_status')})</span>
        </Message>
      )}
      {isDelegate && !canEnter && <p className="muted">{t('tax.read_only_note')}</p>}
      {isDelegate && <p className="muted">{t('q72_delegate')}</p>}
      <div className="actions">
        {!isDelegate && !data.remote_owner && (
          <>
            <Button aria-disabled={!data.switch_on} aria-describedby="start-link-reason" onClick={(e) => !data.switch_on && e.preventDefault()} variant="secondary">
              {t('tax.start_link')}
            </Button>
            {!data.switch_on && <span id="start-link-reason" className="muted">{t('tax.not_available_body')}</span>}
          </>
        )}
        {data.status === 'error' && (
          <>
            <Button variant="secondary" onClick={load}>{t('tax.try_again')}</Button>
            <Button variant="secondary">{t('contact_support')}</Button>
          </>
        )}
        {data.status === 'format_unrecognised' && <Button variant="secondary">{t('contact_support')}</Button>}
        {data.status === 'stale' && data.switch_on && <Button variant="secondary" onClick={load}>{t('tax.read_again')}</Button>}
        {data.status === 'consent_withdrawn' && data.switch_on && !isDelegate && !data.remote_owner && <Button variant="secondary">{t('tax.give_again')}</Button>}
        {canEnter && <Button onClick={() => setEditing((x) => !x)} aria-expanded={editing}>{t('tax.enter_manually')}</Button>}
      </div>
      {editing && canEnter && companyId && <ManualEntry companyId={companyId} initial={vat} onSaved={() => { setEditing(false); load() }} />}
    </Panel>
  )
}

function ValueRows({ vat, ct, old, lang }: { vat?: TaxProfile; ct?: TaxProfile; old: boolean; lang: string }) {
  const { t } = useTranslation('consent')
  const p = vat ?? ct
  const source = (x?: TaxProfile) =>
    x ? (
      <span className="muted" style={{ fontSize: '.85rem' }}>
        {' '}
        · {x.source === 'fta_live' ? t('tax.from_authority') : t('tax.by_hand')} · <Chip tone={x.source === 'fta_live' ? 'ok' : 'draft'} icon={x.source === 'fta_live' ? '✓' : '✎'}>{x.source === 'fta_live' ? t('tax.verified_source') : t('tax.unverified')}</Chip>{' '}
        {x.source !== 'fta_live' && t('tax.not_confirmed')} · {t('tax.as_provided', { date: formatDateTime(x.as_of, lang) })}
        {old && <> · {t('tax.old_value')}</>}
        {x.is_demo && <span className="tag"> {t('demo')}</span>}
      </span>
    ) : null
  const val = (v: string | null | undefined) => (v ? <bdi dir="ltr" className="ident">{v}</bdi> : <span className="muted">— {t('tax.no_value')}</span>)
  const nextDue = vat?.due_dates?.[0]
  const sbr = ct?.small_business_relief?.[0]
  const manualStyle = p && p.source !== 'fta_live' ? { border: '1px dashed var(--border)', padding: 8, borderRadius: 8 } : undefined
  return (
    <dl className="kv" style={manualStyle}>
      <dt>{t('tax.row.vat_trn')}</dt>
      <dd>{val(vat?.trn)}{source(vat)}</dd>
      <dt>{t('tax.row.ct_trn')}</dt>
      <dd>{val(ct?.trn)}{source(ct)}</dd>
      <dt>{t('tax.row.registration')}</dt>
      <dd>{vat?.registration_status ? t(`tax.reg.${vat.registration_status}`, { defaultValue: vat.registration_status }) : val(null)}</dd>
      <dt>{t('tax.row.filing')}</dt>
      <dd>{vat?.filing_status ?? val(null)}</dd>
      <dt>{t('tax.row.frequency')}</dt>
      <dd>{vat?.filing_frequency ? t(`tax.freq.${vat.filing_frequency}`) : val(null)}</dd>
      <dt>{t('tax.row.due')}</dt>
      <dd>
        {nextDue ? (
          <>
            {formatDate(nextDue.due_date, lang)} <span className="muted">({t(`tax.due_source.${nextDue.source}`)}{p && p.source !== 'fta_live' ? `; ${t('tax.based_unverified')}` : ''})</span>
          </>
        ) : (
          val(null)
        )}
      </dd>
      <dt>{t('tax.row.sbr')}</dt>
      <dd>{sbr ? (sbr.indicator === 'unknown' ? t('tax.sbr_unknown') : sbr.indicator) : val(null)}</dd>
    </dl>
  )
}

function ManualEntry({ companyId, initial, onSaved }: { companyId: string; initial?: TaxProfile; onSaved: () => void }) {
  const { t } = useTranslation('consent')
  const [form, setForm] = useState({ tax_type: 'vat', trn: initial?.trn ?? '', registration_status: initial?.registration_status ?? 'registered', filing_frequency: initial?.filing_frequency ?? 'quarterly', tax_period_start: initial?.tax_period_start ?? '', tax_period_end: initial?.tax_period_end ?? '' })
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const set = (k: string, v: string) => setForm((f) => ({ ...f, [k]: v }))
  const save = async (e: React.FormEvent) => {
    e.preventDefault()
    setBusy(true)
    setErr(null)
    try {
      await put(`/api/companies/${companyId}/tax-profile`, { ...form, tax_period_start: form.tax_period_start || null, tax_period_end: form.tax_period_end || null })
      onSaved()
    } catch (x) {
      setErr(x instanceof ApiError ? x.message : t('save_failed'))
    } finally {
      setBusy(false)
    }
  }
  return (
    <form onSubmit={save} className="card" style={{ marginTop: 12, borderStyle: 'dashed' }}>
      {err && <Message kind="error" id="tax-entry-error">{err}</Message>}
      <Field label={t('tax.field_type')} id="tx-type">
        <select id="tx-type" value={form.tax_type} onChange={(e) => set('tax_type', e.target.value)}>
          <option value="vat">{t('tax.vat')}</option>
          <option value="corporate_tax">{t('tax.ct')}</option>
        </select>
      </Field>
      <Field label={t('tax.field_trn')} id="tx-trn">
        <input id="tx-trn" dir="ltr" inputMode="numeric" value={form.trn} onChange={(e) => set('trn', e.target.value)} aria-describedby={err ? 'tax-entry-error' : undefined} />
      </Field>
      <Field label={t('tax.field_status')} id="tx-reg">
        <select id="tx-reg" value={form.registration_status} onChange={(e) => set('registration_status', e.target.value)}>
          {['registered', 'not_registered', 'pending', 'unknown'].map((v) => (
            <option key={v} value={v}>{t(`tax.reg.${v}`)}</option>
          ))}
        </select>
      </Field>
      <Field label={t('tax.row.frequency')} id="tx-freq">
        <select id="tx-freq" value={form.filing_frequency} onChange={(e) => set('filing_frequency', e.target.value)}>
          {['monthly', 'quarterly', 'annual'].map((v) => (
            <option key={v} value={v}>{t(`tax.freq.${v}`)}</option>
          ))}
        </select>
      </Field>
      <Field label={t('tax.field_period_start')} id="tx-ps">
        <input id="tx-ps" type="date" value={form.tax_period_start} onChange={(e) => set('tax_period_start', e.target.value)} />
      </Field>
      <Field label={t('tax.field_period_end')} id="tx-pe">
        <input id="tx-pe" type="date" value={form.tax_period_end} onChange={(e) => set('tax_period_end', e.target.value)} />
      </Field>
      <p className="muted">{t('tax.by_hand')} · {t('tax.unverified')}</p>
      <Button type="submit" disabled={busy}>{t('tax.save')}</Button>
    </form>
  )
}
