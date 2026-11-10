import { Activity, Film, TrendingUp } from "lucide-react";
import type { AdminStats } from "@/api/client";
import { points } from "@/lib/points";
import { dashboardRangeLabel, type DashboardFilterState } from "@/pages/dashboard/DashboardFilters";
import { DashboardKpiCard } from "@/pages/dashboard/DashboardKpiCard";
import { sumDailyUsage } from "@/pages/dashboard/dashboardMetrics";

type DashboardPeriodKpisProps = {
  stats: AdminStats | null;
  filters: DashboardFilterState;
  loading: boolean;
};

/** 第二行 KPI：随筛选时间窗变化的调用/扣费及项目规模 */
export function DashboardPeriodKpis({ stats, filters, loading }: DashboardPeriodKpisProps) {
  const placeholder = loading ? "…" : "—";
  const rangeLabel = dashboardRangeLabel(filters.days);
  const period = sumDailyUsage(stats?.daily_usage ?? []);

  return (
    <div className="admin-dashboard-kpi-grid admin-dashboard-kpi-grid--secondary min-[1401px]:!grid-cols-3">
      <DashboardKpiCard
        label={`${rangeLabel}调用`}
        value={stats ? period.calls.toLocaleString() : placeholder}
        hint={stats ? `累计 ${stats.usage_calls_total ?? 0} 次` : "调用次数"}
        icon={Activity}
        tone="mint"
      />
      <DashboardKpiCard
        label={`${rangeLabel}扣费`}
        value={stats ? `${points(period.charge_fen)}` : placeholder}
        hint={stats ? `本月 ${points(stats.usage_charge_month_fen ?? 0)}` : "用户扣费"}
        icon={TrendingUp}
        tone="blue"
      />
      <DashboardKpiCard
        label="漫剧项目"
        value={stats ? stats.drama_project_count ?? 0 : placeholder}
        hint={stats ? `用户 ${stats.user_count}` : "项目规模"}
        icon={Film}
        tone="slate"
      />
    </div>
  );
}
