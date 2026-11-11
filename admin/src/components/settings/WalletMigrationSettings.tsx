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
type Report = {
  state: CutoverState; missing_schema: string[]; ready: number; blocked: number;
  already_migrated: number; active_tasks: boolean;
  accounts: { user_id: number; status: string; balance_fen?: number; merged_balance_fen?: number; reason?: string }[];
};
const endpoint = "/api/admin/settings/wallet-migration";
const statusNames: Record<string, string> = { ready: "可迁移", blocked: "需人工核对", already_migrated: "已核对" };

export function WalletMigrationSettings() {
  const [report, setReport] = useState<Report>();
  const [busy, setBusy] = useState(false);
  const [reason, setReason] = useState("");
  const [filter, setFilter] = useState("");
  const [error, setError] = useState("");
  async function refresh() { setReport(await api<Report>(endpoint)); }
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
  async function download() {
    setBusy(true);
    try {
      const response = await fetch(endpoint + "/backup", { headers: { Authorization: `Bearer ${getToken()}` } });
      if (!response.ok) throw new Error("备份下载失败，请检查管理员会话和备份挂载目录");
      const url = URL.createObjectURL(await response.blob());
      const link = document.createElement("a"); link.href = url; link.download = `${report?.state.job_id}.dump`;
      link.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (e) { setError(e instanceof Error ? e.message : "下载失败"); }
    finally { setBusy(false); }
  }
  const paused = !!report?.state.paused;
  const completed = report?.state.phase === "completed";
  const matched = report?.accounts.filter(row => (!filter || String(row.user_id).includes(filter) || row.reason?.includes(filter))) || [];
  const blockedRows = matched.filter(row => row.status === "blocked").sort((a, b) => a.user_id - b.user_id);
  const otherRows = matched.filter(row => row.status !== "blocked").sort((a, b) => a.user_id - b.user_id);
  const rows = [...blockedRows, ...otherRows.slice(0, 100)];
  return <SettingsPanel title="统一钱包迁移与核对" description="只读检查不会改余额。迁移按历史订单和流水建立来源，不会重新充值，也不会把 Sandbox 资金转换为正式资金。">
    <div className="space-y-4">
      <Button type="button" disabled={busy} onClick={() => void run()}>刷新只读核对报告</Button>
      <p>迁移期间全站暂停写入，浏览与查询继续开放。支付回调返回可重试状态；在途任务必须全部结算，排队任务请在任务页取消。失败后保持维护，请复核后重试或取消。</p>
      {error && <p role="alert" className="text-red-600">{error}</p>}
      {report && <>
        <p>当前：{paused ? "维护中" : "正常服务"} · 待迁移 {report.ready} · 异常 {report.blocked} · 已核对 {report.already_migrated} · 在途任务：{report.active_tasks ? "有（暂不能迁移）" : "无"}</p>
        {report.missing_schema.length > 0 && <p role="alert">数据库结构未就绪：{report.missing_schema.join("、")}</p>}
        <label className="block">操作理由<input className="block w-full" value={reason} maxLength={500} onChange={e => setReason(e.target.value)} placeholder="填写维护、迁移或恢复的原因" /></label>
        <div className="flex flex-wrap gap-3">
          <Button type="button" disabled={busy || paused || !!report.missing_schema.length} onClick={() => void run("pause")}>1. 暂停写入</Button>
          <Button type="button" disabled={busy || !paused || completed || !!report.blocked || report.active_tasks || !!report.missing_schema.length} onClick={() => void run("apply")}>2. 备份并迁移（成功后启用统一钱包）</Button>
          <Button type="button" disabled={busy || !paused} onClick={() => void run("resume")}>{completed ? "3. 复核并恢复服务" : "取消维护（不迁移）"}</Button>
          {report.state.backup_sha256 && <Button type="button" disabled={busy} onClick={() => void download()}>下载数据库备份</Button>}
        </div>
        {report.state.job_id && <p className="break-all">迁移编号：{report.state.job_id} · 备份 SHA256：{report.state.backup_sha256 || "尚未完成"}</p>}
        {completed && <p>已迁移 {report.state.migrated_count} 个账户。统一钱包已启用；恢复后请重新加载本页再编辑其他支付配置。</p>}
        <label className="block">按用户 ID 或异常原因过滤<input className="block w-full" value={filter} onChange={e => setFilter(e.target.value)} /></label>
        <div className="overflow-x-auto"><table className="w-full text-left"><thead><tr><th>用户 ID</th><th>状态</th><th>原积分</th><th>迁移后积分</th><th>异常原因</th></tr></thead><tbody>{rows.slice(0, 100).map(row => <tr key={row.user_id}><td>{row.user_id}</td><td>{statusNames[row.status] || row.status}</td><td>{row.balance_fen ?? "—"}</td><td>{row.merged_balance_fen ?? "—"}</td><td>{row.reason || "—"}</td></tr>)}</tbody></table></div>
        <p>符合条件 {matched.length} 条。需人工核对的 {blockedRows.length} 条全部列出，其余最多显示 100 条；可输入用户 ID 或异常原因定位。</p>
        <details><summary>操作审计</summary>{report.state.history?.map((item, i) => <div key={i}><p>{item.at} · {item.action} · 操作人 {item.operator_id} · {item.reason} · {item.job_id}</p>{item.report != null && <details><summary>查看该次迁移核对报告快照</summary><pre className="overflow-x-auto">{JSON.stringify(item.report, null, 2)}</pre></details>}</div>)}</details>
      </>}
    </div>
  </SettingsPanel>;
}
