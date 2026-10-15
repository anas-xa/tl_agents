import { useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { useAuth } from '../app/auth'
import { Button, Message } from '../components/ui'
import { post } from '../lib/api'
import { explicitLanguage } from '../i18n'
import { LanguageToggle } from './Shell'

/** SC1 Sign-in. UAE PASS only; no fallback link (settled). */
export default function SignIn() {
  const { t, i18n } = useTranslation()
  const [params] = useSearchParams()
  const { me, sessionEnded } = useAuth()
  const nav = useNavigate()
  const reason = params.get('reason')
  const ref = params.get('ref')
  const [stage, setStage] = useState<'idle' | 'redirecting'>('idle')
  const [longWait, setLongWait] = useState(false)
  const [state, setState] = useState<string | null>(null)
  const primary = useRef<HTMLButtonElement>(null)
  const panel = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (me) nav('/', { replace: true })
  }, [me, nav])
  useEffect(() => {
    if (reason) panel.current?.querySelector<HTMLElement>('[role]')?.focus()
  }, [reason])

  const start = async () => {
    setStage('redirecting')
    const timer = setTimeout(() => setLongWait(true), 8000)
    try {
      const returnTo = params.get('return_to')
      const safeReturn = returnTo && returnTo.startsWith('/') && !returnTo.startsWith('//') ? returnTo : undefined
      const res = await post<{ redirect_url: string; state: string }>(`/api/auth/start?language=${i18n.language}${explicitLanguage() ? '&explicit_language=true' : ''}${safeReturn ? `&return_to=${encodeURIComponent(safeReturn)}` : ''}`)
      setState(res.state)
      window.location.assign(res.redirect_url)
    } catch {
      clearTimeout(timer)
      setStage('idle')
      nav('/signin?reason=PROVIDER_UNAVAILABLE')
    }
  }
  const cancel = async () => {
    if (state) await post(`/api/auth/cancel?state=${state}`).catch(() => undefined)
    setStage('idle')
    setLongWait(false)
    setTimeout(() => primary.current?.focus(), 0)
  }

  const isInfo = reason === 'CANCELLED' || reason === 'SESSION_ENDED'
  const messageKey = reason === 'SESSION_ENDED' ? 'signin.session_ended' : reason ? `signin.${reason}` : null

  return (
    <div className="signin-page">
      <div className="signin-card">
        <div className="signin-top"><LanguageToggle /></div>
        <h1>{t('app.name')}</h1>
        <p className="muted">{t('app.det')}</p>
        <div ref={panel}>
          {(sessionEnded && !reason) && <Message kind="info">{t('signin.session_ended')}</Message>}
          {messageKey && (
            <Message kind={isInfo ? 'info' : 'error'}>
              <p>{t(messageKey)}</p>
              {ref && <p className="muted">{t('signin.reference')}: <bdi dir="ltr">{ref}</bdi></p>}
            </Message>
          )}
          {params.get('no_company') && <Message kind="info">{t('signin.no_company')}</Message>}
        </div>
        {stage === 'redirecting' ? (
          <div className="interstitial" role="status" aria-live="polite">
            <span className="spinner" aria-hidden="true" />
            <p>{t('signin.redirecting')}</p>
            {longWait && (
              <>
                <p>{t('signin.long_wait')}</p>
                <Button variant="secondary" onClick={start}>{t('signin.try_again')}</Button>
              </>
            )}
            <Button variant="link" onClick={cancel}>{t('signin.cancel')}</Button>
          </div>
        ) : (
          <>
            <Button ref={primary} className="uaepass-btn" onClick={start}>
              <span className="uaepass-logo" aria-hidden="true">ID</span> <bdi dir="ltr">{t('signin.button')}</bdi>
            </Button>
            <p className="helper">{t('signin.helper')}</p>
          </>
        )}
        <p className="det-support">{t('shell.det_support')}</p>
        <footer className="signin-footer">
          <a href="/help">{t('shell.help')}</a> · <a href="/privacy">{t('shell.privacy')}</a> · <a href="/accessibility">{t('shell.accessibility')}</a>
        </footer>
      </div>
    </div>
  )
}
