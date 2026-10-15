import { lazy } from 'react'
import { registerFeature, registerSlot } from '../registry'
import './i18n'

registerFeature(
  [{ path: '/audit', element: lazy(() => import('./AuditPage')), permission: 'audit.view', scope: 'company' }],
  [{ path: '/audit', labelKey: 'nav.audit', icon: '🔎', permission: 'audit.view', scope: 'company', order: 30 }],
)
registerSlot('dashboard.panels', { id: 'audit', labelKey: 'audit:panel', element: lazy(() => import('./DashboardPanel')), permission: 'audit.view', order: 30 })
