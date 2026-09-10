import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { AdminDailyUsage } from "@/api/client";
import { fenToYuan } from "@/lib/utils";
import type { DashboardMetric } from "./DashboardFilters";

type UsageTrendChartProps = {
  data: AdminDailyUsage[];
  metric: DashboardMetric;
};

function metricLabel(metric: DashboardMetric): string {
  if (metric === "cost") return "上游成本";
  if (metric === "calls") return "调用次数";
  return "扣费金额";
}

function readMetric(row: AdminDailyUsage, metric: DashboardMetric): number {
  if (metric === "cost") return row.cost_fen ?? 0;
  if (metric === "calls") return row.calls;
  return row.charge_fen;
}

function formatMetric(value: number, metric: DashboardMetric): string {
  if (metric === "calls") return String(value);
  return `¥${fenToYuan(value)}`;
}

function shortDate(iso: string): string {
  const parts = iso.split("-");
  return parts.length === 3 ? `${parts[1]}/${parts[2]}` : iso;
}

/** 用量趋势面积图 */
export function UsageTrendChart({ data, metric }: UsageTrendChartProps) {
  const chartData = data.map((row) => ({
    date: row.date,
    label: shortDate(row.date),
    value: readMetric(row, metric),
  }));

  if (chartData.length === 0) {
    return <div className="admin-chart-empty">暂无趋势数据</div>;
  }

  return (
    <div className="admin-chart-wrap">
      <ResponsiveContainer width="100%" height={240}>
        <AreaChart data={chartData} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
          <defs>
            <linearGradient id="usageTrendFill" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="var(--admin-accent)" stopOpacity={0.35} />
              <stop offset="100%" stopColor="var(--admin-accent)" stopOpacity={0.02} />
            </linearGradient>
          </defs>
          <CartesianGrid stroke="var(--admin-border)" strokeDasharray="3 3" vertical={false} />
          <XAxis
            dataKey="label"
            tick={{ fill: "var(--admin-muted)", fontSize: 11 }}
            axisLine={false}
            tickLine={false}
            minTickGap={16}
          />
          <YAxis
            tick={{ fill: "var(--admin-muted)", fontSize: 11 }}
            axisLine={false}
            tickLine={false}
            width={metric === "calls" ? 36 : 52}
            tickFormatter={(v) => (metric === "calls" ? String(v) : `¥${fenToYuan(Number(v))}`)}
          />
          <Tooltip
            contentStyle={{
              background: "var(--admin-card)",
              border: "1px solid var(--admin-border)",
              borderRadius: "10px",
              fontSize: "12px",
            }}
            labelFormatter={(_, payload) => {
              const row = payload?.[0]?.payload as { date?: string } | undefined;
              return row?.date ?? "";
            }}
            formatter={(value) => [formatMetric(Number(value ?? 0), metric), metricLabel(metric)]}
          />
          <Area
            type="monotone"
            dataKey="value"
            stroke="var(--admin-forest)"
            strokeWidth={2}
            fill="url(#usageTrendFill)"
            dot={false}
            activeDot={{ r: 4, fill: "var(--admin-forest)" }}
          />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}
