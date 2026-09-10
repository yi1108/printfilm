import type { LucideIcon } from "lucide-react";
import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

type DashboardKpiTone = "teal" | "blue" | "purple" | "sand" | "rose" | "mint" | "slate";

type DashboardKpiCardProps = {
  label: string;
  value: ReactNode;
  hint?: string;
  icon: LucideIcon;
  tone?: DashboardKpiTone;
  trend?: string;
  className?: string;
};

/** 仪表盘渐变 KPI 卡片 */
export function DashboardKpiCard({
  label,
  value,
  hint,
  icon: Icon,
  tone = "teal",
  trend,
  className,
}: DashboardKpiCardProps) {
  return (
    <div className={cn("admin-dashboard-kpi", `tone-${tone}`, className)}>
      <div className="admin-dashboard-kpi-icon">
        <Icon className="h-5 w-5" />
      </div>
      <div className="admin-dashboard-kpi-label">{label}</div>
      <div className="admin-dashboard-kpi-value">{value}</div>
      {hint || trend ? (
        <div className="admin-dashboard-kpi-foot">
          {hint ? <span>{hint}</span> : null}
          {trend ? <span className="admin-dashboard-kpi-trend">{trend}</span> : null}
        </div>
      ) : null}
    </div>
  );
}
