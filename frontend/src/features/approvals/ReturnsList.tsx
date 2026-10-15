import { useCallback, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'
import { useAuth } from '../../app/auth'
import { Button, Chip, Empty, Message, Panel, Skeleton, Table } from '../../components/ui'
import { get, post } from '../../lib/api'
import { formatAED, formatDate } from '../../lib/format'
import { DueDate, RequestChip, refusalText, returnTitle, useLang, when } from './parts'
import type { HistoryRow, ListResponse } from './types'

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

  return (
    <div className="page returns-page">
      <h1>{t('title')}</h1>
      {company && (
        <p>
          <bdi>{company.trade_name_en}</bdi> · <bdi lang="ar">{company.trade_name_ar}</bdi>
        </p>
      )}
      <p>{t('intro')}</p>
      <Message kind="info">{t('nothing_filed_auto')}</Message>
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
          <Panel title={t('awaiting_title')} id="awaiting">
            {data.awaiting.length === 0 ? (
              <Empty title={t('empty')} />
            ) : (
              <ul className="card-list">
                {data.awaiting.map((r) => (
                  <li key={r.request_id} className="card">
                    <div className="card-row">
                      <strong>{returnTitle(t, r)}</strong> <RequestChip r={r} /> {r.is_demo && <Chip tone="info">{t('demo_data')}</Chip>}
                    </div>
                    <DueDate date={r.due_date} />
                    {r.amounts?.filter((a) => a.key === 'net_vat' || a.key === 'tax').map((a) => (
                      <div key={a.key}>
                        {a.term?.[lang]}: <bdi>{formatAED(a.value_fils, lang)}</bdi>
                      </div>
                    ))}
                    {r.status === 'blocked' && <Message kind="warning">{t('authority_unclear')}</Message>}
                    {r.awaiting_owner && <Chip tone="attention">{t('awaiting_owner')}</Chip>}
                    <Link className="btn btn-secondary" to={`/returns/approve/${r.request_id}`}>
                      {t('open')}
                    </Link>
                  </li>
                ))}
              </ul>
            )}
          </Panel>
          {data.can_send && data.packs_ready.length > 0 && (
            <Panel title={t('ready_title')} id="ready">
              <ul className="card-list">
                {data.packs_ready.map((p) => (
                  <li key={p.pack_id} className="card">
                    <strong>{returnTitle(t, { return_type: p.tax_type, period_id: p.period_id })}</strong>{' '}
                    <Chip tone="draft">{t('ai_label')}</Chip> {p.not_reviewed_by_human && <Chip tone="attention">{t('stage_not_reviewed')}</Chip>}
                    <div className="hint">{t('version_only', { v: p.version })}</div>
                    <Button onClick={() => send(p.pack_id)} disabled={busy === p.pack_id || !data.flow_enabled}>
                      {data.role === 'delegate' ? t('send_for_approval') : t('start_approval')}
                    </Button>
                  </li>
                ))}
              </ul>
            </Panel>
          )}
          <History rows={data.history} />
        </>
      )}
    </div>
  )
}

function History({ rows }: { rows: HistoryRow[] }) {
  const { t } = useTranslation('approvals')
  const lang = useLang()
  const chip = (r: HistoryRow) =>
    r.status_chip === 'approved' ? <Chip tone="ok">{t('st_approved')}</Chip> : r.status_chip === 'expired' ? <Chip tone="attention">{t('st_approval_expired')}</Chip> : r.status_chip === 'not_approved' ? <Chip tone="neutral">{t('st_not_approved')}</Chip> : <Chip tone="info">{t('st_waiting')}</Chip>
  return (
    <Panel title={t('history_title')} id="history">
      {rows.length === 0 ? (
        <Empty title={t('history_empty')} />
      ) : (
        <Table headers={[t('history_version'), t('status_col'), t('approved_by'), t('submitted_by'), '']}>
          {rows.map((r) => (
            <tr key={r.request_id}>
              <td>
                {r.needs_attention && (
                  <div>
                    <Chip tone="urgent">{t('needs_attention')}</Chip> {r.needs_attention}
                  </div>
                )}
                {returnTitle(t, r)}
                <div className="hint">{t('prepared_on', { date: formatDate(r.data_version.prepared_on, lang), n: r.data_version.version })}</div>
              </td>
              <td>
                {chip(r)}
                <div className="hint">{r.submission_label[lang]}</div>
              </td>
              <td>
                {r.approved_by ? (
                  <>
                    <bdi>{r.approved_by.name}</bdi>
                    <div className="hint">{t(`role_${r.approved_by.role}`, { defaultValue: r.approved_by.role })}</div>
                    <div className="hint">{when(r.decided_at, lang)}</div>
                  </>
                ) : (
                  '—'
                )}
              </td>
              <td>{r.submitted_by ? <bdi>{r.submitted_by}</bdi> : t('not_submitted')}</td>
              <td>
                <Link to={`/returns/approve/${r.request_id}`}>{t('open')}</Link>
              </td>
            </tr>
          ))}
        </Table>
      )}
    </Panel>
  )
}
