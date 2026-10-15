import { render, screen, waitFor, fireEvent } from '@testing-library/react'
import fs from 'node:fs'
import i18n from 'i18next'
import '../../i18n'
import { initReactI18next } from 'react-i18next'
import './i18n'
import KpisTab from './KpisTab'
import LicenceLookup from './LicenceLookup'

const dir = '/tmp/claude-0/-home-user-tl-agents/8c4a5b2b-d7c2-57e0-a1e6-169e602930ff/scratchpad/kpi'
function mockFetch(dash: string) {
  globalThis.fetch = (async (url: string) => {
    const u = String(url)
    const body = u.includes('/settings') ? fs.readFileSync(dir + '/settings.json', 'utf8') : u.includes('/kpis/K1') ? fs.readFileSync(dir + '/k1.json', 'utf8') : u.includes('/licences/') ? JSON.stringify({ licence: { licence_number: 'DET-1', trade_name_en: 'X', trade_name_ar: 'س', issuing_authority: 'DET', licence_status: 'active', issue_date: '2024-01-01', expiry_date: '2027-01-01', subscription_status: 'active', subscription_badge: 'active', billing_status: 'billed', collection_status: 'collected', enrolment_mode: 'opt_in', subscription_start: '2026-01-01', subscription_end: '2026-12-31', cohort: 'PILOT1', wave: '1b', open_support_cases: 0 } }) : fs.readFileSync(dir + '/' + dash, 'utf8')
    return new Response(body, { status: 200, headers: { 'Content-Type': 'application/json' } })
  }) as unknown as typeof fetch
}

beforeAll(async () => {
  if (!i18n.isInitialized) await i18n.use(initReactI18next).init({ lng: 'en', fallbackLng: 'en', resources: {} })
})

for (const lng of ['en', 'ar']) {
  for (const dash of ['dash.json', 'dash_live.json']) {
    test('renders ' + dash + ' ' + lng, async () => {
      await i18n.changeLanguage(lng)
      mockFetch(dash)
      const { container } = render(<KpisTab />)
      await waitFor(() => expect(container.querySelectorAll('article').length).toBeGreaterThan(5))
      fireEvent.click(screen.getAllByRole('button', { name: lng === 'en' ? 'Show breakdown' : 'عرض التفصيل' })[0])
      await waitFor(() => expect(container.textContent).toContain(lng === 'en' ? 'Other (combined)' : 'أخرى (مجمّعة)'))
      for (const d of container.querySelectorAll('details')) d.setAttribute('open', '')
      const txt = container.textContent || ''
      expect(txt).not.toContain('undefined')
      expect(txt).not.toContain('NaN')
      expect(txt).not.toMatch(/kpis:|tbl\.|cnt\.|val\.|dim\./)
      fs.writeFileSync(dir + '/render_' + lng + '_' + dash + '.html', container.innerHTML)
    })
  }
}

test('lookup', async () => {
  await i18n.changeLanguage('en')
  mockFetch('dash.json')
  const { container } = render(<LicenceLookup />)
  fireEvent.change(screen.getByLabelText('Licence number'), { target: { value: 'DET-1' } })
  fireEvent.click(screen.getByRole('button', { name: 'Look up' }))
  await waitFor(() => expect(container.textContent).toContain('This view is logged'))
})
