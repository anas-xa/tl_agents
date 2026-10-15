import { Suspense, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useSearchParams } from 'react-router-dom'
import { useAuth } from '../../app/auth'
import { Placeholder } from '../../components/Placeholder'
import { useSlotEntries } from '../../components/Slot'
import { Skeleton } from '../../components/ui'
import AccessBanner from './AccessBanner'
import ProfileTab from './ProfileTab'
import TeamTab from './TeamTab'

/** SC11 Team, delegates and settings. Tabs: team (owner full / delegate own view), profile, plus `settings.tabs` slot entries. */
export default function Settings() {
  const { t } = useTranslation('settings')
  const { me, companyId, can } = useAuth()
  const [params, setParams] = useSearchParams()
  const extra = useSlotEntries('settings.tabs')
  const showTeam = !!companyId && (can('delegates.manage', companyId) || can('settings.view_own', companyId))
  const [tab, setTab] = useState(params.get('tab') || (showTeam ? 'team' : 'profile'))
  if (!me || !companyId) return null
  if (!can('settings.manage', companyId) && !can('settings.view_own', companyId)) return <Placeholder variant="C" />
  const tabs = [
    // Team management is for the owner (delegates.manage) and a delegate's own rights view; a remote owner
    // manages no delegates in the MVP, so the tab is not offered rather than failing.
    ...(showTeam ? [{ id: 'team', label: t('tab_team') }] : []),
    { id: 'profile', label: t('tab_profile') },
    ...extra.map((e) => ({ id: e.id, label: t(e.labelKey.includes(':') ? e.labelKey : `settings:${e.labelKey}`) })),
  ]
  const select = (id: string) => {
    setTab(id)
    setParams({ tab: id }, { replace: true })
  }
  const Extra = extra.find((e) => e.id === tab)?.element as React.ComponentType | undefined
  return (
    <div className="settings-page">
      <style>{`
        .people-cards { display: none; }
        @media (max-width: 720px) { .people-table { display: none; } .people-cards { display: grid; gap: 12px; } }
        .switch { display: flex; align-items: flex-start; gap: 12px; padding: 10px 0; border-bottom: 1px solid var(--border); }
        .switch input { width: 44px; height: 24px; margin-top: 4px; flex: none; }
        .switch .switch-state { font-weight: 600; margin-inline-start: auto; }
        .switch .desc { color: var(--muted); font-size: .9rem; }
        .stepper { font-size: .9rem; color: var(--muted); margin-bottom: 8px; }
      `}</style>
      <h1>{t('title')}</h1>
      <AccessBanner />
      <div className="tabs" role="tablist" aria-label={t('title')}>
        {tabs.map((x) => (
          <button key={x.id} role="tab" id={`tab-${x.id}`} aria-selected={tab === x.id} aria-controls={`panel-${x.id}`} onClick={() => select(x.id)} onKeyDown={(e) => {
            const i = tabs.findIndex((y) => y.id === tab)
            if (e.key === 'ArrowRight' || e.key === 'ArrowLeft') {
              const dir = (e.key === 'ArrowRight') !== (document.documentElement.dir === 'rtl') ? 1 : -1
              select(tabs[(i + dir + tabs.length) % tabs.length].id)
            }
          }}>
            {x.label}
          </button>
        ))}
      </div>
      <div role="tabpanel" id={`panel-${tab}`} aria-labelledby={`tab-${tab}`}>
        {tab === 'team' && showTeam && <TeamTab companyId={companyId} />}
        {tab === 'profile' && <ProfileTab />}
        {Extra && (
          <Suspense fallback={<Skeleton rows={3} />}>
            <Extra />
          </Suspense>
        )}
      </div>
    </div>
  )
}
