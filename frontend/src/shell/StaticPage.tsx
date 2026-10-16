import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, useParams } from 'react-router-dom'
import { Ident, Message, Skeleton } from '../components/ui'
import { Icon, type IconName } from '../components/Icon'
import { get } from '../lib/api'
import { formatDate } from '../lib/format'
import { BrandMark, LanguageToggle } from './Shell'
import './entry.css'

interface Verification {
  status: string
  status_label_en: string
  status_label_ar: string
  reference: string | null
  doc_type_label_en: string | null
  doc_type_label_ar: string | null
  issued_at: string | null
}

const VERIFY_TONE: Record<string, { tone: string; icon: IconName }> = {
  valid: { tone: 'ok', icon: 'check' },
  superseded: { tone: 'attention', icon: 'history' },
  not_found: { tone: 'neutral', icon: 'search' },
}

/** Public pages that need no sign-in: privacy notice, accessibility statement and document verification (SC9). */
export default function StaticPage({ page }: { page: 'privacy' | 'accessibility' | 'verify' }) {
  const { t, i18n } = useTranslation()
  const lang = i18n.language.startsWith('ar') ? 'ar' : 'en'
  const { code } = useParams()
  const [verify, setVerify] = useState<Verification | null>(null)
  const [failed, setFailed] = useState(false)
  useEffect(() => {
    if (page === 'verify' && code) get<Verification>(`/api/documents/verify/${encodeURIComponent(code)}`).then(setVerify).catch(() => setFailed(true))
  }, [page, code])
  const v = verify ? VERIFY_TONE[verify.status] ?? { tone: 'critical', icon: 'alert' as IconName } : null
  const a11y = ['a11y_keyboard', 'a11y_targets', 'a11y_contrast', 'a11y_rtl', 'a11y_motion', 'a11y_zoom']
  return (
    <div className="entry-static">
      <header className="entry-bar">
        <Link to="/signin" className="brand">
          <BrandMark />
          <span className="brand-text">
            <span className="brand-name">{t('app.short')}</span>
            <span className="brand-sub">{t('app.det')}</span>
          </span>
        </Link>
        <LanguageToggle />
      </header>
      <main className="entry-main">
        <article className="entry-article">
          <p className="page-eyebrow"><Icon name="info" size={14} />{t('entry.public_page')}</p>
          {page === 'privacy' && (
            <>
              <h1>{t('signin.privacy_title')}</h1>
              <p className="entry-prose">{t('signin.privacy_body')}</p>
            </>
          )}
          {page === 'accessibility' && (
            <>
              <h1>{t('shell.accessibility')}</h1>
              <p className="entry-prose">{t('entry.a11y_intro')}</p>
              <h2>{t('entry.a11y_standard_label')}</h2>
              <p className="entry-callout">{t('entry.a11y_standard')}</p>
              <h2>{t('entry.a11y_what')}</h2>
              <ul className="entry-list">
                {a11y.map((k) => <li key={k}><Icon name="check" size={18} /><span>{t(`entry.${k}`)}</span></li>)}
              </ul>
              <p className="entry-muted-note">{t('entry.a11y_contact')}</p>
            </>
          )}
          {page === 'verify' && (
            <>
              <h1>{t('entry.verify_title')}</h1>
              <p className="entry-prose muted">{t('entry.verify_lead')}</p>
              <p className="entry-code">{t('entry.verify_code')}: <Ident>{code}</Ident></p>
              {failed && <Message kind="error">{t('entry.verify_failed')}</Message>}
              {!verify && !failed && <Skeleton rows={3} />}
              {verify && v && (
                <div role="status" className={`entry-verify entry-verify-${v.tone}`}>
                  <span className="entry-verify-icon" aria-hidden="true"><Icon name={v.icon} size={26} /></span>
                  <div className="entry-verify-body">
                    <p className="entry-verify-label">{t('entry.verify_result')}</p>
                    <p className="entry-verify-status">{lang === 'ar' ? verify.status_label_ar : verify.status_label_en}</p>
                    {verify.reference && (
                      <dl className="kv">
                        <dt>{t('entry.verify_type')}</dt>
                        <dd>{lang === 'ar' ? verify.doc_type_label_ar : verify.doc_type_label_en}</dd>
                        <dt>{t('entry.verify_ref')}</dt>
                        <dd><Ident>{verify.reference}</Ident></dd>
                        {verify.issued_at && (<><dt>{t('entry.verify_issued')}</dt><dd>{formatDate(verify.issued_at, lang)}</dd></>)}
                      </dl>
                    )}
                  </div>
                </div>
              )}
              <p className="entry-muted-note">{t('entry.verify_note')}</p>
            </>
          )}
          <Link to="/signin" className="entry-back"><Icon name="chevron-start" size={18} className="flip-rtl" />{t('shell.back_to_signin')}</Link>
        </article>
      </main>
    </div>
  )
}
