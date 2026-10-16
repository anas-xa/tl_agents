import { useEffect, useMemo, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Icon } from '../../components/Icon'
import { Button, Chip } from '../../components/ui'
import { formatDate } from '../../lib/format'
import { tierTone, useBi, useFetch, type Obligation } from './lib'
import { DaysBadge } from './parts'

interface MonthCal { year: number; month: number; weekend_days: number[]; holidays: { jurisdiction: string; start_date: string; end_date: string; name: { en: string; ar: string }; list_version: string | null; list_version_date: string | null }[] }

const MONTHS_EN = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December']
const MONTHS_AR = ['يناير', 'فبراير', 'مارس', 'أبريل', 'مايو', 'يونيو', 'يوليو', 'أغسطس', 'سبتمبر', 'أكتوبر', 'نوفمبر', 'ديسمبر']

function iso(d: Date) {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

/** SC4 calendar month view (Gregorian primary): same data as the list; weekends and official holidays as text, never colour alone. */
export default function CalendarView({ rows, companyId, onOpen }: { rows: Obligation[]; companyId: string | null; onOpen: (id: string) => void }) {
  const { t, i18n } = useTranslation('deadlines')
  const { tx, lang } = useBi()
  const today = new Date()
  const firstDated = rows.find((r) => r.due_date)?.due_date
  const start = firstDated ? new Date(firstDated + 'T00:00:00') : today
  const [ym, setYm] = useState({ y: start.getFullYear(), m: start.getMonth() })
  const [focusDay, setFocusDay] = useState(1)
  const [openDay, setOpenDay] = useState<string | null>(null)
  const gridRef = useRef<HTMLDivElement>(null)
  const cal = useFetch<MonthCal>(companyId ? `/api/companies/${companyId}/deadline-calendar?month=${ym.y}-${String(ym.m + 1).padStart(2, '0')}` : null)
  const daysInMonth = new Date(ym.y, ym.m + 1, 0).getDate()
  const lead = (new Date(ym.y, ym.m, 1).getDay() + 6) % 7 // Monday-first grid
  const byDay = useMemo(() => {
    const map: Record<string, Obligation[]> = {}
    for (const r of rows) if (r.due_date) (map[r.due_date] ||= []).push(r)
    return map
  }, [rows])
  const holidays = useMemo(() => {
    const map: Record<string, string[]> = {}
    for (const h of cal.data?.holidays ?? []) {
      const d = new Date(h.start_date + 'T00:00:00')
      const end = new Date(h.end_date + 'T00:00:00')
      while (d <= end) {
        ;(map[iso(d)] ||= []).push(lang === 'ar' ? h.name.ar : h.name.en)
        d.setDate(d.getDate() + 1)
      }
    }
    return map
  }, [cal.data, lang])
  const listVersion = cal.data?.holidays[0]
  const weekend = cal.data?.weekend_days ?? [5, 6]
  useEffect(() => {
    const el = gridRef.current?.querySelector<HTMLButtonElement>(`[data-day="${focusDay}"]`)
    if (el && gridRef.current?.contains(document.activeElement)) el.focus()
  }, [focusDay, ym])
  const shiftMonth = (n: number) => {
    const d = new Date(ym.y, ym.m + n, 1)
    setYm({ y: d.getFullYear(), m: d.getMonth() })
    setFocusDay(1)
  }
  const onKey = (e: React.KeyboardEvent) => {
    const rtl = document.documentElement.dir === 'rtl'
    const step: Record<string, number> = { ArrowRight: rtl ? -1 : 1, ArrowLeft: rtl ? 1 : -1, ArrowDown: 7, ArrowUp: -7 }
    if (e.key in step) {
      e.preventDefault()
      setFocusDay(Math.min(daysInMonth, Math.max(1, focusDay + step[e.key])))
    } else if (e.key === 'Home') {
      e.preventDefault()
      setFocusDay(1)
    } else if (e.key === 'End') {
      e.preventDefault()
      setFocusDay(daysInMonth)
    } else if (e.key === 'PageUp' || e.key === 'PageDown') {
      e.preventDefault()
      shiftMonth(e.key === 'PageUp' ? -1 : 1)
    }
  }
  const monthName = (lang === 'ar' ? MONTHS_AR : MONTHS_EN)[ym.m]
  const weekdays = t('weekdays', { returnObjects: true }) as string[]
  const cells: (number | null)[] = [...Array(lead).fill(null), ...Array.from({ length: daysInMonth }, (_, i) => i + 1)]
  const undated = rows.filter((r) => !r.due_date)
  const openRows = openDay ? byDay[openDay] ?? [] : []
  return (
    <div>
      <div className="dln-cal-head">
        <Button variant="secondary" className="btn-sm dln-cal-nav" onClick={() => shiftMonth(-1)} aria-label={t('prev_month')}><Icon name="chevron-start" size={18} className="flip-rtl" /></Button>
        <h2 aria-live="polite">{monthName} {ym.y}</h2>
        <Button variant="secondary" className="btn-sm dln-cal-nav" onClick={() => shiftMonth(1)} aria-label={t('next_month')}><Icon name="chevron-end" size={18} className="flip-rtl" /></Button>
        <Button variant="link" onClick={() => setYm({ y: today.getFullYear(), m: today.getMonth() })}>{t('today')}</Button>
      </div>
      <p className="helper">{t('calendar_hint')}</p>
      {listVersion?.list_version && <p className="helper">{t('public_holiday')} · {t('list_version', { v: listVersion.list_version, date: formatDate(listVersion.list_version_date, i18n.language) })}</p>}
      <div ref={gridRef} role="grid" aria-label={`${monthName} ${ym.y}`} onKeyDown={onKey} className="dln-cal-grid">
        {weekdays.map((w) => <div key={w} role="columnheader" className="dln-cal-wd">{w}</div>)}
        {cells.map((d, i) => {
          if (d === null) return <div key={`b${i}`} role="gridcell" aria-hidden="true" />
          const date = new Date(ym.y, ym.m, d)
          const key = iso(date)
          const items = byDay[key] ?? []
          const isWeekend = weekend.includes((date.getDay() + 6) % 7)
          const hol = holidays[key]
          const label = `${formatDate(key, i18n.language)}${isWeekend ? `, ${t('weekend_label')}` : ''}${hol ? `, ${t('public_holiday')}: ${hol.join(', ')}` : ''}${items.length ? `, ${t('day_items', { n: items.length })}` : ''}`
          return (
            <div key={key} role="gridcell" className={`dln-cal-cell ${isWeekend || hol ? 'is-off' : ''} ${key === iso(today) ? 'is-today' : ''} ${items.length ? 'has-items' : ''}`}>
              <button data-day={d} tabIndex={d === focusDay ? 0 : -1} aria-label={label} onFocus={() => setFocusDay(d)} onClick={() => setOpenDay(items.length ? key : null)}>
                <span className="dln-cal-day">{d}</span>
                {isWeekend && <span className="dln-cal-note">{t('weekend_label')}</span>}
                {hol && <span className="dln-cal-note">★ {hol[0]}</span>}
                {items.slice(0, 2).map((o) => <span key={o.obligation_id} className={`dln-cal-item tier-${o.done ? 'done' : o.days_left_tier}`}><span aria-hidden="true">{o.done ? '✓' : tierTone(o.days_left_tier).icon} </span>{tx(o.name)}</span>)}
                {items.length > 2 && <span className="dln-cal-note">+{items.length - 2}</span>}
              </button>
            </div>
          )
        })}
      </div>
      {openDay && (
        <div className="dln-cal-open" role="region" aria-label={formatDate(openDay, i18n.language)}>
          <h3>{formatDate(openDay, i18n.language)}</h3>
          <ul>
            {openRows.map((o) => (
              <li key={o.obligation_id} style={{ marginBottom: 6 }}>
                <bdi>{tx(o.company_name)}</bdi>: {tx(o.name)} <DaysBadge o={o} /> <Button variant="link" onClick={() => onOpen(o.obligation_id)}>{t('open_detail')}</Button>
              </li>
            ))}
          </ul>
        </div>
      )}
      {undated.length > 0 && (
        <div style={{ marginTop: 12 }}>
          <h3>{t('undated')}</h3>
          <ul>{undated.map((o) => <li key={o.obligation_id}><bdi>{tx(o.company_name)}</bdi>: {tx(o.name)} <Chip tone="info" icon="?">{t('undated')}</Chip></li>)}</ul>
        </div>
      )}
    </div>
  )
}
