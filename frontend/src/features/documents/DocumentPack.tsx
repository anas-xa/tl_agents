import { useCallback, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'
import { useAuth } from '../../app/auth'
import { Button, Chip, Empty, Field, Ident, Message, Panel, Skeleton, Table } from '../../components/ui'
import { ApiError, get, post } from '../../lib/api'
import { formatDate, formatDateTime } from '../../lib/format'

type Bi = { en: string; ar: string }
interface Doc {
  id: string; reference: string; doc_type: string; type_class: string; title: Bi; file_names: Bi; version_no: number; status: string; status_label: Bi; official: boolean; ai_label: Bi
  watermark: Bi | null; verification_code: string | null; verify_path: string | null; signer_name: string | null; signer_licence: string | null; issued_at: string; superseded_by_id: string | null
  revoked_at: string | null; revoked_label: Bi | null; banner: Bi | null; is_demo: boolean
  provenance?: { source: string | null; model_version: string; review_status: string; sig_rule_version: string }
  bilingual_check?: { document_mismatch: boolean; fields_mismatched: string[]; versions_match: Bi | null } | null
}
interface DocList { documents: Doc[]; role: string; empty: Bi | null; can_issue: boolean; issue_note: Bi | null; delegate_note: Bi | null; issuable_types: { doc_type: string; label: Bi; class: string }[] }

const pick = (b: Bi | null | undefined, lang: string) => (b ? (lang === 'ar' ? b.ar : b.en) : '')
const TONE: Record<string, 'neutral' | 'ok' | 'attention' | 'critical' | 'draft' | 'info'> = { draft: 'draft', issued: 'info', signed: 'ok', superseded: 'neutral', revoked: 'critical', in_review: 'info', withdrawn: 'neutral' }

/** SC9 Document pack: bilingual documents with AI-prepared label and status; downloads and sharing are logged. */
export default function DocumentPack() {
  const { t, i18n } = useTranslation('documents')
  const lang = i18n.language.startsWith('ar') ? 'ar' : 'en'
  const { companyId } = useAuth()
  const [data, setData] = useState<DocList | null>(null)
  const [err, setErr] = useState(false)
  const [sel, setSel] = useState<string | null>(null)
  const [issueType, setIssueType] = useState('')
  const [msg, setMsg] = useState<{ kind: 'error' | 'success' | 'info'; text: string } | null>(null)
  const load = useCallback(() => {
    if (!companyId) return
    get<DocList>(`/api/companies/${companyId}/documents`).then((d) => { setData(d); setErr(false) }).catch(() => setErr(true))
  }, [companyId])
  useEffect(() => { load() }, [load])
  const issue = async () => {
    try {
      await post(`/api/companies/${companyId}/documents/issue`, { doc_type: issueType })
      setMsg({ kind: 'success', text: t('versions_match') })
      load()
    } catch (e) {
      const ex = e as ApiError
      const details = ex.details as { fields?: string[] } | undefined
      setMsg({ kind: 'error', text: ex.code === 'BILINGUAL_MISMATCH' ? t('refused_mismatch', { field: (details?.fields ?? []).join(', ') }) : ex.code === 'SIGNATURE_REQUIRED' || ex.code === 'FEATURE_SWITCHED_OFF' ? t('refused_signature') : t('issue_failed') })
    }
  }
  if (sel) return <DocDetail id={sel} lang={lang} companyId={companyId!} role={data?.role ?? ''} onBack={() => { setSel(null); load() }} />
  return (
    <div>
      <h1>{t('title')}</h1>
      {err && <Message kind="error">{t('error')} <Button variant="link" onClick={load}>{t('retry')}</Button></Message>}
      {!data && !err && <><p aria-live="polite">{t('loading')}</p><Skeleton rows={4} /></>}
      {data && data.documents.length === 0 && (data.role === 'delegate' ? <Empty title={t('ask_owner')} /> : <Empty title={t('empty')} action={<Link to="/deadlines">{t('view_calendar')}</Link>} />)}
      {data && data.documents.length > 0 && (
        <Table headers={[t('cols.document'), t('cols.status'), t('cols.version'), t('cols.issued'), t('cols.code')]}>
          {data.documents.map((d) => (
            <tr key={d.id}>
              <td>
                <button type="button" className="btn btn-link" onClick={() => setSel(d.id)}>{pick(d.title, lang)}</button>
                <br /><Chip tone="draft" icon="✎">{d.official ? t('ai_platform') : t('ai_draft')}</Chip>{d.is_demo && <> <Chip tone="neutral">{t('demo')}</Chip></>}
                {d.watermark && <div className="watermark" style={{ fontSize: '.8rem' }}>{pick(d.watermark, lang)}</div>}
              </td>
              <td><Chip tone={TONE[d.status] ?? 'neutral'}>{t(`status.${d.status}`)}</Chip>{d.signer_name && <div>{t('signer', { name: d.signer_name, number: d.signer_licence })}</div>}</td>
              <td><Ident>{d.version_no}</Ident></td>
              <td>{formatDate(d.issued_at, lang)}</td>
              <td>{d.verification_code ? <Link to={d.verify_path!}><Ident>{d.verification_code}</Ident></Link> : <span className="muted">{t('no_code')}</span>}</td>
            </tr>
          ))}
        </Table>
      )}
      {data && data.can_issue && (
        <Panel title={t('actions.issue')}>
          <Field label={t('actions.issue_type')} id="issue-type">
            <select id="issue-type" value={issueType} onChange={(e) => setIssueType(e.target.value)}>
              <option value="" />
              {data.issuable_types.map((x) => <option key={x.doc_type} value={x.doc_type}>{pick(x.label, lang)}</option>)}
            </select>
          </Field>
          <Button disabled={!issueType} onClick={issue}>{t('actions.issue')}</Button>
        </Panel>
      )}
      {data?.issue_note && <p className="muted">{pick(data.issue_note, lang)}</p>}
      {msg && <Message kind={msg.kind}>{msg.text}</Message>}
    </div>
  )
}

function DocDetail({ id, lang, companyId, role, onBack }: { id: string; lang: string; companyId: string; role: string; onBack: () => void }) {
  const { t } = useTranslation('documents')
  const [d, setD] = useState<Doc | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [previewLang, setPreviewLang] = useState<'both' | 'en' | 'ar'>('both')
  const [log, setLog] = useState<{ event: string; by: string; at: string }[] | null>(null)
  const [shareTo, setShareTo] = useState('')
  const [msg, setMsg] = useState<string | null>(null)
  useEffect(() => {
    get<Doc>(`/api/companies/${companyId}/documents/${id}`).then(setD).catch((e: ApiError) => setErr(e.code === 'DOCUMENT_NOT_SHARED' ? t('ask_owner') : t('error')))
  }, [companyId, id, t])
  if (err) return <div><Message kind="error">{err}</Message><Button variant="secondary" onClick={onBack}>{t('retry')}</Button></div>
  if (!d) return <div><p aria-live="polite">{t('checking')}</p><Skeleton rows={4} /></div>
  const renderUrl = `/api/companies/${companyId}/documents/${id}/render?lang=${previewLang}`
  const download = () => post<{ render_url: string }>(`/api/companies/${companyId}/documents/${id}/download`, { kind: 'downloaded', lang: previewLang === 'both' ? null : previewLang }).then(() => window.open(renderUrl, '_blank', 'noopener'))
  const share = () => post(`/api/companies/${companyId}/documents/${id}/share`, { identity_uuid: shareTo }).then(() => setMsg(t('actions.share_done'))).catch((e: ApiError) => setMsg(e.message))
  return (
    <div>
      <Button variant="secondary" onClick={onBack}>{t('title')}</Button>
      <h1>{pick(d.title, lang)}</h1>
      <p><Chip tone="draft" icon="✎">{d.official ? t('ai_platform') : t('ai_draft')}</Chip> <Chip tone={TONE[d.status] ?? 'neutral'}>{t(`status.${d.status}`)}</Chip> <Ident>{d.reference}</Ident></p>
      {d.status === 'superseded' && <Message kind="warning">{t('superseded')}</Message>}
      {d.status === 'revoked' && <Message kind="error">{pick(d.revoked_label, lang)}</Message>}
      {d.bilingual_check && !d.bilingual_check.document_mismatch && <p><Chip tone="ok">{t('versions_match')}</Chip></p>}
      {d.verification_code && <p>{t('actions.verify_link')}: <Link to={d.verify_path!}><Ident>{d.verification_code}</Ident></Link></p>}
      {d.provenance && (
        <Panel title={t('provenance.title')}>
          <dl className="kv"><dt>{t('provenance.source')}</dt><dd><Ident>{d.provenance.source ?? '—'}</Ident></dd><dt>{t('provenance.model')}</dt><dd><Ident>{d.provenance.model_version}</Ident></dd><dt>{t('provenance.review')}</dt><dd>{t(`status.${d.provenance.review_status}`)}</dd><dt>{t('provenance.rule')}</dt><dd><Ident>{d.provenance.sig_rule_version}</Ident></dd></dl>
        </Panel>
      )}
      <Field label={t('preview.lang')} id="pv-lang">
        <select id="pv-lang" value={previewLang} onChange={(e) => setPreviewLang(e.target.value as 'both' | 'en' | 'ar')}><option value="both">{t('preview.both')}</option><option value="en">{t('preview.en')}</option><option value="ar">{t('preview.ar')}</option></select>
      </Field>
      <iframe title={pick(d.title, lang)} src={renderUrl} style={{ width: '100%', minHeight: 420, border: '1px solid var(--border)', borderRadius: 8 }} />
      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginTop: 12 }}>
        <Button onClick={download}>{d.official ? t('actions.download') : t('actions.download_draft')}</Button>
        <Button variant="secondary" onClick={() => get<{ event: string; by: string; at: string }[]>(`/api/companies/${companyId}/documents/${id}/download-log`).then(setLog)}>{t('actions.log')}</Button>
      </div>
      {role === 'owner' && (
        <Panel title={t('actions.share')}>
          <Field label={t('actions.share_who')} id="share-to"><input id="share-to" dir="ltr" value={shareTo} onChange={(e) => setShareTo(e.target.value)} /></Field>
          <Button variant="secondary" disabled={!shareTo} onClick={share}>{t('actions.share')}</Button>
          {msg && <Message kind="info">{msg}</Message>}
        </Panel>
      )}
      {log && (
        <Table headers={[t('log.event'), t('log.by'), t('log.at')]}>
          {log.map((r, i) => <tr key={i}><td>{t(`log.events.${r.event}`)}</td><td>{r.by}</td><td>{formatDateTime(r.at, lang)}</td></tr>)}
        </Table>
      )}
    </div>
  )
}
