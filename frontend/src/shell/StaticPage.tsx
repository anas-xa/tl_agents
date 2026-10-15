import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, useParams } from 'react-router-dom'
import { Chip, Ident, Message, Skeleton } from '../components/ui'
import { get } from '../lib/api'
import { formatDate } from '../lib/format'
import { LanguageToggle } from './Shell'

interface Verification {
  status: string
  status_label_en: string
  status_label_ar: string
  reference: string | null
  doc_type_label_en: string | null
  doc_type_label_ar: string | null
  issued_at: string | null
}

const COPY = {
  en: { title: 'Document verification', code: 'Verification code', type: 'Document', ref: 'Reference', issued: 'Issued on', note: 'This page shows the status of a document issued through Smart Licence Services. It never shows amounts or company financial details.', failed: 'We could not check this code right now. Try again in a few minutes.' },
  ar: { title: 'التحقق من المستند', code: 'رمز التحقق', type: 'المستند', ref: 'المرجع', issued: 'تاريخ الإصدار', note: 'تعرض هذه الصفحة حالة مستند صادر عبر خدمات الرخصة الذكية، ولا تعرض أي مبالغ أو بيانات مالية للشركة.', failed: 'تعذر التحقق من هذا الرمز الآن. حاول مرة أخرى بعد دقائق.' },
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
  const c = COPY[lang]
  const tone = verify?.status === 'valid' ? 'ok' : verify?.status === 'not_found' ? 'neutral' : verify?.status === 'superseded' ? 'attention' : 'critical'
  return (
    <div className="signin-page">
      <div className="signin-card wide">
        <div className="signin-top"><LanguageToggle /></div>
        {page === 'privacy' && (<><h1>{t('signin.privacy_title')}</h1><p>{t('signin.privacy_body')}</p></>)}
        {page === 'accessibility' && (<><h1>{t('shell.accessibility')}</h1><p>WCAG 2.2 AA (assumed DET standard until DET states otherwise). Keyboard operable, 44 px targets, 4.5:1 text contrast, right-to-left mirroring, reduced motion, 200% zoom.</p></>)}
        {page === 'verify' && (
          <>
            <h1>{c.title}</h1>
            <p className="muted">{c.code}: <Ident>{code}</Ident></p>
            {failed && <Message kind="error">{c.failed}</Message>}
            {!verify && !failed && <Skeleton rows={3} />}
            {verify && (
              <div role="status">
                <p><Chip tone={tone}>{lang === 'ar' ? verify.status_label_ar : verify.status_label_en}</Chip></p>
                {verify.reference && (
                  <dl className="kv">
                    <dt>{c.type}</dt>
                    <dd>{lang === 'ar' ? verify.doc_type_label_ar : verify.doc_type_label_en}</dd>
                    <dt>{c.ref}</dt>
                    <dd><Ident>{verify.reference}</Ident></dd>
                    {verify.issued_at && (<><dt>{c.issued}</dt><dd>{formatDate(verify.issued_at, lang)}</dd></>)}
                  </dl>
                )}
              </div>
            )}
            <p className="muted" style={{ marginTop: 16 }}>{c.note}</p>
          </>
        )}
        <p><Link to="/signin">{t('shell.back_to_signin')}</Link></p>
      </div>
    </div>
  )
}
