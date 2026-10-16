import { useCallback, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'
import { useAuth } from '../../app/auth'
import { Icon } from '../../components/Icon'
import { Button, Chip, Empty, Message, PageHeader, Panel, Skeleton } from '../../components/ui'
import { get, post } from '../../lib/api'
import { formatAED, formatDate } from '../../lib/format'
import { DaysChip, DueDate, RequestChip, refusalText, returnTitle, useLang, when } from './parts'
import type { HistoryRow, ListResponse, RequestRow } from './types'
import './approvals.css'

/** SC7 Return review: returns waiting for approval, prepared packs not yet sent, and the approval history. */
export default function ReturnsList() {
  const { t } = useTranslation('approvals')
  const lang = useLang()
  const { companyId, company } = useAuth()
  const [data, setData] = useState<ListResponse | null>(null)
  const [error, setError] = useState(false)
  const [notice, setNotice] = useState<{ kind: 'success' | 'error'; text: string } | null>(null)
  const [busy, setBusy] = useState<string | null>(null)

  const load = useCallback(async () => {
    if (!companyId) return
    try {
      setData(await get<ListResponse>(`/api/companies/${companyId}/approvals`))
      setError(false)
    } catch {
      setError(true)
    }
  }, [companyId])
  useEffect(() => {
    load()
  }, [load])

  const send = async (packId: string) => {
    setBusy(packId)
    try {
      await post(`/api/companies/${companyId}/approvals/requests`, { pack_id: packId })
      setNotice({ kind: 'success', text: t('sent_for_approval') })
      await load()
    } catch (e) {
      setNotice({ kind: 'error', text: refusalText(t, e) })
    } finally {
      setBusy(null)
    }
  }

  const companyName = company ? (lang === 'ar' ? company.trade_name_ar : company.trade_name_en) : null

  return (
    <div className="page returns-page">
      <PageHeader
        eyebrow={companyName ? <bdi>{companyName}</bdi> : undefined}
        title={t('title')}
        subtitle={t('intro')}
        meta={
          <span className="ret-note">
            <Icon name="info" size={16} />
            <span>{t('nothing_filed_auto')}</span>
          </span>
        }
      />
      {notice && <Message kind={notice.kind}>{notice.text}</Message>}
      {error && (
        <Message kind="error">
          {t('history_error')} <Button variant="secondary" onClick={load}>{t('try_again')}</Button>
        </Message>
      )}
      {!data && !error && (
        <div aria-live="polite">
          <span className="visually-hidden">{t('loading_latest')}</span>
          <Skeleton rows={4} />
        </div>
      )}
      {data && (
        <>
          {!data.flow_enabled && <Message kind="warning">{t('flow_off')}</Message>}
          <section className="ret-section" id="awaiting" aria-labelledby="awaiting-title">
            <div className="ret-section-head">
              <h2 id="awaiting-title">{t('awaiting_title')}</h2>
              {data.awaiting.length > 0 && <span className="ret-count">{data.awaiting.length}</span>}
            </div>
            {data.awaiting.length === 0 ? (
              <Empty icon="check" title={t('empty')} />
            ) : (
              <ul className="card-list">
                {data.awaiting.map((r) => (
                  <TaskCard key={r.request_id} r={r} delegate={data.role === 'delegate'} />
                ))}
              </ul>
            )}
          </section>
          {data.can_send && data.packs_ready.length > 0 && (
            <Panel title={t('ready_title')} id="ready" className="ret-ready">
              {data.packs_ready.map((p) => (
                <div key={p.pack_id} className="list-row">
                  <div className="list-row-main">
                    <div className="list-row-title">{returnTitle(t, { return_type: p.tax_type, period_id: p.period_id })}</div>
                    <div className="list-row-meta ret-labels">
                      <span>{t('version_only', { v: p.version })}</span>
                      <Chip tone="draft">{t('ai_label')}</Chip>
                      {p.not_reviewed_by_human && <Chip tone="attention">{t('stage_not_reviewed')}</Chip>}
                    </div>
                  </div>
                  <Button onClick={() => send(p.pack_id)} disabled={busy === p.pack_id || !data.flow_enabled}>
                    {data.role === 'delegate' ? t('send_for_approval') : t('start_approval')}
                  </Button>
                </div>
              ))}
            </Panel>
          )}
          <History rows={data.history} />
        </>
      )}
    </div>
  )
}

/** The waiting return as the one clear task: title, due date with days left, the net amount, one primary action. */
function TaskCard({ r, delegate }: { r: RequestRow; delegate: boolean }) {
  const { t } = useTranslation('approvals')
  const lang = useLang()
  const key = r.amounts?.find((a) => a.key === 'net_vat' || a.key === 'tax')
  const titleId = `task-${r.request_id}`
  return (
    <li className="ret-task">
      <div className="ret-task-main">
        <p className="ret-task-eyebrow">
          <Icon name="file-check" size={16} />
          {delegate || r.awaiting_owner ? t('waiting_owner_approval') : t('needs_your_approval')}
        </p>
        <h3 id={titleId}>{returnTitle(t, r)}</h3>
        <div className="ret-task-due">
          <DueDate date={r.due_date} />
          <DaysChip date={r.due_date} />
        </div>
        <div className="ret-task-chips ret-labels">
          <RequestChip r={r} />
          {r.awaiting_owner && <Chip tone="attention">{t('awaiting_owner')}</Chip>}
          {r.is_demo && <Chip tone="info">{t('demo_data')}</Chip>}
        </div>
      </div>
      {key && (
        <div className="ret-task-figure">
          <div className="ret-task-figure-label">{key.term?.[lang]}</div>
          <div className="ret-task-figure-value"><bdi dir="ltr">{formatAED(key.value_fils, lang)}</bdi></div>
        </div>
      )}
      <div className="ret-task-action">
        <Link className={`btn ${delegate ? 'btn-secondary' : 'btn-primary'}`} to={`/returns/approve/${r.request_id}`} aria-describedby={titleId}>
          {delegate ? t('view_return') : t('review_and_approve')}
          <Icon name="chevron-end" size={18} className="flip-rtl" />
        </Link>
      </div>
      {r.status === 'blocked' && <Message kind="warning">{t('authority_unclear')}</Message>}
    </li>
  )
}

function History({ rows }: { rows: HistoryRow[] }) {
  const { t } = useTranslation('approvals')
  const lang = useLang()
  const chip = (r: HistoryRow) =>
    r.status_chip === 'approved' ? <Chip tone="ok">{t('st_approved')}</Chip> : r.status_chip === 'expired' ? <Chip tone="attention">{t('st_approval_expired')}</Chip> : r.status_chip === 'not_approved' ? <Chip tone="neutral">{t('st_not_approved')}</Chip> : <Chip tone="info">{t('st_waiting')}</Chip>
  const headers = [t('col_return'), t('status_col'), t('approved_by'), t('submitted_by')]
  return (
    <Panel title={t('history_title')} id="history" className="ret-history">
      {rows.length === 0 ? (
        <div className="panel-body"><Empty icon="history" title={t('history_empty')} /></div>
      ) : (
        <div className="table-wrap">
          <table className="table-compact">
            <thead>
              <tr>
                {headers.map((h) => <th key={h} scope="col">{h}</th>)}
                <th scope="col"><span className="visually-hidden">{t('open')}</span></th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.request_id}>
                  <td data-label={headers[0]}>
                    {r.needs_attention && (
                      <div className="ret-attn">
                        <Chip tone="urgent">{t('needs_attention')}</Chip> <span className="hint">{r.needs_attention}</span>
                      </div>
                    )}
                    <strong>{returnTitle(t, r)}</strong>
                    <div className="hint nowrap">{t('prepared_on', { date: formatDate(r.data_version.prepared_on, lang), n: r.data_version.version })}</div>
                  </td>
                  <td data-label={headers[1]}>
                    {chip(r)}
                    <div className="hint">{r.submission_label[lang]}</div>
                  </td>
                  <td data-label={headers[2]}>
                    {r.approved_by ? (
                      <>
                        <bdi>{r.approved_by.name}</bdi>
                        <div className="hint nowrap">{t(`role_${r.approved_by.role}`, { defaultValue: r.approved_by.role })} · {when(r.decided_at, lang)}</div>
                      </>
                    ) : (
                      <span className="muted">—</span>
                    )}
                  </td>
                  <td data-label={headers[3]}>{r.submitted_by ? <bdi>{r.submitted_by}</bdi> : <span className="muted">{t('not_submitted')}</span>}</td>
                  <td className="ret-col-action">
                    <Link className="ret-open" to={`/returns/approve/${r.request_id}`} aria-label={`${t('open')}: ${returnTitle(t, r)}`}>
                      {t('open')}
                      <Icon name="chevron-end" size={16} className="flip-rtl" />
                    </Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Panel>
  )
}
