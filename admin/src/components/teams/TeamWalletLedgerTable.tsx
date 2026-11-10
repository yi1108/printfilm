import { useState } from "react";
import type { PageResult } from "@/api/types/common";
import type { AdminTeamWalletLedger } from "@/api/types/teams";
import { teamPaths } from "@/api/teams";
import { AdminFilterBar, AdminFilterField } from "@/components/admin/AdminFilterBar";
import { AdminSearchInput } from "@/components/admin/AdminSearchInput";
import { PaginationBar } from "@/components/PaginationBar";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Select } from "@/components/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { TeamQueryFeedback } from "./TeamQueryFeedback";
import { useAdminTeamQuery } from "@/hooks/useAdminTeamQuery";
import { teamDate } from "@/lib/teamLabels";
import { DEFAULT_PAGE_SIZE } from "@/lib/pagination";
import { points } from "@/lib/points";

/** 团队钱包流水：独立于模型消费记录，包含充值、任务记账与后台调账。 */
export function TeamWalletLedgerTable({ teamId }: { teamId: number }) {
  /* draft 为输入搜索，q/adjustmentsOnly 为已应用的服务端筛选。 */
  const [draft, setDraft] = useState("");
  const [q, setQ] = useState("");
  const [adjustmentsOnly, setAdjustmentsOnly] = useState(false);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(DEFAULT_PAGE_SIZE);
  const { data, loading, error, reload } = useAdminTeamQuery<PageResult<AdminTeamWalletLedger>>(teamPaths.walletLedger(teamId, { q, adjustmentsOnly, page, pageSize }));
  const kindLabels: Record<string, string> = { topup: "充值", freeze: "任务冻结", settle: "任务结算", refund: "退款", adjust: "后台调账" };
  return <div className="space-y-4">
    <form onSubmit={(event) => { event.preventDefault(); setQ(draft.trim()); setPage(1); reload(); }}>
      <AdminFilterBar>
        <AdminSearchInput value={draft} onChange={setDraft} placeholder="搜索调整备注、操作人或关联号" />
        <AdminFilterField label="流水范围"><Select value={String(adjustmentsOnly)} onChange={(event) => { setAdjustmentsOnly(event.target.value === "true"); setPage(1); }}><option value="false">全部钱包流水</option><option value="true">仅后台调账</option></Select></AdminFilterField>
        <Button type="submit" size="sm" disabled={loading}>搜索</Button>
      </AdminFilterBar>
    </form>
    <p className="text-xs text-[var(--admin-muted)]">每条流水记录变动金额及当时的调整后余额；后台调账展示实际操作人。</p>
    <TeamQueryFeedback loading={loading} error={error} empty={!data?.items.length} onRetry={reload} />
    {data && data.items.length > 0 && <Table><TableHeader><TableRow>
      <TableHead>时间（上海）</TableHead><TableHead>类型</TableHead><TableHead>变动金额</TableHead><TableHead>变动后余额</TableHead><TableHead>操作人</TableHead><TableHead>备注 / 关联</TableHead>
    </TableRow></TableHeader><TableBody>{data.items.map((row) => <TableRow key={row.id}>
      <TableCell className="whitespace-nowrap text-xs">{teamDate(row.created_at)}</TableCell>
      <TableCell><Badge variant={row.ref_type === "admin_adjust" ? "warning" : "info"}>{kindLabels[row.kind] || row.kind}</Badge></TableCell>
      <TableCell className="font-semibold tabular-nums">{row.delta_fen >= 0 ? "+" : "−"}{points(Math.abs(row.delta_fen))}</TableCell>
      <TableCell className="tabular-nums">{points(row.balance_after_fen)}</TableCell>
      <TableCell><div>{row.operator_nickname || "—"}</div><div className="mt-1 text-xs text-[var(--admin-muted)]">{row.operator_email} · #{row.actor_user_id}</div></TableCell>
      <TableCell className="max-w-xs break-words whitespace-normal"><div>{row.note || "—"}</div><div className="mt-1 break-all text-xs text-[var(--admin-muted)]">流水 #{row.id}{row.ref_id && row.ref_type !== "admin_adjust" ? ` · ${row.ref_type} #${row.ref_id}` : ""}</div></TableCell>
    </TableRow>)}</TableBody></Table>}
    {data && <PaginationBar page={page} pageSize={pageSize} total={data.meta.total} onPageChange={setPage} onPageSizeChange={(size) => { setPageSize(size); setPage(1); }} />}
  </div>;
}
