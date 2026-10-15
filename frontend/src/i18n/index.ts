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

const EXPLICIT_KEY = 'qx_lang_explicit'

/** A language chosen explicitly during this visit (toggle or ?lang= on sign-in) outranks the saved profile. */
export function markExplicitLanguage(lang: 'ar' | 'en') {
  try {
    sessionStorage.setItem(EXPLICIT_KEY, lang)
  } catch {
    /* storage unavailable: precedence falls back to profile */
  }
}
export function explicitLanguage(): 'ar' | 'en' | null {
  try {
    const v = sessionStorage.getItem(EXPLICIT_KEY)
    return v === 'ar' || v === 'en' ? v : null
  } catch {
    return null
  }
}

/** Precedence (E1-S5): explicit choice this visit > profile (applied after sign-in) > cookie > browser > Arabic. */
export function initialLanguage(): 'ar' | 'en' {
  const url = new URLSearchParams(window.location.search).get('lang')
  if ((url === 'ar' || url === 'en') && window.location.pathname.startsWith('/signin')) markExplicitLanguage(url)
  if (url === 'ar' || url === 'en') return url
  const explicit = explicitLanguage()
  if (explicit) return explicit
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
writeCookieLang(i18n.language as 'ar' | 'en')
i18n.on('languageChanged', (lng) => {
  applyDirection(lng)
  writeCookieLang(lng as 'ar' | 'en')
})

export default i18n
