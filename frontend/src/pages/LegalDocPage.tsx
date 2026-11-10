import { Link } from 'react-router-dom'
import AppShell from '../components/layout/AppShell'
import { useI18n } from '../i18n'
import { getLegalDoc, type LegalDocument } from '../lib/legalDocuments'
import { GITHUB_REPO_URL } from '../lib/siteLinks'

const INLINE_TOKEN = /(\*\*[^*]+\*\*|\[[^\]]+\]\([^)]+\))/g

/** 将条款中的有限 Markdown 标记渲染为安全文本、链接和重点节点。 */
function LegalInlineText({ text }: { text: string }) {
  return (
    <>
      {text.split(INLINE_TOKEN).filter(Boolean).map((part, index) => {
        if (part.startsWith('**') && part.endsWith('**')) {
          return <strong key={index}>{part.slice(2, -2)}</strong>
        }
        const link = part.match(/^\[([^\]]+)\]\(([^)]+)\)$/)
        if (!link) return <span key={index}>{part}</span>
        const [, label, href] = link
        if (href.startsWith('/')) return <Link key={index} to={href}>{label}</Link>
        const external = href.startsWith('https://')
        return (
          <a
            key={index}
            href={href}
            target={external ? '_blank' : undefined}
            rel={external ? 'noopener noreferrer' : undefined}
          >
            {label}
          </a>
        )
      })}
    </>
  )
}

/** 使用站点壳层渲染单份法务文档，正文只来自结构化数据。 */
function LegalBody({ doc }: { doc: LegalDocument }) {
  const { t } = useI18n()
  return (
    <article className="pf-legal-doc">
      <header className="pf-legal-hero">
        <p className="pf-legal-crumb">
          <Link to="/">{t('common.home')}</Link>
          <span aria-hidden> / </span>
          <span>{doc.title}</span>
        </p>
        <p className="pf-legal-brand">PRINTFILM</p>
        <h1>{doc.title}</h1>
        <p className="pf-legal-meta">{t('legal.updatedAt', { date: doc.updatedAt })}</p>
      </header>

      <div className="pf-legal-sections">
        <div className="pf-legal-intro">
          {doc.intro.map((paragraph, index) => (
            <p key={index}><LegalInlineText text={paragraph} /></p>
          ))}
        </div>
        {doc.sections.map((section) => (
          <section key={section.title} className="pf-legal-section">
            <h2>{section.title}</h2>
            {section.blocks.map((block, index) => (
              block.type === 'paragraph' ? (
                <p key={index}><LegalInlineText text={block.text} /></p>
              ) : (
                <ul key={index}>
                  {block.items.map((bullet, bulletIndex) => (
                    <li key={bulletIndex}><LegalInlineText text={bullet} /></li>
                  ))}
                </ul>
              )
            ))}
          </section>
        ))}
      </div>

      <nav className="pf-legal-foot-nav" aria-label={t('legal.related')}>
        <Link to="/terms">{t('footer.terms')}</Link>
        <Link to="/privacy">{t('footer.privacy')}</Link>
        <Link to="/contact">{t('footer.contact')}</Link>
        <Link to="/help">{t('footer.help')}</Link>
        <a href={GITHUB_REPO_URL} target="_blank" rel="noopener noreferrer">
          {t('footer.github')}
        </a>
      </nav>
    </article>
  )
}

/** 按当前界面语言渲染指定法务文档。 */
function LegalPage({ slug }: { slug: 'terms' | 'privacy' }) {
  const { locale } = useI18n()
  return (
    <AppShell>
      <div className="pf-legal-page">
        <LegalBody doc={getLegalDoc(slug, locale)} />
      </div>
    </AppShell>
  )
}

/** 用户协议页。 */
export function TermsPage() {
  return <LegalPage slug="terms" />
}

/** 隐私政策页。 */
export function PrivacyPage() {
  return <LegalPage slug="privacy" />
}
