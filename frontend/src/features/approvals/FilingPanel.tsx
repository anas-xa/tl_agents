import { useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'
import { useAuth } from '../../app/auth'
import { Icon } from '../../components/Icon'
import { Button, Chip, Disclosure, Field, Message } from '../../components/ui'
import { ApiError, patch, post } from '../../lib/api'
import { formatAED, formatDate } from '../../lib/format'
import { refusalText, useLang, when } from './parts'
import type { RequestDetail } from './types'

const RECEIPT_TYPES = ['application/pdf', 'image/png', 'image/jpeg']

/** E6-S3 manual filing path (Phase 1 live): download -> file on EmaraTax -> record here. No Submit control. */
export default function FilingPanel({ data, reload }: { data: RequestDetail; reload: () => Promise<void> }) {
  const { t } = useTranslation('approvals')
  const lang = useLang()
  const { companyId } = useAuth()
  const base = `/api/companies/${companyId}/approvals`
  const f = data.filing
  const netKey = data.return_type === 'ct' ? 'tax' : 'net_vat'
  const today = new Date(Date.now() + 4 * 3600 * 1000).toISOString().slice(0, 10)
  const [filedDate, setFiledDate] = useState('')
  const [ref, setRef] = useState('')
  const [net, setNet] = useState('')
  const [receipt, setReceipt] = useState<File | null>(null)
  const [selfFiled, setSelfFiled] = useState(false)
  const [errors, setErrors] = useState<Record<string, string>>({})
  const [saving, setSaving] = useState(false)
  const [blocked, setBlocked] = useState<{ cause: string } | null>(null)
  const [msg, setMsg] = useState<{ kind: 'success' | 'error' | 'info'; text: string } | null>(null)
  const [editing, setEditing] = useState(false)
  const summaryRef = useRef<HTMLDivElement>(null)
  const bannerRef = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (Object.keys(errors).length) summaryRef.current?.focus()
  }, [errors])

  const isDelegate = data.role === 'delegate'
  const mayRecord = !isDelegate || data.phase_b_on
  const approvedOnce = data.status === 'decided' && !!data.approved_by
  const owner = data.entitled_owner ?? ''
  const stepN = data.status === 'open' ? 4 : 2

  const validate = (): Record<string, string> => {
    const e: Record<string, string> = {}
    if (!filedDate || filedDate > today) e.filed_date = t('filed_date_hint')
    if (ref && !/^[A-Za-z0-9]+$/.test(ref.trim())) e.authority_reference = t('reference_hint')
    if (!selfFiled) e.self_filed_confirmed = t('self_filed_required')
    if (receipt && (receipt.size > 10 * 1024 * 1024 || !RECEIPT_TYPES.includes(receipt.type))) e.receipt = t('receipt_hint')
    return e
  }

  const record = async (outcome: 'filed' | 'authority_unavailable') => {
    setBlocked(null)
    if (outcome === 'filed') {
      const e = validate()
      setErrors(e)
      if (Object.keys(e).length) return
    }
    setSaving(true)
    try {
      await post(`${base}/${data.request_id}/filing`, {
        outcome,
        filed_date: outcome === 'filed' ? filedDate : null,
        authority_reference: ref.trim() || null,
        figures_as_filed: net ? { [netKey]: Math.round(Number(net) * 100) } : null,
        self_filed_confirmed: selfFiled,
        receipt: receipt ? { name: receipt.name, size_bytes: receipt.size, content_type: receipt.type } : null,
      })
      setMsg({ kind: 'success', text: t('recorded_declared') })
      await reload()
      setTimeout(() => bannerRef.current?.focus(), 0)
    } catch (e) {
      if (e instanceof ApiError && e.code === 'GATE_BLOCKED') setBlocked({ cause: String(e.details?.cause ?? 'approval_missing') })
      else if (e instanceof ApiError && e.code === 'FORM_INVALID') setErrors((e.details?.fields as Record<string, string>) ?? {})
      else if (e instanceof ApiError && e.code === 'NO_FILING_RIGHT') setMsg({ kind: 'info', text: t('no_filing_right', { owner }) })
      else setMsg({ kind: 'error', text: t('record_save_failed') })
    } finally {
      setSaving(false)
    }
  }

  const saveEdit = async () => {
    if (!f.record_id) return
    setSaving(true)
    try {
      await patch(`${base}/filing/${f.record_id}`, { authority_reference: ref.trim() || null, figures_as_filed: net ? { [netKey]: Math.round(Number(net) * 100) } : null })
      setEditing(false)
      await reload()
    } catch (e) {
      setMsg({ kind: 'error', text: e instanceof ApiError && e.code === 'FORM_INVALID' ? t('fix_fields') : t('record_save_failed') })
    } finally {
      setSaving(false)
    }
  }

  const download = async () => {
    try {
      const doc = await post<Record<string, unknown>>(`${base}/${data.request_id}/release?lang=${lang}`)
      const blob = new Blob([JSON.stringify(doc, null, 2)], { type: 'application/json' })
      const a = document.createElement('a')
      a.href = URL.createObjectURL(blob)
      a.download = `prepared-return-draft-${data.return_type}-${data.period_id}.json`
      a.click()
      URL.revokeObjectURL(a.href)
    } catch (e) {
      if (e instanceof ApiError && e.code === 'GATE_BLOCKED') setBlocked({ cause: String(e.details?.cause ?? 'approval_missing') })
      else setMsg({ kind: 'error', text: refusalText(t, e) })
    }
  }

  const banner = () => {
    if (f.state === 'filed_outside_self_declared')
      return <Message kind="info">{t('filed_self_declared', { name: f.recorded_by ?? '', when: f.filed_date ? formatDate(f.filed_date, lang) : '' })}</Message>
    if (f.state === 'filed_outside_values_differ')
      return (
        <Message kind="warning">
          <strong>{t('values_differ_title')}</strong> {t('values_differ_body')}
        </Message>
      )
    if (f.state === 'authority_unavailable') return <Message kind="info">{t('authority_unavailable', { date: data.due_date ? formatDate(data.due_date, lang) : '', source: data.due_date_source ?? '' })}</Message>
    return (
      <Message kind="info">
        {t('not_filed')} {t('not_available_here')}
      </Message>
    )
  }

  return (
    <section className="ret-step ret-filing" id="filing" aria-labelledby="filing-title">
      <div className="ret-step-head">
        <span className="ret-step-num" aria-hidden="true">{stepN}</span>
        <div>
          <h2 id="filing-title"><span className="visually-hidden">{t('step_n', { n: stepN })}: </span>{t('filing_title')}</h2>
          <p>{t('step_filing_desc')}</p>
        </div>
      </div>
      <div className="ret-step-body">
      <div ref={bannerRef} tabIndex={-1} aria-live="polite">
        <div className="ret-filing-state">
          <Chip tone={f.state === 'not_filed' ? 'neutral' : 'info'}>{t(`filed_state_${f.state}`)}</Chip>
          {f.state !== 'not_filed' && <span className="hint">{t('not_verified_authority')}</span>}
        </div>
        {banner()}
        {msg && <Message kind={msg.kind}>{msg.text}</Message>}
        {blocked && (
          <Message kind="error">
            {t('blocked', { cause: t(`cause_${blocked.cause}`) })} {t('blocked_next', { step: t(`next_${blocked.cause}`) })}
          </Message>
        )}
      </div>
      <dl className="record">
        <dt>{t('approved_by')}</dt>
        <dd>{data.approved_by ? <bdi>{data.approved_by.approver_name}</bdi> : '—'}</dd>
        <dt>{t('submitted_by')}</dt>
        <dd>
          {f.submitted_by ? <bdi>{f.submitted_by}</bdi> : t('not_submitted')}
          {f.acting_under_grant && <div className="hint">{t('recorded_under_grant', { delegate: f.acting_under_grant.delegate_name, owner: f.acting_under_grant.granting_owner_name, date: formatDate(f.acting_under_grant.grant_date, lang) })}</div>}
        </dd>
        {f.authority_reference && (
          <>
            <dt>{t('reference')}</dt>
            <dd><bdi dir="ltr">{f.authority_reference}</bdi></dd>
          </>
        )}
        {f.receipt && (
          <>
            <dt>{t('receipt')}</dt>
            <dd>{f.receipt.name} <span className="hint">· {t('receipt_hint')}</span></dd>
          </>
        )}
      </dl>
      {f.edited && <p className="hint">{t('edited', { date: when(f.edited.at, lang), name: f.edited.by })}</p>}
      <p className="hint">{t('read_back')}</p>
      {f.differences && f.differences.length > 0 && (
        <>
          <div className="table-wrap">
            <table className="table-compact ret-figures">
              <thead>
                <tr><th scope="col">{t('differ_field')}</th><th scope="col" className="num">{t('differ_yours')}</th><th scope="col" className="num">{t('differ_ours')}</th></tr>
              </thead>
              <tbody>
                {f.differences.map((d) => (
                  <tr key={d.key}>
                    <th scope="row">{d.term?.[lang] ?? d.key}</th>
                    <td className="num"><bdi dir="ltr">{formatAED(d.declared_fils, lang)}</bdi></td>
                    <td className="num"><bdi dir="ltr">{formatAED(d.prepared_fils, lang)}</bdi></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="actions">
            <a className="btn btn-secondary btn-sm" href="#figures">{t('review_difference')}</a>
            <Link className="btn btn-secondary btn-sm" to="/help">{t('ask_specialist')}</Link>
            <Button variant="secondary" className="btn-sm" onClick={() => setMsg({ kind: 'info', text: t('recorded_declared') })}>{t('keep_declared')}</Button>
          </div>
        </>
      )}
      {f.state !== 'not_filed' && f.record_id && mayRecord && (
        <div className="actions">
          <Button variant="secondary" className="btn-sm" onClick={() => setEditing((v) => !v)} aria-expanded={editing}>{t('edit')}</Button>
        </div>
      )}
      {editing && (
        <div className="form">
          <Field label={t('reference')} id="ed-ref" hint={t('reference_hint')}>
            <input id="ed-ref" dir="ltr" value={ref} onChange={(e) => setRef(e.target.value)} />
          </Field>
          <Field label={t('figures_as_filed')} id="ed-net">
            <input id="ed-net" type="number" step="0.01" dir="ltr" value={net} onChange={(e) => setNet(e.target.value)} />
          </Field>
          <div className="ret-form-actions">
            <Button onClick={saveEdit} disabled={saving}>{saving ? t('saving') : t('save')}</Button>
          </div>
        </div>
      )}

      {f.state === 'not_filed' && (
        <>
          <h3>{t('manual_heading')}</h3>
          <ol className="ret-filing-steps">
            <li>
              <span>{t('step_download')} <Chip tone="draft">{t('download_label')}</Chip></span>
              <Button variant="secondary" className="btn-sm" onClick={download} disabled={!approvedOnce || !mayRecord}>
                <Icon name="download" size={16} />
                {t('download')}
              </Button>
            </li>
            <li><span>{t('step_open')}</span></li>
            <li><span>{t('step_record')}</span></li>
          </ol>
          {!mayRecord && (
            <Message kind="info">
              {t('no_filing_right', { owner })}{' '}
              {data.status === 'open' && <Button variant="secondary" className="btn-sm" onClick={() => post(`${base}/${data.request_id}/remind`).then(() => setMsg({ kind: 'success', text: t('owner_reminded') })).catch((e) => setMsg({ kind: 'info', text: refusalText(t, e) }))}>{t('request_approval')}</Button>}
            </Message>
          )}
          {mayRecord && approvedOnce && (
            <form className="form" noValidate onSubmit={(e) => { e.preventDefault(); record('filed') }}>
              {Object.keys(errors).length > 0 && (
                <div ref={summaryRef} tabIndex={-1} role="alert" className="message message-error">
                  <strong>{t('fix_fields')}</strong>
                  <ul>
                    {Object.entries(errors).map(([k, v]) => (
                      <li key={k}><a href={`#fl-${k}`}>{v}</a></li>
                    ))}
                  </ul>
                </div>
              )}
              <div className="ret-form-grid">
                <Field label={t('filed_date')} id="fl-filed_date" required hint={t('filed_date_hint')}>
                  <input id="fl-filed_date" type="date" max={today} value={filedDate} onChange={(e) => setFiledDate(e.target.value)} aria-invalid={!!errors.filed_date} />
                </Field>
                <Field label={t('reference')} id="fl-authority_reference" hint={t('reference_hint')}>
                  <input id="fl-authority_reference" dir="ltr" value={ref} onChange={(e) => setRef(e.target.value)} aria-invalid={!!errors.authority_reference} />
                </Field>
                <Field label={t('figures_as_filed')} id="fl-figures">
                  <input id="fl-figures" type="number" step="0.01" dir="ltr" value={net} onChange={(e) => setNet(e.target.value)} />
                </Field>
                <Field label={t('receipt')} id="fl-receipt" hint={t('receipt_hint')}>
                  <input id="fl-receipt" type="file" accept=".pdf,.png,.jpg,.jpeg" onChange={(e) => setReceipt(e.target.files?.[0] ?? null)} aria-invalid={!!errors.receipt} />
                </Field>
              </div>
              <label className="ret-confirm" id="fl-self_filed_confirmed">
                <input type="checkbox" checked={selfFiled} onChange={(e) => setSelfFiled(e.target.checked)} /> <span>{t('self_filed')}</span>
              </label>
              <div className="ret-form-actions">
                <Button type="submit" disabled={saving}>{saving ? t('saving') : t('record_filed')}</Button>
                <Button type="button" variant="secondary" disabled={saving} onClick={() => record('authority_unavailable')}>{t('record_unavailable')}</Button>
              </div>
            </form>
          )}
        </>
      )}

      <Disclosure summary={t('fixtures_title')} className="ret-fixtures">
        {data.fixtures.map((x) => (
          <div key={x.state} className="fixture">
            <Chip tone="info">{t('demo_data')}</Chip> <strong>{x.label}</strong>
            <p>{x.banner}</p>
            {x.caution && <p className="hint">{x.caution}</p>}
          </div>
        ))}
      </Disclosure>
      </div>
    </section>
  )
}
