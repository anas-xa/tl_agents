import i18n from 'i18next'
import { initReactI18next } from 'react-i18next'
import en from './en.json'
import ar from './ar.json'

/**
 * Language precedence (E1-S5): explicit choice this visit > profile > cookie > browser > Arabic.
 * The cookie holds the language only.
 */
export const LANG_COOKIE = 'qx_lang'

export function readCookieLang(): 'ar' | 'en' | null {
  const m = document.cookie.match(/(?:^|; )qx_lang=(ar|en)/)
  return m ? (m[1] as 'ar' | 'en') : null
}

export function writeCookieLang(lang: 'ar' | 'en') {
  document.cookie = `${LANG_COOKIE}=${lang}; path=/; max-age=31536000; samesite=lax`
}

export function initialLanguage(): 'ar' | 'en' {
  const url = new URLSearchParams(window.location.search).get('lang')
  if (url === 'ar' || url === 'en') return url
  const cookie = readCookieLang()
  if (cookie) return cookie
  const browser = (navigator.language || '').toLowerCase()
  if (browser.startsWith('en')) return 'en'
  return 'ar'
}

export function applyDirection(lang: string) {
  document.documentElement.lang = lang
  document.documentElement.dir = lang === 'ar' ? 'rtl' : 'ltr'
}

i18n.use(initReactI18next).init({
  resources: { en: { translation: en }, ar: { translation: ar } },
  lng: initialLanguage(),
  fallbackLng: false,
  interpolation: { escapeValue: false },
  returnNull: false,
})

applyDirection(i18n.language)
i18n.on('languageChanged', (lng) => {
  applyDirection(lng)
  writeCookieLang(lng as 'ar' | 'en')
})

export default i18n
