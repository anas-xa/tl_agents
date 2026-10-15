import { lazy } from 'react'
import { registerFeature, registerSlot } from '../registry'
import './i18n'

// SC6 Tax workspace (E5-S1, E5-S2) and the draft pack viewer (E5-S3). Nav 'Tax workspace' order 20.
// The owner approval act (E6-S1) lives at /returns and is built separately; /returns/:packId is this viewer.
registerFeature(
  [
    { path: '/tax', element: lazy(() => import('./TaxWorkspace')), permission: 'tax.view', scope: 'company' },
    { path: '/returns/:packId', element: lazy(() => import('./DraftViewer')), permission: 'returns.view', scope: 'company' },
  ],
  [{ path: '/tax', labelKey: 'nav.tax', icon: '%', permission: 'tax.view', scope: 'company', order: 20 }],
)
registerSlot('dashboard.panels', { id: 'tax', labelKey: 'tax:panel_title', element: lazy(() => import('./DashboardPanel')), permission: 'tax.view', order: 20 })
