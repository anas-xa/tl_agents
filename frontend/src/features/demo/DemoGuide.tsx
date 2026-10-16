import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useAuth } from '../../app/auth'
import { Button, Dialog, Message, Skeleton } from '../../components/ui'
import { BrandMark, LanguageToggle } from '../../shell/Shell'
import { Icon } from '../../components/Icon'
import { currentChapterId, loadStory, pick, resetDemo, startChapter, useStory, type Chapter } from './story'
import { ChapterScript } from './ChapterScript'
import './i18n'
import './demo.css'

/** Public guide for the guided demo journey (demo mode only): the story told chapter by chapter. */
export default function DemoGuide() {
  const { t, i18n } = useTranslation('demo')
  const lang: 'ar' | 'en' = i18n.language.startsWith('ar') ? 'ar' : 'en'
  const story = useStory()
  const { refresh } = useAuth()
  const [busy, setBusy] = useState<string | null>(null)
  const [message, setMessage] = useState<{ kind: 'success' | 'error'; text: string } | null>(null)
  const [confirmReset, setConfirmReset] = useState(false)
  const active = currentChapterId()
  const [inView, setInView] = useState<string | null>(null)

  // '/demo#chapter-x' from the story bar: scroll once the chapters have loaded.
  useEffect(() => {
    if (story && window.location.hash) document.getElementById(window.location.hash.slice(1))?.scrollIntoView({ block: 'start' })
  }, [story])

  // Table of contents: highlight the section being read.
  useEffect(() => {
    if (!story || typeof IntersectionObserver === 'undefined') return
    const io = new IntersectionObserver(
      (entries) => {
        const seen = entries.filter((e) => e.isIntersecting).sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top)[0]
        if (seen) setInView(seen.target.id)
      },
      { rootMargin: '-20% 0px -65% 0px' },
    )
    document.querySelectorAll('.demo-page [data-toc]').forEach((el) => io.observe(el))
    return () => io.disconnect()
  }, [story])

  const start = async (c: Chapter) => {
    setBusy(c.id)
    setMessage(null)
    try {
      await startChapter(c, lang)
    } catch {
      setBusy(null)
      setMessage({ kind: 'error', text: t('start_failed') })
    }
  }
  const reset = async () => {
    setBusy('reset')
    setMessage(null)
    try {
      await resetDemo()
      await loadStory(true)
      await refresh()
      setMessage({ kind: 'success', text: t('reset_done') })
    } catch {
      setMessage({ kind: 'error', text: t('reset_failed') })
    } finally {
      setBusy(null)
      setConfirmReset(false)
    }
  }

  if (story === undefined) return <div className="page"><Skeleton rows={6} /></div>
  if (story === null) {
    return (
      <div className="signin-page">
        <div className="signin-card"><Message kind="info">{t('unavailable')}</Message><p><a href="/signin">{t('translation:signin.button')}</a></p></div>
      </div>
    )
  }

  const total = story.chapters.length
  const people = Object.values(story.personas)
  const toc = [
    { id: 'prologue', n: null as number | null, label: t('prologue_label'), title: pick(story.prologue.title, lang) },
    ...story.chapters.map((c, i) => ({ id: `chapter-${c.id}`, n: i + 1, label: '', title: pick(c.title, lang) })),
    { id: 'epilogue', n: null, label: t('epilogue_label'), title: pick(story.epilogue.title, lang) },
  ]
  return (
    <div className="demo-page">
      <header className="demo-top">
        <span className="demo-brand"><BrandMark size={36} /><span><strong>{t('translation:app.short')}</strong><span className="muted">{t('translation:app.det')}</span></span></span>
        <div className="demo-header-actions">
          <LanguageToggle />
          <Button variant="secondary" onClick={() => setConfirmReset(true)} disabled={!!busy}>{t('reset')}</Button>
        </div>
      </header>

      <header className="demo-header">
        <p className="page-eyebrow"><Icon name="play" size={14} />{t('tag')}</p>
        <h1>{t('title')}</h1>
        <p className="page-subtitle">{t('intro')}</p>
        <div className="page-meta">
          <span className="chip chip-neutral"><Icon name="file" size={14} />{t('n_chapters', { n: total })}</span>
          <span className="chip chip-neutral"><Icon name="users" size={14} />{t('n_people', { n: people.length })}</span>
        </div>
      </header>
      {message && <Message kind={message.kind}>{message.text}</Message>}

      <div className="demo-layout">
        <nav className="demo-toc" aria-label={t('chapters_nav')}>
          <p className="demo-toc-title">{t('chapters_nav')}</p>
          <ol>
            {toc.map((e) => {
              const isCurrent = active && e.id === `chapter-${active}`
              return (
                <li key={e.id}>
                  <a href={`#${e.id}`} className={`${inView === e.id ? 'in-view' : ''}${isCurrent ? ' current' : ''}`} aria-current={inView === e.id ? 'location' : undefined}>
                    <span className="demo-toc-num" aria-hidden="true">{e.n ?? '•'}</span>
                    <span className="demo-toc-text">{e.n ? e.title : <><span className="visually-hidden">{e.label}: </span>{e.title}</>}</span>
                  </a>
                </li>
              )
            })}
          </ol>
        </nav>

        <div className="demo-main">
          <section id="prologue" data-toc className="demo-chapter demo-bookend" aria-labelledby="demo-prologue">
            <p className="demo-kicker">{t('prologue_label')}</p>
            <h2 id="demo-prologue">{pick(story.prologue.title, lang)}</h2>
            <p className="demo-narration">{pick(story.prologue.narration, lang)}</p>
            <h3>{t('cast')}</h3>
            <ul className="demo-cast">
              {people.map((p) => (
                <li key={p.key}>
                  <span className="avatar" aria-hidden="true">{p.name.slice(0, 1)}</span>
                  <span className="demo-cast-text"><bdi>{p.name}</bdi><span className="muted">{pick(p.role, lang)}</span></span>
                </li>
              ))}
            </ul>
            <div className="demo-how">
              <Icon name="info" size={18} />
              <p><strong>{t('how_title')}: </strong>{t('how_body')}</p>
            </div>
          </section>

          <ol className="demo-chapters">
            {story.chapters.map((c, i) => {
              const persona = story.personas[c.persona]
              const isCurrent = active === c.id
              return (
                <li key={c.id} id={`chapter-${c.id}`} data-toc className={`demo-chapter${isCurrent ? ' current' : ''}`}>
                  <div className="demo-chapter-head">
                    <span className="demo-num" aria-hidden="true">{i + 1}</span>
                    <div className="demo-chapter-titles">
                      <p className="demo-kicker">{t('chapter_n', { n: i + 1, total })}{isCurrent && <span className="demo-current"> · {t('current')}</span>}</p>
                      <h2>{pick(c.title, lang)}</h2>
                      <p className="demo-persona">
                        <span className="avatar" aria-hidden="true">{(persona?.name ?? c.persona).slice(0, 1)}</span>
                        <span>{t('as_persona', { name: persona?.name ?? c.persona, role: persona ? pick(persona.role, lang) : '' })}</span>
                      </p>
                    </div>
                    <Button onClick={() => start(c)} disabled={!!busy} className="demo-start">
                      <Icon name="play" size={16} />
                      {busy === c.id ? t('starting', { name: persona?.name ?? c.persona }) : t('start')}
                    </Button>
                  </div>
                  <ChapterScript chapter={c} lang={lang} collapsible open={isCurrent} />
                  {c.id === 'documents' && story.verification_code && (
                    <p className="demo-verify">
                      <Icon name="link" size={16} />
                      <a href={`/verify/${story.verification_code}`} target="_blank" rel="noreferrer">{t('verify_link')}</a>
                      {' '}<span className="muted">{t('verify_hint')}</span>
                    </p>
                  )}
                </li>
              )
            })}
          </ol>

          <section id="epilogue" data-toc className="demo-chapter demo-bookend" aria-labelledby="demo-epilogue">
            <p className="demo-kicker">{t('epilogue_label')}</p>
            <h2 id="demo-epilogue">{pick(story.epilogue.title, lang)}</h2>
            <p className="demo-narration">{pick(story.epilogue.narration, lang)}</p>
          </section>
        </div>
      </div>

      <Dialog open={confirmReset} title={t('reset_title')} onClose={() => setConfirmReset(false)} labelledBy="demo-reset-title">
        <p>{t('reset_body')}</p>
        <div className="actions">
          <Button variant="danger" onClick={reset} disabled={busy === 'reset'}>{t('reset_confirm')}</Button>
          <Button variant="secondary" onClick={() => setConfirmReset(false)}>{t('cancel')}</Button>
        </div>
      </Dialog>
    </div>
  )
}
