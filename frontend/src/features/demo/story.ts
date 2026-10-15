import { useEffect, useState } from 'react'
import { get, post } from '../../lib/api'
import { markExplicitLanguage } from '../../i18n'

export type Bilingual = { en: string; ar: string }
export type Chapter = {
  id: string
  persona: string
  path: string
  company_id: string | null
  title: Bilingual
  narration: Bilingual
  steps: Bilingual[]
  points: Bilingual[]
}
export type Story = {
  prologue: { title: Bilingual; narration: Bilingual }
  epilogue: { title: Bilingual; narration: Bilingual }
  chapters: Chapter[]
  personas: Record<string, { key: string; name: string; role: Bilingual }>
  verification_code: string | null
}

const CHAPTER_KEY = 'qx_demo_chapter'
let cached: Promise<Story | null> | null = null

/** The story, or null when demo mode is off (the endpoint answers 404). Fetched once per page load. */
export function loadStory(force = false): Promise<Story | null> {
  if (!cached || force) cached = get<Story>('/api/demo/story').catch(() => null)
  return cached
}

export function useStory() {
  const [story, setStory] = useState<Story | null | undefined>(undefined)
  useEffect(() => {
    let live = true
    loadStory().then((s) => live && setStory(s))
    return () => {
      live = false
    }
  }, [])
  return story
}

export function currentChapterId(): string | null {
  try {
    return sessionStorage.getItem(CHAPTER_KEY)
  } catch {
    return null
  }
}

export function clearChapter() {
  try {
    sessionStorage.removeItem(CHAPTER_KEY)
  } catch {
    /* ignore */
  }
}

export const pick = (b: Bilingual, lang: string) => (lang.startsWith('ar') ? b.ar : b.en)

/** Sign out, then sign in as the chapter's persona through the sandbox UAE PASS and land on its screen. */
export async function startChapter(chapter: Chapter, lang: 'ar' | 'en') {
  try {
    sessionStorage.setItem(CHAPTER_KEY, chapter.id)
    if (chapter.company_id) localStorage.setItem('qx_company', chapter.company_id)
    else localStorage.removeItem('qx_company')
  } catch {
    /* storage unavailable: the chapter still opens, without the story bar */
  }
  markExplicitLanguage(lang)
  await post('/api/auth/signout').catch(() => undefined)
  const res = await post<{ redirect_url: string }>(`/api/auth/start?language=${lang}&explicit_language=true&return_to=${encodeURIComponent(chapter.path)}`)
  window.location.assign(`${res.redirect_url}&persona=${encodeURIComponent(chapter.persona)}`)
}

export async function resetDemo() {
  await post('/api/demo/reset')
  clearChapter()
  try {
    localStorage.removeItem('qx_company')
  } catch {
    /* ignore */
  }
}
