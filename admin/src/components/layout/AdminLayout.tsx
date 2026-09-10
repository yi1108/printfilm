import { useState } from "react";

import { NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";

import {

  Bell,

  Clapperboard,

  FileVideo,

  Film,

  Image,

  Layers,

  LayoutDashboard,

  ListVideo,

  LogOut,

  Maximize2,

  Menu,

  Receipt,

  Settings,

  Shapes,

  Users,

  Wallet,

} from "lucide-react";

import { clearAuth, getCachedUser } from "@/lib/auth";

import { cn } from "@/lib/utils";



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

      { to: "/orders", label: "订单流水", icon: Receipt },
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

  "/": "仪表盘",

  "/users": "用户管理",

  "/orders": "订单流水",
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

  if (pathname.startsWith("/drama-projects/")) return "漫剧项目详情";

  if (pathname.startsWith("/drama-assets/")) return "资产详情";

  if (pathname.startsWith("/drama-episodes/")) return "分集详情";

  if (pathname.startsWith("/drama-fragments/")) return "分镜详情";

  return titles[pathname] ?? "管理后台";

}



// Admin shell: dark sidebar + glass top bar

export function AdminLayout() {

  const navigate = useNavigate();

  const location = useLocation();

  const user = getCachedUser();

  /*

   * collapsed sidebar collapsed state

   */

  const [collapsed, setCollapsed] = useState(false);



  // Logout and return to login

  function handleLogout() {

    clearAuth();

    navigate("/login");

  }



  const title = resolveTitle(location.pathname);

  const initial = (user?.nickname || user?.email || "A").slice(0, 1).toUpperCase();



  return (

    <div className={cn("admin-app", collapsed && "is-collapsed")}>

      <aside className="admin-sidebar">

        <div className="admin-brand">

          <div className="admin-brand-mark">PF</div>

          {!collapsed && (

            <div>

              <div className="admin-brand-name">PRINTFILM</div>

              <div className="admin-brand-sub">管理后台</div>

            </div>

          )}

        </div>

        <nav className="admin-nav">

          {navGroups.map((group) => (

            <div key={group.label} className="admin-nav-group">

              {!collapsed ? <div className="admin-nav-group-label">{group.label}</div> : null}

              {group.items.map((item) => (

                <NavLink

                  key={item.to}

                  to={item.to}

                  end={item.end ?? !item.matchPrefix}

                  className={({ isActive }) =>

                    cn(

                      "admin-nav-item",

                      (isActive || (item.matchPrefix && location.pathname.startsWith(`${item.to}/`))) &&

                        "is-active",

                    )

                  }

                  title={item.label}

                >

                  <item.icon className="h-[18px] w-[18px] shrink-0" />

                  {!collapsed && <span>{item.label}</span>}

                </NavLink>

              ))}

            </div>

          ))}

        </nav>

        <div className="admin-user-card">

          <div className="admin-avatar">{initial}</div>

          {!collapsed && (

            <div className="min-w-0 flex-1">

              <div className="truncate text-[13px] font-medium text-[#e8f0eb]">{user?.email}</div>

              <div className="text-xs text-[rgba(240,245,242,0.45)]">超级管理员</div>

            </div>

          )}

          <button type="button" className="admin-icon-btn !text-[rgba(240,245,242,0.55)] hover:!text-[#e8f0eb]" onClick={handleLogout} title="退出登录">

            <LogOut className="h-4 w-4" />

          </button>

        </div>

      </aside>



      <div className="admin-main">

        <header className="admin-topbar">

          <div className="flex items-center gap-3">

            <button

              type="button"

              className="admin-icon-btn"

              onClick={() => setCollapsed((v) => !v)}

              aria-label="折叠侧栏"

            >

              <Menu className="h-4 w-4" />

            </button>

            <div>

              <div className="admin-topbar-title">{title}</div>

              <div className="admin-topbar-crumb">PRINTFILM · 运营管理</div>

            </div>

          </div>

          <div className="flex items-center gap-1">

            <button type="button" className="admin-icon-btn" title="通知">

              <Bell className="h-4 w-4" />

            </button>

            <button

              type="button"

              className="admin-icon-btn"

              title="全屏"

              onClick={() => {

                if (!document.fullscreenElement) void document.documentElement.requestFullscreen();

                else void document.exitFullscreen();

              }}

            >

              <Maximize2 className="h-4 w-4" />

            </button>

          </div>

        </header>

        <main className="admin-content">

          <Outlet />

        </main>

      </div>

    </div>

  );

}


