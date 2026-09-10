import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import AppShell from '../components/layout/AppShell'
import { useI18n } from '../i18n'
import { filterHelpFaq } from '../lib/helpContent'

/** 帮助中心整页：分类入口、上手步骤、可搜索 FAQ */
export default function HelpPage() {
  const { t, m } = useI18n()
  /*
   * q 搜索关键词
   * openFaq 当前展开的 FAQ 下标
   */
  const [q, setQ] = useState('')
  const [openFaq, setOpenFaq] = useState<number | null>(0)

  const faqFiltered = useMemo(() => filterHelpFaq([...m.help.faq], q), [m.help.faq, q])

  return (
    <AppShell>
      <div className="pf-help-page">
        <header className="pf-help-page-hero">
          <h1>{t('help.title')}</h1>
          <p className="pf-muted">{t('help.lead')}</p>
          <label className="pf-help-search pf-help-search-lg">
            <span className="sr-only">{t('help.search')}</span>
            <input
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder={t('help.searchPlaceholder')}
            />
          </label>
        </header>

        <div className="pf-help-cats pf-help-cats-lg">
          {m.help.cats.map((c) => (
            <Link key={c.id} to={c.href} className="pf-help-cat">
              <strong>{c.title}</strong>
              <span>{c.desc}</span>
            </Link>
          ))}
        </div>

        <section className="pf-help-guide-block" aria-labelledby="pf-land-guide-title">
          <h2 id="pf-land-guide-title">{t('help.guideTitle')}</h2>
          <ol className="pf-help-steps pf-help-steps-page">
            {m.help.steps.map((s) => (
              <li key={s.n}>
                <span className="pf-help-step-n" aria-hidden>
                  {s.n}
                </span>
                <div>
                  <strong>{s.title}</strong>
                  <p>{s.body}</p>
                </div>
              </li>
            ))}
          </ol>
        </section>

        <section id="faq" className="pf-help-faq-block">
          <h2>{t('help.faqTitle')}</h2>
          <div className="pf-help-faq">
            {faqFiltered.map((item, i) => {
              const expanded = openFaq === i
              return (
                <div key={item.q} className={`pf-help-faq-item${expanded ? ' open' : ''}`}>
                  <button
                    type="button"
                    className="pf-help-faq-q"
                    aria-expanded={expanded}
                    onClick={() => setOpenFaq(expanded ? null : i)}
                  >
                    <span>{item.q}</span>
                    <span className="pf-help-faq-chev" aria-hidden />
                  </button>
                  {expanded ? <p className="pf-help-faq-a">{item.a}</p> : null}
                </div>
              )
            })}
            {faqFiltered.length === 0 ? <p className="pf-muted">{t('help.noMatch')}</p> : null}
          </div>
        </section>

        <section className="pf-help-more">
          <p className="pf-muted">
            {t('help.morePrefix')}{' '}
            <Link to="/settings">{t('help.profile')}</Link>
            {t('help.moreMid')}{' '}
            <Link to="/pricing">{t('help.pricing')}</Link>
            {t('help.moreMid2')}{' '}
            <Link to="/terms">{t('help.terms')}</Link>、<Link to="/privacy">{t('help.privacy')}</Link>
            {t('help.moreOr')}
            <Link to="/contact">{t('help.contact')}</Link>
            {t('help.moreSuffix')}
          </p>
        </section>
      </div>
    </AppShell>
  )
}
