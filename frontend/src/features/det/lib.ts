import { useCallback, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { ApiError, get } from '../../lib/api'

export type Bi = { en: string; ar: string }

/** Picks the current language from a bilingual backend text. */
export function useBi() {
  const { i18n } = useTranslation()
  const lang = i18n.language.startsWith('ar') ? 'ar' : 'en'
  return { lang, tx: (b: Bi | null | undefined) => (b ? b[lang] || b.en : '') }
}

/** Fetch with loading / error / retry; keeps the last good value while refreshing (spec: last known, dated). */
export function useFetch<T>(path: string | null, deps: unknown[] = []) {
  const [data, setData] = useState<T | null>(null)
  const [error, setError] = useState<ApiError | Error | null>(null)
  const [loading, setLoading] = useState(!!path)
  const [loadedAt, setLoadedAt] = useState<Date | null>(null)
  const load = useCallback(async () => {
    if (!path) return
    setLoading(true)
    try {
      const d = await get<T>(path)
      setData(d)
      setError(null)
      setLoadedAt(new Date())
    } catch (e) {
      setError(e as Error)
    } finally {
      setLoading(false)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [path, ...deps])
  useEffect(() => {
    load()
  }, [load])
  return { data, error, loading, loadedAt, reload: load, setData }
}

export function errorCode(e: Error | null): string | null {
  return e instanceof ApiError ? e.code : null
}
