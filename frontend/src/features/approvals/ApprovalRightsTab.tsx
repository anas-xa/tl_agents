import { useCallback, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useAuth } from '../../app/auth'
import { Button, Chip, Dialog, Empty, Field, Message, Panel, Skeleton, Table } from '../../components/ui'
import { ApiError, get, post } from '../../lib/api'
import { formatDate, formatDateTime, iso } from '../../lib/format'
import { useLang } from './parts'
import type { Grant, GrantsResponse } from './types'
import '../settings/settings.css'

const FIXED = ['NO_OWNER_ROLE', 'NOT_OWNER_DELEGATE', 'STALE_DATA', 'REAUTH_FAILED']

/** SC11 'Approval rights' tab (E6-S2): Phase B delegate approval grants, locked while switched off. */
export default function ApprovalRightsTab() {
  const { t } = useTranslation('approvals')
  const lang = useLang()
  const { companyId, company } = useAuth()
  const [data, setData] = useState<GrantsResponse | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [refusal, setRefusal] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [form, setForm] = useState({ delegate_uuid: '', tax: 'vat', scope_option: 'single_return', period_id: '', start_date: '', end_date: '', max_amount: '' })
  const [confirm, setConfirm] = useState(false)
  const [revoking, setRevoking] = useState<Grant | null>(null)
  const [saving, setSaving] = useState(false)
  const companyName = company ? (lang === 'ar' ? company.trade_name_ar : company.trade_name_en) : ''

  const load = useCallback(async () => {
    if (!companyId) return
    try {
      const d = await get<GrantsResponse>(`/api/companies/${companyId}/delegate-grants`)
      setData(d)
      setError(null)
      if (d.defaults) setForm((f) => ({ ...f, start_date: f.start_date || d.defaults!.start_date, end_date: f.end_date || d.defaults!.end_date, scope_option: d.defaults!.scope_option }))
    } catch (e) {
      setError(e instanceof ApiError && FIXED.includes(e.code) ? `${t(`ref_${e.code}`)} ${t('reference_id', { ref: e.reference })}` : t('generic_error'))
    }
  }, [companyId, t])
  useEffect(() => {
    load()
  }, [load])

  if (error) return <Message kind="error">{error}</Message>
  if (!data)
    return (
      <div aria-live="polite">
        <p>{t('loading')}</p>
        <Skeleton rows={3} />
      </div>
    )

  const refuse = (e: unknown) => {
    const code = e instanceof ApiError ? e.code : ''
    const ref = e instanceof ApiError && e.reference ? ` ${t('reference_id', { ref: e.reference })}` : ''
    if (FIXED.includes(code)) return setRefusal(t(`ref_${code}`) + ref)
    if (code === 'DATES_INVALID') return setRefusal(t('dates_invalid'))
    if (code === 'RIGHT_SWITCHED_OFF') return setRefusal(t('rights_off_owner'))
    setRefusal((e instanceof ApiError && e.status === 422 ? e.message : t('generic_error')) + ref)
  }

  const chip = (code: string, end?: string | null) => {
    if (code === 'active') return <Chip tone="ok">{t('chip_active', { date: end ? formatDate(end, lang) : '' })}</Chip>
    if (code === 'suspended') return <Chip tone="attention">{t('chip_suspended')}</Chip>
    if (code === 'expired') return <Chip tone="neutral">{t('chip_expired')}</Chip>
    if (code === 'revoked') return <Chip tone="neutral">{t('chip_revoked')}</Chip>
    return <Chip tone="neutral">{t('chip_no_right')}</Chip>
  }

  // Delegate: read-only 'My rights'
  if (data.role === 'delegate') {
    return (
      <Panel title={t('my_rights', { company: companyName })} id="my-rights">
        {data.locked ? (
          <Message kind="info">{t('phase_b_off')}</Message>
        ) : data.grants.length === 0 ? (
          <p>{t('can_prepare_view')}</p>
        ) : (
          <ul className="card-list">
            {data.grants.map((g) => (
              <li key={g.grant_id} className="card">
                {chip(g.status, g.end_date)} <bdi dir="ltr">{g.grant_id}</bdi> · {formatDate(g.start_date, lang)} – {formatDate(g.end_date, lang)}
                {g.status === 'suspended' && <p>{t('suspended_line', { company: companyName })}</p>}
                {g.status === 'expired' && <p>{t('expired_line', { date: formatDate(g.end_date, lang) })}</p>}
              </li>
            ))}
          </ul>
        )}
      </Panel>
    )
  }

  const stale = data.det_data.stale
  const locked = data.locked || stale
  const selected = data.delegates.find((d) => d.identity_uuid === form.delegate_uuid)
  const taxLabel = form.tax === 'ct' ? t('ct') : t('vat')
  const summary = form.max_amount
    ? t('grant_summary', { name: selected?.name ?? '', tax: taxLabel, company: companyName, amount: form.max_amount, from: form.start_date && formatDate(form.start_date, lang), to: form.end_date && formatDate(form.end_date, lang) })
    : t('grant_summary_nolimit', { name: selected?.name ?? '', tax: taxLabel, company: companyName, from: form.start_date && formatDate(form.start_date, lang), to: form.end_date && formatDate(form.end_date, lang) })

  const create = async () => {
    setSaving(true)
    setRefusal(null)
    try {
      await post(`/api/companies/${companyId}/delegate-grants`, { delegate_uuid: form.delegate_uuid, tax_types: [form.tax], scope_option: form.scope_option, period_id: form.scope_option === 'single_return' ? form.period_id : null, start_date: form.start_date, end_date: form.end_date, max_amount_fils: form.max_amount ? Math.round(Number(form.max_amount) * 100) : null, uaepass: 'confirmed' })
      setConfirm(false)
      await load()
    } catch (e) {
      setConfirm(false)
      refuse(e)
    } finally {
      setSaving(false)
    }
  }

  const revoke = async () => {
    if (!revoking) return
    try {
      await post(`/api/companies/${companyId}/delegate-grants/${revoking.grant_id}/revoke`)
      setNotice(t('revoked', { name: revoking.delegate_name ?? '' }))
      setRevoking(null)
      await load()
    } catch (e) {
      setRevoking(null)
      refuse(e)
    }
  }

  return (
    <Panel title={t('rights_title')} id="approval-rights">
      {data.locked && (
        <Message kind="info">
          <Chip tone="neutral" icon="⊘">{t('rights_locked')}</Chip> {t('rights_off_owner')}
        </Message>
      )}
      {stale && (
        <Message kind="warning">
          {t('stale_data', { when: data.det_data.refreshed_at ? formatDateTime(data.det_data.refreshed_at, lang) : '' })} <Button variant="secondary" onClick={load}>{t('retry')}</Button>
        </Message>
      )}
      {refusal && <Message kind="error">{refusal}</Message>}
      {notice && <Message kind="success">{notice}</Message>}
      {data.delegates.length === 0 ? (
        <Empty title={t('no_delegates')} />
      ) : (
        <ul className="set-people set-people-flat" aria-label={t('delegate')}>
          {data.delegates.map((d) => (
            <li key={d.identity_uuid} className="set-person">
              <span className="set-avatar is-delegate" aria-hidden="true">{(d.name ?? '?').trim().charAt(0).toUpperCase()}</span>
              <div className="set-person-main">
                <div className="set-person-name"><strong><bdi>{d.name ?? '—'}</bdi></strong></div>
                {d.chip === 'no_approval_right' && <div className="set-person-meta">{t('can_prepare_view')}</div>}
              </div>
              <div className="set-person-actions">{chip(d.chip, d.end_date)}</div>
            </li>
          ))}
        </ul>
      )}
      <h3 className="set-rights-sub">{t('give_right')}</h3>
      <form className="form set-grant-form" onSubmit={(e) => { e.preventDefault(); if (form.end_date <= form.start_date) setRefusal(t('dates_invalid')); else setConfirm(true) }}>
        <fieldset disabled={locked} aria-describedby={locked ? 'rights-locked-reason' : undefined}>
          <Field label={t('delegate')} id="gr-delegate" required>
            <select id="gr-delegate" value={form.delegate_uuid} onChange={(e) => setForm({ ...form, delegate_uuid: e.target.value })}>
              <option value="" />
              {data.delegates.map((d) => (
                <option key={d.identity_uuid} value={d.identity_uuid}>{d.name ?? d.identity_uuid}</option>
              ))}
            </select>
          </Field>
          <Field label={t('tax_type')} id="gr-tax">
            <select id="gr-tax" value={form.tax} onChange={(e) => setForm({ ...form, tax: e.target.value })}>
              <option value="vat">{t('vat')}</option>
              <option value="ct">{t('ct')}</option>
            </select>
          </Field>
          <Field label={t('scope')} id="gr-scope">
            <select id="gr-scope" value={form.scope_option} onChange={(e) => setForm({ ...form, scope_option: e.target.value })}>
              <option value="single_return">{t('scope_single')}</option>
              <option value="time_period">{t('scope_period')}</option>
            </select>
          </Field>
          {form.scope_option === 'single_return' && (
            <Field label={t('tax_period')} id="gr-period" required>
              <input id="gr-period" dir="ltr" value={form.period_id} placeholder="2026-Q3" onChange={(e) => setForm({ ...form, period_id: e.target.value })} />
            </Field>
          )}
          <Field label={t('start_date')} id="gr-start" required>
            <input id="gr-start" type="date" value={form.start_date} onChange={(e) => setForm({ ...form, start_date: e.target.value })} />
          </Field>
          <Field label={t('end_date')} id="gr-end" required>
            <input id="gr-end" type="date" max={data.defaults?.max_end_date} value={form.end_date} onChange={(e) => setForm({ ...form, end_date: e.target.value })} />
          </Field>
          <Field label={t('max_amount')} id="gr-max">
            <input id="gr-max" type="number" dir="ltr" value={form.max_amount} onChange={(e) => setForm({ ...form, max_amount: e.target.value })} />
          </Field>
          <div className="set-form-actions"><Button type="submit" disabled={!form.delegate_uuid}>{t('give_right')}</Button></div>
        </fieldset>
        {locked && <p id="rights-locked-reason" className={data.locked ? 'visually-hidden' : 'hint'}>{data.locked ? t('rights_off_owner') : t('ref_STALE_DATA')}</p>}
      </form>
      {data.grants.length > 0 && (
        <>
          <h3 className="set-rights-sub">{t('history')}</h3>
          <Table headers={[t('delegate'), t('status_col'), t('scope'), '']}>
            {data.grants.map((g) => (
              <tr key={g.grant_id}>
                <td><bdi>{g.delegate_name}</bdi><div className="hint"><bdi dir="ltr">{g.grant_id}</bdi></div></td>
                <td>{chip(g.status, g.end_date)}</td>
                <td>{g.scope_items.map((s) => `${s.tax_type.toUpperCase()}${s.period_id ? ` ${iso(s.period_id)}` : ''}`).join(', ')}<div className="hint nowrap">{formatDate(g.start_date, lang)} – {formatDate(g.end_date, lang)}</div></td>
                <td>{g.status === 'active' && <Button variant="danger" className="btn-sm" onClick={() => setRevoking(g)}>{t('revoke')}</Button>}</td>
              </tr>
            ))}
          </Table>
        </>
      )}
      <Dialog open={confirm} title={t('give_right')} onClose={() => setConfirm(false)} labelledBy="grant-confirm-title">
        <p>{summary}</p>
        <p>{t('not_shared')}</p>
        <p className="hint">{t('record_permission')}</p>
        <div className="dialog-actions">
          <Button variant="secondary" onClick={() => setConfirm(false)}>{t('close')}</Button>
          <Button onClick={create} disabled={saving}>{saving ? t('saving') : t('continue_uaepass')}</Button>
        </div>
      </Dialog>
      <Dialog open={!!revoking} title={t('revoke')} onClose={() => setRevoking(null)} labelledBy="grant-revoke-title">
        <p><bdi>{revoking?.delegate_name}</bdi></p>
        <div className="dialog-actions">
          <Button variant="secondary" onClick={() => setRevoking(null)}>{t('close')}</Button>
          <Button variant="danger" onClick={revoke}>{t('revoke')}</Button>
        </div>
      </Dialog>
    </Panel>
  )
}
