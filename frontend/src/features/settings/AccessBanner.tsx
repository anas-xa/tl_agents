import { useCallback, useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../../app/auth'
import { Button, Message, Panel } from '../../components/ui'
import { get, post } from '../../lib/api'
import type { Change } from './types'

/**
 * Delegate access-change banner and access-ended screen (SC11). A 30-second background check (config
 * `delegates.rights_cache_ttl_seconds`) picks up rights edits and removals; the banner is never auto-dismissed
 * and focus moves to its heading once. Owners see nothing here (their confirmation is in their own session).
 */
export default function AccessBanner() {
  const { t, i18n } = useTranslation('settings')
  const { me, refresh } = useAuth()
  const nav = useNavigate()
  const [changes, setChanges] = useState<Change[]>([])
  const [interval, setIntervalSec] = useState(30)
  const heading = useRef<HTMLHeadingElement>(null)
  const announced = useRef<string | null>(null)
  const lang = i18n.language.startsWith('ar') ? 'ar' : 'en'

  const check = useCallback(async () => {
    try {
      const r = await get<{ changes: Change[]; check_interval_seconds: number }>('/api/delegates/my-access-changes')
      setChanges(r.changes)
      setIntervalSec(r.check_interval_seconds || 30)
    } catch {
      /* session ended or offline: the next request shows the real state */
    }
  }, [])
  useEffect(() => {
    if (!me) return
    check()
    const id = setInterval(check, Math.max(5, interval) * 1000)
    return () => clearInterval(id)
  }, [me, check, interval])
  useEffect(() => {
    const first = changes[0]
    if (first && announced.current !== first.id) {
      announced.current = first.id
      heading.current?.focus()
    }
  }, [changes])
  if (!me || changes.length === 0) return null
  const c = changes[0]
  const company = (lang === 'ar' ? c.company_name_ar : c.company_name_en) || c.company_id
  const ack = async (go: string) => {
    try {
      await post(`/api/delegates/my-access-changes/${c.id}/ack`)
    } finally {
      setChanges((xs) => xs.filter((x) => x.id !== c.id))
      await refresh()
      nav(go)
    }
  }
  if (c.change_type === 'removed' || c.change_type === 'suspended' || c.change_type === 'authority_suspended') {
    return (
      <Panel tone="warning" id="access-ended">
        <h2 ref={heading} tabIndex={-1}>{t('access_removed', { company })}</h2>
        <p>{t('access_changed_full', { company })}</p>
        <div className="actions">
          <Button onClick={() => ack('/')}>{t('back_to_companies')}</Button>
        </div>
      </Panel>
    )
  }
  return (
    <Message kind="info" id="access-changed">
      <h2 ref={heading} tabIndex={-1} style={{ fontSize: '1rem', margin: 0 }}>{t('access_changed_banner', { company })}</h2>
      <div className="actions">
        <Button onClick={() => ack(`/settings?tab=team`)}>{t('review_access')}</Button>
      </div>
    </Message>
  )
}
