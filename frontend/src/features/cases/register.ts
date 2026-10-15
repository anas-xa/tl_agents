import { lazy } from 'react'
import { registerFeature, registerSlot } from '../registry'
import './i18n'

registerFeature(
  [{ path: '/cases', element: lazy(() => import('./CaseQueue')), permission: 'cases.queue.view', scope: 'staff' }],
  [{ path: '/cases', labelKey: 'nav.cases', icon: '☷', permission: 'cases.queue.view', scope: 'staff', order: 72 }],
)
registerSlot('det.tabs', { id: 'escalations', labelKey: 'cases:det_tab', element: lazy(() => import('./EscalationsTab')), permission: 'escalation_dashboard.view', order: 60 })
