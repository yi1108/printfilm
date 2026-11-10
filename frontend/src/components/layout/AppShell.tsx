import type { ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { useI18n } from '../../i18n'
import { GITHUB_REPO_URL } from '../../lib/siteLinks'
import { BRAND_NAME, COMPANY_NAME_ZH, SUPPORT_EMAIL, SUPPORT_PHONE, SUPPORT_PHONE_HREF, WECHAT_ID } from '../../lib/siteContact'
import SiteNav, { type NavActive } from './SiteNav'
import './topbar.css'

type Props = {
  children: ReactNode
  active?: NavActive
  wide?: boolean
  flush?: boolean
  /** 隐藏页脚（全屏工作台） */
  hideFooter?: boolean
}

export default function AppShell({ children, active, wide, flush, hideFooter }: Props) {
  const { t } = useI18n()

  return (
    <div className="pf-shell pf-shell--topbar">
      <a className="pf-skip-content" href="#pf-main-content">{t('nav.skipContent')}</a>
      <SiteNav active={active} />
      <main id="pf-main-content" tabIndex={-1} className={['pf-shell-main', wide ? 'wide' : '', flush ? 'flush' : ''].filter(Boolean).join(' ')}>
        {children}
      </main>
      {!hideFooter && !flush ? (
        <footer className="pf-shell-footer">
          <nav className="pf-shell-footer-links" aria-label={t('footer.links')}>
            <Link to="/terms">{t('footer.terms')}</Link>
            <Link to="/privacy">{t('footer.privacy')}</Link>
            <Link to="/contact">{t('footer.contact')}</Link>
            <Link to="/help">{t('footer.help')}</Link>
            <a href={GITHUB_REPO_URL} target="_blank" rel="noopener noreferrer">
              {t('footer.github')}
            </a>
          </nav>
          <p>© {new Date().getFullYear()} {COMPANY_NAME_ZH} · {BRAND_NAME}</p>
          <p className="pf-shell-footer-contacts">
            <a href={`mailto:${SUPPORT_EMAIL}`}>{t('footer.email')}：{SUPPORT_EMAIL}</a>
            <a href={SUPPORT_PHONE_HREF}>{t('footer.phone')}：{SUPPORT_PHONE}</a>
            <span>{t('footer.wechat')}：{WECHAT_ID}</span>
          </p>
        </footer>
      ) : null}
    </div>
  )
}
