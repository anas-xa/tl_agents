import { useTranslation } from 'react-i18next'
import { Icon } from '../../components/Icon'
import { Disclosure } from '../../components/ui'
import { pick, type Chapter } from './story'
import './i18n'

/** A chapter's script: what to say, what to click, what to point out. Used by the guide and the story bar. */
export function ChapterScript({ chapter, lang, collapsible = false, open = false }: { chapter: Chapter; lang: string; collapsible?: boolean; open?: boolean }) {
  const { t } = useTranslation('demo')
  const columns = (
    <div className="demo-columns">
      <div>
        <h3>{t('do')}</h3>
        <ol className="demo-steps">{chapter.steps.map((s, k) => <li key={k}>{pick(s, lang)}</li>)}</ol>
      </div>
      <div>
        <h3>{t('point')}</h3>
        <ul className="demo-points">{chapter.points.map((s, k) => <li key={k}><Icon name="check" size={16} /><span>{pick(s, lang)}</span></li>)}</ul>
      </div>
    </div>
  )
  return (
    <>
      <div className="demo-say">
        <p className="demo-label">{t('say')}</p>
        <p className="demo-narration">{pick(chapter.narration, lang)}</p>
      </div>
      {collapsible ? <Disclosure summary={t('script_more', { steps: chapter.steps.length, points: chapter.points.length })} open={open} className="demo-more">{columns}</Disclosure> : columns}
    </>
  )
}

