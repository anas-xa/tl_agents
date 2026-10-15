import { useCallback, useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, useParams } from 'react-router-dom'
import { useAuth } from '../../app/auth'
import { Button, Chip, Dialog, Field, Message, Panel, Skeleton, Table } from '../../components/ui'
import { ApiError, get, post } from '../../lib/api'
import { formatAED, formatDate } from '../../lib/format'
import FilingPanel from './FilingPanel'
import { DueDate, Hash, RequestChip, refusalText, returnTitle, useLang, when } from './parts'
import type { ApprovalRecord, PackLine, RequestDetail } from './types'

interface DraftPack {
  review_status: string
  review_status_label: { en: string; ar: string } | null
  lines: PackLine[]
  sources: Record<string, unknown>[]
  basis: { formula?: string; rule_refs?: Record<string, { rule_id: string; version: string; instrument?: string }> } | null
  history: { to: string; by: string | null; system: boolean }[]
}

type Banner = { kind: 'info' | 'warning' | 'error'; text: string; newId?: string; support?: boolean; retry?: boolean }

/** SC7 Return review and approval: the approval act, the approval record and the manual filing panel. */
export default function ApprovalScreen() {
  const { requestId } = useParams()
  const { t } = useTranslation('approvals')
  const lang = useLang()
  const { companyId } = useAuth()
  const [data, setData] = useState<RequestDetail | null>(null)
  const [draft, setDraft] = useState<DraftPack | null>(null)
  const [loadError, setLoadError] = useState(false)
  const [reviewed, setReviewed] = useState(false)
  const [informed, setInformed] = useState(false)
  const [confirmOpen, setConfirmOpen] = useState(false)
  const [changesOpen, setChangesOpen] = useState(false)
  const [reason, setReason] = useState('')
  const [reasonError, setReasonError] = useState(false)
  const [banner, setBanner] = useState<Banner | null>(null)
  const [busy, setBusy] = useState(false)
  const [done, setDone] = useState<string | null>(null)
  const approveRef = useRef<HTMLButtonElement>(null)
  const bannerRef = useRef<HTMLDivElement>(null)
  const base = `/api/companies/${companyId}/approvals`

  const load = useCallback(async () => {
    if (!companyId || !requestId) return
    try {
      const d = await get<RequestDetail>(`${base}/requests/${requestId}`)
      setData(d)
      setLoadError(false)
      try {
        setDraft(await get<DraftPack>(`/api/companies/${companyId}/drafts/${d.pack_id}`))
      } catch {
        setDraft(null) // e.g. owner abroad: the draft viewer is not available; the request carries the figures
      }
    } catch {
      setLoadError(true)
    }
  }, [base, companyId, requestId])
  useEffect(() => {
    load()
  }, [load])
  useEffect(() => {
    if (banner) bannerRef.current?.focus()
  }, [banner])

  if (loadError)
    return (
      <div className="page">
        <Message kind="error">
          {t('generic_error')} <Button variant="secondary" onClick={load}>{t('try_again')}</Button>
        </Message>
      </div>
    )
  if (!data)
    return (
      <div className="page" aria-live="polite">
        <p>{t('loading_latest')}</p>
        <Skeleton rows={6} />
        <Button disabled>{t('approve')}</Button>
      </div>
    )

  const ent = data.entitlement ?? { allowed: false, reason_code: 'NO_PERMISSION' }
  const isDelegate = data.role === 'delegate'
  const open = data.status === 'open'
  const lines: PackLine[] = draft?.lines ?? data.pack?.lines ?? []
  const amount = (key: string) => formatAED(lines.find((l) => l.key === key)?.value_fils ?? data.amounts?.find((a) => a.key === key)?.value_fils ?? null, lang)
  const reviewer = draft?.history.filter((h) => !h.system && h.by).map((h) => h.by).pop()
  const notReviewed = data.not_reviewed_by_human
  const approveDisabled = !open || !ent.allowed || busy || !reviewed || (notReviewed && !informed) || !!banner?.newId
  const approvedBy = data.approved_by

  const fail = (e: unknown) => {
    const code = e instanceof ApiError ? e.code : 'NETWORK'
    const details = (e instanceof ApiError ? e.details : {}) as Record<string, unknown>
    if (code === 'HASH_MISMATCH') {
      setReviewed(false)
      setBanner({ kind: 'warning', text: t('hash_mismatch', { id: data.short_hash }), newId: '' })
      load()
    } else if (code === 'REQUEST_SUPERSEDED') {
      setReviewed(false)
      setBanner({ kind: 'warning', text: t('superseded_viewing', { id: String(details.new_request_id || '').slice(-8) }), newId: String(details.new_request_id || '') })
    } else if (code === 'REQUEST_EXPIRED') {
      setReviewed(false)
      setBanner({ kind: 'warning', text: t('request_expired') })
      load()
    } else if (code === 'REAUTH_FAILED') {
      setBanner({ kind: 'error', text: t('uaepass_failed'), support: Boolean(details.show_support), retry: true })
    } else if (code === 'UAEPASS_CANCELLED') {
      setBanner({ kind: 'info', text: t('uaepass_cancelled'), retry: true })
    } else if (code === 'NETWORK') {
      setBanner({ kind: 'error', text: `${t('save_failed')} ${t('check_connection')}`, retry: true })
    } else if (['LEVEL_TOO_LOW_FOR_ACTION', 'RIGHT_SWITCHED_OFF', 'AUTHORITY_UNCLEAR', 'ALREADY_APPROVED_BY_YOU', 'APPROVAL_FLOW_SWITCHED_OFF', 'NO_APPROVAL_RIGHT'].includes(code)) {
      setBanner({ kind: 'error', text: refusalText(t, e) })
    } else {
      setBanner({ kind: 'error', text: t('save_failed'), retry: true })
    }
    setTimeout(() => approveRef.current?.focus(), 0)
  }

  const approve = async () => {
    setBusy(true)
    setConfirmOpen(false)
    try {
      const res = await post<{ status: string; approval: ApprovalRecord }>(`${base}/${data.request_id}/approve`, { expected_hash: data.draft_content_hash, reviewed_figures: reviewed, informed_unreviewed: informed, uaepass: 'confirmed' })
      setBanner(null)
      setDone(res.status === 'pending_joint' ? t('pending_joint', { n: data.quorum_n, x: data.joint_collected + 1 }) : t('decision_recorded'))
      await load()
    } catch (e) {
      fail(e)
    } finally {
      setBusy(false)
    }
  }

  const sendChanges = async () => {
    if (reason.trim().length < 5) {
      setReasonError(true)
      return
    }
    setBusy(true)
    try {
      await post(`${base}/${data.request_id}/decline`, { decision: 'request_changes', reason: reason.trim(), expected_hash: data.draft_content_hash, uaepass: 'confirmed' })
      setChangesOpen(false)
      setDone(t('decision_recorded'))
      await load()
    } catch (e) {
      setChangesOpen(false)
      fail(e)
    } finally {
      setBusy(false)
    }
  }

  const remind = async () => {
    try {
      await post(`${base}/${data.request_id}/remind`)
      setDone(t('owner_reminded'))
    } catch (e) {
      setBanner({ kind: 'info', text: refusalText(t, e) })
    }
  }

  const viewOnlyReason = !ent.allowed && open ? (ent.reason_code === 'RIGHT_SWITCHED_OFF' ? t('right_switched_off') : ent.reason_code === 'LEVEL_TOO_LOW_FOR_ACTION' ? t('level_too_low') : ent.reason_code === 'AUTHORITY_UNCLEAR' ? t('authority_unclear') : ent.reason_code === 'ON_HOLD' ? t('on_hold') : t('view_only')) : null

  return (
    <div className="page approval-screen">
      <p>
        <Link to="/returns">← {t('title')}</Link>
      </p>
      <header>
        {data.company_name && (
          <p>
            <bdi>{data.company_name.en}</bdi> · <bdi lang="ar">{data.company_name.ar}</bdi>
          </p>
        )}
        <h1>{returnTitle(t, data)}</h1>
        <p>
          <RequestChip r={data} /> {data.is_demo && <Chip tone="info">{t('demo_data')}</Chip>}
        </p>
        <DueDate date={data.due_date} />
      </header>

      <div aria-live="assertive">
        {banner && (
          <div ref={bannerRef} tabIndex={-1}>
            <Message kind={banner.kind}>
              {banner.text}{' '}
              {banner.newId && (
                <Link className="btn btn-secondary" to={`/returns/approve/${banner.newId}`} onClick={() => setBanner(null)}>
                  {t('show_new_version')}
                </Link>
              )}
              {banner.retry && (
                <>
                  <Button variant="secondary" onClick={() => { setBanner(null); approveRef.current?.focus() }}>{t('try_again')}</Button>{' '}
                  <Button variant="link" onClick={() => setBanner(null)}>{t('close')}</Button>
                </>
              )}
              {banner.support && <Link to="/help"> {t('need_help')}</Link>}
            </Message>
          </div>
        )}
      </div>
      <div aria-live="polite">{done && <Message kind="success">{done}</Message>}</div>
      {!data.flow_enabled && <Message kind="warning">{t('flow_off')}</Message>}
      {data.status === 'superseded' && !banner && (
        <Message kind="warning">
          {t('superseded_viewing', { id: (data.superseded_by || '').slice(-8) })}{' '}
          {data.superseded_by && <Link className="btn btn-secondary" to={`/returns/approve/${data.superseded_by}`}>{t('show_new_version')}</Link>}
        </Message>
      )}
      {data.status === 'expired' && !banner && <Message kind="warning">{t('request_expired')}</Message>}
      {data.status === 'blocked' && (
        <Message kind="warning">
          {t('authority_unclear')} {data.escalation_case_id && t('authority_routed', { id: data.escalation_case_id.slice(-8) })}
        </Message>
      )}
      {data.pack?.on_hold && <Message kind="warning">{t('on_hold')}</Message>}
      {viewOnlyReason && <Message kind="info">{viewOnlyReason}</Message>}
      {data.awaiting_owner && <Message kind="info">{t('awaiting_owner')}</Message>}
      <Message kind="info">{t('nothing_filed_auto')}</Message>

      <div className="two-col">
        <div>
          <Panel title={t('summary_title')} id="summary">
            <ul className="stages">
              <li><Chip tone="draft">{t('stage_draft')}</Chip></li>
              <li>{notReviewed ? <Chip tone="attention">{t('stage_not_reviewed')}</Chip> : <Chip tone="ok">{t('stage_review', { status: (draft?.review_status_label ?? data.human_review_label)?.[lang] ?? '' })}</Chip>}</li>
              <li>{data.status === 'decided' && data.approval_valid ? <Chip tone="ok">{t('stage_approved')}</Chip> : <Chip tone="neutral">{t('stage_not_approved')}</Chip>}</li>
            </ul>
            <p><Chip tone="draft">{t('ai_label')}</Chip></p>
            <p>{reviewer ? t('actor_line', { name: reviewer }) : t('actor_line_none')}</p>
            <p>{data.return_type === 'vat' ? t('summary_vat', { period: data.period_id, out: amount('output_vat'), inp: amount('input_vat'), net: amount('net_vat') }) : t('summary_ct', { period: data.period_id, tax: amount('tax') })}</p>
            <p className="hint">
              {t('version_label', { v: data.pack_version, hash: '' })}<Hash value={data.draft_content_hash} /> · {when(data.created_at, lang)}
            </p>
            <Link to={`/returns/${data.pack_id}`}>{t('open_draft')}</Link>
          </Panel>
          <Panel title={t('figures_title')} id="figures">
            <Table headers={[t('differ_field'), t('differ_ours')]}>
              {lines.map((l) => (
                <tr key={l.key}>
                  <td>{l.term?.[lang] ?? l.key}</td>
                  <td><bdi>{l.value_fils !== null ? formatAED(l.value_fils, lang) : l.text}</bdi></td>
                </tr>
              ))}
            </Table>
          </Panel>
          <details className="panel">
            <summary>{t('source_title')}</summary>
            <p>{draft ? t('source_count', { n: draft.sources.length }) : data.pack ? t('source_count', { n: data.pack.sources_count }) : t('source_not_available')}</p>
            {draft?.sources.slice(0, 20).map((s, i) => (
              <div key={i} className="hint"><bdi>{String(s.source_id ?? s.source ?? '')}</bdi> {s.tax_point_date ? formatDate(String(s.tax_point_date), lang) : ''}</div>
            ))}
          </details>
          <details className="panel">
            <summary>{t('basis_title')}</summary>
            {(draft?.basis ?? (data.pack?.basis as DraftPack['basis']))?.formula && <p>{(draft?.basis ?? (data.pack?.basis as DraftPack['basis']))?.formula}</p>}
            <p>{t('rule_versions', { v: data.rule_version ?? '' })}</p>
          </details>
        </div>
        <div>
          {approvedBy && <RecordPanel a={approvedBy} filingBy={data.filing.submitted_by} />}
          {open && (
            <Panel title={t('approve_title')} id="act">
              {notReviewed && (
                <Message kind="warning">
                  <strong>{t('informed_title')}</strong> {t('informed_body')}
                </Message>
              )}
              {notReviewed && (
                <label className="check">
                  <input type="checkbox" checked={informed} disabled={!ent.allowed} onChange={(e) => setInformed(e.target.checked)} /> {t('informed_tick')}
                </label>
              )}
              <label className="check">
                <input type="checkbox" checked={reviewed} disabled={!ent.allowed} onChange={(e) => setReviewed(e.target.checked)} /> {t('tick_reviewed')}
              </label>
              <div className="sticky-actions">
                <Button ref={approveRef} onClick={() => setConfirmOpen(true)} disabled={approveDisabled} aria-describedby={viewOnlyReason ? 'approve-reason' : undefined}>
                  {t('approve')}
                </Button>{' '}
                <Button variant="secondary" onClick={() => setChangesOpen(true)} disabled={!ent.allowed || busy}>
                  {t('request_changes')}
                </Button>{' '}
                <Link className="btn btn-link" to="/help">{t('escalate')}</Link>
                {isDelegate && (
                  <>
                    {' '}<Button variant="secondary" onClick={remind}>{t('remind_owner')}</Button>
                  </>
                )}
              </div>
              {viewOnlyReason && <p id="approve-reason" className="hint">{viewOnlyReason}</p>}
              <p className="hint">{t('escalate_note')}</p>
            </Panel>
          )}
          <FilingPanel data={data} reload={load} />
          {data.history.length > 0 && (
            <Panel title={t('history_title')} id="act-history">
              <Table headers={[t('history_who'), t('history_role'), t('history_decision'), t('history_when'), t('history_version'), t('history_reason')]}>
                {data.history.map((h) => (
                  <tr key={h.approval_id}>
                    <td><bdi>{h.approver_name}</bdi></td>
                    <td>{t(`role_${h.display_role}`, { defaultValue: h.display_role })}</td>
                    <td>{t(`dec_${h.decision}`)}{h.status === 'pending_joint' ? ` · ${t('st_pending_joint')}` : ''}</td>
                    <td>{when(h.decided_at, lang)}</td>
                    <td>{h.pack_version} · <Hash value={h.data_version_hash} /></td>
                    <td><bdi dir="auto">{h.reason ?? ''}</bdi></td>
                  </tr>
                ))}
              </Table>
            </Panel>
          )}
        </div>
      </div>

      <Dialog open={confirmOpen} title={t('approve_title')} onClose={() => setConfirmOpen(false)} labelledBy="approve-dialog-title">
        <p>{t('approving_version', { id: data.short_hash, when: when(data.created_at, lang) })}</p>
        <p>{t('validity_after_approval', { days: data.validity_days })}</p>
        <p>{t('platform_line')}</p>
        <p className="hint">{t('record_permission')}</p>
        <div className="dialog-actions">
          <Button onClick={approve} disabled={busy} autoFocus>{t('continue_uaepass')}</Button>{' '}
          <Button variant="secondary" onClick={() => { setConfirmOpen(false); approveRef.current?.focus() }}>{t('close')}</Button>
        </div>
      </Dialog>
      <Dialog open={changesOpen} title={t('request_changes')} onClose={() => setChangesOpen(false)} labelledBy="changes-dialog-title">
        <Field label={t('reason_label')} id="reason" required hint={t('reason_counter', { x: reason.trim().length })}>
          <textarea id="reason" dir="auto" maxLength={500} value={reason} onChange={(e) => { setReason(e.target.value); setReasonError(false) }} aria-invalid={reasonError} aria-describedby={reasonError ? 'reason-err' : undefined} rows={4} />
        </Field>
        {reasonError && <p id="reason-err" role="alert" className="field-error">{t('reason_error')}</p>}
        <div className="dialog-actions">
          <Button onClick={sendChanges} disabled={busy}>{t('send_request')}</Button>{' '}
          <Button variant="secondary" onClick={() => setChangesOpen(false)}>{t('close')}</Button>
        </div>
      </Dialog>
    </div>
  )
}

function RecordPanel({ a, filingBy }: { a: ApprovalRecord; filingBy: string | null }) {
  const { t } = useTranslation('approvals')
  const lang = useLang()
  return (
    <Panel title={t('record_title')} id="record">
      <dl className="record">
        <dt>{t('approved_by')}</dt>
        <dd>
          {a.delegation_basis ? (
            t('approved_by_delegate', { delegate: a.approver_name, owner: a.delegation_basis.granting_owner_name ?? '', id: a.delegation_basis.grant_id })
          ) : (
            <>
              <bdi>{a.approver_name}</bdi> · {t(`role_${a.display_role}`, { defaultValue: a.display_role })}
            </>
          )}
        </dd>
        <dt>{t('submitted_by')}</dt>
        <dd>{filingBy ? <bdi>{filingBy}</bdi> : t('not_submitted')}</dd>
        <dt>{t('record_when')}</dt>
        <dd>{when(a.decided_at, lang)}</dd>
        <dt>{t('record_data')}</dt>
        <dd>{t('version_only', { v: a.pack_version })}</dd>
        <dt>{t('record_hash')}</dt>
        <dd><Hash value={a.data_version_hash} /></dd>
        <dt>{t('record_valid_until')}</dt>
        <dd>{when(a.valid_until, lang)} {a.status !== 'active' && <Chip tone="attention">{t(a.status === 'expired' ? 'st_approval_expired' : a.status === 'superseded' ? 'st_superseded' : 'st_not_approved')}</Chip>}</dd>
        <dt>{t('record_id')}</dt>
        <dd><bdi dir="ltr">{a.approval_id}</bdi></dd>
        <dt>{t('record_wording')}</dt>
        <dd><bdi dir="ltr">{a.declaration_wording_version_id}</bdi></dd>
        <dt>{t('record_method')}</dt>
        <dd>{a.channel} · {a.assurance_level}</dd>
      </dl>
      {a.valid_until && <p>{t('validity_line', { date: formatDate(a.valid_until, lang) })}</p>}
      <p className="hint">{t('platform_line')}</p>
      <p className="hint">{t('record_permission')}</p>
    </Panel>
  )
}
