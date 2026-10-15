import { useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'
import { useAuth } from '../../app/auth'
import { Button, Chip, Field, Message, Panel, Table } from '../../components/ui'
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
    <Panel title={t('filing_title')} id="filing">
      <div ref={bannerRef} tabIndex={-1} aria-live="polite">
        <p>
          <Chip tone={f.state === 'not_filed' ? 'neutral' : 'info'}>{t(`filed_state_${f.state}`)}</Chip>{' '}
          {f.state !== 'not_filed' && <span className="hint">{t('not_verified_authority')}</span>}
        </p>
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
      </dl>
      {f.authority_reference && (
        <p>
          {t('reference')}: <bdi dir="ltr">{f.authority_reference}</bdi>
        </p>
      )}
      {f.receipt && <p className="hint">{f.receipt.name} · {t('receipt_hint')}</p>}
      {f.edited && <p className="hint">{t('edited', { date: when(f.edited.at, lang), name: f.edited.by })}</p>}
      <p className="hint">{t('read_back')}</p>
      {f.differences && f.differences.length > 0 && (
        <>
          <Table headers={[t('differ_field'), t('differ_yours'), t('differ_ours')]}>
            {f.differences.map((d) => (
              <tr key={d.key}>
                <th scope="row">{d.term?.[lang] ?? d.key}</th>
                <td><bdi>{formatAED(d.declared_fils, lang)}</bdi></td>
                <td><bdi>{formatAED(d.prepared_fils, lang)}</bdi></td>
              </tr>
            ))}
          </Table>
          <p>
            <a className="btn btn-secondary" href="#figures">{t('review_difference')}</a>{' '}
            <Link className="btn btn-secondary" to="/help">{t('ask_specialist')}</Link>{' '}
            <Button variant="secondary" onClick={() => setMsg({ kind: 'info', text: t('recorded_declared') })}>{t('keep_declared')}</Button>
          </p>
        </>
      )}
      {f.state !== 'not_filed' && f.record_id && mayRecord && (
        <p>
          <Button variant="secondary" onClick={() => setEditing((v) => !v)}>{t('edit')}</Button>
        </p>
      )}
      {editing && (
        <div className="form">
          <Field label={t('reference')} id="ed-ref" hint={t('reference_hint')}>
            <input id="ed-ref" dir="ltr" value={ref} onChange={(e) => setRef(e.target.value)} />
          </Field>
          <Field label={t('figures_as_filed')} id="ed-net">
            <input id="ed-net" type="number" step="0.01" dir="ltr" value={net} onChange={(e) => setNet(e.target.value)} />
          </Field>
          <Button onClick={saveEdit} disabled={saving}>{saving ? t('saving') : t('save')}</Button>
        </div>
      )}

      {f.state === 'not_filed' && (
        <>
          <h3>{t('manual_heading')}</h3>
          <ol className="steps">
            <li>
              {t('step_download')} <Chip tone="draft">{t('download_label')}</Chip>{' '}
              <Button variant="secondary" onClick={download} disabled={!approvedOnce || !mayRecord}>{t('download')}</Button>
            </li>
            <li>{t('step_open')}</li>
            <li>{t('step_record')}</li>
          </ol>
          {!mayRecord && (
            <Message kind="info">
              {t('no_filing_right', { owner })}{' '}
              {data.status === 'open' && <Button variant="secondary" onClick={() => post(`${base}/${data.request_id}/remind`).then(() => setMsg({ kind: 'success', text: t('owner_reminded') })).catch((e) => setMsg({ kind: 'info', text: refusalText(t, e) }))}>{t('request_approval')}</Button>}
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
              <label className="check" id="fl-self_filed_confirmed">
                <input type="checkbox" checked={selfFiled} onChange={(e) => setSelfFiled(e.target.checked)} /> {t('self_filed')}
              </label>
              <div>
                <Button type="submit" disabled={saving}>{saving ? t('saving') : t('record_filed')}</Button>{' '}
                <Button type="button" variant="secondary" disabled={saving} onClick={() => record('authority_unavailable')}>{t('record_unavailable')}</Button>
              </div>
            </form>
          )}
        </>
      )}

      <details className="fixtures">
        <summary>{t('fixtures_title')}</summary>
        {data.fixtures.map((x) => (
          <div key={x.state} className="fixture">
            <Chip tone="info">{t('demo_data')}</Chip> <strong>{x.label}</strong>
            <p>{x.banner}</p>
            {x.caution && <p className="hint">{x.caution}</p>}
          </div>
        ))}
      </details>
    </Panel>
  )
}
