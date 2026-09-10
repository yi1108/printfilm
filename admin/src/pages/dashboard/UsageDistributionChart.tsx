import {
  Bar,
  BarChart,
  Cell,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { AdminUsageBucket } from "@/api/client";
import { fenToYuan } from "@/lib/utils";
import type { DashboardMetric } from "./DashboardFilters";

const CHART_COLORS = [
  "var(--admin-forest)",
  "var(--admin-accent)",
  "#5a9e86",
  "#7ab89f",
  "#9fd0b8",
  "#c2e2d4",
];

type UsageDistributionChartProps = {
  data: AdminUsageBucket[];
  metric: DashboardMetric;
  labelForKey: (key: string) => string;
  variant?: "bar" | "donut";
  chartHeight?: number;
  yAxisWidth?: number;
};

function readMetric(row: AdminUsageBucket, metric: DashboardMetric): number {
  if (metric === "cost") return row.cost_fen ?? 0;
  if (metric === "calls") return row.calls;
  return row.charge_fen;
}

function formatMetric(value: number, metric: DashboardMetric): string {
  if (metric === "calls") return String(value);
  return `¥${fenToYuan(value)}`;
}

/** 能力 / 领域分布图 */
export function UsageDistributionChart({
  data,
  metric,
  labelForKey,
  variant = "bar",
  chartHeight = 220,
  yAxisWidth = 72,
}: UsageDistributionChartProps) {
  const chartData = data
    .map((row) => ({
      key: row.key,
      name: labelForKey(row.key),
      value: readMetric(row, metric),
    }))
    .filter((row) => row.value > 0);

  if (chartData.length === 0) {
    return <div className="admin-chart-empty">暂无分布数据</div>;
  }

  if (variant === "donut") {
    return (
      <div className="admin-chart-wrap admin-chart-wrap--compact">
        <ResponsiveContainer width="100%" height={220}>
          <PieChart>
            <Pie
              data={chartData}
              dataKey="value"
              nameKey="name"
              innerRadius={52}
              outerRadius={78}
              paddingAngle={2}
              stroke="none"
            >
              {chartData.map((row, idx) => (
                <Cell key={row.key} fill={CHART_COLORS[idx % CHART_COLORS.length]} />
              ))}
            </Pie>
            <Tooltip
              contentStyle={{
                background: "var(--admin-card)",
                border: "1px solid var(--admin-border)",
                borderRadius: "10px",
                fontSize: "12px",
              }}
              formatter={(value, _name, item) => {
                const row = item?.payload as { name?: string } | undefined;
                return [formatMetric(Number(value ?? 0), metric), row?.name ?? ""];
              }}
            />
          </PieChart>
        </ResponsiveContainer>
        <div className="admin-chart-legend">
          {chartData.map((row, idx) => (
            <div key={row.key} className="admin-chart-legend-item">
              <span
                className="admin-chart-legend-dot"
                style={{ background: CHART_COLORS[idx % CHART_COLORS.length] }}
              />
              <span className="admin-chart-legend-label">{row.name}</span>
              <span className="admin-chart-legend-value">{formatMetric(row.value, metric)}</span>
            </div>
          ))}
        </div>
      </div>
    );
  }

  return (
    <div className="admin-chart-wrap admin-chart-wrap--compact">
      <ResponsiveContainer width="100%" height={chartHeight}>
        <BarChart data={chartData} layout="vertical" margin={{ top: 0, right: 8, left: 0, bottom: 0 }}>
          <XAxis type="number" hide />
          <YAxis
            type="category"
            dataKey="name"
            width={yAxisWidth}
            tick={{ fill: "var(--admin-muted)", fontSize: 11 }}
            axisLine={false}
            tickLine={false}
          />
          <Tooltip
            cursor={{ fill: "var(--admin-accent-soft)" }}
            contentStyle={{
              background: "var(--admin-card)",
              border: "1px solid var(--admin-border)",
              borderRadius: "10px",
              fontSize: "12px",
            }}
            formatter={(value) => [formatMetric(Number(value ?? 0), metric), "数值"]}
          />
          <Bar dataKey="value" radius={[0, 6, 6, 0]} maxBarSize={18}>
            {chartData.map((row, idx) => (
              <Cell key={row.key} fill={CHART_COLORS[idx % CHART_COLORS.length]} />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
