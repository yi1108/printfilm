import { points } from "@/lib/points";
import { ArrowLeft, RefreshCw, UsersRound } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { teamPaths } from "@/api/teams";
import type { AdminTeam } from "@/api/types/teams";
import { AdminListStats } from "@/components/admin/AdminListStats";
import { TeamMembersTable } from "@/components/teams/TeamMembersTable";
import { TeamUsageTable } from "@/components/teams/TeamUsageTable";
import { TeamWalletLedgerTable } from "@/components/teams/TeamWalletLedgerTable";
import { TeamBudgetModal } from "@/components/teams/TeamBudgetModal";
import { TeamQueryFeedback } from "@/components/teams/TeamQueryFeedback";
import { teamDate } from "@/lib/teamLabels";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { useAdminTeamQuery } from "@/hooks/useAdminTeamQuery";
import { cn } from "@/lib/utils";

/** 团队二级详情：基本资料、成员与可追溯的团队消费记录。 */
export function TeamDetailPage() {
  /* id 为当前团队，tab 与 member_id 留在 URL 以支持深链和返回。 */
  const { teamId } = useParams<{ teamId: string }>();
  const id = Number(teamId);
  const [params, setParams] = useSearchParams();
  const tab = params.get("tab") === "wallet" ? "wallet" : params.get("tab") === "usage" ? "usage" : "members";
  const [adjustOpen, setAdjustOpen] = useState(false);
  const activeTeam = useRef(id);
  useEffect(() => { activeTeam.current = id; setAdjustOpen(false); }, [id]);
  const { data: team, loading, error, reload } = useAdminTeamQuery<AdminTeam>(teamPaths.detail(Number.isSafeInteger(id) && id > 0 ? id : 0));
  return <div className="space-y-5">
    <div className="flex flex-wrap items-center justify-between gap-3"><Button type="button" asChild variant="ghost"><Link to="/teams"><ArrowLeft className="h-4 w-4" />返回团队列表</Link></Button><div className="flex gap-2"><Button type="button" variant="outline" disabled={loading} onClick={reload}><RefreshCw className="h-4 w-4" />刷新团队概况</Button><Button type="button" disabled={!team || loading} onClick={() => setAdjustOpen(true)}>设置消费上限</Button></div></div>
    <TeamQueryFeedback loading={loading} error={error} empty={false} onRetry={reload} />
    {team && <>
      <div className="flex flex-wrap items-start gap-4 rounded-2xl border border-[var(--admin-border)] bg-white p-6">
        <span className="flex h-14 w-14 items-center justify-center rounded-2xl bg-[var(--admin-accent-soft)] text-[var(--admin-forest)]"><UsersRound className="h-7 w-7" /></span>
        <div className="min-w-0 flex-1"><div className="flex flex-wrap items-center gap-3"><h1 className="text-xl font-semibold">{team.name}</h1><Badge variant="info">团队 #{team.id}</Badge></div><p className="mt-2 break-words text-sm text-[var(--admin-muted)]">{team.description || "暂无团队介绍"}</p><p className="mt-3 break-words text-xs text-[var(--admin-muted)]">所有者：{team.owner_nickname || "—"} · {team.owner_email} · #{team.owner_user_id}<br />创建于 {teamDate(team.created_at)}</p></div>
      </div>
      <AdminListStats items={[
        { label: "在队成员", value: team.member_count, hint: `${team.project_count} 个团队项目` },
        { label: "所有者个人积分", value: points(team.balance_fen), hint: `冻结 ${points(team.frozen_fen)}` },
        { label: "团队月度上限", value: team.monthly_limit_fen === null ? "不限额" : points(team.monthly_limit_fen), hint: "预留 " + points(team.month_reserved_fen) },
        { label: "本月已消费", value: points(team.month_spent_fen), hint: `${team.period} · 上海自然月` },
        { label: "累计已消费", value: points(team.total_spent_fen), hint: "已结算金额，包含历史成员" },
      ]} />
      <nav className="flex gap-2 border-b border-[var(--admin-border)] pb-3" aria-label="团队详情导航">
        {([['members', '团队成员'], ['usage', '团队消费记录'], ['wallet', '历史团队钱包流水']] as const).map(([value, label]) => <Button key={value} type="button" variant={tab === value ? "soft" : "ghost"} aria-current={tab === value ? "page" : undefined} className={cn(tab === value && "font-bold")} onClick={() => { const next = new URLSearchParams(params); next.set("tab", value); if (value !== "usage") next.delete("member_id"); setParams(next); }}>{label}</Button>)}
      </nav>
      {tab === "members" ? <TeamMembersTable key={`members-${id}`} teamId={id} /> : tab === "wallet" ? <TeamWalletLedgerTable key={`wallet-${id}`} teamId={id} /> : <TeamUsageTable key={`usage-${id}-${params.get("member_id") || "all"}`} teamId={id} />}
      {adjustOpen && <TeamBudgetModal key={id} teamId={id} name={team.name} limit={team.monthly_limit_fen} onClose={() => setAdjustOpen(false)} onSaved={() => { if (id === activeTeam.current) reload(); }} />}
    </>}
  </div>;
}
