import { useEffect, useState } from 'react'
import { get } from '../../lib/api'
import { useBi, type Bi } from './lib'

interface Statement { state: 'neutral' | 'approved' | 'under_review'; en: string; ar: string; neutral: Bi; last_check_at: string | null; label: string | null }

/**
 * Owner residency statement line (footer, bank/financial consent screen, owner dashboard).
 * Inventory-driven: 'hosted in the UAE' wording only after the register passes; otherwise 'Residency under review'
 * with the neutral design statement; neutral while no inventory exists. Exported for the shell owner to wire.
 */
export function ResidencyStatement({ compact = false }: { compact?: boolean }) {
  const { tx } = useBi()
  const [st, setSt] = useState<Statement | null>(null)
  useEffect(() => {
    get<Statement>('/api/hosting/residency-statement').then(setSt).catch(() => setSt(null))
  }, [])
  if (!st) return null
  const main = tx(st)
  const neutral = tx(st.neutral)
  return (
    <p className="residency-statement" data-state={st.state} style={{ fontSize: compact ? '.85rem' : undefined }}>
      {st.state === 'under_review' ? (
        <>
          <strong>{main}</strong>
          {!compact && <> {neutral}</>}
        </>
      ) : (
        main
      )}
      {st.state === 'approved' && st.label && <span className="notice-tbc"> ({st.label})</span>}
    </p>
  )
}

export default ResidencyStatement
