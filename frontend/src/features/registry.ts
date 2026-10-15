import type { ComponentType, LazyExoticComponent } from 'react'
import type { Me } from '../app/auth'

/**
 * Feature registry. Each feature's `register.ts` calls these functions; nothing else is shared.
 *
 * - routes/nav: pages and primary navigation (company-scoped or staff).
 * - home resolvers: where a role lands after sign-in.
 * - slots: named extension points inside shared screens (SC3 dashboard panels, SC11 settings tabs,
 *   SC14 DET dashboard tabs, SC2 welcome checklist items). Owners of those screens render the slot.
 */
export interface FeatureRoute {
  path: string
  element: LazyExoticComponent<ComponentType<unknown>> | ComponentType<unknown>
  permission?: string
  scope?: 'company' | 'staff' | 'any'
  /** When the role lacks the permission: Placeholder C (default) or A (feature not in this phase). */
  fallback?: 'A' | 'C'
}

export interface NavItem {
  path: string
  labelKey: string
  icon: string
  permission?: string
  scope?: 'company' | 'staff' | 'any'
  order: number
}

export type SlotName = 'dashboard.panels' | 'settings.tabs' | 'det.tabs' | 'welcome.checklist' | 'help.sections' | 'dashboard.alerts'

export interface SlotEntry {
  id: string
  labelKey: string
  element: LazyExoticComponent<ComponentType<unknown>> | ComponentType<unknown>
  permission?: string
  order: number
}

export type HomeResolver = (me: Me, companyId: string | null) => string | null

export const ROUTES: FeatureRoute[] = []
export const NAV: NavItem[] = []
export const SLOTS: Record<SlotName, SlotEntry[]> = { 'dashboard.panels': [], 'settings.tabs': [], 'det.tabs': [], 'welcome.checklist': [], 'help.sections': [], 'dashboard.alerts': [] }
export const HOME_RESOLVERS: HomeResolver[] = []

export function registerFeature(routes: FeatureRoute[], nav: NavItem[] = []) {
  ROUTES.push(...routes)
  NAV.push(...nav)
}

export function registerSlot(slot: SlotName, entry: SlotEntry) {
  SLOTS[slot].push(entry)
  SLOTS[slot].sort((a, b) => a.order - b.order)
}

export function registerHome(resolver: HomeResolver) {
  HOME_RESOLVERS.push(resolver)
}
