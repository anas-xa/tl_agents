import { lazy } from 'react'
import { registerFeature, registerSlot } from '../registry'
import './i18n'

// SC5 Consent Centre (E4-S1..S6). Nav 'Consent' order 40.
registerFeature(
  [{ path: '/consent', element: lazy(() => import('./ConsentCentre')), permission: 'consent.view', scope: 'company' }],
  [{ path: '/consent', labelKey: 'nav.consent', icon: '✓', permission: 'consent.view', scope: 'company', order: 40 }],
)
registerSlot('settings.tabs', { id: 'data-links', labelKey: 'consent:tab_data_links', element: lazy(() => import('./DataLinksTab')), permission: 'dashboard.view', order: 30 })
registerSlot('dashboard.alerts', { id: 'link-alerts', labelKey: 'consent:links_title', element: lazy(() => import('./LinkAlerts')), permission: 'dashboard.view', order: 20 })
registerSlot('dashboard.panels', { id: 'data-links', labelKey: 'consent:links_title', element: lazy(() => import('./DashboardPanel')), permission: 'dashboard.view', order: 50 })
