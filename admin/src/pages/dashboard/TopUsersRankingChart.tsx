import type { AdminTopUser, AdminUsageBucket } from "@/api/client";
import type { DashboardMetric } from "@/pages/dashboard/DashboardFilters";
import { UsageDistributionChart } from "@/pages/dashboard/UsageDistributionChart";

/** 用户排行转为柱状图数据桶 */
export function topUsersToBuckets(users: AdminTopUser[]): AdminUsageBucket[] {
  return users.map((user) => ({
    key: String(user.user_id),
    calls: user.calls,
    charge_fen: user.charge_fen,
    cost_fen: user.cost_fen ?? 0,
  }));
}

/** 柱状图 Y 轴用户简称 */
export function topUserChartLabel(userId: string, users: AdminTopUser[]): string {
  const user = users.find((item) => String(item.user_id) === userId);
  const email = user?.email ?? "";
  const local = email.split("@")[0]?.trim();
  if (local) return local.length > 12 ? `${local.slice(0, 11)}…` : local;
  return `ID ${userId}`;
}

type TopUsersRankingChartProps = {
  users: AdminTopUser[];
  metric: DashboardMetric;
};

/** 用户消费排行：与领域分布一致的横向柱状图 */
export function TopUsersRankingChart({ users, metric }: TopUsersRankingChartProps) {
  const rows = topUsersToBuckets(users);
  if (rows.length === 0) {
    return <div className="admin-chart-empty">暂无排行</div>;
  }

  return (
    <UsageDistributionChart
      data={rows}
      metric={metric}
      labelForKey={(key) => topUserChartLabel(key, users)}
      variant="bar"
      chartHeight={Math.max(220, rows.length * 36)}
      yAxisWidth={96}
    />
  );
}
