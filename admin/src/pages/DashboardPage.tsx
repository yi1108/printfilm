import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import {
  Activity,
  Banknote,
  Clapperboard,
  Film,
  Layers,
  Receipt,
  Settings,
  Shapes,
  Users,
  Wallet,
  Zap,
} from "lucide-react";
import { toast } from "sonner";
import { PageSection } from "@/components/admin/PageSection";
import { PageHeader } from "@/components/ui/page";
import { api, type AdminOrder, type AdminStats, type AdminUpstreamUsage, type PageMeta } from "@/api/client";
import { AdminEntityLink } from "@/components/admin/AdminEntityLink";
import { fenToYuan } from "@/lib/utils";
import { projectStatusLabel, taskDomainLabel } from "@/lib/statusLabels";
import { Button } from "@/components/ui/button";
import {
  buildStatsQuery,
  dashboardRangeLabel,
  DashboardFilters,
  DEFAULT_DASHBOARD_FILTERS,
  PROJECTS_DASHBOARD_FILTERS,
  type DashboardFilterState,
} from "@/pages/dashboard/DashboardFilters";
import { DashboardKpiCard } from "@/pages/dashboard/DashboardKpiCard";
import { DashboardInsightGrid } from "@/pages/dashboard/DashboardInsightGrid";
import { DashboardPeriodKpis } from "@/pages/dashboard/DashboardPeriodKpis";
import { DashboardSectionTabs, type DashboardSection } from "@/pages/dashboard/DashboardSectionTabs";
import { buildDomainInsights } from "@/pages/dashboard/dashboardInsightMaps";
import { buildFinanceInsights, buildProjectInsights } from "@/pages/dashboard/dashboardSectionInsights";
import { sumDailyUsage } from "@/pages/dashboard/dashboardMetrics";
import { UsageDistributionChart } from "@/pages/dashboard/UsageDistributionChart";
import { TopUsersRankingChart } from "@/pages/dashboard/TopUsersRankingChart";
import { UsageTrendChart } from "@/pages/dashboard/UsageTrendChart";

type OrderRes = { items: AdminOrder[]; meta: PageMeta };

const CAPABILITY_LABELS: Record<string, string> = {
  llm: "LLM 文本",
  image: "生图",
  video: "视频",
  tts: "配音",
  unknown: "其他",
  other: "其他",
};

function statusClass(status: string): string {
  if (status === "DONE") return "is-done";
  if (status === "FAILED" || status === "REJECTED" || status === "CANCELLED") return "is-fail";
  if (status === "SCRIPTING" || status === "IMAGING" || status === "VIDEOING" || status === "COMPOSING") {
    return "is-run";
  }
  return "is-warn";
}

function capabilityLabel(key: string): string {
  return CAPABILITY_LABELS[key] ?? key;
}

function domainChartLabel(key: string): string {
  if (key === "kepu") return "AI短视频";
  return taskDomainLabel(key);
}

/** 管理端仪表盘：板块切换 + 渐变 KPI + 可筛选用量图表 */
export function DashboardPage() {
  const [section, setSection] = useState<DashboardSection>("overview");
  const [filters, setFilters] = useState<DashboardFilterState>(DEFAULT_DASHBOARD_FILTERS);
  const [stats, setStats] = useState<AdminStats | null>(null);
  const [orders, setOrders] = useState<AdminOrder[]>([]);
  const [upstreamUsage, setUpstreamUsage] = useState<AdminUpstreamUsage | null>(null);
  const [upstreamSyncing, setUpstreamSyncing] = useState(false);
  const [loading, setLoading] = useState(true);

  const loadUpstreamUsage = useCallback(async () => {
    try {
      const data = await api<AdminUpstreamUsage>("/api/admin/stats/upstream-usage?days=30");
      setUpstreamUsage(data);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "官方用量加载失败");
    }
  }, []);

  const syncUpstreamUsage = useCallback(async () => {
    setUpstreamSyncing(true);
    try {
      await api("/api/admin/stats/upstream-usage/sync?days=30", { method: "POST" });
      toast.success("官方用量已刷新");
      await loadUpstreamUsage();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "刷新失败");
    } finally {
      setUpstreamSyncing(false);
    }
  }, [loadUpstreamUsage]);

  const loadData = useCallback(async (nextFilters: DashboardFilterState) => {
    setLoading(true);
    try {
      const [s, o] = await Promise.all([
        api<AdminStats>(buildStatsQuery(nextFilters)),
        api<OrderRes>("/api/admin/orders?page=1&page_size=8&status=paid"),
      ]);
      setStats(s);
      setOrders(o.items);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "加载失败");
    } finally {
      setLoading(false);
    }
  }, []);

  const kpiReady = Boolean(stats);
  const kpiPlaceholder = loading ? "…" : "—";
  const statsFilters = section === "projects" ? PROJECTS_DASHBOARD_FILTERS : filters;
  const projectsRangeLabel = dashboardRangeLabel(PROJECTS_DASHBOARD_FILTERS.days);

  useEffect(() => {
    void loadData(statsFilters);
  }, [statsFilters, loadData]);

  useEffect(() => {
    void loadUpstreamUsage();
  }, [loadUpstreamUsage]);

  const statusEntries = Object.entries(stats?.project_status_counts ?? {}).sort((a, b) => b[1] - a[1]);
  const daily = stats?.daily_usage ?? [];
  const byCapability = stats?.usage_by_capability ?? [];
  const byDomain = stats?.usage_by_domain ?? [];
  const topUsers = stats?.top_users_by_charge ?? [];
  const rangeLabel = dashboardRangeLabel(filters.days);
  const showUsageFilters = section === "overview" || section === "usage";
  const domainInsights = buildDomainInsights(byDomain, filters.metric, domainChartLabel);
  const financeInsights = buildFinanceInsights(stats, upstreamUsage);
  const projectInsights = buildProjectInsights(stats, sumDailyUsage(daily));
  const metricHint =
    filters.metric === "cost" ? "上游成本" : filters.metric === "calls" ? "调用次数" : "扣费金额";

  return (
    <div className="admin-page admin-dashboard-page">
      <PageHeader description="用户、充值、AI 调用与费用概览" />

      <div className="admin-dashboard-kpi-grid">
        <DashboardKpiCard
          label="用户总数"
          value={kpiReady ? stats!.user_count : kpiPlaceholder}
          hint="总注册用户"
          icon={Users}
          tone="teal"
        />
        <DashboardKpiCard
          label="累计已付"
          value={kpiReady ? `¥${fenToYuan(stats!.order_paid_total_fen)}` : kpiPlaceholder}
          hint="历史充值"
          icon={Banknote}
          tone="blue"
        />
        <DashboardKpiCard
          label="本月 AI 扣费"
          value={kpiReady ? `¥${fenToYuan(stats!.usage_charge_month_fen ?? 0)}` : kpiPlaceholder}
          hint={kpiReady ? `今日 ¥${fenToYuan(stats!.usage_charge_today_fen ?? 0)}` : "今日扣费"}
          icon={Zap}
          tone="purple"
        />
        <DashboardKpiCard
          label="本月上游成本"
          value={kpiReady ? `¥${fenToYuan(stats!.usage_cost_month_fen ?? 0)}` : kpiPlaceholder}
          hint={kpiReady ? `今日 ¥${fenToYuan(stats!.usage_cost_today_fen ?? 0)}` : "成本汇总"}
          icon={Wallet}
          tone="sand"
        />
      </div>

      <DashboardSectionTabs value={section} onChange={setSection} />

      {showUsageFilters ? <DashboardFilters value={filters} onChange={setFilters} /> : null}
      {showUsageFilters ? <DashboardPeriodKpis stats={stats} filters={filters} loading={loading} /> : null}

      {section === "overview" ? (
        <>
          <div className="admin-dashboard-charts">
            <PageSection
              title={`${rangeLabel}用量趋势`}
              description={loading ? "加载中…" : "按筛选条件聚合的日趋势"}
              bodyClassName="!pt-2"
              className="admin-dashboard-chart-main admin-dashboard-glass min-h-0"
            >
              <UsageTrendChart data={daily} metric={filters.metric} />
            </PageSection>

            <PageSection
              title="能力分布"
              description={`${rangeLabel} · ${metricHint}`}
              bodyClassName="!pt-2"
              className="admin-dashboard-chart-side admin-dashboard-glass min-h-0"
            >
              <UsageDistributionChart
                data={byCapability}
                metric={filters.metric}
                labelForKey={capabilityLabel}
                variant="donut"
              />
            </PageSection>
          </div>

          <PageSection
            title={`用户消费 TOP3（${rangeLabel}）`}
            actions={
              <Link to="/orders?tab=usage" className="admin-link">
                更多 →
              </Link>
            }
            bodyClassName="!pt-2"
            className="admin-dashboard-glass min-h-0"
          >
            <TopUsersRankingChart users={topUsers.slice(0, 3)} metric={filters.metric} />
          </PageSection>

          <div className="admin-dashboard-charts">
            <PageSection
              title="领域分布"
              description={`${rangeLabel} · ${metricHint}`}
              bodyClassName="!pt-2"
              className="admin-dashboard-chart-main admin-dashboard-glass min-h-0"
            >
              <UsageDistributionChart
                data={byDomain}
                metric={filters.metric}
                labelForKey={domainChartLabel}
                variant="bar"
              />
            </PageSection>
            <PageSection
              title="领域洞察"
              description={`${rangeLabel} · ${metricHint}`}
              bodyClassName="!pt-2"
              className="admin-dashboard-chart-side admin-dashboard-glass min-h-0"
            >
              <DashboardInsightGrid items={domainInsights} columns={2} />
            </PageSection>
          </div>
        </>
      ) : null}

      {section === "usage" ? (
        <>
          <div className="admin-dashboard-charts">
            <PageSection
              title={`${rangeLabel}用量趋势`}
              description={loading ? "加载中…" : "扣费 / 成本 / 调用按日聚合"}
              bodyClassName="!pt-2"
              className="admin-dashboard-chart-main admin-dashboard-glass min-h-0"
            >
              <UsageTrendChart data={daily} metric={filters.metric} />
            </PageSection>

            <PageSection
              title="能力分布"
              description={`${rangeLabel} · ${metricHint}`}
              bodyClassName="!pt-2"
              className="admin-dashboard-chart-side admin-dashboard-glass min-h-0"
            >
              <UsageDistributionChart
                data={byCapability}
                metric={filters.metric}
                labelForKey={capabilityLabel}
                variant="donut"
              />
            </PageSection>
          </div>

          <div className="admin-dashboard-charts">
            <PageSection
              title="领域分布"
              description={`${rangeLabel} · ${metricHint}`}
              bodyClassName="!pt-2"
              className="admin-dashboard-chart-main admin-dashboard-glass min-h-0"
            >
              <UsageDistributionChart
                data={byDomain}
                metric={filters.metric}
                labelForKey={domainChartLabel}
                variant="bar"
              />
            </PageSection>
            <PageSection
              title={`用户消费排行（${rangeLabel}）`}
              actions={
                <Link to="/orders?tab=usage" className="admin-link">
                  用量明细 →
                </Link>
              }
              description={metricHint}
              bodyClassName="!pt-2"
              className="admin-dashboard-chart-side admin-dashboard-glass min-h-0"
            >
              <TopUsersRankingChart users={topUsers} metric={filters.metric} />
            </PageSection>
          </div>
        </>
      ) : null}

      {section === "finance" ? (
        <div className="admin-dashboard-body admin-dashboard-body--finance">
          <PageSection
            title="财务概览"
            description="充值、扣费、成本与毛利"
            actions={
              <Link to="/finance" className="admin-link">
                财务列表 →
              </Link>
            }
            bodyClassName="!pt-2"
            className="admin-dashboard-glass min-h-0 admin-dashboard-body--full"
          >
            <DashboardInsightGrid items={financeInsights} columns={3} />
          </PageSection>

          <PageSection
            title="Seedance 官方用量对照"
            description={
              upstreamUsage?.configured
                ? `近 30 日本地 seedance 成本 vs 方舟 GetInferenceUsage${upstreamUsage.last_sync_at ? ` · 最近同步 ${new Date(upstreamUsage.last_sync_at).toLocaleString()}` : ""}`
                : "未配置火山 Access Key，请在「支付计费 → 上游成本监控」配置后刷新官方数据"
            }
            actions={
              upstreamUsage?.configured ? (
                <Button type="button" size="sm" variant="outline" disabled={upstreamSyncing} onClick={() => void syncUpstreamUsage()}>
                  {upstreamSyncing ? "刷新中…" : "刷新官方数据"}
                </Button>
              ) : null
            }
            bodyClassName="!pt-0"
            className="admin-dashboard-glass min-h-0"
          >
            <div className="admin-table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>日期</th>
                    <th>本地成本</th>
                    <th>本地 token</th>
                    <th>官方 token</th>
                    <th>官方成本</th>
                    <th>差额</th>
                  </tr>
                </thead>
                <tbody>
                  {(upstreamUsage?.series ?? []).length === 0 ? (
                    <tr>
                      <td colSpan={6} className="!text-center text-[var(--admin-muted)]">
                        暂无对照数据
                      </td>
                    </tr>
                  ) : (
                    [...(upstreamUsage?.series ?? [])].reverse().slice(0, 14).map((row) => (
                      <tr key={row.date}>
                        <td className="font-mono text-xs">{row.date}</td>
                        <td>¥{fenToYuan(row.local_cost_fen)}</td>
                        <td>{row.local_tokens.toLocaleString()}</td>
                        <td>{row.official_tokens > 0 ? row.official_tokens.toLocaleString() : "—"}</td>
                        <td>{row.official_cost_fen > 0 ? `¥${fenToYuan(row.official_cost_fen)}` : "—"}</td>
                        <td>
                          {row.official_cost_fen > 0
                            ? `¥${fenToYuan(row.delta_fen)}${row.delta_pct != null ? ` (${row.delta_pct}%)` : ""}`
                            : "—"}
                        </td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>
          </PageSection>

          <PageSection
            title="最近订单"
            description="仅展示支付成功"
            actions={
              <Link to="/orders" className="admin-link">
                全部 →
              </Link>
            }
            bodyClassName="!pt-0"
            className="admin-dashboard-glass min-h-0"
          >
            <div className="admin-table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>用户名</th>
                    <th>金额</th>
                    <th>支付时间</th>
                  </tr>
                </thead>
                <tbody>
                  {orders.length === 0 ? (
                    <tr>
                      <td colSpan={3} className="!text-center text-[var(--admin-muted)]">
                        暂无已支付订单
                      </td>
                    </tr>
                  ) : (
                    orders.map((o) => (
                      <tr key={o.id}>
                        <td>
                          <AdminEntityLink kind="user" id={o.user_id} label={o.user_email ?? undefined} />
                        </td>
                        <td className="font-semibold text-[var(--admin-forest)]">¥{fenToYuan(o.amount_fen)}</td>
                        <td className="text-xs text-[var(--admin-muted)]">
                          {o.paid_at ? new Date(o.paid_at).toLocaleString() : "—"}
                        </td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>
          </PageSection>
        </div>
      ) : null}

      {section === "projects" ? (
        <>
          <PageSection
            title="运维概览"
            description="项目规模、调用与状态分布"
            bodyClassName="!pt-2"
            className="admin-dashboard-glass min-h-0"
          >
            <DashboardInsightGrid items={projectInsights} columns={4} />
          </PageSection>

          <div className="admin-dashboard-project-row">
            <PageSection
              title="AI短视频项目状态"
              description={`漫剧项目 ${stats?.drama_project_count ?? 0} 部`}
              bodyClassName="!pt-2"
              className="admin-dashboard-glass min-h-0"
            >
              <div className="flex flex-wrap gap-1.5">
                {statusEntries.length === 0 ? (
                  <span className="text-xs text-[var(--admin-muted)]">暂无数据</span>
                ) : (
                  statusEntries.map(([status, count]) => (
                    <span key={status} className={`admin-status-pill !px-2.5 !py-1 !text-[11px] ${statusClass(status)}`}>
                      {projectStatusLabel(status)} {count}
                    </span>
                  ))
                )}
              </div>
            </PageSection>

            <PageSection title="调用统计" bodyClassName="!pt-2" className="admin-dashboard-glass min-h-0">
              <div className="admin-dashboard-stat-grid">
                <div>
                  <div className="admin-dashboard-stat-grid-label">今日调用</div>
                  <div className="admin-dashboard-stat-grid-value">
                    {kpiReady ? stats!.usage_calls_today ?? 0 : kpiPlaceholder}
                  </div>
                </div>
                <div>
                  <div className="admin-dashboard-stat-grid-label">本月调用</div>
                  <div className="admin-dashboard-stat-grid-value">
                    {kpiReady ? stats!.usage_calls_month ?? 0 : kpiPlaceholder}
                  </div>
                </div>
                <div>
                  <div className="admin-dashboard-stat-grid-label">累计调用</div>
                  <div className="admin-dashboard-stat-grid-value">
                    {kpiReady ? stats!.usage_calls_total ?? 0 : kpiPlaceholder}
                  </div>
                </div>
              </div>
            </PageSection>
          </div>

          <PageSection title={`领域分布（${projectsRangeLabel}）`} bodyClassName="!pt-2" className="admin-dashboard-glass min-h-0">
            <UsageDistributionChart
              data={byDomain}
              metric="charge"
              labelForKey={domainChartLabel}
              variant="bar"
            />
          </PageSection>

          <PageSection title="快捷入口" bodyClassName="!pt-2" className="admin-dashboard-glass">
            <div className="admin-dashboard-tools">
              <Link to="/templates" className="admin-dashboard-tool-btn">
                <Shapes className="h-5 w-5" />
                <span>模板管理</span>
              </Link>
              <Link to="/orders?tab=usage" className="admin-dashboard-tool-btn">
                <Receipt className="h-5 w-5" />
                <span>订单用量</span>
              </Link>
              <Link to="/users" className="admin-dashboard-tool-btn">
                <Users className="h-5 w-5" />
                <span>用户管理</span>
              </Link>
              <Link to="/projects" className="admin-dashboard-tool-btn">
                <Clapperboard className="h-5 w-5" />
                <span>AI短视频</span>
              </Link>
              <Link to="/drama-projects" className="admin-dashboard-tool-btn">
                <Film className="h-5 w-5" />
                <span>漫剧项目</span>
              </Link>
              <Link to="/queues" className="admin-dashboard-tool-btn">
                <Layers className="h-5 w-5" />
                <span>任务队列</span>
              </Link>
              <Link to="/settings" className="admin-dashboard-tool-btn">
                <Settings className="h-5 w-5" />
                <span>系统配置</span>
              </Link>
              <Link to="/orders" className="admin-dashboard-tool-btn">
                <Activity className="h-5 w-5" />
                <span>财务流水</span>
              </Link>
            </div>
          </PageSection>
        </>
      ) : null}
    </div>
  );
}
