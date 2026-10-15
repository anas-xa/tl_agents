import { lazy } from 'react'
import { registerSlot } from '../registry'
import './i18n'

/**
 * E9-S1 SC14: 'Pilot KPIs' is the first DET dashboard tab (order 5 so it sorts ahead of the residency tab,
 * which also uses order 10); the per-licence operational view is a separate tab for roles with det.per_licence.view.
 */
registerSlot('det.tabs', { id: 'pilot-kpis', labelKey: 'kpis:tab', element: lazy(() => import('./KpisTab')), permission: 'det.aggregates.view', order: 5 })
registerSlot('det.tabs', { id: 'licence-lookup', labelKey: 'kpis:lookup_tab', element: lazy(() => import('./LicenceLookup')), permission: 'det.per_licence.view', order: 7 })
