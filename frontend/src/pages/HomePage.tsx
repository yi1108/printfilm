/** PRINTFILM 官网首页：产品主张、漫剧/科普入口、成片流程与创作入口 */
import { useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { ArrowRight, ArrowUpRight, Cloud, Cpu, Video as KepuIcon } from 'lucide-react'
import AppShell from '../components/layout/AppShell'
import Button from '../components/ui/Button'
import { IconGithub } from '../components/ui/Icons'
import CreateChoiceModal from '../components/ui/CreateChoiceModal'
import { useI18n } from '../i18n'
import { getDramaImageStylePreviewUrl } from '../lib/dramaImageStylePreviews'
import { FILM_SKILLS_URL, GITHUB_REPO_URL } from '../lib/siteLinks'
import { api, type Template } from '../api'
import { SHORT_VIDEO_LIST_PATH } from '../lib/shortVideoRoutes'

export default function HomePage() {
  const nav = useNavigate()
  const { t, m } = useI18n()
  const loggedIn = Boolean(localStorage.getItem('token'))
  const [createOpen, setCreateOpen] = useState(false)
  const [templates, setTemplates] = useState<Template[]>([])

  useEffect(() => {
    let active = true
    api.templates().then((items) => {
      if (active) setTemplates(items)
    }).catch(() => {
      if (active) setTemplates([])
    })
    return () => { active = false }
  }, [])

  // 未登录去登录；已登录弹出产品选择
  function goCreate() {
    if (!loggedIn) {
      nav('/auth?next=/')
      return
    }
    setCreateOpen(true)
  }

  // 产品入口：未登录带 next 回跳
  function goAuthOr(path: string) {
    nav(loggedIn ? path : `/auth?next=${encodeURIComponent(path)}`)
  }

  return (
    <AppShell active="home" hideFooter>
      <section className="pf-land-hero">
        <div className="pf-land-hero-copy">
          <p className="pf-land-kicker">PRINTFILM</p>
          <h1>
            {t('home.headlineBefore')}
            <br />
            <em>{t('home.headlineEm')}</em>
          </h1>
          <p className="pf-land-lede">{t('home.lede')}</p>
          <div className="pf-land-cta">
            <Button variant="lime" size="lg" icon onClick={goCreate}>
              {t('home.startCreate')}
              <ArrowRight size={16} strokeWidth={2} aria-hidden />
            </Button>
            <a className="pf-btn pf-btn-ghost pf-btn-lg pf-btn-icon" href={FILM_SKILLS_URL} target="_blank" rel="noopener noreferrer">
              {t('nav.skills')}
              <ArrowUpRight size={16} strokeWidth={2} aria-hidden />
            </a>
          </div>
          <a
            className="pf-land-github"
            href={GITHUB_REPO_URL}
            target="_blank"
            rel="noopener noreferrer"
          >
            <IconGithub size={16} />
            <span>{t('home.githubCta')}</span>
            <ArrowRight size={14} strokeWidth={2.2} aria-hidden />
          </a>
        </div>
        <div className="pf-land-frames" aria-hidden>
          <figure className="pf-land-frame is-drama">
            <img src={getDramaImageStylePreviewUrl('ancient-chinese-mythology')} alt="" />
            <figcaption>{t('home.dramaTitle')}</figcaption>
          </figure>
          <figure className="pf-land-frame is-kepu">
            <img src={api.assetUrl(templates[0]?.preview_cover || '/static/templates/covers/anim_3d.png')} alt="" />
            <figcaption>{t('home.kepuTitle')}</figcaption>
          </figure>
        </div>
      </section>

      <section className="pf-land-products" id="products" aria-label={t('home.products')}>
        <button type="button" className="pf-land-product is-drama" onClick={() => goAuthOr('/drama')}>
          <span className="pf-land-product-icon" aria-hidden>
            <Cpu size={26} strokeWidth={1.6} />
          </span>
          <span className="pf-land-product-body">
            <strong>{t('home.dramaSelfHostedTitle')}</strong>
            <em>{t('home.dramaFor')}</em>
            <span>{t('home.dramaDesc')}</span>
            <span className="pf-land-chips">
              {m.home.dramaSteps.map((label) => (
                <span key={label}>{label}</span>
              ))}
            </span>
          </span>
          <span className="pf-land-product-go" aria-hidden>
            <ArrowRight size={16} strokeWidth={2} />
          </span>
        </button>
        <button type="button" className="pf-land-product is-api" onClick={() => goAuthOr('/drama')}>
          <span className="pf-land-product-icon" aria-hidden>
            <Cloud size={26} strokeWidth={1.6} />
          </span>
          <span className="pf-land-product-body">
            <strong>{t('home.dramaApiTitle')}</strong>
            <em>{t('home.dramaApiFor')}</em>
            <span>{t('home.dramaApiDesc')}</span>
            <span className="pf-land-chips">
              {m.home.dramaApiSteps.map((label) => <span key={label}>{label}</span>)}
            </span>
          </span>
          <span className="pf-land-product-go" aria-hidden>
            <ArrowRight size={16} strokeWidth={2} />
          </span>
        </button>
        <button type="button" className="pf-land-product is-kepu" onClick={() => goAuthOr(SHORT_VIDEO_LIST_PATH)}>
          <span className="pf-land-product-icon" aria-hidden>
            <KepuIcon size={26} strokeWidth={1.6} />
          </span>
          <span className="pf-land-product-body">
            <strong className="pf-land-product-heading">
              {t('home.kepuTitle')}
              <span className="pf-land-product-tag">{t('home.kepuTag')}</span>
            </strong>
            <em>{t('home.kepuFor')}</em>
            <span>{t('home.kepuDesc')}</span>
            <span className="pf-land-chips">
              {m.home.kepuSteps.map((label) => (
                <span key={label}>{label}</span>
              ))}
            </span>
          </span>
          <span className="pf-land-product-go" aria-hidden>
            <ArrowRight size={16} strokeWidth={2} />
          </span>
        </button>
      </section>

      <section className="pf-land-pipeline" aria-labelledby="pf-land-pipeline-title">
        <header className="pf-land-section-head">
          <p className="pf-land-kicker">{t('home.howKicker')}</p>
          <h2 id="pf-land-pipeline-title">{t('home.howTitle')}</h2>
        </header>
        <ol className="pf-land-pipeline-list">
          {m.home.pipeline.map((item) => (
            <li key={item.step}>
              <span className="pf-land-step-no">{item.step}</span>
              <strong>{item.title}</strong>
              <span>{item.desc}</span>
            </li>
          ))}
        </ol>
      </section>

      <section className="pf-land-caps" aria-labelledby="pf-land-caps-title">
        <header className="pf-land-section-head">
          <p className="pf-land-kicker">{t('home.capsKicker')}</p>
          <h2 id="pf-land-caps-title">{t('home.capsTitle')}</h2>
        </header>
        <div className="pf-land-cap-grid">
          {m.home.capabilities.map((item) => (
            <article key={item.title}>
              <strong>{item.title}</strong>
              <p>{item.desc}</p>
            </article>
          ))}
        </div>
      </section>

      <section className="pf-land-who" aria-labelledby="pf-land-who-title">
        <header className="pf-land-section-head">
          <p className="pf-land-kicker">{t('home.whoKicker')}</p>
          <h2 id="pf-land-who-title">{t('home.whoTitle')}</h2>
        </header>
        <div className="pf-land-who-grid">
          {m.home.audiences.map((item) => (
            <article key={item.title}>
              <strong>{item.title}</strong>
              <p>{item.desc}</p>
            </article>
          ))}
        </div>
      </section>

      <section className="pf-land-close">
        <div>
          <h2>{t('home.closeTitle')}</h2>
          <p>{t('home.closeLead')}</p>
        </div>
        <div className="pf-land-cta">
          <Button variant="lime" size="lg" icon onClick={goCreate}>
            {t('home.startCreate')}
            <ArrowRight size={16} strokeWidth={2} aria-hidden />
          </Button>
          <Button variant="ghost" size="lg" to="/pricing">
            {t('home.viewPricing')}
          </Button>
        </div>
      </section>

      <footer className="pf-land-foot">
        <div className="pf-land-foot-brand">
          <strong>PRINTFILM</strong>
          <p>{t('home.footBrand')}</p>
        </div>
        <nav className="pf-land-foot-nav" aria-label={t('home.footNav')}>
          <Link to="/drama">{t('nav.drama')}</Link>
          <Link to={SHORT_VIDEO_LIST_PATH}>{t('nav.kepu')}</Link>
          <Link to="/method">{t('home.methodLink')}</Link>
          <a href={FILM_SKILLS_URL} target="_blank" rel="noopener noreferrer">{t('nav.skills')}</a>
          <Link to="/pricing">{t('nav.pricing')}</Link>
          <Link to="/help">{t('nav.help')}</Link>
          <Link to="/terms">{t('footer.terms')}</Link>
          <Link to="/privacy">{t('footer.privacy')}</Link>
          <Link to="/contact">{t('footer.contact')}</Link>
          <a href={GITHUB_REPO_URL} target="_blank" rel="noopener noreferrer">
            {t('footer.github')}
          </a>
        </nav>
        <p className="pf-land-copy">© {new Date().getFullYear()} PRINTFILM. All rights reserved.</p>
      </footer>

      <CreateChoiceModal open={createOpen} onClose={() => setCreateOpen(false)} />
    </AppShell>
  )
}
