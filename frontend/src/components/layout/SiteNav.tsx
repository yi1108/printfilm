import { Link, NavLink, useLocation, useNavigate } from 'react-router-dom'
import { useEffect, useState } from 'react'
import { api } from '../../api'
import type { User } from '../../api'
import UserAvatar from '../UserAvatar'
import BrandMark from '../BrandMark'
import { IconHelp } from '../ui/Icons'
import Button from '../ui/Button'
import CreateChoiceModal from '../ui/CreateChoiceModal'
import { USER_UPDATED_EVENT } from '../../lib/userEvents'
import { useI18n } from '../../i18n'
import LanguageSwitch from './LanguageSwitch'

export type NavActive = 'home' | 'drama' | 'kepu' | 'tools' | 'assets' | 'pricing' | 'templates' | 'studio' | 'history'

type Props = {
  active?: NavActive
}

// 将旧 active 别名归一到新 IA
function normalizeActive(active: NavActive | undefined, pathname: string): NavActive | undefined {
  if (active === 'studio' || active === 'templates' || active === 'history') return 'kepu'
  if (active) return active
  if (pathname.startsWith('/drama/assets') || pathname.startsWith('/assets')) return 'assets'
  if (pathname.startsWith('/drama')) return 'drama'
  if (
    pathname.startsWith('/studio') ||
    pathname.startsWith('/templates') ||
    pathname.startsWith('/history')
  ) {
    return 'kepu'
  }
  if (pathname.startsWith('/tools')) return 'tools'
  if (pathname.startsWith('/pricing')) return 'pricing'
  if (pathname === '/') return 'home'
  return undefined
}

export default function SiteNav({ active }: Props) {
  const nav = useNavigate()
  const location = useLocation()
  const { t } = useI18n()
  /*
   * user 当前用户
   * menuOpen 移动端抽屉
   * createOpen 开始创作选择弹层
   */
  const [user, setUser] = useState<User | null>(null)
  const [menuOpen, setMenuOpen] = useState(false)
  const [createOpen, setCreateOpen] = useState(false)

  const current = normalizeActive(active, location.pathname)

  useEffect(() => {
    if (!localStorage.getItem('token')) return
    api.me().then(setUser).catch(() => localStorage.removeItem('token'))
  }, [])

  useEffect(() => {
    const onUserUpdated = (event: Event) => {
      const detail = (event as CustomEvent<User>).detail
      if (detail) setUser(detail)
    }
    window.addEventListener(USER_UPDATED_EVENT, onUserUpdated)
    return () => window.removeEventListener(USER_UPDATED_EVENT, onUserUpdated)
  }, [])

  useEffect(() => {
    setMenuOpen(false)
  }, [location.pathname])

  // 未登录去登录；已登录弹出漫剧/科普选择
  function goCreate() {
    if (!user && !localStorage.getItem('token')) {
      nav('/auth?next=/')
      return
    }
    setCreateOpen(true)
  }

  const isActive = (key: NavActive) => (current === key ? 'active' : undefined)

  const centerLinks = (
    <>
      <NavLink to="/" end className={() => isActive('home')}>
        {t('nav.workbench')}
      </NavLink>
      <NavLink to="/drama" className={() => isActive('drama')}>
        {t('nav.drama')}
      </NavLink>
      <NavLink to="/history" className={() => isActive('kepu')}>
        {t('nav.kepu')}
      </NavLink>
      <NavLink to="/tools" className={() => isActive('tools')}>
        {t('nav.tools')}
      </NavLink>
      <NavLink to="/assets" className={() => isActive('assets')}>
        {t('nav.assets')}
      </NavLink>
      <NavLink to="/pricing" className={() => isActive('pricing')}>
        {t('nav.pricing')}
      </NavLink>
    </>
  )

  return (
    <header className="pf-nav">
      <div className="pf-nav-left">
        <BrandMark />
      </div>
      <nav className="pf-nav-center" aria-label={t('nav.main')}>
        {centerLinks}
      </nav>
      <div className="pf-nav-right">
        <LanguageSwitch />
        <button type="button" className="pf-nav-help-btn" title={t('nav.helpCenter')} onClick={() => nav('/help')}>
          <IconHelp size={18} className="pf-nav-help-icon" />
          <span>{t('nav.help')}</span>
        </button>
        {user ? (
          <button
            type="button"
            className="pf-avatar"
            title={`${user.nickname} · ${t('nav.profile')}`}
            onClick={() => nav('/settings')}
          >
            <UserAvatar user={user} size="sm" />
          </button>
        ) : (
          <Link to="/auth?next=/" className="pf-link pf-nav-login">
            {t('nav.login')}
          </Link>
        )}
        <Button variant="lime" size="sm" icon onClick={goCreate}>
          {t('nav.startCreate')}
        </Button>
        <button
          type="button"
          className="pf-nav-burger"
          aria-label={menuOpen ? t('nav.closeMenu') : t('nav.openMenu')}
          aria-expanded={menuOpen}
          onClick={() => setMenuOpen((v) => !v)}
        >
          <span />
          <span />
          <span />
        </button>
      </div>
      {menuOpen ? (
        <div className="pf-nav-drawer" role="dialog" aria-label={t('nav.mobileNav')}>
          <nav className="pf-nav-drawer-links">{centerLinks}</nav>
        </div>
      ) : null}
      <CreateChoiceModal open={createOpen} onClose={() => setCreateOpen(false)} />
    </header>
  )
}
