import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useAuth } from '../../app/auth'
import { Button, Dialog, Message, Skeleton } from '../../components/ui'
import { LanguageToggle } from '../../shell/Shell'
import { currentChapterId, loadStory, pick, resetDemo, startChapter, useStory, type Chapter } from './story'
import './i18n'

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

  // '/demo#chapter-x' from the story bar: scroll once the chapters have loaded.
  useEffect(() => {
    if (story && window.location.hash) document.getElementById(window.location.hash.slice(1))?.scrollIntoView({ block: 'start' })
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
  return (
    <div className="demo-page">
      <header className="demo-header">
        <div>
          <span className="tag">{t('tag')}</span>
          <h1>{t('title')}</h1>
          <p className="muted">{t('intro')}</p>
        </div>
        <div className="demo-header-actions">
          <LanguageToggle />
          <Button variant="secondary" onClick={() => setConfirmReset(true)} disabled={!!busy}>{t('reset')}</Button>
        </div>
      </header>
      {message && <Message kind={message.kind}>{message.text}</Message>}

      <section className="demo-chapter demo-bookend" aria-labelledby="demo-prologue">
        <p className="demo-kicker">{t('prologue_label')}</p>
        <h2 id="demo-prologue">{pick(story.prologue.title, lang)}</h2>
        <p className="demo-narration">{pick(story.prologue.narration, lang)}</p>
        <h3>{t('cast')}</h3>
        <ul className="demo-cast">
          {Object.values(story.personas).map((p) => (
            <li key={p.key}>
              <span className="avatar" aria-hidden="true">{p.name.slice(0, 1)}</span>
              <span><bdi>{p.name}</bdi><br /><span className="muted">{pick(p.role, lang)}</span></span>
            </li>
          ))}
        </ul>
      </section>

      <ol className="demo-chapters">
        {story.chapters.map((c, i) => {
          const persona = story.personas[c.persona]
          return (
            <li key={c.id} id={`chapter-${c.id}`} className={`demo-chapter${active === c.id ? ' current' : ''}`}>
              <div className="demo-chapter-head">
                <div>
                  <p className="demo-kicker">{t('chapter_n', { n: i + 1, total })}</p>
                  <h2>{pick(c.title, lang)}</h2>
                  <p className="muted">{t('as_persona', { name: persona?.name ?? c.persona, role: persona ? pick(persona.role, lang) : '' })}</p>
                </div>
                <Button onClick={() => start(c)} disabled={!!busy}>
                  {busy === c.id ? t('starting', { name: persona?.name ?? c.persona }) : t('start')}
                </Button>
              </div>
              <p className="demo-narration"><strong>{t('say')}: </strong>{pick(c.narration, lang)}</p>
              <div className="demo-columns">
                <div>
                  <h3>{t('do')}</h3>
                  <ol>{c.steps.map((s, k) => <li key={k}>{pick(s, lang)}</li>)}</ol>
                </div>
                <div>
                  <h3>{t('point')}</h3>
                  <ul>{c.points.map((s, k) => <li key={k}>{pick(s, lang)}</li>)}</ul>
                </div>
              </div>
              {c.id === 'documents' && story.verification_code && (
                <p className="demo-verify">
                  <a href={`/verify/${story.verification_code}`} target="_blank" rel="noreferrer">{t('verify_link')}</a>
                  {' '}<span className="muted">{t('verify_hint')}</span>
                </p>
              )}
            </li>
          )
        })}
      </ol>

      <section id="epilogue" className="demo-chapter demo-bookend" aria-labelledby="demo-epilogue">
        <p className="demo-kicker">{t('epilogue_label')}</p>
        <h2 id="demo-epilogue">{pick(story.epilogue.title, lang)}</h2>
        <p className="demo-narration">{pick(story.epilogue.narration, lang)}</p>
      </section>

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
