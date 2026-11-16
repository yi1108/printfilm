import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { useMarketplaceEnabled } from "@/features/marketplace/api";

import { NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";

import {

  ArrowUpRight,
  Aperture,
  ChevronRight,
  KeyRound,
  PanelLeftClose,
  Search,
  X,

  Clapperboard,

  FileVideo,

  Film,

  Image,

  Layers,

  LayoutDashboard,

  ListVideo,

  LogOut,

  Maximize2,


  Receipt,

  Scale,

  Settings,

  Shapes,

  Users,

  Wallet,

} from "lucide-react";

import { clearAuth, getCachedUser } from "@/lib/auth";

import { cn } from "@/lib/utils";
import { AdminNavigationSearch } from "./AdminNavigationSearch";
import { ChangePasswordDialog } from "@/components/admin/ChangePasswordDialog";

type NavItem = {

  to: string;

  label: string;

  icon: typeof LayoutDashboard;

  end?: boolean;

  matchPrefix?: boolean;

};

type NavGroup = {

  label: string;

  items: NavItem[];

};

const navGroups: NavGroup[] = [

  {

    label: "概览",

    items: [{ to: "/", label: "仪表盘", icon: LayoutDashboard, end: true }],

  },

  {

    label: "业务",

    items: [

      { to: "/users", label: "用户管理", icon: Users },

      { to: "/teams", label: "团队管理", icon: Users, matchPrefix: true },

      { to: "/orders", label: "订单流水", icon: Receipt },

      { to: "/adjustments", label: "手动调账", icon: Scale },

      { to: "/finance", label: "财务列表", icon: Wallet },

      { to: "/projects", label: "科普项目", icon: Clapperboard },

      { to: "/works", label: "作品审核", icon: FileVideo },

    ],

  },

  {

    label: "漫剧",

    items: [

      { to: "/drama-projects", label: "漫剧项目", icon: Film, matchPrefix: true },

      { to: "/drama-assets", label: "资产库", icon: Image, matchPrefix: true },

      { to: "/drama-episodes", label: "分集管理", icon: ListVideo, matchPrefix: true },

      { to: "/drama-fragments", label: "分镜管理", icon: Layers, matchPrefix: true },

    ],

  },

  {

    label: "资源",

    items: [

      { to: "/templates", label: "模板管理", icon: Shapes },

      { to: "/queues", label: "任务中心", icon: Layers },

    ],

  },

  {

    label: "系统",

    items: [{ to: "/settings", label: "系统设置", icon: Settings }],

  },

];

const titles: Record<string, string> = {
  "/marketplace": "数字资产平台运营",

  "/": "仪表盘",

  "/users": "用户管理",

  "/teams": "团队管理",

  "/orders": "订单流水",

  "/adjustments": "手动调账",

  "/finance": "财务列表",

  "/projects": "科普项目",

  "/drama-projects": "漫剧项目",

  "/drama-assets": "资产库",

  "/drama-episodes": "分集管理",

  "/drama-fragments": "分镜管理",

  "/works": "作品审核",

  "/templates": "模板管理",

  "/settings": "系统设置",

  "/queues": "任务中心",

};

function resolveTitle(pathname: string): string {

  if (pathname.startsWith("/teams/")) return "团队详情";

  if (pathname.startsWith("/drama-projects/")) return "漫剧项目详情";

  if (pathname.startsWith("/drama-assets/")) return "资产详情";

  if (pathname.startsWith("/drama-episodes/")) return "分集详情";

  if (pathname.startsWith("/drama-fragments/")) return "分镜详情";

  return titles[pathname] ?? "管理后台";

}

/** 统一运营工作台：桌面折叠导航、移动抽屉与可搜索入口。 */
export function AdminLayout() {
  const marketplaceEnabled = useMarketplaceEnabled();
  const visibleNavGroups = navGroups.map((group) => group.label === "业务" && marketplaceEnabled
    ? { ...group, items: [...group.items, { to: "/marketplace", label: "数字资产平台运营", icon: FileVideo } satisfies NavItem] }
    : group);
  const navigate = useNavigate();
  const location = useLocation();
  const user = getCachedUser();
  const [collapsed, setCollapsed] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);
  const [searchOpen, setSearchOpen] = useState(false);
  const [passwordOpen, setPasswordOpen] = useState(false);
  const [isMobile, setIsMobile] = useState(() => window.matchMedia("(max-width: 800px)").matches);
  const sidebarRef = useRef<HTMLElement>(null);
  const navigationToggleRef = useRef<HTMLButtonElement>(null);
  const sidebarCloseRef = useRef<HTMLButtonElement>(null);
  const mobileDrawerOpen = isMobile && mobileOpen;
  const title = resolveTitle(location.pathname);
  const initial = (user?.nickname || user?.email || "A").slice(0, 1).toUpperCase();

  useEffect(() => { setMobileOpen(false); }, [location.pathname]);
  useEffect(() => {
    const media = window.matchMedia("(max-width: 800px)");
    function onChange(event: MediaQueryListEvent) {
      setIsMobile(event.matches);
      if (!event.matches) setMobileOpen(false);
    }
    media.addEventListener("change", onChange);
    return () => media.removeEventListener("change", onChange);
  }, []);

  useLayoutEffect(() => {
    if (!mobileDrawerOpen) return;
    const sidebar = sidebarRef.current;
    if (!sidebar) return;
    const navigationToggle = navigationToggleRef.current;
    const previouslyFocused = document.activeElement instanceof HTMLElement && document.activeElement !== document.body
      ? document.activeElement : null;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    sidebarCloseRef.current?.focus({ preventScroll: true });

    function focusableItems() {
      return Array.from(sidebar!.querySelectorAll<HTMLElement>('a[href], button:not([disabled]), [tabindex]:not([tabindex="-1"])'))
        .filter((element) => element.tabIndex >= 0 && element.getClientRects().length > 0);
    }
    function trapFocus(event: KeyboardEvent) {
      if (event.key !== "Tab") return;
      const items = focusableItems();
      const first = items[0];
      const last = items[items.length - 1];
      if (!first || !last) return;
      if (event.shiftKey && (document.activeElement === first || !sidebar!.contains(document.activeElement))) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && (document.activeElement === last || !sidebar!.contains(document.activeElement))) {
        event.preventDefault();
        first.focus();
      }
    }
    function keepFocusInside(event: FocusEvent) {
      if (event.target instanceof Node && !sidebar!.contains(event.target)) {
        sidebarCloseRef.current?.focus({ preventScroll: true });
      }
    }
    document.addEventListener("keydown", trapFocus, true);
    document.addEventListener("focusin", keepFocusInside);
    return () => {
      document.removeEventListener("keydown", trapFocus, true);
      document.removeEventListener("focusin", keepFocusInside);
      document.body.style.overflow = previousOverflow;
      if (sidebar.contains(document.activeElement) || document.activeElement === document.body) {
        const restoreTarget = previouslyFocused?.isConnected ? previouslyFocused : navigationToggle;
        restoreTarget?.focus({ preventScroll: true });
      }
    };
  }, [mobileDrawerOpen]);

  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setMobileOpen(false);
        setSearchOpen((value) => !value);
      }
      if (event.key === "Escape") setMobileOpen(false);
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  function handleLogout() { clearAuth(); navigate("/login"); }
  function toggleNavigation() {
    if (isMobile) setMobileOpen((value) => !value);
    else setCollapsed((value) => !value);
  }

  return (
    <div className={cn("admin-app", collapsed && "is-collapsed", mobileDrawerOpen && "is-mobile-open")}>
      <a className="admin-skip-link" href="#admin-main-content">跳至页面内容</a>
      {mobileDrawerOpen && <button type="button" className="admin-sidebar-scrim" tabIndex={-1} aria-label="关闭导航" onClick={() => setMobileOpen(false)} />}
      <aside ref={sidebarRef} className="admin-sidebar" id="admin-sidebar" aria-label="管理导航"
        role={mobileDrawerOpen ? "dialog" : undefined} aria-modal={mobileDrawerOpen ? true : undefined}
        aria-hidden={isMobile && !mobileOpen ? true : undefined} inert={isMobile && !mobileOpen}>
        <div className="admin-brand">
          <div className="admin-brand-mark"><Aperture size={23} strokeWidth={1.7} /></div>
          <div className="admin-brand-copy"><div className="admin-brand-name">PRINTFILM<span>®</span></div><div className="admin-brand-sub">运营控制台</div></div>
          <button ref={sidebarCloseRef} type="button" className="admin-icon-btn admin-sidebar-close" aria-label="关闭导航" onClick={() => setMobileOpen(false)}><X size={18} /></button>
        </div>
        <nav className="admin-nav" aria-label="主导航">
          {visibleNavGroups.map((group) => (
            <div key={group.label} className="admin-nav-group">
              <div className="admin-nav-group-label">{group.label}</div>
              {group.items.map((item) => (
                <NavLink key={item.to} to={item.to} end={item.end ?? !item.matchPrefix}
                  className={({ isActive }) => cn("admin-nav-item", (isActive || (item.matchPrefix && location.pathname.startsWith(`${item.to}/`))) && "is-active")}
                  title={item.label} onClick={() => setMobileOpen(false)}>
                  <item.icon className="h-[18px] w-[18px] shrink-0" strokeWidth={1.7} />
                  <span className="admin-nav-label">{item.label}</span><ChevronRight className="admin-nav-arrow" size={14} />
                </NavLink>
              ))}
            </div>
          ))}
        </nav>
        <div className="admin-sidebar-footnote"><span />PRINTFILM OPERATIONS</div>
        <div className="admin-user-card">
          <div className="admin-avatar">{initial}</div>
          <div className="admin-user-copy"><strong>{user?.nickname || "管理员"}</strong><span title={user?.email}>{user?.email}</span></div>
          <button type="button" className="admin-icon-btn admin-logout" onClick={handleLogout} title="退出登录" aria-label="退出登录"><LogOut size={16} /></button>
        </div>
      </aside>
      <div className="admin-main" inert={mobileDrawerOpen}>
        <header className="admin-topbar">
          <div className="admin-topbar-leading">
            <button ref={navigationToggleRef} type="button" className="admin-icon-btn" onClick={toggleNavigation}
              aria-label={isMobile ? (mobileOpen ? "关闭导航" : "展开导航") : (collapsed ? "展开导航" : "折叠导航")}
              aria-controls="admin-sidebar" aria-expanded={isMobile ? mobileOpen : !collapsed}>
              <PanelLeftClose size={19} />
            </button>
            <div className="admin-topbar-breadcrumb"><span>控制台</span><ChevronRight size={13} /><strong>{title}</strong></div>
          </div>
          <div className="admin-topbar-actions">
            <button type="button" className="admin-command-trigger" aria-label="搜索管理功能" aria-keyshortcuts="Control+K Meta+K" onClick={() => setSearchOpen(true)}><Search size={15} /><span>搜索功能…</span><kbd>Ctrl K</kbd></button>
            <a className="admin-site-link" href={import.meta.env.DEV ? "http://127.0.0.1:5173" : "/"} target="_blank" rel="noreferrer">用户端<ArrowUpRight size={14} /></a>
            <button type="button" className="admin-icon-btn admin-fullscreen" title="切换全屏" aria-label="切换全屏" onClick={() => {
              if (!document.fullscreenElement) void document.documentElement.requestFullscreen().catch(() => undefined);
              else void document.exitFullscreen().catch(() => undefined);
            }}><Maximize2 size={17} /></button>
            <button type="button" className="admin-icon-btn" title="修改登录密码" aria-label="修改登录密码"
              onClick={() => setPasswordOpen(true)}><KeyRound size={17} /></button>
            <div className="admin-topbar-avatar" title={user?.email}>{initial}</div>
          </div>
        </header>
        <main className="admin-content" id="admin-main-content" tabIndex={-1}><Outlet /></main>
      </div>
      <AdminNavigationSearch open={searchOpen} onOpenChange={setSearchOpen} groups={visibleNavGroups} />
      {passwordOpen && <ChangePasswordDialog email={user?.email} onClose={() => setPasswordOpen(false)} />}
    </div>
  );
}
