import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";
import type { AdminLedger, PageResult } from "@/api/client";
import { listAdminLedger } from "@/api/finance";
import { AdminDateRangeFilter } from "@/components/admin/AdminDateRangeFilter";
import { AdminEntityLink } from "@/components/admin/AdminEntityLink";
import { AdminFilterBar } from "@/components/admin/AdminFilterBar";
import { AdminUserSearchSelect } from "@/components/admin/AdminUserSearchSelect";
import { PageSection } from "@/components/admin/PageSection";
import { PaginationBar } from "@/components/PaginationBar";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { PageHeader } from "@/components/ui/page";
import { Select } from "@/components/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { points } from "@/lib/points";

type LedgerRes = PageResult<AdminLedger>;

type DirectionFilter = "" | "credit" | "debit";

/** 调账方向文案：正数为调增，负数为调减 */
function directionLabel(deltaFen: number): string {
  return deltaFen >= 0 ? "调增" : "调减";
}

/** 管理端手动调账记录：仅展示 ref_type=admin 的钱包流水 */
export function AdjustRecordsPage() {
  const [userId, setUserId] = useState<number | null>(null);
  const [direction, setDirection] = useState<DirectionFilter>("");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [page, setPage] = useState(1);
  const [data, setData] = useState<LedgerRes | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(
    async (nextPage = page) => {
      setLoading(true);
      try {
        // 后台写流水：调减 kind=adjust，调增 kind=grant。
        setData(await listAdminLedger(nextPage, {
          refType: "admin",
          userId,
          kind: direction === "credit" ? "grant" : direction === "debit" ? "adjust" : "",
          dateFrom,
          dateTo,
        }));
      } catch (err) {
        setData(null);
        toast.error(err instanceof Error ? err.message : "加载调账记录失败");
      } finally {
        setLoading(false);
      }
    },
    [page, userId, direction, dateFrom, dateTo],
  );

  useEffect(() => {
    void load(page);
  }, [load, page]);

  const rows = data?.items ?? [];

  return (
    <div className="admin-page">
      <PageHeader title="手动调账" description="用户管理里手动改余额产生的调账流水，含操作人与备注" />

      <AdminFilterBar>
        <AdminUserSearchSelect value={userId} onChange={setUserId} />
        <Select
          value={direction}
          onChange={(e) => setDirection(e.target.value as DirectionFilter)}
        >
          <option value="">全部方向</option>
          <option value="credit">调增</option>
          <option value="debit">调减</option>
        </Select>
        <AdminDateRangeFilter
          from={dateFrom}
          to={dateTo}
          onChange={({ from, to }) => {
            setDateFrom(from);
            setDateTo(to);
          }}
        />
        <Button
          size="sm"
          variant="secondary"
          className="admin-filter-action"
          onClick={() => {
            setPage(1);
            void load(1);
          }}
        >
          筛选
        </Button>
      </AdminFilterBar>

      <PageSection
        title="手动调账记录"
        description={data ? `共 ${data.meta.total} 条` : undefined}
        bodyClassName="!pt-0"
      >
        <div className="admin-table-wrap">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>ID</TableHead>
                <TableHead>时间</TableHead>
                <TableHead>用户</TableHead>
                <TableHead>方向</TableHead>
                <TableHead>变动</TableHead>
                <TableHead>余额后</TableHead>
                <TableHead>操作人</TableHead>
                <TableHead>备注</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {loading ? (
                <TableRow>
                  <TableCell colSpan={8} className="!text-center text-[var(--admin-muted)]">
                    加载中…
                  </TableCell>
                </TableRow>
              ) : rows.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={8} className="!text-center text-[var(--admin-muted)]">
                    暂无手动调账记录
                  </TableCell>
                </TableRow>
              ) : (
                rows.map((row) => (
                  <TableRow key={row.id}>
                    <TableCell className="font-mono text-xs">{row.id}</TableCell>
                    <TableCell className="text-xs text-muted-foreground whitespace-nowrap">
                      {new Date(row.created_at).toLocaleString()}
                    </TableCell>
                    <TableCell>
                      <AdminEntityLink kind="user" id={row.user_id} label={row.user_email ?? undefined} />
                    </TableCell>
                    <TableCell>
                      <Badge variant={row.delta_fen >= 0 ? "success" : "secondary"}>
                        {directionLabel(row.delta_fen)}
                      </Badge>
                    </TableCell>
                    <TableCell className={row.delta_fen >= 0 ? "text-emerald-700" : "text-red-600"}>
                      {row.delta_fen >= 0 ? "+" : ""}{points(row.delta_fen)}
                    </TableCell>
                    <TableCell>{points(row.balance_after)}</TableCell>
                    <TableCell>
                      {row.ref_id && /^\d+$/.test(row.ref_id) ? (
                        <AdminEntityLink
                          kind="user"
                          id={Number(row.ref_id)}
                          label={row.operator_email ?? undefined}
                        />
                      ) : (
                        row.operator_email || "—"
                      )}
                    </TableCell>
                    <TableCell className="max-w-[240px] truncate" title={row.note || undefined}>
                      {row.note || "—"}
                    </TableCell>
                  </TableRow>
                ))
              )}
            </TableBody>
          </Table>
        </div>
        {data ? (
          <PaginationBar
            page={data.meta.page}
            pageSize={data.meta.page_size}
            total={data.meta.total}
            onPageChange={setPage}
          />
        ) : null}
      </PageSection>
    </div>
  );
}
