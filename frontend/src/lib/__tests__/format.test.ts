import { describe, expect, it } from 'vitest'
import { daysLeftLabel, daysLeftTier, digits, formatAED, formatDate, setNumeralStyle } from '../format'

describe('formatter (E1-S5)', () => {
  it('writes the month out in both languages', () => {
    expect(formatDate('2026-09-30', 'en')).toBe('30 September 2026')
    expect(formatDate('2026-09-30', 'ar')).toBe('30 سبتمبر 2026')
  })
  it('formats AED from fils with two decimals', () => {
    expect(formatAED(125000, 'en')).toBe('AED 1,250.00')
    expect(formatAED(60000, 'ar')).toBe('AED 600.00')
  })
  it('uses Arabic day-count agreement', () => {
    expect(daysLeftLabel(1, 'ar')).toBe('مستحق خلال يوم واحد')
    expect(daysLeftLabel(2, 'ar')).toBe('مستحق خلال يومان')
    expect(daysLeftLabel(5, 'ar')).toBe('مستحق خلال 5 أيام')
    expect(daysLeftLabel(12, 'ar')).toBe('مستحق خلال 12 يومًا')
    expect(daysLeftLabel(-1, 'ar')).toBe('متأخر منذ يوم واحد')
    expect(daysLeftLabel(0, 'ar')).toBe('مستحق اليوم')
    expect(daysLeftLabel(1, 'en')).toBe('Due in 1 day')
    expect(daysLeftLabel(-3, 'en')).toBe('Overdue by 3 days')
  })
  it('tiers days left per the versioned bands', () => {
    expect(daysLeftTier(45)).toBe('neutral')
    expect(daysLeftTier(20)).toBe('attention')
    expect(daysLeftTier(3)).toBe('urgent')
    expect(daysLeftTier(-1)).toBe('critical')
    expect(daysLeftTier(null)).toBe('unknown')
  })
  it('keeps Western digits unless the platform style says otherwise', () => {
    expect(digits('123', 'ar')).toBe('123')
    setNumeralStyle('arabic_indic')
    expect(digits('123', 'ar')).toBe('١٢٣')
    setNumeralStyle('western')
  })
})
