import { Link, useLocation, useNavigate } from 'react-router-dom'
import { useCallback, useEffect, useRef, useState } from 'react'
import {
  ChevronRight, CircleHelp, Clapperboard, CodeXml, CreditCard, House,
  Menu, Plus, Store,
  Video, Workflow, X,
} from 'lucide-react'
import { api } from '../../api'
import type { User } from '../../api'
import BrandMark from '../BrandMark'
import CreateChoiceModal from '../ui/CreateChoiceModal'
import { USER_UPDATED_EVENT } from '../../lib/userEvents'
import { loadSessionUser } from '../../lib/sessionUser'
import { CODE_VIDEO_URL } from '../../lib/siteLinks'
import { HOME_NAV, CREATION_NAV, RESOURCE_NAV, PERSONAL_NAV, resolveNavActive, type NavActive } from '../../lib/siteNavigation'
import { useI18n } from '../../i18n'
import LanguageSwitch from './LanguageSwitch'
import AccountMenu from './AccountMenu'
import { setWorkspaceTeam } from '../../features/teams/workspaceScope'
import { useMarketplace } from '../../features/marketplace/hooks'

export type { NavActive } from '../../lib/siteNavigation'

type Props = { active?: NavActive }
type NavItem = typeof HOME_NAV | (typeof CREATION_NAV)[number] | (typeof RESOURCE_NAV)[number]

const NAV_ICONS = {
  home: House,
  drama: Clapperboard,
  canvas: Workflow,
  kepu: Video,
  pricing: CreditCard,
}

/** 桌面与窄屏共用精简产品导航，个人入口由头像菜单承载。 */
export default function SiteNav({ active }: Props) {
  const { capabilities: marketplace } = useMarketplace()
  const nav = useNavigate()
  const location = useLocation()
  const { t, locale } = useI18n()
  const selectTeam = setWorkspaceTeam
  const [user, setUser] = useState<User | null>(null)
  const [menuOpen, setMenuOpen] = useState(false)
  const [accountOpen, setAccountOpen] = useState(false)
  const [createOpen, setCreateOpen] = useState(false)
  const menuRef = useRef<HTMLElement>(null)
  const menuButtonRef = useRef<HTMLButtonElement>(null)
  const closeButtonRef = useRef<HTMLButtonElement>(null)
  const current = resolveNavActive(location.pathname, active)
  const inMarketplace = location.pathname === '/marketplace' || location.pathname.startsWith('/marketplace/')
  const currentItem = [HOME_NAV, ...CREATION_NAV, ...RESOURCE_NAV, ...PERSONAL_NAV].find((item) => item.key === current)
  const currentLabel = inMarketplace ? (locale === 'en' ? 'Marketplace' : '数字资产市场') : currentItem ? t(currentItem.label) : current ? t(`nav.${current === 'settings' ? 'profile' : current}`) : t('nav.home')

  /** 产品菜单与头像菜单互斥，回调保持稳定以免重复移动焦点。 */
  const changeAccountOpen = useCallback((open: boolean) => {
    setAccountOpen(open)
    if (open) setMenuOpen(false)
  }, [])

  useEffect(() => {
    let active = true
    let generation = 0
    /** 只有当前请求的明确 401 可以清理会话，切空间导致的取消不会登出。 */
    function refreshUser() {
      const currentGeneration = ++generation
      if (!localStorage.getItem('token')) { setUser(null); return }
      void loadSessionUser({
        loadUser: () => api.me(),
        getToken: () => localStorage.getItem('token'),
        isCurrent: () => active && currentGeneration === generation,
        onUser: setUser,
        onUnauthorized: () => {
          localStorage.removeItem('token')
          setUser(null)
          window.dispatchEvent(new Event(USER_UPDATED_EVENT))
        },
      })
    }
    /** 用户事件先废弃旧请求，避免旧账号覆盖新登录或最新资料。 */
    const onUserUpdated = (event: Event) => {
      generation += 1
      const detail = (event as CustomEvent<User>).detail
      if (detail && localStorage.getItem('token')) setUser(detail)
      else refreshUser()
    }
    window.addEventListener(USER_UPDATED_EVENT, onUserUpdated)
    refreshUser()
    return () => { active = false; generation += 1; window.removeEventListener(USER_UPDATED_EVENT, onUserUpdated) }
  }, [])

  useEffect(() => { setMenuOpen(false); setAccountOpen(false) }, [location.pathname, location.search])

  useEffect(() => {
    const desktop = window.matchMedia('(min-width: 1024px)')
    function closeOnDesktop() { if (desktop.matches) setMenuOpen(false) }
    closeOnDesktop()
    desktop.addEventListener('change', closeOnDesktop)
    return () => desktop.removeEventListener('change', closeOnDesktop)
  }, [])

  useEffect(() => {
    if (!menuOpen) return
    const previousOverflow = document.body.style.overflow
    const menuButton = menuButtonRef.current
    document.body.style.overflow = 'hidden'
    const focusFrame = window.requestAnimationFrame(() => closeButtonRef.current?.focus())

    function keepFocusInside(event: KeyboardEvent) {
      // 独立弹窗优先接管键盘事件。
      const modal = document.querySelector<HTMLElement>('[role="dialog"][aria-modal="true"]:not(#pf-topbar-menu)')
      if (modal && !menuRef.current?.contains(modal)) return
      if (event.key === 'Escape') {
        event.preventDefault()
        setMenuOpen(false)
        return
      }
      if (event.key !== 'Tab' || !menuRef.current) return
      const focusable = Array.from(menuRef.current.querySelectorAll<HTMLElement>(
        'a[href], button:not(:disabled), summary, input:not(:disabled), select:not(:disabled), textarea:not(:disabled), [tabindex]:not([tabindex="-1"])',
      )).filter((element) => element.getClientRects().length > 0 && !element.closest('[inert]'))
      const first = focusable[0]
      const last = focusable[focusable.length - 1]
      if (!first || !last) { event.preventDefault(); return }
      const focused = document.activeElement
      if (!menuRef.current.contains(focused) || (event.shiftKey && focused === first)) {
        event.preventDefault()
        ;(event.shiftKey ? last : first).focus()
      } else if (!event.shiftKey && focused === last) {
        event.preventDefault()
        first.focus()
      }
    }

    document.addEventListener('keydown', keepFocusInside, true)
    return () => {
      window.cancelAnimationFrame(focusFrame)
      document.body.style.overflow = previousOverflow
      document.removeEventListener('keydown', keepFocusInside, true)
      if (menuButton?.getClientRects().length) menuButton.focus()
    }
  }, [menuOpen])

  /** 根据会话打开创作选择或登录页。 */
  function goCreate() {
    setMenuOpen(false)
    setAccountOpen(false)
    selectTeam(null)
    if (!user && !localStorage.getItem('token')) {
      nav('/auth?next=/')
      return
    }
    setCreateOpen(true)
  }

  /** 个人入口始终使用个人空间，清理原有团队选择。 */
  function goPersonal() {
    selectTeam(null)
    setAccountOpen(false)
  }

  /** 沿用账户页的退出流程，同步所有会话订阅者。 */
  function logout() {
    localStorage.removeItem('token')
    setUser(null)
    setAccountOpen(false)
    selectTeam(null)
    window.dispatchEvent(new Event(USER_UPDATED_EVENT))
    nav('/')
  }

  /** 顶栏使用文字导航，展开菜单补充图标；所有入口沿用同一份路由配置。 */
  function renderLink(item: NavItem, expanded = false) {
    const Icon = NAV_ICONS[item.key]
    const selected = current === item.key
    return <Link
      key={item.key}
      to={item.path}
      className={`pf-topbar-link${expanded ? ' pf-topbar-menu-link' : ''}${selected ? ' is-active' : ''}`}
      aria-current={selected ? 'page' : undefined}
      onClick={() => {
        selectTeam(null)
        setMenuOpen(false)
      }}
    >
      {expanded && <Icon size={18} strokeWidth={1.8} aria-hidden />}
      <span>{t(item.label)}</span>
      {expanded && selected && <ChevronRight size={15} className="pf-topbar-link-arrow" aria-hidden />}
    </Link>
  }

  function renderCodeVideo(expanded = false) {
    return <a href={CODE_VIDEO_URL} target="_blank" rel="noopener noreferrer" className={`pf-topbar-link${expanded ? ' pf-topbar-menu-link' : ''}`} onClick={() => setMenuOpen(false)}>
      {expanded && <CodeXml size={18} strokeWidth={1.8} aria-hidden />}
      <span>{t('nav.codeVideo')}</span>
    </a>
  }

  /** 市场入口遵从服务端能力开关，进入个人市场时清理团队请求范围。 */
  function renderMarketplace(expanded = false) {
    if (!marketplace?.enabled) return null
    return <Link to="/marketplace" className={`pf-topbar-link${expanded ? ' pf-topbar-menu-link' : ''}${inMarketplace ? ' is-active' : ''}`} aria-current={inMarketplace ? 'page' : undefined} onClick={() => { selectTeam(null); setMenuOpen(false) }}>
      {expanded && <Store size={18} strokeWidth={1.8} aria-hidden />}
      <span>{locale === 'en' ? 'Marketplace' : '数字资产市场'}</span>
      {expanded && inMarketplace && <ChevronRight size={15} className="pf-topbar-link-arrow" aria-hidden />}
    </Link>
  }

  return <>
    <header className={`pf-app-topbar${accountOpen ? ' pf-app-topbar--account-open' : ''}`} data-locale={locale}>
      <div className="pf-topbar-brand" onClick={() => selectTeam(null)}><BrandMark /></div>
      <nav className="pf-topbar-links" aria-label={t('nav.main')}>
        {renderLink(HOME_NAV)}
        {CREATION_NAV.map((item) => renderLink(item))}
        {renderMarketplace()}
        {renderCodeVideo()}
        {RESOURCE_NAV.map((item) => renderLink(item))}
      </nav>
      <div className="pf-topbar-actions">
        <div className="pf-topbar-language"><LanguageSwitch /></div>
        <Link to="/help" className={`pf-topbar-help${current === 'help' ? ' is-active' : ''}`} aria-label={t('nav.helpCenter')} aria-current={current === 'help' ? 'page' : undefined}><CircleHelp size={18} aria-hidden /><span>{t('nav.help')}</span></Link>
        <AccountMenu user={user} open={accountOpen} marketplaceEnabled={Boolean(marketplace?.enabled)} onOpenChange={changeAccountOpen} onNavigate={goPersonal} onLogout={logout} />
        <button type="button" className="pf-topbar-create" aria-label={t('nav.startCreate')} onClick={goCreate}><Plus size={17} aria-hidden /><span>{t('nav.startCreate')}</span></button>
        <button ref={menuButtonRef} type="button" className="pf-topbar-menu-toggle" aria-label={t('nav.openMenu')} aria-controls="pf-topbar-menu" aria-expanded={menuOpen} onClick={() => { setAccountOpen(false); setMenuOpen(true) }}><Menu size={21} aria-hidden /></button>
      </div>
    </header>
    {menuOpen && <>
      <button type="button" className="pf-topbar-backdrop" aria-label={t('nav.closeMenu')} tabIndex={-1} onClick={() => setMenuOpen(false)} />
      <section ref={menuRef} id="pf-topbar-menu" className="pf-topbar-menu" role="dialog" aria-modal="true" aria-label={t('nav.mobileNav')}>
        <div className="pf-topbar-menu-heading"><div><span>{t('nav.main')}</span><strong>{currentLabel}</strong></div><button ref={closeButtonRef} type="button" className="pf-topbar-menu-close" aria-label={t('nav.closeMenu')} onClick={() => setMenuOpen(false)}><X size={20} aria-hidden /></button></div>
        <nav aria-label={t('nav.main')}>
          <div className="pf-topbar-menu-home">{renderLink(HOME_NAV, true)}</div>
          <div className="pf-topbar-menu-group"><span>{t('nav.creation')}</span><div>{CREATION_NAV.map((item) => renderLink(item, true))}</div></div>
          <div className="pf-topbar-menu-group"><div>{renderMarketplace(true)}{renderCodeVideo(true)}{RESOURCE_NAV.map((item) => renderLink(item, true))}</div></div>
        </nav>
        <div className="pf-topbar-menu-footer">
          <LanguageSwitch />
          <Link to="/help" onClick={() => setMenuOpen(false)}><CircleHelp size={17} aria-hidden /><span>{t('nav.help')}</span></Link>
        </div>
      </section>
    </>}
    <CreateChoiceModal open={createOpen} onClose={() => setCreateOpen(false)} />
  </>
}
