import { BarChart3, Clapperboard, LayoutDashboard, Wallet } from "lucide-react";
import { cn } from "@/lib/utils";

/** 仪表盘主板块 */
export type DashboardSection = "overview" | "usage" | "finance" | "projects";

const SECTIONS: {
  id: DashboardSection;
  label: string;
  desc: string;
  icon: typeof LayoutDashboard;
}[] = [
  { id: "overview", label: "经营概览", desc: "核心指标与趋势", icon: LayoutDashboard },
  { id: "usage", label: "用量分析", desc: "调用与分布", icon: BarChart3 },
  { id: "finance", label: "财务账单", desc: "充值与成本", icon: Wallet },
  { id: "projects", label: "项目运维", desc: "生产与快捷入口", icon: Clapperboard },
];

type DashboardSectionTabsProps = {
  value: DashboardSection;
  onChange: (next: DashboardSection) => void;
};

/** 仪表盘板块切换 */
export function DashboardSectionTabs({ value, onChange }: DashboardSectionTabsProps) {
  return (
    <div className="admin-dashboard-section-tabs" role="tablist" aria-label="仪表盘板块">
      {SECTIONS.map((item) => {
        const active = value === item.id;
        const Icon = item.icon;
        return (
          <button
            key={item.id}
            type="button"
            role="tab"
            aria-selected={active}
            className={cn("admin-dashboard-section-tab", active && "is-active")}
            onClick={() => onChange(item.id)}
          >
            <span className="admin-dashboard-section-tab-icon">
              <Icon className="h-4 w-4" />
            </span>
            <span className="admin-dashboard-section-tab-text">
              <span className="admin-dashboard-section-tab-label">{item.label}</span>
              <span className="admin-dashboard-section-tab-desc">{item.desc}</span>
            </span>
          </button>
        );
      })}
    </div>
  );
}
