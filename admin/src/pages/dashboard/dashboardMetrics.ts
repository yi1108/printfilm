import type { AdminDailyUsage, AdminStats, AdminUsageBucket } from "@/api/client";
import type { DashboardMetric } from "@/pages/dashboard/DashboardFilters";
import { points } from "@/lib/points";

/** 时间窗内日趋势汇总 */
export function sumDailyUsage(daily: AdminDailyUsage[]) {
  return daily.reduce(
    (acc, row) => ({
      calls: acc.calls + row.calls,
      charge_fen: acc.charge_fen + row.charge_fen,
    }),
    { calls: 0, charge_fen: 0 },
  );
}

/** 按当前图表指标读取桶数值 */
export function readBucketMetric(row: AdminUsageBucket, metric: DashboardMetric): number {
  if (metric === "calls") return row.calls;
  return row.charge_fen;
}

/** 格式化指标展示值 */
export function formatDashboardMetric(value: number, metric: DashboardMetric): string {
  if (metric === "calls") return value.toLocaleString();
  return `${points(value)}`;
}

/** 科普项目总数（各状态之和） */
export function sumProjectStatuses(counts: Record<string, number> | undefined): number {
  return Object.values(counts ?? {}).reduce((sum, n) => sum + n, 0);
}

/** 漫剧 + 科普项目规模摘要 */
export function projectScaleHint(stats: AdminStats | null): string | undefined {
  if (!stats) return undefined;
  const kepu = sumProjectStatuses(stats.project_status_counts);
  const drama = stats.drama_project_count ?? 0;
  return `科普 ${kepu} · 漫剧 ${drama}`;
}
