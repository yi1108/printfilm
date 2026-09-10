import { useState, type FormEvent } from 'react'
import { Link } from 'react-router-dom'
import { HelpCircle, Mail, Building2 } from 'lucide-react'
import AppShell from '../components/layout/AppShell'
import { useI18n } from '../i18n'

const CHANNEL_ICONS = [Mail, HelpCircle, Building2] as const

/** 联系我们：渠道说明 + 本地反馈表单（引导发邮件） */
export default function ContactPage() {
  const { t, m } = useI18n()
  /*
   * topic 反馈主题
   * email 联系邮箱
   * message 问题描述
   * sent 是否已生成邮件草稿提示
   */
  const [topic, setTopic] = useState<string>(m.contact.topics[0])
  const [email, setEmail] = useState('')
  const [message, setMessage] = useState('')
  const [sent, setSent] = useState(false)

  function onSubmit(e: FormEvent) {
    e.preventDefault()
    const body = [
      t('contact.mailSubject', { topic }),
      t('contact.mailEmail', { email: email.trim() || t('contact.mailEmailEmpty') }),
      '',
      message.trim() || t('contact.mailEmpty'),
    ].join('\n')
    const href = `mailto:support@printfilm.com?subject=${encodeURIComponent(
      `[PRINTFILM] ${topic}`,
    )}&body=${encodeURIComponent(body)}`
    window.location.href = href
    setSent(true)
  }

  return (
    <AppShell>
      <div className="pf-legal-page pf-contact-page">
        <header className="pf-legal-hero">
          <p className="pf-legal-crumb">
            <Link to="/">{t('common.home')}</Link>
            <span aria-hidden> / </span>
            <span>{t('contact.crumb')}</span>
          </p>
          <h1>{t('contact.title')}</h1>
          <p className="pf-legal-intro">
            {t('contact.introPrefix')} <Link to="/help">{t('contact.introLink')}</Link>
            {t('contact.introSuffix')}
          </p>
        </header>

        <div className="pf-contact-channels">
          {m.contact.channels.map((ch, i) => {
            const Icon = CHANNEL_ICONS[i] || Mail
            const isExternal = ch.href?.startsWith('mailto:')
            return (
              <article key={ch.title} className="pf-contact-card">
                <span className="pf-contact-card-icon" aria-hidden>
                  <Icon size={22} strokeWidth={1.8} />
                </span>
                <h2>{ch.title}</h2>
                <p>{ch.desc}</p>
                {ch.href ? (
                  isExternal ? (
                    <a className="pf-contact-card-link" href={ch.href}>
                      {ch.actionLabel || t('contact.contactAction')}
                    </a>
                  ) : (
                    <Link className="pf-contact-card-link" to={ch.href}>
                      {ch.actionLabel || t('contact.goAction')}
                    </Link>
                  )
                ) : null}
              </article>
            )
          })}
        </div>

        <section className="pf-contact-form-block" aria-labelledby="pf-contact-form-title">
          <h2 id="pf-contact-form-title">{t('contact.formTitle')}</h2>
          <p className="pf-muted">{t('contact.formLead')}</p>

          <form className="pf-contact-form" onSubmit={onSubmit}>
            <label>
              <span>{t('contact.topic')}</span>
              <select value={topic} onChange={(e) => setTopic(e.target.value)}>
                {m.contact.topics.map((item) => (
                  <option key={item} value={item}>
                    {item}
                  </option>
                ))}
              </select>
            </label>
            <label>
              <span>{t('contact.email')}</span>
              <input
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder={t('contact.emailPlaceholder')}
                autoComplete="email"
              />
            </label>
            <label>
              <span>{t('contact.message')}</span>
              <textarea
                value={message}
                onChange={(e) => setMessage(e.target.value)}
                rows={5}
                placeholder={t('contact.messagePlaceholder')}
                required
              />
            </label>
            <button type="submit" className="pf-btn pf-btn-lime">
              {t('contact.submit')}
            </button>
            {sent ? (
              <p className="pf-contact-sent pf-muted">
                {t('contact.sentPrefix')}{' '}
                <a href="mailto:support@printfilm.com">support@printfilm.com</a>
              </p>
            ) : null}
          </form>
        </section>

        <nav className="pf-legal-foot-nav" aria-label={t('contact.related')}>
          <Link to="/terms">{t('footer.terms')}</Link>
          <Link to="/privacy">{t('footer.privacy')}</Link>
          <Link to="/help">{t('footer.help')}</Link>
          <Link to="/pricing">{t('contact.pricing')}</Link>
        </nav>
      </div>
    </AppShell>
  )
}
