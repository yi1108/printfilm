import { useState } from "react";
import { toast } from "sonner";
import { api } from "@/api/client";
import { getToken } from "@/lib/auth";
import { Button } from "@/components/ui/button";
import { SettingsPanel } from "./SettingsPanel";

type CutoverState = {
  paused?: boolean; phase?: string; job_id?: string; backup_sha256?: string; migrated_count?: number;
  history?: { action: string; operator_id: number; reason: string; at: string; job_id?: string; report?: unknown }[];
};
type BalancePreview = {
  eligible: boolean; reason?: string; fingerprint?: string; original_balance_fen?: number;
  merged_balance_fen?: number; remaining_debt_fen?: number; platform_grant_fen?: number;
  pending_units?: number; preserved_units?: number;
};
type Report = {
  state: CutoverState; missing_schema: string[];   ready: number; blocked: number; opening?: number;
  already_migrated: number; balance_approved?: number; active_tasks: boolean; approval_required?: number; fingerprint?: string;
  backups?: { job_id: string; status: string; sha256?: string; migration_status?: string; updated_at: string }[];
  accounts: { user_id: number; status: string; balance_fen?: number; merged_balance_fen?: number; frozen_fen?: number; legacy_debt_fen?: number; remaining_debt_fen?: number; pending_source_count?: number; pending_sources?: { source_type: string; source_ref: string; units: number; valuation_status: string }[]; approval_status?: string; fingerprint?: string; environment?: string; reason?: string; balance_migration?: BalancePreview; balance_resolution?: BalancePreview & { operator_id: number; reason: string; backup_reference: string } }[];
};
const endpoint = "/api/admin/settings/wallet-migration";
const statusNames: Record<string, string> = { ready: "可迁移", opening: "历史期初待确认", blocked: "需人工核对", already_migrated: "已核对", balance_approved: "按原积分已确认" };

export function WalletMigrationSettings() {
  const [report, setReport] = useState<Report>();
  const [busy, setBusy] = useState(false);
  const [reason, setReason] = useState("");
  const [filter, setFilter] = useState("");
  const [error, setError] = useState("");
  const [selected, setSelected] = useState<number[]>([]);
  const [acceptGrant, setAcceptGrant] = useState(false);
  async function refresh() { setReport(await api<Report>(endpoint)); setSelected([]); setAcceptGrant(false); }
  async function run(action?: "pause" | "apply" | "resume") {
    if (action && reason.trim().length < 3) { toast.error("请填写至少 3 字的操作理由"); return; }
    if (action === "pause" && !window.confirm("将暂停全站写入（包括充值回调、新任务和视频解锁），现有任务继续结算。确认进入维护？")) return;
    if (action === "apply" && !window.confirm("将备份数据库并迁移所有核对通过的历史账户，同时启用统一钱包。成功后仍保持维护，是否执行？")) return;
    if (action === "resume" && !window.confirm("确认结束维护？已完成迁移时会再次核对，未执行迁移时仅取消维护。")) return;
    setBusy(true); setError("");
    try {
      if (action) await api(endpoint + "/" + action, { method: "POST", body: JSON.stringify({ reason: reason.trim(), job_id: report?.state.job_id || "" }) });
      await refresh();
      if (action) toast.success(action === "apply" ? "迁移完成，仍处于维护状态；请下载备份、复核后恢复" : "操作完成");
    } catch (e) {
      setError(e instanceof Error ? e.message : "操作失败，保持现有维护状态");
      // A timed-out response is not proof that the transaction failed.
      try { await refresh(); } catch { /* retain the last known state */ }
    } finally { setBusy(false); }
  }
  async function approve(row: Report["accounts"][number]) {
    if (reason.trim().length < 3) { toast.error("请填写逐户确认的核对依据（至少 3 字）"); return; }
    if (!window.confirm(`确认用户 ${row.user_id} 的缺失期初历史？原积分 ${row.balance_fen}，欠费 ${row.remaining_debt_fen ?? 0}。未知实付保持待核算，不视为零成本赠额。`)) return;
    setBusy(true); setError("");
    try {
      await api(`${endpoint}/approvals/${row.user_id}`, { method: "POST", body: JSON.stringify({
        job_id: report?.state.job_id, reason: reason.trim(), fingerprint: row.fingerprint, environment: row.environment,
      }) });
      await refresh(); toast.success("已确认该账户；数据变化后必须重新核对");
    } catch (e) {
      setError(e instanceof Error ? e.message : "确认失败");
      try { await refresh(); } catch { /* keep last report */ }
    } finally { setBusy(false); }
  }
  async function approveBalances() {
    if (reason.trim().length < 3) { toast.error("请填写本批按原积分迁移的核对依据（至少 3 字）"); return; }
    if (!chosen.length || chosen.length > 500) { toast.error("请选择 1 至 500 个账户"); return; }
    if (giftTotal > 0 && !acceptGrant) { toast.error("请确认沙箱替代额度由平台补发正式赠额"); return; }
    if (!window.confirm(`确认这 ${chosen.length} 个账户按原积分迁移？迁移后可用合计 ${balanceTotal} 积分，欠费 ${debtTotal} 积分；其中平台正式补赠 ${giftTotal} 积分，待核算 ${pendingTotal} 积分。原流水保留，补赠包含在迁移后积分中，不是额外再加一次。此处仅保存确认，之后仍须备份并迁移。`)) return;
    setBusy(true); setError("");
    try {
      await api(endpoint + "/balance-approvals", { method: "POST", body: JSON.stringify({
        job_id: report?.state.job_id, reason: reason.trim(), accept_platform_grant: acceptGrant,
        selections: chosen.map(row => ({ user_id: row.user_id, fingerprint: row.balance_migration?.fingerprint })),
      }) });
      await refresh(); toast.success("已保存本批确认；请继续备份并迁移");
    } catch (e) {
      setError(e instanceof Error ? e.message : "确认失败");
      try { await refresh(); } catch { /* keep last report */ }
    } finally { setBusy(false); }
  }
  async function downloadResolution(userId: number) {
    setBusy(true); setError("");
    try {
      const result = await api<unknown>(`${endpoint}/balance-resolutions/${userId}`);
      const url = URL.createObjectURL(new Blob([JSON.stringify(result, null, 2)], { type: "application/json" }));
      const link = document.createElement("a"); link.href = url; link.download = `wallet-migration-${userId}.json`;
      link.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (e) { setError(e instanceof Error ? e.message : "迁移记录下载失败"); }
    finally { setBusy(false); }
  }
  async function download(jobId = report?.state.job_id) {
    setBusy(true);
    try {
      const response = await fetch(endpoint + "/backup" + (jobId ? `?job_id=${encodeURIComponent(jobId)}` : ""), { headers: { Authorization: `Bearer ${getToken()}` } });
      if (!response.ok) throw new Error("备份下载失败，请检查管理员会话和备份挂载目录");
      const url = URL.createObjectURL(await response.blob());
      const link = document.createElement("a"); link.href = url; link.download = `${jobId}.dump`;
      link.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (e) { setError(e instanceof Error ? e.message : "下载失败"); }
    finally { setBusy(false); }
  }
  const paused = !!report?.state.paused;
  const completed = report?.state.phase === "completed";
  const matched = report?.accounts.filter(row => (!filter || String(row.user_id).includes(filter) || row.reason?.includes(filter))) || [];
  const blockedRows = matched.filter(row => row.status === "blocked").sort((a, b) => a.user_id - b.user_id);
  const openingRows = matched.filter(row => row.status === "opening").sort((a, b) => a.user_id - b.user_id);
  const balanceRows = matched.filter(row => row.status === "balance_approved");
  const otherRows = matched.filter(row => row.status !== "blocked" && row.status !== "opening" && row.status !== "balance_approved").sort((a, b) => a.user_id - b.user_id);
  const rows = [...blockedRows, ...openingRows, ...balanceRows, ...otherRows.slice(0, 100)];
  const eligible = matched.filter(row => row.balance_migration?.eligible && row.status !== "balance_approved");
  const chosen = report?.accounts.filter(row => selected.includes(row.user_id) && row.balance_migration?.eligible) || [];
  const sumPreview = (key: keyof BalancePreview) => chosen.reduce((total, row) => total + Number(row.balance_migration?.[key] ?? 0), 0);
  const balanceTotal = sumPreview("merged_balance_fen"), debtTotal = sumPreview("remaining_debt_fen");
  const giftTotal = sumPreview("platform_grant_fen"), pendingTotal = sumPreview("pending_units");
  return <SettingsPanel title="统一钱包迁移与核对" description="只读检查不改余额。可按原来源正常迁移，也可明确选择按原积分建立新基线：沙箱替代额度由平台正式赠送，未知差额待核算，真实付款来源保留。原流水和沙箱交易不删除、不改成正式付款。负积分转为欠费；实际冻结、在途任务及无法证明的真实付款来源仍须先处理。">
    <div className="space-y-4">
      <Button type="button" disabled={busy} onClick={() => void run()}>刷新只读核对报告</Button>
      <p>迁移期间全站暂停写入，浏览与查询继续开放。支付回调返回可重试状态；在途任务必须全部结算，排队任务请在任务页取消。失败后保持维护，请复核后重试或取消。</p>
      {error && <p role="alert" className="text-red-600">{error}</p>}
      {report && <>
        <p>当前：{paused ? "维护中" : "正常服务"} · 待迁移 {report.ready} · 历史期初 {report.opening ?? 0}（待确认 {report.approval_required ?? 0}） · 按原积分已确认 {report.balance_approved ?? 0} · 异常 {report.blocked} · 已核对 {report.already_migrated} · 在途任务：{report.active_tasks ? "有（暂不能迁移）" : "无"}</p>
        {report.missing_schema.length > 0 && <p role="alert">数据库结构未就绪：{report.missing_schema.join("、")}</p>}
        <label className="block">操作理由<input className="block w-full" value={reason} maxLength={500} onChange={e => setReason(e.target.value)} placeholder="填写维护、迁移或恢复的原因" /></label>
        <div className="flex flex-wrap gap-3">
          <Button type="button" disabled={busy || paused || !!report.missing_schema.length} onClick={() => void run("pause")}>1. 暂停写入</Button>
          <Button type="button" disabled={busy || !paused || completed || !!report.blocked || !!report.approval_required || report.active_tasks || !!report.missing_schema.length} onClick={() => void run("apply")}>2. 备份并迁移（成功后启用统一钱包）</Button>
          <Button type="button" disabled={busy || !paused} onClick={() => void run("resume")}>{completed ? "3. 复核并恢复服务" : "取消维护（不迁移）"}</Button>
          {report.state.backup_sha256 && <Button type="button" disabled={busy} onClick={() => void download()}>下载数据库备份</Button>}
        </div>
        {report.state.job_id && <p className="break-all">迁移编号：{report.state.job_id} · 备份 SHA256：{report.state.backup_sha256 || "尚未完成"}</p>}
        {completed && <p>已迁移 {report.state.migrated_count} 个账户。统一钱包已启用；恢复后请重新加载本页再编辑其他支付配置。</p>}
        <label className="block">按用户 ID 或异常原因过滤<input className="block w-full" value={filter} onChange={e => setFilter(e.target.value)} /></label>
        <div className="space-y-2 rounded border p-3">
          <p>按原积分确认迁移：当前选择 {chosen.length} 个账户，迁移后可用 {balanceTotal} 积分，欠费 {debtTotal} 积分，平台补赠 {giftTotal} 积分，待核算 {pendingTotal} 积分。</p>
          <p>确认只保存本次迁移决策，不会立即改积分。补赠包含在原积分中，不重复加款。真实付款来源损坏及冻结未结算的账户不能选择。</p>
          <div className="flex flex-wrap gap-3">
            <Button type="button" disabled={busy || !paused || completed} onClick={() => setSelected(eligible.slice(0, 500).map(row => row.user_id))}>选择筛选下可迁移账户（最多500个）</Button>
            <Button type="button" disabled={busy || !selected.length} onClick={() => setSelected([])}>清空选择</Button>
            <Button type="button" disabled={busy || !paused || completed || report.active_tasks || !chosen.length} onClick={() => void approveBalances()}>确认所选账户按原积分迁移</Button>
          </div>
          <label className="flex items-center gap-2"><input type="checkbox" checked={acceptGrant} disabled={busy} onChange={e => setAcceptGrant(e.target.checked)} />确认沙箱替代额度由平台补发正式赠额，原 Apple 沙箱交易保留</label>
        </div>
        <div className="overflow-x-auto"><table className="w-full text-left"><thead><tr><th>按原积分选择</th><th>用户 ID / 环境</th><th>状态</th><th>原积分</th><th>冻结</th><th>迁移后可用</th><th>原欠费</th><th>剩余欠费</th><th>待核算来源</th><th>原因 / 确认</th></tr></thead><tbody>{rows.map(row => <tr key={row.user_id}>
          <td>{row.balance_migration?.eligible && row.status !== "balance_approved" ? <input aria-label={`选择用户 ${row.user_id} 按原积分迁移`} type="checkbox" checked={selected.includes(row.user_id)} disabled={busy || !paused || completed} onChange={e => setSelected(ids => e.target.checked ? [...ids, row.user_id] : ids.filter(id => id !== row.user_id))} /> : row.status === "balance_approved" ? "已确认" : "—"}</td>
          <td>{row.user_id} / {row.environment ?? "未计算"}</td><td>{statusNames[row.status] || row.status}{row.approval_status === "approved" && "（本次已确认）"}</td>
          <td>{row.balance_fen ?? "未计算"}</td><td>{row.frozen_fen ?? "未计算"}</td><td>{row.merged_balance_fen ?? "未计算"}</td>
          <td>{row.legacy_debt_fen ?? "未计算"}</td><td>{row.remaining_debt_fen ?? "未计算"}</td><td>{row.pending_source_count ?? "未计算"}{!!row.pending_sources?.length && <details><summary>来源明细</summary>{row.pending_sources.map(item => <p key={`${item.source_type}:${item.source_ref}`}>{item.source_type} / {item.source_ref} · {item.units} 积分 · 实付待核算</p>)}</details>}</td>
          <td>{row.reason || "无"}{row.balance_resolution && <details><summary>已按原积分迁移 · 查看依据</summary><p>操作人 {row.balance_resolution.operator_id} · {row.balance_resolution.reason} · 平台补赠 {row.balance_resolution.platform_grant_fen} 积分 · 原积分 {row.balance_resolution.original_balance_fen}</p><Button type="button" disabled={busy} onClick={() => void downloadResolution(row.user_id)}>下载原始快照及处理记录</Button></details>}{row.balance_migration && <details><summary>按原积分迁移预览</summary>{row.balance_migration.eligible ? <p>原积分 {row.balance_migration.original_balance_fen} → 可用 {row.balance_migration.merged_balance_fen}，欠费 {row.balance_migration.remaining_debt_fen}；平台补赠 {row.balance_migration.platform_grant_fen}，待核算 {row.balance_migration.pending_units}。</p> : <p>暂不可执行：{row.balance_migration.reason}</p>}</details>}{row.approval_status === "required" && <Button type="button" disabled={busy || !paused || completed} onClick={() => void approve(row)}>逐户确认历史期初</Button>}</td>
        </tr>)}</tbody></table></div>
        <p>符合条件 {matched.length} 条。异常 {blockedRows.length} 条及历史期初 {openingRows.length} 条全部列出，其余最多显示 100 条。数据变化将使原确认失效。</p>
        <details><summary>历史备份与执行结果</summary>{report.backups?.map(item => <div key={item.job_id} className="break-all">
          <p>{item.job_id} · 备份 {item.status} · 迁移 {item.migration_status ?? "未完成"} · {item.updated_at} · SHA256 {item.sha256 ?? "未生成"}</p>
          {item.sha256 && <Button type="button" disabled={busy} onClick={() => void download(item.job_id)}>校验并下载备份</Button>}
        </div>)}</details>
        <details><summary>操作审计</summary>{report.state.history?.map((item, i) => <div key={i}><p>{item.at} · {item.action} · 操作人 {item.operator_id} · {item.reason} · {item.job_id}</p>{item.report != null && <details><summary>查看该次迁移核对报告快照</summary><pre className="overflow-x-auto">{JSON.stringify(item.report, null, 2)}</pre></details>}</div>)}</details>
      </>}
    </div>
  </SettingsPanel>;
}
