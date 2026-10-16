import { useCallback, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useAuth } from '../../app/auth'
import { Icon } from '../../components/Icon'
import { Button, Chip, Dialog, Field, Message, Panel, Skeleton } from '../../components/ui'
import { ApiError, api, del, get } from '../../lib/api'
import { formatDate, formatDateTime } from '../../lib/format'
import { useLinks } from './LinkStatusList'
import { useLang } from './parts'
import type { Upload, UploadsOut } from './types'
import './consent.css'

const PURPOSES = ['bookkeeping_classification', 'vat_return_preparation', 'corporate_tax_return_preparation', 'audit_preparation', 'deadline_compliance']
const EXPORTS = ['trial_balance', 'general_ledger', 'sales_invoices', 'purchase_invoices']

/** SC11 'Data links' tab: ERP connector register (empty in the pilot), file upload with its notice record, history. */
export default function DataLinksTab() {
  const { t } = useTranslation('consent')
  const lang = useLang()
  const { companyId, can, company } = useAuth()
  const links = useLinks(companyId)
  const [uploads, setUploads] = useState<UploadsOut | null>(null)
  const [loadErr, setLoadErr] = useState(false)
  const [toDelete, setToDelete] = useState<Upload | null>(null)
  const load = useCallback(async () => {
    if (!companyId) return
    try {
      setUploads(await get<UploadsOut>(`/api/companies/${companyId}/uploads?lang=${lang}`))
      setLoadErr(false)
    } catch {
      setLoadErr(true)
    }
  }, [companyId, lang])
  useEffect(() => {
    load()
  }, [load])
  if (!companyId) return null
  const isOwner = !!company?.roles.some((r) => r === 'owner' || r === 'remote_owner')
  const remoteReadOnly = !!links.data?.remote_owner_read_only
  const canLinks = can('links.manage', companyId) && !remoteReadOnly
  const canUpload = can('uploads.manage', companyId)
  const erpLinks = links.data?.erp_links ?? []
  const supported = links.data?.erp.supported_systems ?? []
  const remove = async () => {
    if (!toDelete) return
    try {
      await del(`/api/companies/${companyId}/uploads/${toDelete.upload_id}`)
    } finally {
      setToDelete(null)
      load()
      links.reload()
    }
  }
  return (
    <div>
      <Panel title={t('erp_title')}>
        {links.loading && !links.data ? (
          <Skeleton rows={2} />
        ) : (
          <>
            {erpLinks.length === 0 && <p>{t('erp_empty')}</p>}
            {supported.length === 0 && (
              <div className="dl-erp-empty">
                <Chip tone="neutral" icon="◌">{t('erp_not_available')}</Chip>
                <p>{t('erp_not_available_body')}</p>
              </div>
            )}
            {erpLinks.map((l) => {
              const run = l.runs[0]
              return (
                <div key={l.link_id} className="dl-erp">
                  <div className="dl-erp-head">
                    <strong><bdi>{l.system_type === 'file_export' ? t('kind_erp') : l.system_type}</bdi></strong>
                    <Chip tone={l.chip === 'connected' ? 'ok' : l.chip === 'disconnected' ? 'neutral' : 'attention'} icon={l.chip === 'connected' ? '✓' : l.chip === 'disconnected' ? '⏹' : '!'}>{t(`erp_chip.${l.chip}`)}</Chip>
                    {l.link_type === 'manual upload' && <Chip tone="draft" icon="✎">{t('manual_chip')}</Chip>}
                  </div>
                  {l.last_refreshed_at && <p className="dl-line">{t('erp_last', { date: formatDateTime(l.last_refreshed_at, lang), n: l.data_version })}</p>}
                  <p className="dl-meta">{t('erp_connected_by', { name: l.created_by ?? '-', role: l.created_by_role ?? '-', date: formatDate(l.created_at.slice(0, 10), lang) })}</p>
                  {run && run.failed_count > 0 && <Message kind="warning">{t('erp_attention', { m: run.failed_count })}</Message>}
                  {run && run.needs_mapping.length > 0 && <p className="dl-meta">{t('needs_mapping', { codes: run.needs_mapping.join(', ') })}</p>}
                </div>
              )
            })}
            <div className="actions dl-connect">
              <Button aria-disabled="true" aria-describedby="erp-connect-reason" variant="secondary" className="btn-sm" onClick={(e) => e.preventDefault()}>{t('erp_connect')}</Button>
              <span id="erp-connect-reason" className="muted">
                {!canLinks ? (remoteReadOnly ? t('erp_no_permission') : t('erp_ask_function')) : t('erp_not_available')}
              </span>
            </div>
            <p className="dl-meta">{t('erp_secure')} {t('erp_disconnect_note')}</p>
          </>
        )}
      </Panel>
      {canUpload && uploads && <UploadForm companyId={companyId} limits={uploads.limits} banks={links.data?.banks ?? []} onDone={() => { load(); links.reload() }} />}
      <Panel title={t('history_title')}>
        {loadErr && <Message kind="error">{t('status_load_failed')} <Button variant="link" onClick={load}>{t('retry')}</Button></Message>}
        {!uploads && !loadErr && <Skeleton rows={3} />}
        {uploads && uploads.uploads.length === 0 && <p>{t('history_empty')}</p>}
        {uploads && uploads.uploads.length > 0 && (
          <ul className="dl-history">
            {uploads.uploads.map((u) => (
              <li key={u.upload_id}>
                <span className="dl-file-icon" aria-hidden="true"><Icon name="file" size={18} /></span>
                <div className="dl-history-main">
                  <div className="dl-history-title">
                    <bdi dir="ltr" className="dl-file">{u.file_name}</bdi>
                    <Chip tone={u.status === 'ready' ? 'ok' : u.status === 'quarantined' ? 'urgent' : u.status === 'rejected' ? 'critical' : 'neutral'} icon={u.status === 'ready' ? '✓' : '✕'}>{t(`up_status.${u.status}`)}</Chip>
                    <Chip tone="draft" icon="✎">{t('manual_chip')}</Chip>
                    {u.is_demo && <span className="tag">{t('demo')}</span>}
                    {u.statement_age_badge === 'update_due' && u.kind === 'bank_statement' && u.status === 'ready' && <Chip tone="attention" icon="◷">{t('update_due')}</Chip>}
                  </div>
                  <div className="dl-meta dl-history-meta">
                    <span>{u.kind === 'erp_export' ? t(`export.${u.export_type}`) : <><bdi>{u.bank_name ?? ''}</bdi> <bdi dir="ltr">{u.account_masked ?? ''}</bdi></>}</span>
                    <span><span className="visually-hidden">{t('col_period')}: </span>{u.period_start && u.period_end ? <><span className="nowrap">{formatDate(u.period_start, lang)}</span> – <span className="nowrap">{formatDate(u.period_end, lang)}</span></> : '-'}</span>
                    {u.data_as_of && u.kind === 'bank_statement' && u.status === 'ready' && <span>{t('data_as_of', { date: formatDate(u.data_as_of, lang) })}</span>}
                    <span><span className="visually-hidden">{t('col_rows')}: </span>{t('rows_summary', { accepted: u.rows_accepted, rejected: u.rows_rejected, dup: u.rows_skipped_duplicate })}</span>
                    <span><span className="visually-hidden">{t('col_by')}: </span>{u.uploaded_by} · <span className="nowrap">{formatDateTime(u.uploaded_at, lang)}</span></span>
                  </div>
                  {(u.rejection_cause || u.quarantine_reason) && <div className="dl-meta">{t(`rejected.${u.rejection_cause ?? u.quarantine_reason}`)}</div>}
                </div>
                {isOwner && u.status !== 'deleted' && <div className="dl-history-action"><Button variant="secondary" className="btn-sm" onClick={() => setToDelete(u)}>{t('delete')}</Button></div>}
              </li>
            ))}
          </ul>
        )}
      </Panel>
      <Dialog open={!!toDelete} title={t('delete_title')} onClose={() => setToDelete(null)} labelledBy="del-title">
        <p>{t('delete_warning')}</p>
        <div className="dialog-actions">
          <Button variant="secondary" autoFocus onClick={() => setToDelete(null)}>{t('translation:common.cancel')}</Button>
          <Button variant="danger" onClick={remove}>{t('delete')}</Button>
        </div>
      </Dialog>
    </div>
  )
}

function UploadForm({ companyId, limits, banks, onDone }: { companyId: string; limits: UploadsOut['limits']; banks: { bank_id: string; name_en: string; name_ar: string }[]; onDone: () => void }) {
  const { t } = useTranslation('consent')
  const lang = useLang()
  const [kind, setKind] = useState<'bank_statement' | 'erp_export'>('bank_statement')
  const [exportType, setExportType] = useState(EXPORTS[0])
  const [bankId, setBankId] = useState(banks[0]?.bank_id ?? '')
  const [account, setAccount] = useState('')
  const [ps, setPs] = useState('')
  const [pe, setPe] = useState('')
  const [purpose, setPurpose] = useState(PURPOSES[0])
  const [ack, setAck] = useState(false)
  const [file, setFile] = useState<File | null>(null)
  const [busy, setBusy] = useState(false)
  const [result, setResult] = useState<{ kind: 'success' | 'error' | 'warning'; text: string } | null>(null)
  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!file) return
    const fd = new FormData()
    fd.append('file', file)
    fd.append('kind', kind)
    if (kind === 'erp_export') fd.append('export_type', exportType)
    else {
      const bank = banks.find((b) => b.bank_id === bankId)
      if (bankId) fd.append('bank_id', bankId)
      if (bank) fd.append('bank_name', bank.name_en)
      if (account) fd.append('account_ref', account)
    }
    if (ps) fd.append('period_start', ps)
    if (pe) fd.append('period_end', pe)
    fd.append('purpose', purpose)
    fd.append('notice_acknowledged', ack ? 'true' : 'false')
    fd.append('notice_version', limits.notice_version)
    setBusy(true)
    setResult(null)
    try {
      const u = await api<Upload>(`/api/companies/${companyId}/uploads`, { method: 'POST', body: fd })
      if (u.status === 'ready') setResult({ kind: 'success', text: `${t('upload_ready')} ${t('you_uploaded')}` })
      else setResult({ kind: u.status === 'quarantined' ? 'warning' : 'error', text: t(`rejected.${u.rejection_cause ?? u.quarantine_reason}`) })
      setFile(null)
      setAck(false)
      onDone()
    } catch (x) {
      setResult({ kind: 'error', text: x instanceof ApiError && x.status === 403 ? x.message : t('upload_failed') })
    } finally {
      setBusy(false)
    }
  }
  return (
    <Panel title={t('upload_title')} actions={<span className="dl-meta">{t('not_bank_link')}</span>}>
      {result && <Message kind={result.kind}>{result.text}</Message>}
      <form onSubmit={submit} className="dl-form">
        <fieldset className="dl-kind">
          <legend>{t('upload_kind')}</legend>
          <div className="dl-seg">
            {(['bank_statement', 'erp_export'] as const).map((k) => (
              <label key={k} className={kind === k ? 'is-on' : undefined}>
                <input type="radio" name="upload-kind" checked={kind === k} onChange={() => setKind(k)} /> {k === 'bank_statement' ? t('kind_bank') : t('kind_erp')}
              </label>
            ))}
          </div>
        </fieldset>
        {kind === 'erp_export' ? (
          <Field label={t('export_type')} id="u-export">
            <select id="u-export" value={exportType} onChange={(e) => setExportType(e.target.value)}>
              {EXPORTS.map((x) => <option key={x} value={x}>{t(`export.${x}`)}</option>)}
            </select>
          </Field>
        ) : (
          <>
            <Field label={t('upload_bank')} id="u-bank">
              <select id="u-bank" value={bankId} onChange={(e) => setBankId(e.target.value)}>
                {banks.map((b) => <option key={b.bank_id} value={b.bank_id}>{lang === 'ar' ? b.name_ar : b.name_en}</option>)}
              </select>
            </Field>
            <Field label={t('upload_account')} id="u-acc">
              <input id="u-acc" dir="ltr" value={account} onChange={(e) => setAccount(e.target.value)} autoComplete="off" />
            </Field>
          </>
        )}
        <Field label={t('upload_period_start')} id="u-ps"><input id="u-ps" type="date" value={ps} onChange={(e) => setPs(e.target.value)} /></Field>
        <Field label={t('upload_period_end')} id="u-pe"><input id="u-pe" type="date" value={pe} onChange={(e) => setPe(e.target.value)} /></Field>
        <Field label={t('upload_purpose')} id="u-purpose">
          <select id="u-purpose" value={purpose} onChange={(e) => setPurpose(e.target.value)}>
            {PURPOSES.map((p) => <option key={p} value={p}>{t(`purpose.${p}`)}</option>)}
          </select>
        </Field>
        <Field label={t('upload_file', { mb: limits.max_size_mb, rows: limits.max_rows })} id="u-file" required>
          <input id="u-file" type="file" accept=".csv,.xlsx,.pdf" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
        </Field>
        <div className="dl-notice">
          <h3>{t('notice_title')} <span className="muted">(<bdi dir="ltr">{limits.notice_version}</bdi>)</span></h3>
          <p>{lang === 'ar' ? limits.notice_ar : limits.notice_en}</p>
          <label className="check">
            <input type="checkbox" checked={ack} onChange={(e) => setAck(e.target.checked)} /> {t('notice_ack')}
          </label>
          {!ack && <p className="muted">{t('notice_needed')}</p>}
        </div>
        {busy && file && <p role="status" aria-live="polite" className="dl-wide">{t('uploading', { name: file.name })}</p>}
        <div className="dl-wide"><Button type="submit" disabled={!file || busy}><Icon name="upload" size={18} />{t('upload_btn')}</Button></div>
      </form>
    </Panel>
  )
}
