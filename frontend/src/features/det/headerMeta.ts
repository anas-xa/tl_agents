import { createContext, useContext, useEffect, type ReactNode } from 'react'
import { formatDate } from '../../lib/format'

/**
 * Lets a DET dashboard tab place its data provenance line (demo data, minimum group size, data as of, version)
 * in the page header meta row instead of repeating it at the top of the tab.
 */
export const DetHeaderMetaContext = createContext<((node: ReactNode) => void) | null>(null)

export function useDetHeaderMeta(node: ReactNode, deps: unknown[]) {
  const set = useContext(DetHeaderMetaContext)
  useEffect(() => {
    set?.(node)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [set, ...deps])
  useEffect(() => () => set?.(null), [set])
  return !!set
}

/** Today's date in Dubai as YYYY-MM-DD (for reply-by and deadline clocks). */
export function dubaiToday(): string {
  return new Date().toLocaleDateString('en-CA', { timeZone: 'Asia/Dubai' })
}

/** Whole calendar days from today (Dubai) to an ISO date; negative when past. */
export function daysUntil(date: string | null | undefined): number | null {
  if (!date) return null
  const a = Date.parse(dubaiToday())
  const b = Date.parse(date.slice(0, 10))
  if (Number.isNaN(b)) return null
  return Math.round((b - a) / 86400000)
}

/** Calendar date of a timestamp in Dubai (a timestamp without zone is UTC, as formatDateTime reads it). */
export function formatDubaiDate(value: string | null | undefined, lang: string): string {
  if (!value) return ''
  if (value.length === 10) return formatDate(value, lang)
  const d = new Date(value.endsWith('Z') || value.includes('+') ? value : value + 'Z')
  if (Number.isNaN(d.getTime())) return ''
  return formatDate(new Date(d.toLocaleString('en-US', { timeZone: 'Asia/Dubai' })), lang)
}
