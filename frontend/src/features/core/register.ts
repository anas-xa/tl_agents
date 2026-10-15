import { lazy } from 'react'
import { registerFeature, registerHome } from '../registry'

registerFeature(
  [
    { path: '/', element: lazy(() => import('./Home')), scope: 'any' },
    { path: '/admin/config', element: lazy(() => import('./ConfigRegister')), permission: 'config.view', scope: 'staff' },
    { path: '/admin/audit-trail', element: lazy(() => import('./AuditTrail')), permission: 'audit_trail.view', scope: 'staff' },
    { path: '/admin/staff-roles', element: lazy(() => import('./StaffRoles')), permission: 'staff_roles.manage', scope: 'staff' },
  ],
  [
    { path: '/', labelKey: 'nav.home', icon: '⌂', scope: 'any', order: 0 },
    { path: '/admin/audit-trail', labelKey: 'nav.audit_trail', icon: '☰', permission: 'audit_trail.view', scope: 'staff', order: 90 },
    { path: '/admin/config', labelKey: 'nav.admin', icon: '⚙', permission: 'config.view', scope: 'staff', order: 95 },
  ],
)

/** Staff accounts (no company role) land on their own workspace; the first matching role wins. */
const STAFF_HOME: [string, string, string][] = [
  ['licensed_auditor', 'engagements.view', '/auditor'],
  ['det_complaint_handler', 'complaints.handle', '/det/requests'],
  ['det_pilot_manager', 'det.aggregates.view', '/det'],
  ['det_admin', 'det.aggregates.view', '/det'],
  ['det_compliance_lead', 'det.aggregates.view', '/det'],
  ['tax_specialist', 'cases.queue.view', '/cases'],
  ['legal_specialist', 'cases.queue.view', '/cases'],
  ['escalation_ops', 'cases.queue.view', '/cases'],
  ['compliance_reviewer', 'audit_trail.view', '/admin/audit-trail'],
  ['platform_security_admin', 'audit_trail.view', '/admin/audit-trail'],
  ['qeonix_product_owner', 'config.view', '/admin/config'],
]
registerHome((me) => {
  if (me.companies.length > 0) return null
  for (const [role, permission, path] of STAFF_HOME) {
    if (me.staff_roles.includes(role) && me.staff_permissions.includes(permission)) return path
  }
  return null
})
