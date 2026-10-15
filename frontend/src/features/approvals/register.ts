import { lazy } from 'react'
import { registerFeature, registerSlot } from '../registry'
import './i18n'

// SC7 Return review and approval (E6-S1, E6-S3). /returns/:packId is the draft pack viewer (tax feature).
registerFeature(
  [
    { path: '/returns', element: lazy(() => import('./ReturnsList')), permission: 'returns.view', scope: 'company' },
    { path: '/returns/approve/:requestId', element: lazy(() => import('./ApprovalScreen')), permission: 'returns.view', scope: 'company' },
  ],
  [{ path: '/returns', labelKey: 'nav.returns', icon: '✔', permission: 'returns.view', scope: 'company', order: 25 }],
)
// SC11 'Approval rights' (E6-S2, Phase B: locked while switched off) and SC14 'Approval compliance' (E6-S4).
registerSlot('settings.tabs', { id: 'approval-rights', labelKey: 'approvals:rights_tab', element: lazy(() => import('./ApprovalRightsTab')), permission: 'returns.view', order: 30 })
registerSlot('det.tabs', { id: 'approval-compliance', labelKey: 'approvals:comp_tab', element: lazy(() => import('./ComplianceTab')), permission: 'approval_compliance.view', order: 70 })
