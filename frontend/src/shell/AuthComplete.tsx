import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { useAuth } from '../app/auth'
import { Button, Message } from '../components/ui'
import { get, patch } from '../lib/api'

/** Landing after the UAE PASS callback: checks access, shows the one-time privacy notice, then routes home. */
export default function AuthComplete() {
  const { t } = useTranslation()
  const [params] = useSearchParams()
  const { refresh, me, loading, setCompanyId } = useAuth()
  const nav = useNavigate()
  const [showPrivacy, setShowPrivacy] = useState(false)
  useEffect(() => {
    refresh().then((data) => {
      if (!data) {
        nav('/signin?reason=SESSION_ENDED', { replace: true })
        return
      }
      if (!data.privacy_notice_seen) setShowPrivacy(true)
      else finish(data)
    })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])
  const finish = async (data: NonNullable<typeof me>) => {
    const rt = params.get('return_to')
    const safe = rt && rt.startsWith('/') && !rt.startsWith('//') ? rt : '/'
    if (data.companies.length === 0 && data.staff_roles.length === 0) {
      nav('/?no_company=1', { replace: true })
      return
    }
    // First run (SC2): an owner whose subscription welcome is still pending sees it once before the dashboard.
    const owned = data.companies.find((c) => c.roles.includes('owner') || c.roles.includes('remote_owner'))
    if (owned && safe === '/' && owned.permissions.includes('subscription.view')) {
      try {
        const w = await get<{ welcome?: { status: string } }>(`/api/companies/${owned.company_id}/welcome`)
        if (w.welcome?.status === 'pending') {
          setCompanyId(owned.company_id)
          nav('/welcome', { replace: true })
          return
        }
      } catch {
        /* welcome unavailable: never block the way in */
      }
    }
    nav(safe, { replace: true })
  }
  if (loading && !me) return <div className="signin-page"><div className="signin-card" role="status">{t('signin.checking')}</div></div>
  if (showPrivacy && me)
    return (
      <div className="signin-page">
        <div className="signin-card">
          <h1>{t('signin.privacy_title')}</h1>
          <Message kind="info">{t('signin.privacy_body')}</Message>
          <Button autoFocus onClick={async () => { await patch('/api/auth/me/preferences', { privacy_notice_version: '2025-01' }).catch(() => undefined); finish(me) }}>{t('signin.privacy_ok')}</Button>
        </div>
      </div>
    )
  return null
}
