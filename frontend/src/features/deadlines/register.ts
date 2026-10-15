import { lazy } from 'react'
import { registerFeature } from '../registry'
import './i18n'

// SC4 Deadline calendar and list (E1-S3 SC4 contract from the E3-S2 deadline engine). Nav 'Deadlines' order 10.
registerFeature(
  [{ path: '/deadlines', element: lazy(() => import('./Deadlines')), permission: 'deadlines.view', scope: 'company' }],
  [{ path: '/deadlines', labelKey: 'nav.deadlines', icon: '⏱', permission: 'deadlines.view', scope: 'company', order: 10 }],
)
