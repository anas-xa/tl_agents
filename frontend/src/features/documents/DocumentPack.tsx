import { useCallback, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'
import { useAuth } from '../../app/auth'
import { Icon } from '../../components/Icon'
import { Button, Chip, Disclosure, Empty, Field, Ident, Message, PageHeader, Panel, Skeleton } from '../../components/ui'
import { ApiError, get, post } from '../../lib/api'
import { formatDate, formatDateTime } from '../../lib/format'
import './documents.css'

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
  const { companyId, company } = useAuth()
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
  const companyName = company ? (lang === 'ar' ? company.trade_name_ar : company.trade_name_en) : null
  const anyDemo = !!data?.documents.some((d) => d.is_demo)
  const allDemo = !!data?.documents.length && data.documents.every((d) => d.is_demo)
  return (
    <div className="page doc-page">
      <PageHeader
        eyebrow={companyName ? <bdi>{companyName}</bdi> : undefined}
        title={t('title')}
        subtitle={t('ui.subtitle')}
        meta={anyDemo ? <Chip tone="neutral">{t('demo')}</Chip> : undefined}
      />
      {err && <Message kind="error">{t('error')} <Button variant="link" onClick={load}>{t('retry')}</Button></Message>}
      {!data && !err && <><p aria-live="polite">{t('loading')}</p><Skeleton rows={4} /></>}
      {data && data.documents.length === 0 && (data.role === 'delegate' ? <Empty icon="lock" title={t('ask_owner')} /> : <Empty icon="file" title={t('empty')} action={<Link className="btn btn-secondary" to="/deadlines"><Icon name="calendar" size={18} />{t('view_calendar')}</Link>} />)}
      {data && data.documents.length > 0 && (
        <ul className="doc-list">
          {data.documents.map((d) => (
            <li key={d.id} className="doc-row">
              <span className={`doc-icon doc-icon-${d.official ? 'official' : 'draft'}`} aria-hidden="true"><Icon name={d.official ? 'file-check' : 'file'} size={22} /></span>
              <div className="doc-main">
                <button type="button" className="doc-title" onClick={() => setSel(d.id)}>{pick(d.title, lang)}</button>
                <div className="doc-meta">
                  <Chip tone={TONE[d.status] ?? 'neutral'}>{t(`status.${d.status}`)}</Chip>
                  <span className="nowrap">{t('ui.version_n', { n: d.version_no })}</span>
                  <span className="nowrap">{t('ui.issued_on', { date: formatDate(d.issued_at, lang) })}</span>
                  {d.signer_name && <span>{t('signer', { name: d.signer_name, number: d.signer_licence })}</span>}
                </div>
                <div className="doc-labels">
                  <Chip tone="draft" icon="✎">{d.official ? t('ai_platform') : t('ai_draft')}</Chip>
                  {d.is_demo && !allDemo && <Chip tone="neutral">{t('demo')}</Chip>}
                </div>
                {d.watermark && <div className="doc-watermark">{pick(d.watermark, lang)}</div>}
              </div>
              <div className="doc-side">
                <div className="doc-code">
                  <span className="doc-code-label">{t('cols.code')}</span>
                  {d.verification_code ? <Link to={d.verify_path!} aria-label={`${t('ui.verify')}: ${d.verification_code}`}><Ident>{d.verification_code}</Ident></Link> : <span className="muted">{t('no_code')}</span>}
                </div>
                <Button variant="secondary" className="btn-sm" onClick={() => setSel(d.id)} aria-label={`${t('actions.open')}: ${pick(d.title, lang)}`}>
                  {t('actions.open')}
                  <Icon name="chevron-end" size={16} className="flip-rtl" />
                </Button>
              </div>
            </li>
          ))}
        </ul>
      )}
      {data && data.can_issue && (
        <section className="card doc-issue" aria-labelledby="doc-issue-title">
          <h2 id="doc-issue-title">{t('actions.issue')}</h2>
          <div className="doc-issue-row">
            <Field label={t('actions.issue_type')} id="issue-type">
              <select id="issue-type" value={issueType} onChange={(e) => setIssueType(e.target.value)}>
                <option value="" />
                {data.issuable_types.map((x) => <option key={x.doc_type} value={x.doc_type}>{pick(x.label, lang)}</option>)}
              </select>
            </Field>
            <Button disabled={!issueType} onClick={issue}>{t('actions.issue')}</Button>
          </div>
        </section>
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
  const back = (
    <button type="button" className="doc-back" onClick={onBack}>
      <Icon name="chevron-start" size={18} className="flip-rtl" />
      {t('ui.back')}
    </button>
  )
  if (err) return <div className="page doc-page">{back}<Message kind="error">{err}</Message><Button variant="secondary" onClick={onBack}>{t('retry')}</Button></div>
  if (!d) return <div className="page doc-page">{back}<p aria-live="polite">{t('checking')}</p><Skeleton rows={4} /></div>
  const renderUrl = `/api/companies/${companyId}/documents/${id}/render?lang=${previewLang}`
  const download = () => post<{ render_url: string }>(`/api/companies/${companyId}/documents/${id}/download`, { kind: 'downloaded', lang: previewLang === 'both' ? null : previewLang }).then(() => window.open(renderUrl, '_blank', 'noopener'))
  const share = () => post(`/api/companies/${companyId}/documents/${id}/share`, { identity_uuid: shareTo }).then(() => setMsg(t('actions.share_done'))).catch((e: ApiError) => setMsg(e.message))
  return (
    <div className="page doc-page">
      {back}
      <PageHeader
        eyebrow={t('title')}
        title={pick(d.title, lang)}
        meta={
          <>
            <Chip tone={TONE[d.status] ?? 'neutral'}>{t(`status.${d.status}`)}</Chip>
            <Chip tone="draft" icon="✎">{d.official ? t('ai_platform') : t('ai_draft')}</Chip>
            {d.bilingual_check && !d.bilingual_check.document_mismatch && <Chip tone="ok">{t('versions_match')}</Chip>}
            <span>{t('ui.reference')}: <Ident>{d.reference}</Ident></span>
          </>
        }
        actions={<Button onClick={download}><Icon name="download" size={18} />{d.official ? t('actions.download') : t('actions.download_draft')}</Button>}
      />
      {d.status === 'superseded' && <Message kind="warning">{t('superseded')}</Message>}
      {d.status === 'revoked' && <Message kind="error">{pick(d.revoked_label, lang)}</Message>}
      <div className="doc-detail">
        <section className="card doc-preview" aria-labelledby="doc-preview-title">
          <div className="doc-preview-head">
            <h2 id="doc-preview-title">{t('ui.preview')}</h2>
            <Field label={t('preview.lang')} id="pv-lang">
              <select id="pv-lang" value={previewLang} onChange={(e) => setPreviewLang(e.target.value as 'both' | 'en' | 'ar')}><option value="both">{t('preview.both')}</option><option value="en">{t('preview.en')}</option><option value="ar">{t('preview.ar')}</option></select>
            </Field>
          </div>
          <iframe title={pick(d.title, lang)} src={renderUrl} className="doc-frame" />
        </section>
        <div className="doc-aside">
          <Panel title={t('ui.details')}>
            <dl className="record">
              <dt>{t('cols.status')}</dt><dd>{t(`status.${d.status}`)}</dd>
              <dt>{t('cols.version')}</dt><dd><Ident>{d.version_no}</Ident></dd>
              <dt>{t('cols.issued')}</dt><dd>{formatDate(d.issued_at, lang)}</dd>
              {d.signer_name && <><dt>{t('status.signed')}</dt><dd>{t('signer', { name: d.signer_name, number: d.signer_licence })}</dd></>}
              <dt>{t('actions.verify_link')}</dt>
              <dd>{d.verification_code ? <Link to={d.verify_path!}><Ident>{d.verification_code}</Ident></Link> : <span className="muted">{t('no_code')}</span>}</dd>
            </dl>
            {d.provenance && (
              <Disclosure summary={t('provenance.title')}>
                <dl className="kv"><dt>{t('provenance.source')}</dt><dd><Ident>{d.provenance.source ?? '—'}</Ident></dd><dt>{t('provenance.model')}</dt><dd><Ident>{d.provenance.model_version}</Ident></dd><dt>{t('provenance.review')}</dt><dd>{t(`status.${d.provenance.review_status}`)}</dd><dt>{t('provenance.rule')}</dt><dd><Ident>{d.provenance.sig_rule_version}</Ident></dd></dl>
              </Disclosure>
            )}
            <div className="doc-aside-actions">
              <Button variant="secondary" className="btn-sm" onClick={() => get<{ event: string; by: string; at: string }[]>(`/api/companies/${companyId}/documents/${id}/download-log`).then(setLog)}><Icon name="history" size={16} />{t('actions.log')}</Button>
            </div>
            {log && (
              <ul className="doc-log">
                {log.map((r, i) => <li key={i}><span>{t(`log.events.${r.event}`)}</span><span className="muted">{r.by}</span><span className="muted nowrap">{formatDateTime(r.at, lang)}</span></li>)}
              </ul>
            )}
          </Panel>
          {role === 'owner' && (
            <Panel title={t('actions.share')}>
              <Field label={t('actions.share_who')} id="share-to"><input id="share-to" dir="ltr" value={shareTo} onChange={(e) => setShareTo(e.target.value)} /></Field>
              <Button variant="secondary" disabled={!shareTo} onClick={share}>{t('actions.share')}</Button>
              {msg && <Message kind="info">{msg}</Message>}
            </Panel>
          )}
        </div>
      </div>
    </div>
  )
}
