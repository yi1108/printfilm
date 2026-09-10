import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";
import { AdminChipFilter } from "@/components/admin/AdminChipFilter";
import { AdminFilterBar } from "@/components/admin/AdminFilterBar";
import { PageSection } from "@/components/admin/PageSection";
import { Button } from "@/components/ui/button";
import { PageHeader } from "@/components/ui/page";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { api, type AdminFinanceDaily } from "@/api/client";
import { fenToYuan } from "@/lib/utils";

type FinanceDays = "7" | "14" | "30" | "90";

const DAY_OPTIONS = [
  { value: "7", label: "近 7 日" },
  { value: "14", label: "近 14 日" },
  { value: "30", label: "近 30 日" },
  { value: "90", label: "近 90 日" },
];

function profitClass(profitFen: number): string {
  if (profitFen > 0) return "text-[var(--admin-forest)] font-semibold";
  if (profitFen < 0) return "text-red-600 font-semibold";
  return "";
}

/** 管理端财务列表：按日展示扣费、成本、token、实际成本与利润 */
export function FinanceListPage() {
  const [days, setDays] = useState<FinanceDays>("30");
  const [data, setData] = useState<AdminFinanceDaily | null>(null);
  const [loading, setLoading] = useState(true);
  const [syncing, setSyncing] = useState(false);

  const loadData = useCallback(async () => {
    setLoading(true);
    try {
      const res = await api<AdminFinanceDaily>(`/api/admin/finance/daily?days=${days}`);
      setData(res);
    } catch (err) {
      setData(null);
      toast.error(err instanceof Error ? err.message : "财务列表加载失败");
    } finally {
      setLoading(false);
    }
  }, [days]);

  const syncOfficial = useCallback(async () => {
    setSyncing(true);
    try {
      const res = await api<AdminFinanceDaily>(`/api/admin/finance/daily/sync?days=${days}`, { method: "POST" });
      setData(res);
      toast.success("官方成本已刷新");
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "刷新失败");
    } finally {
      setSyncing(false);
    }
  }, [days]);

  useEffect(() => {
    void loadData();
  }, [loadData]);

  const rows = [...(data?.series ?? [])].reverse();
  const totals = data?.totals;
  const rangeMismatch = data != null && String(data.days) !== days;

  return (
    <div className="admin-page">
      <PageHeader description="按日汇总本地扣费、成本与官方实际成本，计算利润" />

      <AdminFilterBar>
        <AdminChipFilter
          label="时间范围"
          value={days}
          options={DAY_OPTIONS}
          onChange={(v) => setDays(v as FinanceDays)}
          className="admin-chip-filter--segment"
        />
      </AdminFilterBar>

      <PageSection
        title="财务列表"
        description={
          rangeMismatch
            ? "数据与当前时间范围不一致，请重新加载"
            : data?.configured
            ? `近 ${days} 日 · 实际成本来自方舟官方用量${data.last_sync_at ? ` · 最近同步 ${new Date(data.last_sync_at).toLocaleString()}` : ""}`
            : "未配置火山 Access Key，实际成本列为空；可在「系统设置 → 支付计费 → 上游成本监控」配置后刷新"
        }
        actions={
          data?.configured ? (
            <Button type="button" size="sm" variant="outline" disabled={syncing || loading} onClick={() => void syncOfficial()}>
              {syncing ? "刷新中…" : "刷新官方成本"}
            </Button>
          ) : null
        }
        bodyClassName="!pt-0"
      >
        <div className="admin-table-wrap">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>日期</TableHead>
                <TableHead>本地扣费</TableHead>
                <TableHead>本地成本</TableHead>
                <TableHead>Token</TableHead>
                <TableHead>实际成本</TableHead>
                <TableHead>利润</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {loading ? (
                <TableRow>
                  <TableCell colSpan={6} className="!text-center text-[var(--admin-muted)]">
                    加载中…
                  </TableCell>
                </TableRow>
              ) : rows.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={6} className="!text-center text-[var(--admin-muted)]">
                    暂无数据
                  </TableCell>
                </TableRow>
              ) : (
                <>
                  {rows.map((row) => (
                    <TableRow key={row.date}>
                      <TableCell className="font-mono text-xs">{row.date}</TableCell>
                      <TableCell>¥{fenToYuan(row.charge_fen)}</TableCell>
                      <TableCell>¥{fenToYuan(row.cost_fen)}</TableCell>
                      <TableCell>{row.tokens.toLocaleString()}</TableCell>
                      <TableCell>
                        {row.actual_cost_fen > 0 ? `¥${fenToYuan(row.actual_cost_fen)}` : "—"}
                      </TableCell>
                      <TableCell className={profitClass(row.profit_fen)}>
                        ¥{fenToYuan(row.profit_fen)}
                        {row.profit_pct != null ? ` (${row.profit_pct}%)` : ""}
                      </TableCell>
                    </TableRow>
                  ))}
                  {totals ? (
                    <TableRow className="bg-[rgba(15,45,32,0.04)] font-medium">
                      <TableCell>合计</TableCell>
                      <TableCell>¥{fenToYuan(totals.charge_fen)}</TableCell>
                      <TableCell>¥{fenToYuan(totals.cost_fen)}</TableCell>
                      <TableCell>{totals.tokens.toLocaleString()}</TableCell>
                      <TableCell>
                        {totals.actual_cost_fen > 0 ? `¥${fenToYuan(totals.actual_cost_fen)}` : "—"}
                      </TableCell>
                      <TableCell className={profitClass(totals.profit_fen)}>
                        ¥{fenToYuan(totals.profit_fen)}
                        {totals.profit_pct != null ? ` (${totals.profit_pct}%)` : ""}
                      </TableCell>
                    </TableRow>
                  ) : null}
                </>
              )}
            </TableBody>
          </Table>
        </div>
      </PageSection>
    </div>
  );
}
