import { lazy } from 'react'
import { registerFeature } from '../registry'
import './i18n'

registerFeature(
  [{ path: '/det/requests', element: lazy(() => import('./RequestsAndComplaints')), scope: 'any' }],
  [
    { path: '/det/requests', labelKey: 'detops:nav', icon: '✉', permission: 'complaints.handle', scope: 'staff', order: 82 },
    { path: '/det/requests', labelKey: 'detops:nav', icon: '✉', permission: 'det.cases.decide', scope: 'staff', order: 82 },
  ],
)
