import { useEffect, useState } from 'react'
import { get } from '../../lib/api'
import { Icon } from '../../components/Icon'
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
  const tone = st.state === 'approved' ? 'var(--ok)' : st.state === 'under_review' ? 'var(--attention)' : 'var(--accent)'
  return (
    <p className="residency-statement" data-state={st.state} style={{ display: 'flex', alignItems: 'flex-start', gap: 6, margin: 0, fontSize: compact ? 'var(--fs-xs)' : undefined, lineHeight: 1.5 }}>
      <span aria-hidden="true" style={{ color: tone, display: 'inline-flex', marginTop: compact ? 1 : 3, flex: 'none' }}><Icon name={st.state === 'under_review' ? 'clock' : 'shield'} size={compact ? 14 : 16} /></span>
      <span>
        {st.state === 'under_review' ? (
          <>
            <strong>{main}</strong>
            {!compact && <> {neutral}</>}
          </>
        ) : (
          main
        )}
        {st.state === 'approved' && st.label && <span className="notice-tbc"> ({st.label})</span>}
      </span>
    </p>
  )
}

export default ResidencyStatement
