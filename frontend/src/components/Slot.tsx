import { Suspense } from 'react'
import { useAuth } from '../app/auth'
import { SLOTS, type SlotName } from '../features/registry'
import { Skeleton } from './ui'

/** Renders every registered entry of a slot that the current user may see. */
export function Slot({ name, wrap }: { name: SlotName; wrap?: (id: string, node: React.ReactNode, labelKey: string) => React.ReactNode }) {
  const { can, companyId, me } = useAuth()
  const entries = SLOTS[name].filter((e) => !e.permission || can(e.permission, companyId) || (me?.staff_permissions.includes(e.permission) ?? false))
  return (
    <>
      {entries.map((e) => {
        const El = e.element as React.ComponentType
        const node = (
          <Suspense key={e.id} fallback={<Skeleton rows={2} />}>
            <El />
          </Suspense>
        )
        return wrap ? <div key={e.id}>{wrap(e.id, node, e.labelKey)}</div> : node
      })}
    </>
  )
}

export function useSlotEntries(name: SlotName) {
  const { can, companyId, me } = useAuth()
  return SLOTS[name].filter((e) => !e.permission || can(e.permission, companyId) || (me?.staff_permissions.includes(e.permission) ?? false))
}
