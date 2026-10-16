import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Icon } from '../../components/Icon'
import { Button, Chip, Disclosure, Empty, Field, Ident, Message, Panel, Skeleton, StatCard, Table } from '../../components/ui'
import '../det/det.css'
import { ApiError, post } from '../../lib/api'
import { formatAED, formatDateTime, formatNumber } from '../../lib/format'
import { newRequestId, useFetch } from './lib'

interface Wave { code: string; label_en: string; label_ar: string; cap: number | null; billing: boolean }
interface Config { waves: Wave[]; default_on_mode_enabled: boolean; suppression_n: number; can_approve: boolean; can_manage: boolean; stale_block_threshold_hours: number }
interface Cohort { cohort_id: string; code: string; version: number; name: string; wave: string; size_limit: number | null; enrolment_mode: string; status: string; member_count: number; pending_changes: number; is_demo: boolean }
interface Change { id: string; cohort_id: string; licence_number: string; action: string; state: string; effective_at: string; rejection_reason: string | null; created_at: string }
interface Member { membership_id: string; licence_number: string; status: string; effective_at: string; owner_opted_in: boolean; subscription_badge?: string | null; billing_status: string | null; collection_status: string | null; enrolment_basis: string | null }
interface Cell { value: number | null; suppressed: boolean }
interface Detail { cohort: Cohort; members: Member[]; member_count: number; pending_changes: Change[]; aggregates: { total: Cell; suppression_n: number } }
interface Preview { match_count: number; size_limit: number | null; over_limit: number; stale: boolean; last_pulled_at: string | null; age_hours: number | null; rule_summary: string; excluded: { licence_number: string; reason_codes: string[] }[] }
interface Aggregates {
  money_confirmed_fils: { billed_net: number; collected: number; refunded: number }
  counts: Record<string, number>
  provisional_fils: { platform_derived_collected: number }
  total_subscriptions: Cell
  switches: Record<string, boolean>
  k4: { rule_version: string; observation_window_days: number; flag_opted_out: Record<string, Cell> }
}

/** SC14 tab: pilot cohort register, wave caps, two-person changes, per-licence states (no amounts). */
export default function CohortTab() {
  const { t, i18n } = useTranslation('subscription')
  const lang = i18n.language
  const cfg = useFetch<Config>('/api/det/cohort/config')
  const list = useFetch<{ cohorts: Cohort[] }>('/api/det/cohort')
  const agg = useFetch<Aggregates>('/api/det/subscriptions/aggregates')
  const [openId, setOpenId] = useState<string | null>(null)

  if (cfg.error && (cfg.error as ApiError).status === 403) return <Message kind="info">{t('det.no_access')}</Message>
  if ((cfg.loading && !cfg.data) || (list.loading && !list.data)) return <Skeleton rows={5} />
  if (!cfg.data || !list.data) return <Message kind="error">{t('det.error')} <Button variant="link" onClick={() => { cfg.reload(); list.reload() }}>{t('screen.try_again')}</Button></Message>
  const config = cfg.data
  const waveLabel = (code: string) => {
    const w = config.waves.find((x) => x.code === code)
    return w ? (lang.startsWith('ar') ? w.label_ar : w.label_en) : code
  }
  const cell = (c: Cell | undefined) => (!c ? '–' : c.suppressed ? <Chip tone="info" icon="i" title={t('det.small_groups')}>{t('det.fewer_than', { n: config.suppression_n })}</Chip> : formatNumber(c.value, lang))
  return (
    <div>
      <Panel title={t('det.aggregates')} id="det-sub-agg">
        {agg.error && !agg.data && <Message kind="error">{t('det.error')} <Button variant="link" onClick={agg.reload}>{t('screen.try_again')}</Button></Message>}
        {agg.data && (
          <>
            {agg.data.money_confirmed_fils.billed_net === 0 && <Message kind="info">{t('det.no_billed')}</Message>}
            <div className="stat-grid det-cohort-stats">
              <StatCard icon="card" label={t('det.billed_net')} value={<bdi dir="ltr">{formatAED(agg.data.money_confirmed_fils.billed_net, lang)}</bdi>} status={<Chip tone="draft">{t('example')}</Chip>} />
              <StatCard icon="check" label={t('det.collected')} value={<bdi dir="ltr">{formatAED(agg.data.money_confirmed_fils.collected, lang)}</bdi>} />
              <StatCard icon="history" label={t('det.refunded')} value={<bdi dir="ltr">{formatAED(agg.data.money_confirmed_fils.refunded, lang)}</bdi>} />
              <StatCard icon="clock" tone={agg.data.counts.pending_confirmation ? 'attention' : undefined} label={t('det.pending_confirmation')} value={<bdi dir="ltr">{formatNumber(agg.data.counts.pending_confirmation, lang)}</bdi>} />
              <StatCard icon="alert" tone={agg.data.counts.mismatch ? 'urgent' : undefined} label={t('det.mismatch')} value={<bdi dir="ltr">{formatNumber(agg.data.counts.mismatch, lang)}</bdi>} />
              <StatCard className="det-stat-dashed" icon="info" tone="draft" label={t('det.provisional_tile')} value={<bdi dir="ltr">{formatAED(agg.data.provisional_fils.platform_derived_collected, lang)}</bdi>} />
            </div>
            <dl className="det-facts">
              <div><dt>{t('det.members')}</dt><dd>{cell(agg.data.total_subscriptions)}</dd></div>
              <div><dt>{t('det.k4', { rule: agg.data.k4.rule_version, days: agg.data.k4.observation_window_days })}</dt><dd>{t('det.k4_opted_out')} {cell(agg.data.k4.flag_opted_out.pending)}</dd></div>
              {[['billing_live', 'switch_billing_live'], ['default_on_billing', 'switch_default_on'], ['consent_required_before_billing', 'switch_consent']].map(([k, label]) => (
                <div key={k}><dt>{t(`det.${label}`)}</dt><dd><Chip tone={agg.data!.switches[k] ? 'ok' : 'neutral'} icon={agg.data!.switches[k] ? '●' : '○'}>{agg.data!.switches[k] ? t('det.on') : t('det.off')}</Chip></dd></div>
              ))}
            </dl>
            <p className="det-note"><Icon name="lock" size={16} />{t('det.suppression', { n: config.suppression_n })}</p>
          </>
        )}
      </Panel>

      {openId ? (
        <CohortDetail cohortId={openId} config={config} waveLabel={waveLabel} onBack={() => { setOpenId(null); list.reload() }} />
      ) : (
        <Panel title={t('det.title')} id="det-cohorts" className="det-panel-flush">
          {list.data.cohorts.length === 0 ? <Empty icon="users" title={t('det.no_cohorts')} /> : (
            <div className="table-compact det-table">
            <Table headers={[t('det.name'), t('det.wave'), t('det.mode'), t('det.status'), t('det.members'), t('det.pending'), '']}>
              {list.data.cohorts.map((c) => (
                <tr key={c.cohort_id}>
                  <td><Button variant="link" className="det-ref-btn" onClick={() => setOpenId(c.cohort_id)}>{c.name}</Button><span className="det-cell-sub"><Ident>{c.code}</Ident> {c.is_demo && <Chip tone="draft">{t('demo')}</Chip>}</span></td>
                  <td className="nowrap">{waveLabel(c.wave)}</td>
                  <td className="nowrap">{c.enrolment_mode === 'opt_in' ? t('det.mode_opt_in') : t('det.mode_default_on')}</td>
                  <td><Chip tone={c.status === 'active' ? 'ok' : 'neutral'}>{t(`det.cohort_status_${c.status}`)}</Chip></td>
                  <td className="num"><bdi dir="ltr">{formatNumber(c.member_count, lang)} / {c.size_limit === null ? '–' : formatNumber(c.size_limit, lang)}</bdi></td>
                  <td className="num">{c.pending_changes > 0 ? <Chip tone="attention" icon="◔">{formatNumber(c.pending_changes, lang)}</Chip> : formatNumber(c.pending_changes, lang)}</td>
                  <td className="nowrap"><Button variant="secondary" className="det-rowbtn" onClick={() => setOpenId(c.cohort_id)}>{t('det.open')}</Button></td>
                </tr>
              ))}
            </Table>
            </div>
          )}
          {config.can_manage && <div style={{ padding: '0 20px 12px' }}><NewCohort config={config} waveLabel={waveLabel} onCreated={list.reload} /></div>}
        </Panel>
      )}
    </div>
  )
}

function errorText(t: (k: string, o?: Record<string, unknown>) => string, e: unknown): string {
  if (!(e instanceof ApiError)) return t('det.error')
  const d = (e.details ?? {}) as Record<string, unknown>
  switch (e.code) {
    case 'STALE_LICENCE_DATA': return t('det.stale_blocked')
    case 'SELF_APPROVAL': return t('det.self_approval')
    case 'COHORT_SIZE_LIMIT': return `${e.message}`
    case 'DEFAULT_ON_MODE_OFF': return t('det.mode_off')
    case 'COHORT_LICENCE_INELIGIBLE': return `${t('det.excluded')}: ${((d.reason_codes as string[]) ?? []).join(', ')}`
    case 'NO_PERMISSION': return t('det.approve_hint')
    default: return `${t('det.error')}${e.reference ? ` (${e.reference})` : ''}`
  }
}

function NewCohort({ config, waveLabel, onCreated }: { config: Config; waveLabel: (c: string) => string; onCreated: () => void }) {
  const { t } = useTranslation('subscription')
  const [name, setName] = useState('')
  const [code, setCode] = useState('')
  const [wave, setWave] = useState(config.waves[1]?.code ?? '1b')
  const [reason, setReason] = useState('')
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const create = async () => {
    setBusy(true)
    setErr(null)
    try {
      await post('/api/det/cohort', { name, code, wave, enrolment_mode: 'opt_in', reason, status: 'active' })
      setName(''); setCode(''); setReason('')
      onCreated()
    } catch (e) {
      setErr(errorText(t, e))
    } finally {
      setBusy(false)
    }
  }
  return (
    <Disclosure summary={t('det.new_cohort')}>
      <Field label={t('det.name')} id="nc-name" required><input id="nc-name" value={name} onChange={(e) => setName(e.target.value)} /></Field>
      <Field label={t('det.code')} id="nc-code" required><input id="nc-code" value={code} onChange={(e) => setCode(e.target.value.toUpperCase())} /></Field>
      <Field label={t('det.wave')} id="nc-wave">
        <select id="nc-wave" value={wave} onChange={(e) => setWave(e.target.value)}>
          {config.waves.map((w) => <option key={w.code} value={w.code}>{waveLabel(w.code)}{w.cap !== null ? ` (${t('det.cap')} ${w.cap})` : ''}</option>)}
        </select>
      </Field>
      <Field label={t('det.mode')} id="nc-mode" hint={config.default_on_mode_enabled ? undefined : t('det.mode_off')}>
        <select id="nc-mode" value="opt_in" onChange={() => undefined}>
          <option value="opt_in">{t('det.mode_opt_in')}</option>
          <option value="default_on_with_opt_out" disabled={!config.default_on_mode_enabled}>{t('det.mode_default_on')}</option>
        </select>
      </Field>
      <Field label={t('det.reason')} id="nc-reason" required><input id="nc-reason" value={reason} onChange={(e) => setReason(e.target.value)} /></Field>
      {err && <Message kind="error">{err}</Message>}
      <Button disabled={busy || !name || !code || !reason} onClick={create}>{t('det.create')}</Button>
    </Disclosure>
  )
}

function CohortDetail({ cohortId, config, waveLabel, onBack }: { cohortId: string; config: Config; waveLabel: (c: string) => string; onBack: () => void }) {
  const { t, i18n } = useTranslation('subscription')
  const lang = i18n.language
  const { data, error, loading, reload } = useFetch<Detail>(`/api/det/cohort/${cohortId}`, [cohortId])
  const [licence, setLicence] = useState('')
  const [reason, setReason] = useState('')
  const [err, setErr] = useState<string | null>(null)
  const [ok, setOk] = useState<string | null>(null)
  const [preview, setPreview] = useState<Preview | null>(null)
  const act = async (fn: () => Promise<unknown>, success: string) => {
    setErr(null)
    setOk(null)
    try {
      await fn()
      setOk(success)
      reload()
    } catch (e) {
      setErr(errorText(t, e))
    }
  }
  const request = (action: string, licences: string[]) => act(() => post(`/api/det/cohort/${cohortId}/changes`, { licence_numbers: licences, action, request_id: newRequestId(), reason }), t('det.pending'))
  if (loading && !data) return <Skeleton rows={5} />
  if (error && !data) return <Message kind="error">{t('det.error')} <Button variant="link" onClick={reload}>{t('screen.try_again')}</Button></Message>
  if (!data) return null
  const c = data.cohort
  return (
    <Panel title={<>{c.name} <Ident>{c.code}</Ident> · {t('det.version')} {c.version}</>} id="det-cohort-detail" actions={<Button variant="secondary" onClick={onBack}>{t('det.back')}</Button>}>
      <p>
        {waveLabel(c.wave)} · {t('det.size_limit')}: {c.size_limit === null ? '–' : formatNumber(c.size_limit, lang)} · {t('det.members')}: {formatNumber(data.member_count, lang)} ·{' '}
        {c.enrolment_mode === 'opt_in' ? t('det.mode_opt_in') : t('det.mode_default_on')} · <Chip tone={c.status === 'active' ? 'ok' : 'neutral'}>{t(`det.cohort_status_${c.status}`)}</Chip>
      </p>
      {c.status === 'closed' && <Message kind="info">{t('det.close_note')}</Message>}
      {err && <Message kind="error">{err}</Message>}
      {ok && <Message kind="success">{ok}</Message>}

      <div className="table-compact det-table">
      <Table headers={[t('det.licence_number'), t('det.member_status'), t('det.subscription_status'), t('det.billing_status'), t('det.collection_status'), t('det.basis'), t('det.actions')]}>
        {data.members.map((m) => (
          <tr key={m.membership_id}>
            <td><Ident>{m.licence_number}</Ident></td>
            <td><Chip tone={m.status === 'active' ? 'ok' : 'neutral'}>{t(`screen.pilot_${m.status}`)}</Chip>{m.owner_opted_in && <div className="hint">{t('det.opted_in')}</div>}</td>
            <td>{m.subscription_badge ? t(`screen.badge_${m.subscription_badge}`) : '–'}</td>
            <td>{m.billing_status ? t(`det.billing_${m.billing_status}`) : '–'}</td>
            <td>{m.collection_status ? t(`screen.status_${m.collection_status}`) : '–'}</td>
            <td>{m.enrolment_basis === 'default_on' ? t('det.mode_default_on') : m.enrolment_basis === 'opted_in' ? t('det.mode_opt_in') : '–'}</td>
            <td>
              {config.can_manage && m.status !== 'removed' && (
                <>
                  <Button variant="link" disabled={!reason} title={reason ? undefined : t('det.reason')} onClick={() => request('pause', [m.licence_number])}>{t('det.action_pause')}</Button>
                  <Button variant="link" disabled={!reason} title={reason ? undefined : t('det.reason')} onClick={() => request('remove', [m.licence_number])}>{t('det.action_remove')}</Button>
                </>
              )}
            </td>
          </tr>
        ))}
      </Table>
      </div>
      <p className="det-note det-note-inline">{t('det.removal_note')}</p>

      {config.can_manage && c.status !== 'closed' && (
        <section className="card">
          <h3>{t('det.add_licence')}</h3>
          <Field label={t('det.licence_number')} id="cd-licence"><input id="cd-licence" dir="ltr" value={licence} onChange={(e) => setLicence(e.target.value.trim())} /></Field>
          <Field label={t('det.reason')} id="cd-reason" required hint={t('det.fixed_message')}><input id="cd-reason" value={reason} onChange={(e) => setReason(e.target.value)} /></Field>
          <div className="actions">
            <Button disabled={!licence || !reason} onClick={() => request('enrol', [licence])}>{t('det.request')}</Button>
            <Button variant="secondary" onClick={() => act(async () => setPreview(await post<Preview>(`/api/det/cohort/${cohortId}/preview`)), t('det.preview'))}>{t('det.preview')}</Button>
            <Button variant="danger" disabled={!reason} onClick={() => request('close', [])}>{t('det.action_close')}</Button>
          </div>
          {preview && (
            <div>
              <p>{preview.match_count === 0 ? t('det.no_match') : t('det.preview_match', { n: preview.match_count })}</p>
              {preview.last_pulled_at && <p className="hint">{t('det.last_pulled', { datetime: formatDateTime(preview.last_pulled_at, lang), age: preview.age_hours })}</p>}
              {preview.stale && <Message kind="warning">{t('det.stale_blocked')}</Message>}
              {preview.over_limit > 0 && <Message kind="warning">{t('det.over_limit', { n: preview.match_count, limit: preview.size_limit, excess: preview.over_limit })}</Message>}
              <p className="hint">{preview.rule_summary}</p>
              {preview.excluded.length > 0 && (
                <details><summary>{t('det.excluded')} ({preview.excluded.length})</summary>
                  <ul>{preview.excluded.map((x) => <li key={x.licence_number}><Ident>{x.licence_number}</Ident>: {x.reason_codes.join(', ')}</li>)}</ul>
                </details>
              )}
            </div>
          )}
        </section>
      )}

      <h3 style={{ marginTop: 24 }}>{t('det.pending')}</h3>
      {!config.can_approve && <p className="det-note">{t('det.approve_hint')}</p>}
      <div className="table-compact det-table">
      <Table headers={[t('det.licence_number'), t('det.actions'), t('det.status'), t('det.effective'), '']}>
        {data.pending_changes.map((ch) => (
          <tr key={ch.id}>
            <td><Ident>{ch.licence_number === '*' ? c.code : ch.licence_number}</Ident></td>
            <td>{t(`det.action_${ch.action}`)}</td>
            <td><Chip tone={ch.state === 'applied' ? 'ok' : ch.state === 'rejected' ? 'critical' : 'attention'}>{t(`det.change_${ch.state}`)}</Chip>{ch.rejection_reason && <div className="hint">{ch.rejection_reason}</div>}</td>
            <td>{formatDateTime(ch.effective_at, lang)}</td>
            <td>
              {config.can_approve && ch.state === 'pending' && (
                <>
                  <Button variant="link" onClick={() => act(() => post(`/api/det/cohort/changes/${ch.id}/approve`), t('det.changes_applied'))}>{t('det.approve')}</Button>
                  <Button variant="link" onClick={() => act(() => post(`/api/det/cohort/changes/${ch.id}/reject`, { reason: 'rejected by approver' }), t('det.changes_rejected'))}>{t('det.reject')}</Button>
                </>
              )}
            </td>
          </tr>
        ))}
      </Table>
      </div>
    </Panel>
  )
}
