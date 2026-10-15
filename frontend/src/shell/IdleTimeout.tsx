import { useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../app/auth'
import { post } from '../lib/api'
import { Button, Dialog } from '../components/ui'

/** Idle-timeout warning (WCAG 2.2.1): 2 minutes before the 15-minute idle timeout; one-action extend. */
export function IdleTimeout() {
  const { t } = useTranslation()
  const { me, signOut, markSessionEnded } = useAuth()
  const nav = useNavigate()
  const [warn, setWarn] = useState(false)
  const lastActivity = useRef(Date.now())
  const idleMs = (me?.session.idle_timeout_minutes ?? 15) * 60 * 1000
  const warnMs = (me?.session.warning_minutes ?? 2) * 60 * 1000

  useEffect(() => {
    const bump = () => {
      lastActivity.current = Date.now()
    }
    const events = ['mousemove', 'keydown', 'click', 'touchstart', 'scroll']
    events.forEach((e) => window.addEventListener(e, bump, { passive: true }))
    const id = setInterval(async () => {
      const idle = Date.now() - lastActivity.current
      if (idle >= idleMs) {
        markSessionEnded()
        await signOut().catch(() => undefined)
        nav('/signin?reason=SESSION_ENDED')
      } else if (idle >= idleMs - warnMs) {
        setWarn(true)
      }
    }, 10000)
    return () => {
      events.forEach((e) => window.removeEventListener(e, bump))
      clearInterval(id)
    }
  }, [idleMs, warnMs, signOut, nav, markSessionEnded])

  if (!me) return null
  return (
    <Dialog open={warn} title={t('signin.idle_warning')} onClose={() => setWarn(false)} labelledBy="idle-title">
      <div className="actions">
        <Button autoFocus onClick={async () => { lastActivity.current = Date.now(); setWarn(false); await post('/api/auth/keepalive').catch(() => undefined) }}>{t('signin.stay')}</Button>
        <Button variant="secondary" onClick={async () => { await signOut(); nav('/signin') }}>{t('shell.sign_out')}</Button>
      </div>
    </Dialog>
  )
}
