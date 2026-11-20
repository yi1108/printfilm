import { useState } from "react";
import { api } from "@/api/client";
import { Button } from "@/components/ui/button";
import { SettingsPanel } from "./SettingsPanel";

type Product = { sku_id: string; product_id: string; name: string; purchase_option_id: string;
  offer_id: null; enabled: boolean; credit_fen?: number; reference_amount_fen?: number };
type Config = { version: number; purchasing_enabled: boolean; package_name: string;
  rtdn_audience: string; rtdn_service_account: string; test_user_ids: number[]; products: Product[];
  has_credentials: boolean; notification_url: string; retry_count: number; unconsumed_count: number };
type Transaction = { id: number; user_id: number; google_order_id: string | null; product_id: string;
  environment: string; status: string; credit_fen: number; consumed: boolean; amount_micros: number | null; currency: string | null };
type Work = { id: number; product_id: string; attempts: number; last_error: string; next_attempt_at: string };
const endpoint = "/api/admin/settings/google-play";

export function GooglePlaySettings() {
  const [form, setForm] = useState<Config>();
  const [secret, setSecret] = useState("");
  const [clearSecret, setClearSecret] = useState(false);
  const [reason, setReason] = useState("");
  const [testIds, setTestIds] = useState("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const [transactions, setTransactions] = useState<Transaction[]>([]);
  const [queue, setQueue] = useState<Work[]>([]);
  async function load() {
    setBusy(true); setError("");
    try {
      const config = await api<Config>(endpoint);
      setForm(config);
      setTestIds(config.test_user_ids.join(","));
      setTransactions((await api<{ items: Transaction[] }>(endpoint + "/transactions")).items);
      setQueue((await api<{ items: Work[] }>(endpoint + "/queue")).items);
    } catch (e) { setError(e instanceof Error ? e.message : "读取失败"); }
    finally { setBusy(false); }
  }
  async function save() {
    if (!form) return;
    if (!/^(?:[1-9][0-9]*(?:,[1-9][0-9]*)*)?$/.test(testIds.trim())) { setError("测试用户 ID 请使用正整数，以逗号分隔"); return; }
    setBusy(true); setError(""); setNotice("");
    try {
      await api(endpoint, { method: "PATCH", body: JSON.stringify({
        version: form.version, reason, purchasing_enabled: form.purchasing_enabled,
        package_name: form.package_name, rtdn_audience: form.rtdn_audience,
        rtdn_service_account: form.rtdn_service_account, test_user_ids: testIds.trim() ? testIds.split(",").map(Number) : [],
        products: form.products, service_account_json: secret || null, clear_credentials: clearSecret,
      }) });
      setSecret(""); setClearSecret(false);
      setForm(await api<Config>(endpoint));
      setNotice("已保存。后台登记不代表 Play Console 商品已激活；请完成真实测试轨道验收。");
    } catch (e) { setError(e instanceof Error ? e.message : "保存失败"); }
    finally { setBusy(false); }
  }
  function product(index: number, patch: Partial<Product>) {
    if (form) setForm({ ...form, products: form.products.map((p, i) => i === index ? { ...p, ...patch } : p) });
  }
  return <SettingsPanel title="Google Play 安卓支付" description="复用统一积分钱包。只控制新购；停购后验单、退款及自动消耗继续运行。凭证仅保存在服务端，加密存储，不回显。">
    <div className="space-y-4">
      <Button disabled={busy} onClick={() => void load()}>读取配置与交易状态</Button>
      {error && <p role="alert" className="text-red-600">{error}</p>}
      {notice && <p role="status">{notice}</p>}
      {form && <>
        <label className="flex items-center gap-2"><input type="checkbox" checked={form.purchasing_enabled} onChange={e => setForm({ ...form, purchasing_enabled: e.target.checked })} />允许 Google Play 新购</label>
        <label className="block">Android 包名<input className="admin-input block w-full" value={form.package_name} onChange={e => setForm({ ...form, package_name: e.target.value })} /></label>
        <label className="block">服务账号 JSON（{form.has_credentials ? "已配置，不填写则保留" : "未配置"}）
          <input type="file" accept=".json,application/json" disabled={busy} onChange={async e => {
            const file = e.target.files?.[0]; if (!file) return;
            if (file.size > 30000) { setError("凭证文件不能超过 30KB"); return; }
            setSecret(await file.text()); setClearSecret(false);
          }} />
          {secret && <span>已选择新凭证，保存后生效</span>}
        </label>
        <label className="flex items-center gap-2"><input type="checkbox" checked={clearSecret} onChange={e => { setClearSecret(e.target.checked); if (e.target.checked) setSecret(""); }} />清除服务账号凭证（将阻止验单及补偿，请谨慎）</label>
        <p className="break-all">RTDN 通知地址：{form.notification_url}</p>
        <label className="block">Pub/Sub OIDC audience<input className="admin-input block w-full" value={form.rtdn_audience} onChange={e => setForm({ ...form, rtdn_audience: e.target.value })} /></label>
        <label className="block">Pub/Sub 推送身份服务账号邮箱<input className="admin-input block w-full" value={form.rtdn_service_account} onChange={e => setForm({ ...form, rtdn_service_account: e.target.value })} /></label>
        <label className="block">许可测试用户 ID（逗号分隔）<input className="admin-input block w-full" value={testIds} onChange={e => setTestIds(e.target.value)} /></label>
        <p>测试付款仅限统一钱包环境为 Sandbox 的测试部署及获准账号；正式部署拒绝测试资金，不改变正式账户环境。客户端价格使用 Google formattedPrice。</p>
        <div className="overflow-x-auto"><table className="w-full text-left"><thead><tr><th>共同套餐</th><th>Google 商品 ID</th><th>英文名称</th><th>冻结积分</th><th>新购</th></tr></thead><tbody>
          {form.products.map((p, i) => <tr key={i}>
            <td><input className="admin-input" value={p.sku_id} disabled={!!p.credit_fen} onChange={e => product(i, { sku_id: e.target.value })} /></td>
            <td><input className="admin-input" value={p.product_id} disabled={!!p.credit_fen} onChange={e => product(i, { product_id: e.target.value })} /></td>
            <td><input className="admin-input" value={p.name} onChange={e => product(i, { name: e.target.value })} /></td>
            <td>{p.credit_fen?.toLocaleString() ?? "保存时读取共同套餐"}</td>
            <td><input aria-label={`${p.product_id} 允许新购`} type="checkbox" checked={p.enabled} onChange={e => product(i, { enabled: e.target.checked })} /></td>
          </tr>)}
        </tbody></table></div>
        <Button disabled={busy} onClick={() => setForm({ ...form, products: [...form.products, { sku_id: "", product_id: "", name: "", purchase_option_id: "buy", offer_id: null, enabled: false }] })}>新增商品版本</Button>
        <p>已登记商品额度不随套餐编辑改变。调整额度请停用旧商品并新增商品版本；购买选项固定 buy，不支持折扣 offer 或多数量购买。</p>
        <label className="block">修改理由<input className="admin-input block w-full" value={reason} maxLength={500} onChange={e => setReason(e.target.value)} /></label>
        <Button disabled={busy || reason.trim().length < 3} onClick={() => void save()}>保存 Google Play 配置</Button>
        <p>异常待重试 {form.retry_count} · 已到账待消耗 {form.unconsumed_count}。消耗兜底和退款补偿由后台自动执行。</p>
        <p>购买凭证不包含可信实付时显示待同步，不用人民币套餐价冒充当地支付金额。相关来源保持待核算，不能打款。</p>
        <details><summary>补单队列及脱敏错误码</summary>{queue.map(w => <p key={w.id}>任务 {w.id} · {w.product_id} · 尝试 {w.attempts} · {w.last_error || "等待查询/定期核对"} · 下次 {w.next_attempt_at}</p>)}</details>
        <details><summary>最近 Google 交易（不展示 purchase token）</summary><div className="overflow-x-auto"><table className="w-full text-left"><thead><tr><th>用户</th><th>Google 订单</th><th>环境</th><th>状态</th><th>积分</th><th>消耗</th><th>实付</th></tr></thead><tbody>
          {transactions.map(t => <tr key={t.id}><td>{t.user_id}</td><td>{t.google_order_id ?? "待付款"}</td><td>{t.environment}</td><td>{t.status}</td><td>{t.credit_fen}</td><td>{t.consumed ? "已消耗" : "未消耗"}</td><td>{t.amount_micros == null ? "待同步" : `${t.currency} ${t.amount_micros / 1000000}`}</td></tr>)}
        </tbody></table></div></details>
      </>}
    </div>
  </SettingsPanel>;
}
