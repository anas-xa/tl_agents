import { lazy } from 'react'
import { registerFeature, registerSlot } from '../registry'
import './i18n'

// SC11: owners (settings.manage) manage people; delegates (settings.view_own) see their own rights. The page
// itself gates on either permission, so the route carries none; the two nav entries never overlap.
registerFeature(
  [{ path: '/settings', element: lazy(() => import('./Settings')), scope: 'company' }],
  [
    { path: '/settings', labelKey: 'nav.team', icon: '👥', permission: 'settings.manage', scope: 'company', order: 50 },
    { path: '/settings', labelKey: 'nav.team', icon: '👥', permission: 'settings.view_own', scope: 'company', order: 50 },
  ],
)
registerSlot('dashboard.alerts', { id: 'delegate-access-banner', labelKey: 'settings:access_changed_banner', element: lazy(() => import('./AccessBanner')), order: 1 })
registerSlot('det.tabs', { id: 'delegation-overview', labelKey: 'settings:det_title', element: lazy(() => import('./DetDelegationOverview')), permission: 'det.aggregates.view', order: 60 })
