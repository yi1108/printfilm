import { AdminChipFilter } from "@/components/admin/AdminChipFilter";
import { AdminFilterBar } from "@/components/admin/AdminFilterBar";

/** 仪表盘筛选维度 */
export type DashboardDays = "1" | "7" | "14" | "30";
export type DashboardDomain = "all" | "drama" | "kepu" | "api" | "tools" | "studio";
export type DashboardCapability = "all" | "llm" | "image" | "video" | "tts";
export type DashboardMetric = "charge" | "cost" | "calls";

export type DashboardFilterState = {
  days: DashboardDays;
  domain: DashboardDomain;
  capability: DashboardCapability;
  metric: DashboardMetric;
};

export const DEFAULT_DASHBOARD_FILTERS: DashboardFilterState = {
  days: "7",
  domain: "all",
  capability: "all",
  metric: "charge",
};

/** 运维 Tab 固定全量 30 日，不受隐藏筛选影响 */
export const PROJECTS_DASHBOARD_FILTERS: DashboardFilterState = {
  days: "30",
  domain: "all",
  capability: "all",
  metric: "charge",
};

const DAY_OPTIONS = [
  { value: "1", label: "今日" },
  { value: "7", label: "近 7 日" },
  { value: "14", label: "近 14 日" },
  { value: "30", label: "近 30 日" },
];

/** 图表 / 区块标题用的时间范围文案 */
export function dashboardRangeLabel(days: DashboardDays): string {
  if (days === "1") return "今日";
  return `近 ${days} 日`;
}

const DOMAIN_OPTIONS = [
  { value: "all", label: "全部领域" },
  { value: "drama", label: "漫剧" },
  { value: "kepu", label: "AI短视频" },
  { value: "api", label: "开放 API" },
  { value: "tools", label: "工具" },
  { value: "studio", label: "工作室" },
];

const CAPABILITY_OPTIONS = [
  { value: "all", label: "全部能力" },
  { value: "llm", label: "LLM" },
  { value: "image", label: "生图" },
  { value: "video", label: "视频" },
  { value: "tts", label: "配音" },
];

const METRIC_OPTIONS = [
  { value: "charge", label: "扣费" },
  { value: "cost", label: "成本" },
  { value: "calls", label: "调用" },
];

type DashboardFiltersProps = {
  value: DashboardFilterState;
  onChange: (next: DashboardFilterState) => void;
};

/** 仪表盘用量筛选条（两行紧凑布局） */
export function DashboardFilters({ value, onChange }: DashboardFiltersProps) {
  const patch = (partial: Partial<DashboardFilterState>) => onChange({ ...value, ...partial });

  return (
    <AdminFilterBar className="admin-dashboard-filters">
      <AdminChipFilter
        label="时间维度"
        value={value.days}
        options={DAY_OPTIONS}
        onChange={(days) => patch({ days: days as DashboardDays })}
        className="admin-chip-filter--segment"
      />
      <AdminChipFilter
        label="业务领域"
        value={value.domain}
        options={DOMAIN_OPTIONS}
        onChange={(domain) => patch({ domain: domain as DashboardDomain })}
        className="admin-chip-filter--segment"
      />
      <AdminChipFilter
        label="能力类型"
        value={value.capability}
        options={CAPABILITY_OPTIONS}
        onChange={(capability) => patch({ capability: capability as DashboardCapability })}
        className="admin-chip-filter--segment"
      />
      <AdminChipFilter
        label="统计指标"
        value={value.metric}
        options={METRIC_OPTIONS}
        onChange={(metric) => patch({ metric: metric as DashboardMetric })}
        className="admin-chip-filter--segment"
      />
    </AdminFilterBar>
  );
}

/** 拼接 stats API 查询串 */
export function buildStatsQuery(filters: DashboardFilterState): string {
  const params = new URLSearchParams({
    days: filters.days,
    domain: filters.domain,
    capability: filters.capability,
    top_metric: filters.metric,
  });
  return `/api/admin/stats?${params.toString()}`;
}
