import { Link } from 'react-router-dom'
import AppShell from '../components/layout/AppShell'
import { useI18n } from '../i18n'
import { getLegalDoc, type LegalDoc } from '../lib/legalContent'

/** 渲染单份法律文档正文 */
function LegalBody({ doc }: { doc: LegalDoc }) {
  const { t } = useI18n()
  return (
    <article className="pf-legal-doc">
      <header className="pf-legal-hero">
        <p className="pf-legal-crumb">
          <Link to="/">{t('common.home')}</Link>
          <span aria-hidden> / </span>
          <span>{doc.title}</span>
        </p>
        <h1>{doc.title}</h1>
        <p className="pf-legal-meta">{t('legal.updatedAt', { date: doc.updatedAt })}</p>
        <p className="pf-legal-intro">{doc.intro}</p>
      </header>

      <div className="pf-legal-sections">
        {doc.sections.map((sec) => (
          <section key={sec.title} className="pf-legal-section">
            <h2>{sec.title}</h2>
            {sec.paragraphs?.map((p) => (
              <p key={p.slice(0, 32)}>{p}</p>
            ))}
            {sec.bullets?.length ? (
              <ul>
                {sec.bullets.map((b) => (
                  <li key={b.slice(0, 32)}>{b}</li>
                ))}
              </ul>
            ) : null}
          </section>
        ))}
      </div>

      <nav className="pf-legal-foot-nav" aria-label={t('legal.related')}>
        <Link to="/terms">{t('footer.terms')}</Link>
        <Link to="/privacy">{t('footer.privacy')}</Link>
        <Link to="/contact">{t('footer.contact')}</Link>
        <Link to="/help">{t('footer.help')}</Link>
      </nav>
    </article>
  )
}

/** 用户协议页 */
export function TermsPage() {
  const { locale } = useI18n()
  const doc = getLegalDoc('terms', locale)
  return (
    <AppShell>
      <div className="pf-legal-page">
        <LegalBody doc={doc} />
      </div>
    </AppShell>
  )
}

/** 隐私政策页 */
export function PrivacyPage() {
  const { locale } = useI18n()
  const doc = getLegalDoc('privacy', locale)
  return (
    <AppShell>
      <div className="pf-legal-page">
        <LegalBody doc={doc} />
      </div>
    </AppShell>
  )
}
