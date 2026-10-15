import { useTranslation } from 'react-i18next'
import { Link, useParams } from 'react-router-dom'
import { LanguageToggle } from './Shell'
import { useEffect, useState } from 'react'
import { get } from '../lib/api'
import { Message } from '../components/ui'

export default function StaticPage({ page }: { page: 'privacy' | 'accessibility' | 'verify' }) {
  const { t } = useTranslation()
  const { code } = useParams()
  const [verify, setVerify] = useState<Record<string, unknown> | null>(null)
  const [err, setErr] = useState(false)
  useEffect(() => {
    if (page === 'verify' && code) get<Record<string, unknown>>(`/api/documents/verify/${code}`).then(setVerify).catch(() => setErr(true))
  }, [page, code])
  return (
    <div className="signin-page">
      <div className="signin-card wide">
        <div className="signin-top"><LanguageToggle /></div>
        {page === 'privacy' && (<><h1>{t('signin.privacy_title')}</h1><p>{t('signin.privacy_body')}</p></>)}
        {page === 'accessibility' && (<><h1>{t('shell.accessibility')}</h1><p>WCAG 2.2 AA (assumed DET standard until DET states otherwise). Keyboard operable, 44 px targets, 4.5:1 text contrast, right-to-left mirroring, reduced motion, 200% zoom.</p></>)}
        {page === 'verify' && (
          <>
            <h1>{t('nav.documents')}</h1>
            {err && <Message kind="error">{t('common.no_results')}</Message>}
            {verify && <pre className="verify">{JSON.stringify(verify, null, 2)}</pre>}
          </>
        )}
        <p><Link to="/signin">{t('shell.back_to_signin')}</Link></p>
      </div>
    </div>
  )
}
