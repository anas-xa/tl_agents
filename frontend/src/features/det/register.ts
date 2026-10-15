import { lazy } from 'react'
import { registerFeature, registerSlot } from '../registry'
import './i18n'

/** SC14 DET admin dashboard (skeleton; E9 adds the KPI tiles through the det.tabs slot). */
registerFeature(
  [{ path: '/det', element: lazy(() => import('./DetDashboard')), permission: 'det.aggregates.view', scope: 'staff' }],
  [{ path: '/det', labelKey: 'nav.det', icon: '▦', permission: 'det.aggregates.view', scope: 'staff', order: 80 }],
)
registerSlot('det.tabs', { id: 'residency', labelKey: 'det:residency_title', element: lazy(() => import('./ResidencyTab')), permission: 'det.aggregates.view', order: 10 })
registerSlot('det.tabs', { id: 'phases', labelKey: 'det:phases_title', element: lazy(() => import('./PhaseMapTab')), permission: 'det.aggregates.view', order: 20 })
registerSlot('det.tabs', { id: 'integrations', labelKey: 'det:integrations_title', element: lazy(() => import('./IntegrationsTab')), permission: 'det.aggregates.view', order: 30 })
registerSlot('det.tabs', { id: 'availability', labelKey: 'det:availability_title', element: lazy(() => import('./AvailabilityTab')), permission: 'det.aggregates.view', order: 40 })
// Owner SC3 panel and SC2 checklist entry (rendered by the dashboard-core screens built by the E3 agent).
registerSlot('dashboard.panels', { id: 'whats-live', labelKey: 'det:wl_title', element: lazy(() => import('./WhatsLivePanel')), permission: 'dashboard.view', order: 90 })
registerSlot('welcome.checklist', { id: 'k12', labelKey: 'det:k12_title', element: lazy(() => import('./K12Checklist')), permission: 'dashboard.view', order: 20 })
