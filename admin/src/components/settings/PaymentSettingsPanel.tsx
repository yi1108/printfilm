import { useMemo, useState } from "react";
import {
  LabeledControl,
  SettingsLoading,
  SettingsPanel,
  SettingsStatusBar,
  SettingsTabShell,
} from "@/components/settings/SettingsPanel";
import { SecretField } from "@/components/settings/SecretField";
import { Switch } from "@/components/ui/switch";
import { useAdminModelSettings } from "@/hooks/useAdminModelSettings";

// 易支付与 Token 计费配置
export function PaymentSettingsPanel() {
  const { form, loading, saving, patchField, save } = useAdminModelSettings();
  const [epayKeyInput, setEpayKeyInput] = useState("");
  const [clearEpayKey, setClearEpayKey] = useState(false);
  const [volcAkInput, setVolcAkInput] = useState("");
  const [volcSkInput, setVolcSkInput] = useState("");
  const [clearVolcAk, setClearVolcAk] = useState(false);
  const [clearVolcSk, setClearVolcSk] = useState(false);
  const [smtpPasswordInput, setSmtpPasswordInput] = useState("");
  const [clearSmtpPassword, setClearSmtpPassword] = useState(false);

  const epayReady = useMemo(() => {
    if (!form) return false;
    const hasKey = (form.has_epay_key && !clearEpayKey) || epayKeyInput.trim().length > 0;
    return Boolean(form.epay_pid && form.epay_api_url && hasKey);
  }, [form, clearEpayKey, epayKeyInput]);

  const volcReady = useMemo(() => {
    if (!form) return false;
    const hasAk = (form.has_volc_access_key_id && !clearVolcAk) || volcAkInput.trim().length > 0;
    const hasSk = (form.has_volc_secret_access_key && !clearVolcSk) || volcSkInput.trim().length > 0;
    return Boolean(form.volc_ark_usage_enabled && hasAk && hasSk);
  }, [form, clearVolcAk, clearVolcSk, volcAkInput, volcSkInput]);

  const smtpReady = useMemo(() => {
    if (!form?.smtp_enabled) return false;
    const hasPass = (form.has_smtp_password && !clearSmtpPassword) || smtpPasswordInput.trim().length > 0;
    return Boolean(form.smtp_host && form.smtp_from && hasPass);
  }, [form, clearSmtpPassword, smtpPasswordInput]);

  async function handleSave() {
    if (!form) return;
    await save(
      {
        epay_api_url: form.epay_api_url,
        epay_pid: form.epay_pid,
        epay_key: epayKeyInput.trim() || undefined,
        clear_epay_key: clearEpayKey,
        epay_notify_url: form.epay_notify_url,
        epay_return_url: form.epay_return_url,
        billing_enabled: form.billing_enabled,
        billing_markup: form.billing_markup,
        billing_estimate_buffer: form.billing_estimate_buffer,
        billing_seedance_video0: form.billing_seedance_video0,
        billing_seedance_video1: form.billing_seedance_video1,
        billing_llm_per_m: form.billing_llm_per_m,
        billing_seedream_per_m: form.billing_seedream_per_m,
        billing_tts_per_m: form.billing_tts_per_m,
        billing_est_llm_tokens: form.billing_est_llm_tokens,
        billing_est_seedream_tokens: form.billing_est_seedream_tokens,
        billing_est_tts_tokens: form.billing_est_tts_tokens,
        billing_est_seedance_tokens_per_sec: form.billing_est_seedance_tokens_per_sec,
        billing_signup_grant_fen: form.billing_signup_grant_fen,
        quota_enabled: form.quota_enabled,
        new_user_quota: form.new_user_quota,
        volc_access_key_id: volcAkInput.trim() || undefined,
        volc_secret_access_key: volcSkInput.trim() || undefined,
        clear_volc_access_key_id: clearVolcAk,
        clear_volc_secret_access_key: clearVolcSk,
        volc_ark_region: form.volc_ark_region,
        volc_ark_usage_enabled: form.volc_ark_usage_enabled,
        billing_user_alert_enabled: form.billing_user_alert_enabled,
        billing_user_alert_interval_fen: form.billing_user_alert_interval_fen,
        billing_admin_cost_alert_enabled: form.billing_admin_cost_alert_enabled,
        billing_admin_cost_alert_threshold_fen: form.billing_admin_cost_alert_threshold_fen,
        billing_admin_cost_alert_emails: form.billing_admin_cost_alert_emails,
        billing_admin_cost_alert_period: form.billing_admin_cost_alert_period,
        smtp_enabled: form.smtp_enabled,
        smtp_host: form.smtp_host,
        smtp_port: form.smtp_port,
        smtp_user: form.smtp_user,
        smtp_password: smtpPasswordInput.trim() || undefined,
        clear_smtp_password: clearSmtpPassword,
        smtp_from: form.smtp_from,
        smtp_use_tls: form.smtp_use_tls,
      },
      "支付与计费已保存",
    );
    setEpayKeyInput("");
    setClearEpayKey(false);
    setVolcAkInput("");
    setVolcSkInput("");
    setClearVolcAk(false);
    setClearVolcSk(false);
    setSmtpPasswordInput("");
    setClearSmtpPassword(false);
  }

  if (loading || !form) {
    return <SettingsLoading />;
  }

  return (
    <SettingsTabShell onSave={() => void handleSave()} saving={saving}>
      <SettingsStatusBar
        title="支付就绪状态"
        items={[
          {
            id: "epay",
            label: "易支付",
            ready: epayReady,
            readyText: "已配置",
            pendingText: "未完整",
          },
          {
            id: "billing",
            label: "Token 计费",
            ready: form.billing_enabled,
            readyText: "已开启",
            pendingText: "已关闭",
          },
          {
            id: "volc",
            label: "上游成本",
            ready: volcReady,
            readyText: "已启用",
            pendingText: form.volc_ark_usage_enabled ? "缺凭证" : "未启用",
          },
          {
            id: "smtp",
            label: "SMTP",
            ready: smtpReady,
            readyText: "已配置",
            pendingText: form.smtp_enabled ? "不完整" : "未启用",
          },
        ]}
      />

      <div className="settings-routing-grid">
        <SettingsPanel
          className="settings-panel--compact"
          title="1. 易支付 Epay"
          description="生产回调请用 /epay/notify，勿含 /api/"
        >
          <div className="settings-field-grid">
            <LabeledControl label="网关地址">
              <input
                className="settings-input"
                placeholder="https://pay.gitcc.com"
                value={form.epay_api_url}
                onChange={(e) => patchField("epay_api_url", e.target.value)}
              />
            </LabeledControl>
            <LabeledControl label="商户 PID">
              <input
                className="settings-input"
                value={form.epay_pid}
                onChange={(e) => patchField("epay_pid", e.target.value)}
              />
            </LabeledControl>
            <SecretField
              label="商户密钥"
              value={epayKeyInput}
              configured={form.has_epay_key && !clearEpayKey}
              onChange={setEpayKeyInput}
              onClear={() => {
                setEpayKeyInput("");
                setClearEpayKey(true);
              }}
            />
            <LabeledControl label="异步通知 URL" hint="生产：{域名}/epay/notify" className="settings-field-span-full">
              <input
                className="settings-input"
                value={form.epay_notify_url}
                onChange={(e) => patchField("epay_notify_url", e.target.value)}
              />
            </LabeledControl>
            <LabeledControl label="同步跳转 URL" className="settings-field-span-full">
              <input
                className="settings-input"
                value={form.epay_return_url}
                onChange={(e) => patchField("epay_return_url", e.target.value)}
              />
            </LabeledControl>
          </div>
        </SettingsPanel>

        <SettingsPanel
          className="settings-panel--compact"
          title="2. Token 计费"
          description="按上游成本 × markup 扣费"
        >
          <div className="settings-toggle-row">
            <div>
              <strong>启用 Token 计费</strong>
              <span>关闭后生成不扣余额</span>
            </div>
            <Switch checked={form.billing_enabled} onCheckedChange={(v) => patchField("billing_enabled", v)} />
          </div>
          <div className="settings-field-grid mt-3">
            <LabeledControl label="加价系数 markup">
              <input
                className="settings-input"
                type="number"
                step="0.1"
                min={1}
                value={form.billing_markup}
                onChange={(e) => patchField("billing_markup", Number(e.target.value))}
              />
            </LabeledControl>
            <LabeledControl label="预估缓冲系数">
              <input
                className="settings-input"
                type="number"
                step="0.1"
                min={1}
                value={form.billing_estimate_buffer}
                onChange={(e) => patchField("billing_estimate_buffer", Number(e.target.value))}
              />
            </LabeledControl>
            <LabeledControl label="注册赠送（分）">
              <input
                className="settings-input"
                type="number"
                min={0}
                value={form.billing_signup_grant_fen}
                onChange={(e) => patchField("billing_signup_grant_fen", Number(e.target.value))}
              />
            </LabeledControl>
          </div>

          <div className="settings-subsection-title">单价（元 / 百万 token）</div>
          <div className="settings-field-grid">
            <LabeledControl label="LLM">
              <input
                className="settings-input"
                type="number"
                step="0.1"
                value={form.billing_llm_per_m}
                onChange={(e) => patchField("billing_llm_per_m", Number(e.target.value))}
              />
            </LabeledControl>
            <LabeledControl label="Seedream 生图">
              <input
                className="settings-input"
                type="number"
                step="0.1"
                value={form.billing_seedream_per_m}
                onChange={(e) => patchField("billing_seedream_per_m", Number(e.target.value))}
              />
            </LabeledControl>
            <LabeledControl label="TTS 语音">
              <input
                className="settings-input"
                type="number"
                step="0.1"
                value={form.billing_tts_per_m}
                onChange={(e) => patchField("billing_tts_per_m", Number(e.target.value))}
              />
            </LabeledControl>
            <LabeledControl label="Seedance video0">
              <input
                className="settings-input"
                type="number"
                step="0.1"
                value={form.billing_seedance_video0}
                onChange={(e) => patchField("billing_seedance_video0", Number(e.target.value))}
              />
            </LabeledControl>
            <LabeledControl label="Seedance video1">
              <input
                className="settings-input"
                type="number"
                step="0.1"
                value={form.billing_seedance_video1}
                onChange={(e) => patchField("billing_seedance_video1", Number(e.target.value))}
              />
            </LabeledControl>
          </div>

          <div className="settings-subsection-title">估算 token（缺 usage 时）</div>
          <div className="settings-field-grid">
            <LabeledControl label="LLM 估算">
              <input
                className="settings-input"
                type="number"
                value={form.billing_est_llm_tokens}
                onChange={(e) => patchField("billing_est_llm_tokens", Number(e.target.value))}
              />
            </LabeledControl>
            <LabeledControl label="Seedream 估算">
              <input
                className="settings-input"
                type="number"
                value={form.billing_est_seedream_tokens}
                onChange={(e) => patchField("billing_est_seedream_tokens", Number(e.target.value))}
              />
            </LabeledControl>
            <LabeledControl label="TTS 估算">
              <input
                className="settings-input"
                type="number"
                value={form.billing_est_tts_tokens}
                onChange={(e) => patchField("billing_est_tts_tokens", Number(e.target.value))}
              />
            </LabeledControl>
            <LabeledControl label="Seedance token/秒">
              <input
                className="settings-input"
                type="number"
                value={form.billing_est_seedance_tokens_per_sec}
                onChange={(e) => patchField("billing_est_seedance_tokens_per_sec", Number(e.target.value))}
              />
            </LabeledControl>
          </div>

          <div className="settings-toggle-row mt-3">
            <div>
              <strong>旧版次数配额</strong>
              <span>与 Token 计费并存时以 billing_enabled 为准</span>
            </div>
            <Switch checked={form.quota_enabled} onCheckedChange={(v) => patchField("quota_enabled", v)} />
          </div>
          <div className="settings-field-grid mt-2">
            <LabeledControl label="新用户默认次数">
              <input
                className="settings-input"
                type="number"
                min={0}
                value={form.new_user_quota}
                onChange={(e) => patchField("new_user_quota", Number(e.target.value))}
              />
            </LabeledControl>
          </div>
        </SettingsPanel>
      </div>

      <div className="settings-routing-grid">
        <SettingsPanel
          className="settings-panel--compact"
          title="3. 额度告警与 SMTP"
          description="用户消费提醒与平台费用邮件"
        >
          <div className="settings-toggle-row">
            <div>
              <strong>用户弹窗提醒</strong>
              <span>累计扣费每达间隔档位弹出一次</span>
            </div>
            <Switch
              checked={form.billing_user_alert_enabled}
              onCheckedChange={(v) => patchField("billing_user_alert_enabled", v)}
            />
          </div>
          <div className="settings-field-grid mt-2">
            <LabeledControl label="提醒间隔（分）" hint="1000 = ¥10">
              <input
                className="settings-input"
                type="number"
                min={1}
                value={form.billing_user_alert_interval_fen}
                onChange={(e) => patchField("billing_user_alert_interval_fen", Number(e.target.value))}
              />
            </LabeledControl>
          </div>

          <div className="settings-toggle-row mt-3">
            <div>
              <strong>管理员邮件告警</strong>
              <span>按上游 cost 汇总达阈值后发信</span>
            </div>
            <Switch
              checked={form.billing_admin_cost_alert_enabled}
              onCheckedChange={(v) => patchField("billing_admin_cost_alert_enabled", v)}
            />
          </div>
          <div className="settings-field-grid mt-2">
            <LabeledControl label="告警阈值（分）">
              <input
                className="settings-input"
                type="number"
                min={0}
                value={form.billing_admin_cost_alert_threshold_fen}
                onChange={(e) =>
                  patchField("billing_admin_cost_alert_threshold_fen", Number(e.target.value))
                }
              />
            </LabeledControl>
            <LabeledControl label="统计周期">
              <select
                className="settings-select"
                value={form.billing_admin_cost_alert_period}
                onChange={(e) => patchField("billing_admin_cost_alert_period", e.target.value)}
              >
                <option value="daily">每日</option>
                <option value="monthly">每月</option>
                <option value="all_time">累计</option>
              </select>
            </LabeledControl>
            <LabeledControl label="收件邮箱" hint="逗号分隔" className="settings-field-span-full">
              <input
                className="settings-input"
                placeholder="admin@example.com"
                value={form.billing_admin_cost_alert_emails}
                onChange={(e) => patchField("billing_admin_cost_alert_emails", e.target.value)}
              />
            </LabeledControl>
          </div>

          <div className="settings-toggle-row mt-3">
            <div>
              <strong>启用 SMTP</strong>
              <span>邮件告警依赖 SMTP</span>
            </div>
            <Switch checked={form.smtp_enabled} onCheckedChange={(v) => patchField("smtp_enabled", v)} />
          </div>
          <div className="settings-field-grid mt-2">
            <LabeledControl label="SMTP 主机">
              <input
                className="settings-input"
                placeholder="smtp.example.com"
                value={form.smtp_host}
                onChange={(e) => patchField("smtp_host", e.target.value)}
              />
            </LabeledControl>
            <LabeledControl label="端口">
              <input
                className="settings-input"
                type="number"
                min={1}
                value={form.smtp_port}
                onChange={(e) => patchField("smtp_port", Number(e.target.value))}
              />
            </LabeledControl>
            <LabeledControl label="发件人">
              <input
                className="settings-input"
                value={form.smtp_from}
                onChange={(e) => patchField("smtp_from", e.target.value)}
              />
            </LabeledControl>
            <LabeledControl label="用户名">
              <input
                className="settings-input"
                value={form.smtp_user}
                onChange={(e) => patchField("smtp_user", e.target.value)}
              />
            </LabeledControl>
            <SecretField
              label="SMTP 密码"
              value={smtpPasswordInput}
              configured={form.has_smtp_password && !clearSmtpPassword}
              onChange={setSmtpPasswordInput}
              onClear={() => {
                setSmtpPasswordInput("");
                setClearSmtpPassword(true);
              }}
            />
            <LabeledControl label="使用 TLS">
              <div className="settings-inline-switch">
                <Switch checked={form.smtp_use_tls} onCheckedChange={(v) => patchField("smtp_use_tls", v)} />
              </div>
            </LabeledControl>
          </div>
        </SettingsPanel>

        <SettingsPanel
          className="settings-panel--compact"
          title="4. 上游成本监控"
          description="火山 GetInferenceUsage，与方舟 API Key 分离"
        >
          <div className="settings-toggle-row">
            <div>
              <strong>启用官方用量拉取</strong>
              <span>关闭后仪表盘仅展示本地成本</span>
            </div>
            <Switch
              checked={form.volc_ark_usage_enabled}
              onCheckedChange={(v) => patchField("volc_ark_usage_enabled", v)}
            />
          </div>
          <div className="settings-field-grid mt-3">
            <SecretField
              label="Access Key ID"
              value={volcAkInput}
              configured={form.has_volc_access_key_id && !clearVolcAk}
              onChange={setVolcAkInput}
              onClear={() => {
                setVolcAkInput("");
                setClearVolcAk(true);
              }}
            />
            <SecretField
              label="Secret Access Key"
              value={volcSkInput}
              configured={form.has_volc_secret_access_key && !clearVolcSk}
              onChange={setVolcSkInput}
              onClear={() => {
                setVolcSkInput("");
                setClearVolcSk(true);
              }}
            />
            <LabeledControl label="区域" hint="默认 cn-beijing">
              <input
                className="settings-input"
                value={form.volc_ark_region}
                onChange={(e) => patchField("volc_ark_region", e.target.value)}
              />
            </LabeledControl>
          </div>
        </SettingsPanel>
      </div>
    </SettingsTabShell>
  );
}
