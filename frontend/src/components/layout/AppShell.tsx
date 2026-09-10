import type { ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { useI18n } from '../../i18n'
import SiteNav, { type NavActive } from './SiteNav'

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
    <div className="pf-shell">
      <SiteNav active={active} />
      <main className={['pf-shell-main', wide ? 'wide' : '', flush ? 'flush' : ''].filter(Boolean).join(' ')}>
        {children}
      </main>
      {!hideFooter && !flush ? (
        <footer className="pf-shell-footer">
          <nav className="pf-shell-footer-links" aria-label={t('footer.links')}>
            <Link to="/terms">{t('footer.terms')}</Link>
            <Link to="/privacy">{t('footer.privacy')}</Link>
            <Link to="/contact">{t('footer.contact')}</Link>
            <Link to="/help">{t('footer.help')}</Link>
          </nav>
          <p>© {new Date().getFullYear()} PRINTFILM. All rights reserved.</p>
        </footer>
      ) : null}
    </div>
  )
}
