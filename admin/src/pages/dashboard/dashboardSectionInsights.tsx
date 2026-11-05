import { points } from "@/lib/points";
import {
  Activity,
  Banknote,
  CheckCircle2,
  CircleDollarSign,
  Clapperboard,
  Film,
  Layers,
  TrendingDown,
  Zap,
  type LucideIcon,
} from "lucide-react";
import type { AdminStats } from "@/api/client";
import type { DashboardInsightItem } from "@/pages/dashboard/DashboardInsightGrid";
import { sumDailyUsage, sumProjectStatuses } from "@/pages/dashboard/dashboardMetrics";
import { fenToYuan } from "@/lib/utils";
import { projectStatusLabel } from "@/lib/statusLabels";

/** 财务账单 Tab 图标指标 */
export function buildFinanceInsights(stats: AdminStats | null): DashboardInsightItem[] {
  if (!stats) return [];

  const monthCharge = stats.usage_charge_month_fen ?? 0;

  return [
    {
      key: "paid-total",
      label: "累计充值",
      value: `¥${fenToYuan(stats.order_paid_total_fen)}`,
      hint: `今日 ¥${fenToYuan(stats.order_paid_today_fen)}`,
      icon: Banknote,
      tone: "blue",
    },
    {
      key: "charge-month",
      label: "本月扣费",
      value: `¥${fenToYuan(monthCharge)}`,
      hint: `今日 ${points(stats.usage_charge_today_fen ?? 0)}`,
      icon: Zap,
      tone: "purple",
    },
    {
      key: "paid-today",
      label: "今日到账",
      value: `¥${fenToYuan(stats.order_paid_today_fen)}`,
      hint: "充值订单",
      icon: CircleDollarSign,
      tone: "teal",
    },
  ];
}

const STATUS_META: Record<string, { icon: LucideIcon; tone: DashboardInsightItem["tone"] }> = {
  DONE: { icon: CheckCircle2, tone: "mint" },
  DRAFT: { icon: Layers, tone: "slate" },
  FAILED: { icon: TrendingDown, tone: "rose" },
  SCRIPTING: { icon: Clapperboard, tone: "blue" },
  IMAGING: { icon: Film, tone: "purple" },
  VIDEOING: { icon: Activity, tone: "teal" },
};

/** 项目运维 Tab 图标指标 */
export function buildProjectInsights(stats: AdminStats | null, periodDaily: ReturnType<typeof sumDailyUsage>): DashboardInsightItem[] {
  if (!stats) return [];

  const kepuTotal = sumProjectStatuses(stats.project_status_counts);
  const items: DashboardInsightItem[] = [
    {
      key: "kepu-total",
      label: "科普项目",
      value: kepuTotal,
      hint: `漫剧 ${stats.drama_project_count ?? 0} 部`,
      icon: Clapperboard,
      tone: "blue",
    },
    {
      key: "drama-total",
      label: "漫剧项目",
      value: stats.drama_project_count ?? 0,
      hint: "全站项目",
      icon: Film,
      tone: "teal",
    },
    {
      key: "calls-today",
      label: "今日调用",
      value: (stats.usage_calls_today ?? 0).toLocaleString(),
      hint: `本月 ${stats.usage_calls_month ?? 0} 次`,
      icon: Activity,
      tone: "mint",
    },
    {
      key: "calls-total",
      label: "累计调用",
      value: (stats.usage_calls_total ?? 0).toLocaleString(),
      hint: `近窗 ${periodDaily.calls.toLocaleString()} 次`,
      icon: Layers,
      tone: "slate",
    },
  ];

  const statusEntries = Object.entries(stats.project_status_counts ?? {})
    .sort((a, b) => b[1] - a[1])
    .slice(0, 4);

  for (const [status, count] of statusEntries) {
    const meta = STATUS_META[status] ?? { icon: Layers, tone: "sand" as const };
    items.push({
      key: `status-${status}`,
      label: projectStatusLabel(status),
      value: count,
      hint: kepuTotal > 0 ? `占科普 ${((count / kepuTotal) * 100).toFixed(1)}%` : undefined,
      icon: meta.icon,
      tone: meta.tone,
    });
  }

  return items;
}
