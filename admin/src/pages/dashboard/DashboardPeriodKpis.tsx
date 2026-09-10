import { Activity, Film, Percent, TrendingUp } from "lucide-react";
import type { AdminStats } from "@/api/client";
import { fenToYuan } from "@/lib/utils";
import { dashboardRangeLabel, type DashboardFilterState } from "@/pages/dashboard/DashboardFilters";
import { DashboardKpiCard } from "@/pages/dashboard/DashboardKpiCard";
import { calcProfitFen, sumDailyUsage } from "@/pages/dashboard/dashboardMetrics";

type DashboardPeriodKpisProps = {
  stats: AdminStats | null;
  filters: DashboardFilterState;
  loading: boolean;
};

/** 第二行 KPI：随筛选时间窗变化的调用/扣费/毛利/项目规模 */
export function DashboardPeriodKpis({ stats, filters, loading }: DashboardPeriodKpisProps) {
  const placeholder = loading ? "…" : "—";
  const rangeLabel = dashboardRangeLabel(filters.days);
  const period = sumDailyUsage(stats?.daily_usage ?? []);
  const profitFen = calcProfitFen(period.charge_fen, period.cost_fen);
  const profitPct =
    period.charge_fen > 0 ? `${((profitFen / period.charge_fen) * 100).toFixed(1)}%` : undefined;

  return (
    <div className="admin-dashboard-kpi-grid admin-dashboard-kpi-grid--secondary">
      <DashboardKpiCard
        label={`${rangeLabel}调用`}
        value={stats ? period.calls.toLocaleString() : placeholder}
        hint={stats ? `累计 ${stats.usage_calls_total ?? 0} 次` : "调用次数"}
        icon={Activity}
        tone="mint"
      />
      <DashboardKpiCard
        label={`${rangeLabel}扣费`}
        value={stats ? `¥${fenToYuan(period.charge_fen)}` : placeholder}
        hint={stats ? `本月 ¥${fenToYuan(stats.usage_charge_month_fen ?? 0)}` : "用户扣费"}
        icon={TrendingUp}
        tone="blue"
      />
      <DashboardKpiCard
        label={`${rangeLabel}毛利`}
        value={stats ? `¥${fenToYuan(profitFen)}` : placeholder}
        hint={stats ? `成本 ¥${fenToYuan(period.cost_fen)}` : "扣费减成本"}
        icon={Percent}
        tone="rose"
        trend={profitPct ? `毛利率 ${profitPct}` : undefined}
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
