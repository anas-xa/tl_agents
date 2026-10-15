import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import { ApiError, get, patch, post } from '../lib/api'
import { setNumeralStyle, type NumeralStyle } from '../lib/format'
import { explicitLanguage, markExplicitLanguage } from '../i18n'

export interface CompanySummary {
  company_id: string
  trade_name_en: string
  trade_name_ar: string
  roles: string[]
  rights: string[]
  functions: string[]
  permissions: string[]
}

export interface Me {
  identity_uuid: string
  display_name: string
  assurance_level: string
  profile_type: number
  det_match_result: string
  language: string
  numerals: string
  staff_roles: string[]
  companies: CompanySummary[]
  staff_permissions: string[]
  session: { idle_timeout_minutes: number; warning_minutes: number; idle_expires_at: string; absolute_expires_at: string }
  privacy_notice_seen: boolean
}

interface AuthState {
  me: Me | null
  loading: boolean
  error: string | null
  companyId: string | null
  company: CompanySummary | null
  setCompanyId: (id: string) => void
  refresh: () => Promise<Me | null>
  signOut: () => Promise<void>
  can: (permission: string, companyId?: string | null) => boolean
  hasStaff: (...roles: string[]) => boolean
  sessionEnded: boolean
  markSessionEnded: () => void
  setLanguage: (lang: 'ar' | 'en') => Promise<void>
}

const AuthContext = createContext<AuthState | null>(null)
const COMPANY_KEY = 'qx_company'

export function AuthProvider({ children }: { children: ReactNode }) {
  const { i18n } = useTranslation()
  const [me, setMe] = useState<Me | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [sessionEnded, setSessionEnded] = useState(false)
  const [companyId, setCompanyIdState] = useState<string | null>(() => {
    try {
      return localStorage.getItem(COMPANY_KEY)
    } catch {
      return null
    }
  })

  const refresh = useCallback(async () => {
    setLoading(true)
    try {
      const data = await get<Me>('/api/auth/me')
      setMe(data)
      setError(null)
      // Profile language applies unless the user chose a language explicitly during this visit, which is saved.
      const explicit = explicitLanguage()
      if (explicit) {
        if (explicit !== i18n.language) i18n.changeLanguage(explicit)
        if (data.language !== explicit) patch('/api/auth/me/preferences', { language: explicit }).catch(() => undefined)
      } else if (data.language && data.language !== i18n.language) i18n.changeLanguage(data.language)
      setNumeralStyle((data.numerals as NumeralStyle) || 'western')
      return data
    } catch (e) {
      setMe(null)
      if (e instanceof ApiError && e.status === 401) {
        if (e.code === 'SESSION_ENDED') setSessionEnded(true)
        setError(null)
      } else {
        setError((e as Error).message)
      }
      return null
    } finally {
      setLoading(false)
    }
  }, [i18n])

  useEffect(() => {
    refresh()
  }, [refresh])

  // Keep the session alive while the user is active; show the idle warning dialog near timeout (shell).
  useEffect(() => {
    if (!me) return
    const id = setInterval(() => {
      post('/api/auth/keepalive').catch((e) => {
        if (e instanceof ApiError && e.status === 401) {
          setMe(null)
          setSessionEnded(true)
        }
      })
    }, 5 * 60 * 1000)
    return () => clearInterval(id)
  }, [me])

  const companies = me?.companies ?? []
  const effectiveCompanyId = companyId && companies.some((c) => c.company_id === companyId) ? companyId : companies[0]?.company_id ?? null
  const company = companies.find((c) => c.company_id === effectiveCompanyId) ?? null

  const setCompanyId = useCallback((id: string) => {
    setCompanyIdState(id)
    try {
      localStorage.setItem(COMPANY_KEY, id)
    } catch {
      /* ignore */
    }
  }, [])

  const value = useMemo<AuthState>(
    () => ({
      me,
      loading,
      error,
      companyId: effectiveCompanyId,
      company,
      setCompanyId,
      refresh,
      signOut: async () => {
        try {
          await post('/api/auth/signout')
        } finally {
          setMe(null)
          try {
            localStorage.removeItem(COMPANY_KEY)
          } catch {
            /* ignore */
          }
        }
      },
      can: (permission, cid) => {
        if (!me) return false
        if (me.staff_permissions.includes(permission)) return true
        const c = cid === undefined ? company : companies.find((x) => x.company_id === cid)
        return !!c && c.permissions.includes(permission)
      },
      hasStaff: (...roles) => !!me && roles.some((r) => me.staff_roles.includes(r)),
      sessionEnded,
      markSessionEnded: () => setSessionEnded(true),
      setLanguage: async (lang) => {
        markExplicitLanguage(lang)
        i18n.changeLanguage(lang)
        if (me) {
          // Profile save: retried 3 times with increasing delay; the session keeps the language regardless.
          for (let attempt = 0; attempt < 3; attempt++) {
            try {
              await patch('/api/auth/me/preferences', { language: lang })
              return
            } catch {
              await new Promise((r) => setTimeout(r, 300 * (attempt + 1)))
            }
          }
        }
      },
    }),
    [me, loading, error, effectiveCompanyId, company, setCompanyId, refresh, companies, sessionEnded, i18n],
  )
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth outside AuthProvider')
  return ctx
}

export function roleLabelKey(role: string) {
  return `roles.${role}`
}
