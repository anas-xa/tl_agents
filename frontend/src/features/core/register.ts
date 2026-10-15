import { lazy } from 'react'
import { registerFeature } from '../registry'

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
