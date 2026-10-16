import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Button } from '../../components/ui'
import { Icon } from '../../components/Icon'
import { clearChapter, currentChapterId, pick, startChapter, useStory } from './story'
import { ChapterScript } from './ChapterScript'
import './i18n'
import './demo.css'

/** In-app story bar (demo mode only): the current chapter, its script, and the way to the next one. */
export function StoryBar() {
  const [chapterId, setChapterId] = useState(currentChapterId)
  if (!chapterId) return null // outside a demo chapter nothing is fetched or shown
  return <ChapterBar chapterId={chapterId} onClose={() => { clearChapter(); setChapterId(null) }} />
}

function ChapterBar({ chapterId, onClose }: { chapterId: string; onClose: () => void }) {
  const { t, i18n } = useTranslation('demo')
  const lang: 'ar' | 'en' = i18n.language.startsWith('ar') ? 'ar' : 'en'
  const story = useStory()
  const [open, setOpen] = useState(false)
  const [busy, setBusy] = useState(false)
  if (!story) return null
  const index = story.chapters.findIndex((c) => c.id === chapterId)
  if (index < 0) return null
  const chapter = story.chapters[index]
  const next = story.chapters[index + 1]

  const goNext = async () => {
    if (!next) {
      window.location.assign('/demo#epilogue')
      return
    }
    setBusy(true)
    try {
      await startChapter(next, lang)
    } catch {
      setBusy(false)
    }
  }

  return (
    <aside className="story-bar" aria-label={t('bar_label')}>
      <div className="story-bar-row">
        <span className="story-bar-mode"><Icon name="play" size={14} />{t('presenter')}</span>
        <span className="tag">{t('chapter_n', { n: index + 1, total: story.chapters.length })}</span>
        <strong className="story-bar-title">{pick(chapter.title, lang)}</strong>
        <span className="story-bar-actions">
          <Button variant="link" aria-expanded={open} aria-controls="story-script" onClick={() => setOpen((o) => !o)}>
            <Icon name="chevron-down" size={16} className="story-bar-chev" />{open ? t('bar_hide') : t('bar_show')}
          </Button>
          <a href={`/demo#chapter-${chapter.id}`} className="story-bar-all">{t('bar_all')}</a>
          <Button variant="secondary" className="btn-sm" onClick={goNext} disabled={busy}>
            {next ? <>{t('bar_next')}<span className="story-bar-next">: {pick(next.title, lang)}</span></> : t('bar_finish')}
            <Icon name="chevron-end" size={16} className="flip-rtl" />
          </Button>
          <button type="button" className="story-bar-close" aria-label={t('bar_close')} onClick={onClose}><Icon name="close" size={18} /></button>
        </span>
      </div>
      {open && (
        <div id="story-script" className="story-bar-script">
          <ChapterScript chapter={chapter} lang={lang} />
          {chapter.id === 'documents' && story.verification_code && (
            <p className="demo-verify"><Icon name="link" size={16} /><a href={`/verify/${story.verification_code}`} target="_blank" rel="noreferrer">{t('verify_link')}</a></p>
          )}
        </div>
      )}
    </aside>
  )
}
