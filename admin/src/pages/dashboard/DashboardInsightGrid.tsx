import type { LucideIcon } from "lucide-react";
import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

export type DashboardInsightTone = "teal" | "blue" | "purple" | "sand" | "rose" | "mint" | "slate";

export type DashboardInsightItem = {
  key: string;
  label: string;
  value: ReactNode;
  hint?: string;
  icon: LucideIcon;
  tone?: DashboardInsightTone;
};

type DashboardInsightGridProps = {
  items: DashboardInsightItem[];
  columns?: 2 | 3 | 4 | 6;
  className?: string;
};

/** 仪表盘图标洞察格：能力/领域/周期指标 */
export function DashboardInsightGrid({ items, columns = 4, className }: DashboardInsightGridProps) {
  if (items.length === 0) {
    return <div className="admin-chart-empty !min-h-[88px]">暂无数据</div>;
  }

  return (
    <div className={cn("admin-dashboard-insight-grid", `cols-${columns}`, className)}>
      {items.map((item) => {
        const Icon = item.icon;
        const tone = item.tone ?? "teal";
        return (
          <div key={item.key} className={cn("admin-dashboard-insight", `tone-${tone}`)}>
            <div className="admin-dashboard-insight-icon">
              <Icon className="h-4 w-4" />
            </div>
            <div className="admin-dashboard-insight-body">
              <div className="admin-dashboard-insight-label">{item.label}</div>
              <div className="admin-dashboard-insight-value">{item.value}</div>
              {item.hint ? <div className="admin-dashboard-insight-hint">{item.hint}</div> : null}
            </div>
          </div>
        );
      })}
    </div>
  );
}
