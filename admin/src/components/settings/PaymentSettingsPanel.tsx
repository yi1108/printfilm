import { useState, type ChangeEvent } from "react";
import { Copy } from "lucide-react";
import { toast } from "sonner";
import { LabeledControl, SettingsLoading, SettingsPanel, SettingsStatusBar, SettingsTabShell } from "@/components/settings/SettingsPanel";
import { SecretField } from "@/components/settings/SecretField";
import { Switch } from "@/components/ui/switch";
import { Button } from "@/components/ui/button";
import { useAdminModelSettings } from "@/hooks/useAdminModelSettings";
import { stripeRateInputError, stripeSettingsPatch, stripeSettingsReady } from "@/lib/stripeSettings";
import { MediaPriceSettings } from "./MediaPriceSettings";

const RATE_FIELDS = [
  { key: "billing_llm_per_m", label: "文字 LLM", unit: "元 / 百万 Token" },
  { key: "billing_tts_per_m", label: "TTS 语音", unit: "元 / 百万 Token" },
  { key: "billing_seedream_per_m", label: "Seedream 生图（兼容规则）", unit: "元 / 百万 Token" },
  { key: "billing_seedance_video0", label: "Seedance video0（兼容规则）", unit: "元 / 百万 Token" },
  { key: "billing_seedance_video1", label: "Seedance video1（兼容规则）", unit: "元 / 百万 Token" },
  { key: "billing_kie_fen_per_credit", label: "KIE 积分换算", unit: "分 / Credit" },
] as const;
const ESTIMATE_FIELDS = [
  { key: "billing_est_llm_tokens", label: "文字 LLM", unit: "Token / 次" },
  { key: "billing_est_seedream_tokens", label: "Seedream 生图", unit: "Token / 次" },
  { key: "billing_est_tts_tokens", label: "TTS 语音", unit: "Token / 次" },
  { key: "billing_est_seedance_tokens_per_sec", label: "Seedance 视频", unit: "Token / 秒" },
] as const;
type NumericKey = typeof RATE_FIELDS[number]["key"] | typeof ESTIMATE_FIELDS[number]["key"]
  | "billing_estimate_buffer" | "billing_signup_grant_fen" | "billing_user_alert_interval_fen"
  | "smtp_port";

export function PaymentSettingsPanel() {
  const { form, loading, saving, patchField, save } = useAdminModelSettings();
  const [epayKeyInput, setEpayKeyInput] = useState("");
  const [clearEpayKey, setClearEpayKey] = useState(false);
  const [stripeKeyInput, setStripeKeyInput] = useState("");
  const [clearStripeKey, setClearStripeKey] = useState(false);
  const [stripeWebhookInput, setStripeWebhookInput] = useState("");
  const [clearStripeWebhook, setClearStripeWebhook] = useState(false);
  const [smtpPasswordInput, setSmtpPasswordInput] = useState("");
  const [clearSmtpPassword, setClearSmtpPassword] = useState(false);
  const [numericDrafts, setNumericDrafts] = useState<Partial<Record<NumericKey, string>>>({});
  const stripeDrafts = {
    secretKey: stripeKeyInput,
    webhookSecret: stripeWebhookInput,
    clearSecretKey: clearStripeKey,
    clearWebhookSecret: clearStripeWebhook,
  };

  function numericControl(key: NumericKey) {
    return {
      value: numericDrafts[key] ?? String(form?.[key] ?? ""),
      onChange: (event: ChangeEvent<HTMLInputElement>) => {
        const raw = event.target.value;
        setNumericDrafts((previous) => ({ ...previous, [key]: raw }));
        if (raw.trim() && Number.isFinite(Number(raw))) patchField(key, Number(raw));
      },
    };
  }

  async function copyStripeWebhook() {
    try {
      await navigator.clipboard.writeText(form?.stripe_webhook_url || "/api/billing/stripe/webhook");
      toast.success("Stripe Webhook 地址已复制");
    } catch {
      toast.error("复制失败，请手动复制 Webhook 地址");
    }
  }

  async function handleSave() {
    if (!form) return;
    const saved = await save({
      ...stripeSettingsPatch(form, stripeDrafts),
      epay_api_url: form.epay_api_url.trim(),
      epay_pid: form.epay_pid.trim(),
      epay_key: clearEpayKey ? undefined : epayKeyInput.trim() || undefined,
      clear_epay_key: clearEpayKey,
      epay_notify_url: form.epay_notify_url.trim(),
      epay_return_url: form.epay_return_url.trim(),
      billing_enabled: form.billing_enabled,
      billing_markup: 1.0,
      billing_estimate_buffer: form.billing_estimate_buffer,
      billing_seedance_video0: form.billing_seedance_video0,
      billing_seedance_video1: form.billing_seedance_video1,
      billing_llm_per_m: form.billing_llm_per_m,
      billing_seedream_per_m: form.billing_seedream_per_m,
      billing_tts_per_m: form.billing_tts_per_m,
      billing_kie_fen_per_credit: form.billing_kie_fen_per_credit,
      billing_est_llm_tokens: form.billing_est_llm_tokens,
      billing_est_seedream_tokens: form.billing_est_seedream_tokens,
      billing_est_tts_tokens: form.billing_est_tts_tokens,
      billing_est_seedance_tokens_per_sec: form.billing_est_seedance_tokens_per_sec,
      billing_signup_grant_fen: form.billing_signup_grant_fen,
      billing_user_alert_enabled: form.billing_user_alert_enabled,
      billing_user_alert_interval_fen: form.billing_user_alert_interval_fen,
      smtp_enabled: form.smtp_enabled,
      smtp_host: form.smtp_host.trim(),
      smtp_port: form.smtp_port,
      smtp_user: form.smtp_user.trim(),
      smtp_password: clearSmtpPassword ? undefined : smtpPasswordInput.trim() || undefined,
      clear_smtp_password: clearSmtpPassword,
      smtp_from: form.smtp_from.trim(),
      smtp_use_tls: form.smtp_use_tls,
    }, "支付、计费与通知设置已保存");
    if (!saved) return;
    setEpayKeyInput("");
    setClearEpayKey(false);
    setStripeKeyInput("");
    setClearStripeKey(false);
    setStripeWebhookInput("");
    setClearStripeWebhook(false);
    setSmtpPasswordInput("");
    setClearSmtpPassword(false);
    setNumericDrafts({});
  }

  if (loading || !form) return <SettingsLoading />;

  const hasEpayKey = !clearEpayKey && (form.has_epay_key || Boolean(epayKeyInput.trim()));
  const epayInUse = Boolean(form.epay_pid.trim() || hasEpayKey);
  const epayReady = Boolean(form.epay_api_url.trim() && form.epay_pid.trim() && hasEpayKey);
  const stripeReady = stripeSettingsReady(form, stripeDrafts);
  const usdRateError = stripeRateInputError(form.stripe_usd_cny_rate);
  const hasSmtpPassword = !clearSmtpPassword && (form.has_smtp_password || Boolean(smtpPasswordInput.trim()));
  const smtpNeedsPassword = form.smtp_enabled && Boolean(form.smtp_user.trim());
  const smtpReady = form.smtp_enabled && Boolean(form.smtp_host.trim() && form.smtp_from.trim() && (!smtpNeedsPassword || hasSmtpPassword));
  const moneyHint = (key: NumericKey) => {
    const raw = numericDrafts[key] ?? form[key];
    return raw === "" ? "请输入以分为单位的金额。" : `当前金额 ¥${(Number(raw) / 100).toFixed(2)}；100 分 = 1 元。`;
  };

  return <div className="space-y-5">
    <SettingsTabShell onSave={handleSave} saving={saving} disabled={Boolean(usdRateError)} saveLabel="保存支付与通知设置">
      <SettingsStatusBar title="支付与通知状态" items={[
        { id: "epay", label: "易支付", ready: epayReady, readyText: "配置完整", pendingText: "未完成接入" },
        { id: "stripe", label: "Stripe", ready: stripeReady, readyText: "配置完整", pendingText: form.stripe_enabled ? "请补全 Stripe" : "未启用" },
        { id: "billing", label: "余额计费", ready: form.billing_enabled, readyText: "已开启", pendingText: "已关闭" },
        { id: "smtp", label: "邮件发送", ready: smtpReady, readyText: "配置完整", pendingText: form.smtp_enabled ? "请补全 SMTP" : "未启用" },
      ]} />

      <SettingsPanel title="支付接入" description="配置易支付收款。已有商户密钥不回显，输入新密钥后保存即可替换。">
        <div className="settings-field-grid">
          <LabeledControl label="支付网关地址" required={epayInUse} hint="填写服务商提供的完整网关地址，例如 https://pay.example.com。">
            <input className="settings-input" type="url" placeholder="https://pay.example.com" value={form.epay_api_url} onChange={(event) => patchField("epay_api_url", event.target.value)} autoCapitalize="none" spellCheck={false} />
          </LabeledControl>
          <LabeledControl label="商户编号 PID" required={epayInUse} hint="易支付控制台中的商户编号。">
            <input className="settings-input" placeholder="例如 10001" value={form.epay_pid} onChange={(event) => patchField("epay_pid", event.target.value)} autoCapitalize="none" spellCheck={false} />
          </LabeledControl>
          <SecretField label="商户密钥" value={epayKeyInput} configured={form.has_epay_key} required={epayInUse}
            clearPending={clearEpayKey} onUndoClear={() => setClearEpayKey(false)}
            onChange={(value) => { setEpayKeyInput(value); setClearEpayKey(false); }} onClear={() => setClearEpayKey(true)} />
        </div>
        <details className="settings-advanced mt-5">
          <summary>高级接入 · 回调与支付完成页</summary>
          <div className="settings-field-grid">
            <LabeledControl label="异步通知地址" optional hint="生产示例：https://www.example.com/epay/notify，路径不包含 /api/。">
              <input className="settings-input" type="url" placeholder="https://www.example.com/epay/notify" value={form.epay_notify_url} onChange={(event) => patchField("epay_notify_url", event.target.value)} autoCapitalize="none" spellCheck={false} />
            </LabeledControl>
            <LabeledControl label="支付完成跳转地址" optional hint="用户支付完成后返回的页面，填写完整 http:// 或 https:// 地址。">
              <input className="settings-input" type="url" placeholder="https://www.example.com/settings" value={form.epay_return_url} onChange={(event) => patchField("epay_return_url", event.target.value)} autoCapitalize="none" spellCheck={false} />
            </LabeledControl>
          </div>
        </details>
      </SettingsPanel>

      <SettingsPanel title="Stripe 支付接入" description="按网站语言选择收款币种：中文使用人民币 CNY，英文使用美元 USD。美元报价按后台汇率换算，站内到账余额仍以人民币计。">
        <div className="settings-toggle-row">
          <div><strong>启用 Stripe 支付</strong><span>开启并保存完整配置后，用户可在充值页选择银行卡支付。</span></div>
          <Switch aria-label="启用 Stripe 支付" checked={Boolean(form.stripe_enabled)} onCheckedChange={(value) => patchField("stripe_enabled", value)} />
        </div>
        <div className="settings-field-grid mt-5">
          <LabeledControl label="Stripe 收款币种" hint="根据用户当前网站语言自动选择；支付宝与微信支付仍使用人民币。">
            <input className="settings-input" readOnly value="中文 CNY / 英文 USD（按网站语言）" />
          </LabeledControl>
          <LabeledControl label="美元兑人民币汇率" optional error={usdRateError}
            hint="1 USD = 输入值 CNY；手动设置，最多六位小数。留空时中文 CNY 可用，英文 USD 暂不可用。">
            <input className="settings-input" type="text" inputMode="decimal" placeholder="输入 1 美元对应的人民币金额" value={form.stripe_usd_cny_rate || ""}
              onChange={(event) => patchField("stripe_usd_cny_rate", event.target.value)} autoComplete="off" spellCheck={false} />
          </LabeledControl>
          <SecretField label="Stripe API 密钥" value={stripeKeyInput} configured={Boolean(form.has_stripe_secret_key)} required={form.stripe_enabled}
            placeholder="sk_test_… 或 sk_live_…" hint="填写 Stripe 控制台中的 Secret key；托管收银台不需要 Publishable key。"
            clearPending={clearStripeKey} onUndoClear={() => setClearStripeKey(false)}
            onChange={(value) => { setStripeKeyInput(value); setClearStripeKey(false); }} onClear={() => setClearStripeKey(true)} />
          <SecretField label="Stripe Webhook 签名密钥" value={stripeWebhookInput} configured={Boolean(form.has_stripe_webhook_secret)} required={form.stripe_enabled}
            placeholder="whsec_…" hint="填写此 Webhook 端点对应的 Signing secret，用于验证付款通知。"
            clearPending={clearStripeWebhook} onUndoClear={() => setClearStripeWebhook(false)}
            onChange={(value) => { setStripeWebhookInput(value); setClearStripeWebhook(false); }} onClear={() => setClearStripeWebhook(true)} />
          <LabeledControl label="Stripe 支付返回站点" optional hint="填写用户端源地址，不含页面路径；留空使用「站点工具」的后端公网基址。前后端分离时应填写用户端地址，例如本地 http://127.0.0.1:5183。">
            <input className="settings-input" type="url" placeholder="https://app.example.com" value={form.stripe_frontend_url || ""} onChange={(event) => patchField("stripe_frontend_url", event.target.value)} autoCapitalize="none" spellCheck={false} />
          </LabeledControl>
          <LabeledControl label="Stripe Webhook 通知地址" hint="在 Stripe 控制台添加此端点。公网域名取自「站点工具」的后端公网基址。">
            <div className="flex items-center gap-2">
              <input className="settings-input min-w-0" readOnly value={form.stripe_webhook_url || "/api/billing/stripe/webhook"} />
              <Button type="button" variant="outline" aria-label="复制 Stripe Webhook 通知地址" onClick={() => void copyStripeWebhook()}><Copy size={14} />复制</Button>
            </div>
          </LabeledControl>
        </div>
        <p className="settings-panel-footnote">美元支付金额 = 人民币套餐价格 ÷ 美元汇率，四舍五入到美分。保存新汇率只影响新订单，已创建订单按下单时的金额与汇率支付；充值到账及赠送余额仍以人民币计。</p>
        <p className="settings-panel-footnote">Webhook 使用 Snapshot 事件：checkout.session.completed、checkout.session.async_payment_succeeded、checkout.session.async_payment_failed 和 checkout.session.expired。支付确认到账后才增加余额；停用 Stripe 时保留已有配置。</p>
      </SettingsPanel>

      <SettingsPanel title="余额与计费" description="控制生成扣费及新用户赠送。图片与视频价格在下方单独发布，不随本表单保存。">
        <div className="settings-toggle-row">
          <div><strong>启用余额计费</strong><span>开启后按规则扣除用户余额；关闭后生成不扣余额。</span></div>
          <Switch aria-label="启用余额计费" checked={form.billing_enabled} onCheckedChange={(value) => patchField("billing_enabled", value)} />
        </div>
        <div className="settings-field-grid mt-5">
          <LabeledControl label="注册赠送金额（分）" required hint={moneyHint("billing_signup_grant_fen")}>
            <input className="settings-input" type="number" min={0} step={1} placeholder="0" {...numericControl("billing_signup_grant_fen")} />
          </LabeledControl>
        </div>
        <details className="settings-advanced mt-5">
          <summary>高级计费 · Token 单价、冻结缓冲与缺省估算</summary>
          <div>
            <p className="settings-runtime-note">图视频发布并启用站内价格后优先使用发布价格；下方兼容单价仅用于仍采用原计费规则的调用。LLM、TTS 继续使用 Token 规则。</p>
            <fieldset className="m-0 min-w-0 border-0 p-0" disabled={!form.billing_enabled}>
              <div className="settings-subsection-title">Token 单价与积分换算</div>
              <div className="settings-field-grid">
                {RATE_FIELDS.map((field) => <LabeledControl key={field.key} label={field.label} required={form.billing_enabled} hint={field.unit}>
                  <input className="settings-input" type="number" min={0} step="any" {...numericControl(field.key)} />
                </LabeledControl>)}
              </div>
              <div className="settings-subsection-title">任务预估</div>
              <div className="settings-field-grid">
                <LabeledControl label="冻结缓冲系数（倍）" required={form.billing_enabled} hint="最低 1；例如 1.2 表示在预估费用上预留 20%。">
                  <input className="settings-input" type="number" min={1} step="0.01" {...numericControl("billing_estimate_buffer")} />
                </LabeledControl>
                {ESTIMATE_FIELDS.map((field) => <LabeledControl key={field.key} label={`${field.label} 缺省用量`} required={form.billing_enabled} hint={`${field.unit}；上游未返回 usage 时使用。`}>
                  <input className="settings-input" type="number" min={1} step={1} {...numericControl(field.key)} />
                </LabeledControl>)}
              </div>
            </fieldset>
            {!form.billing_enabled && <p className="settings-panel-footnote">余额计费已关闭；开启后可调整上述规则，现有数值保留。</p>}
          </div>
        </details>
      </SettingsPanel>

      <SettingsPanel title="消费提醒" description="用户累计消费达到设置的间隔金额时，在产品内展示提醒。">
        <div className="settings-toggle-row">
          <div><strong>用户消费弹窗提醒</strong><span>累计扣费达到间隔档位时提醒，每笔结算最多弹出一次。</span></div>
          <Switch aria-label="用户消费弹窗提醒" checked={form.billing_user_alert_enabled} disabled={!form.billing_enabled} onCheckedChange={(value) => patchField("billing_user_alert_enabled", value)} />
        </div>
        <div className="settings-field-grid mt-5">
          <LabeledControl label="消费提醒间隔（分）" required={form.billing_enabled && form.billing_user_alert_enabled} hint={form.billing_enabled ? moneyHint("billing_user_alert_interval_fen") : "需先启用余额计费；原提醒设置保留。"}>
            <input className="settings-input" type="number" min={1} step={1} disabled={!form.billing_enabled || !form.billing_user_alert_enabled} {...numericControl("billing_user_alert_interval_fen")} />
          </LabeledControl>
        </div>
      </SettingsPanel>

      <details className="settings-advanced" open={form.smtp_enabled || undefined}>
        <summary>邮件发送 SMTP · {form.smtp_enabled ? "已启用" : "未启用，点击配置"}</summary>
        <SettingsPanel title="邮件发送" description="用于密码重置、团队邀请等邮件。使用邮箱服务商的 SMTP 服务及授权码；停用时保留已有配置。">
          <div className="settings-toggle-row">
            <div><strong>启用 SMTP 邮件发送</strong><span>开启并保存配置后，可发送密码重置、团队邀请等邮件。</span></div>
            <Switch aria-label="启用 SMTP 邮件发送" checked={form.smtp_enabled} onCheckedChange={(value) => patchField("smtp_enabled", value)} />
          </div>
          <div className="settings-field-grid mt-5">
            <LabeledControl label="SMTP 服务器" required={form.smtp_enabled} hint="仅填写主机名，不含 https://，例如 smtp.example.com。">
              <input className="settings-input" disabled={!form.smtp_enabled} placeholder="smtp.example.com" value={form.smtp_host} onChange={(event) => patchField("smtp_host", event.target.value)} autoCapitalize="none" spellCheck={false} pattern="[^/:\s]+" />
            </LabeledControl>
            <LabeledControl label="SMTP 端口" required={form.smtp_enabled} hint="1–65535；587 常用于 STARTTLS，465 使用隐式 SSL。">
              <input className="settings-input" type="number" disabled={!form.smtp_enabled} min={1} max={65535} step={1} placeholder="587" {...numericControl("smtp_port")} />
            </LabeledControl>
            <LabeledControl label="发件人地址" required={form.smtp_enabled} hint="收件人看到的邮箱地址，例如 notice@example.com。">
              <input className="settings-input" type="email" disabled={!form.smtp_enabled} placeholder="notice@example.com" value={form.smtp_from} onChange={(event) => patchField("smtp_from", event.target.value)} autoCapitalize="none" spellCheck={false} />
            </LabeledControl>
            <LabeledControl label="SMTP 登录用户名" optional hint="服务商要求认证时填写，通常与发件邮箱相同；免认证中继可留空。">
              <input className="settings-input" disabled={!form.smtp_enabled} placeholder="notice@example.com" value={form.smtp_user} onChange={(event) => patchField("smtp_user", event.target.value)} autoCapitalize="none" spellCheck={false} />
            </LabeledControl>
            <SecretField label="SMTP 密码 / 授权码" value={smtpPasswordInput} configured={form.has_smtp_password} required={smtpNeedsPassword}
              clearPending={clearSmtpPassword} onUndoClear={() => setClearSmtpPassword(false)}
              hint="多数邮箱使用 SMTP 授权码；停用时也可更新或清除凭证。"
              error={smtpNeedsPassword && clearSmtpPassword ? "请先停用 SMTP 或清空免认证中继的用户名，再清除密码。" : undefined}
              onChange={(value) => { setSmtpPasswordInput(value); setClearSmtpPassword(false); }} onClear={() => setClearSmtpPassword(true)} />
            <LabeledControl label="STARTTLS 加密" hint={[465, 8465, 2465].includes(form.smtp_port) ? "当前端口使用隐式 SSL，此开关不影响加密。" : "587 端口通常开启；具体以邮箱服务商要求为准。"}>
              <div className="settings-inline-switch">
                <Switch aria-label="启用 SMTP STARTTLS 加密" disabled={!form.smtp_enabled || [465, 8465, 2465].includes(form.smtp_port)} checked={form.smtp_use_tls} onCheckedChange={(value) => patchField("smtp_use_tls", value)} />
              </div>
            </LabeledControl>
          </div>
        </SettingsPanel>
      </details>
    </SettingsTabShell>
    <MediaPriceSettings />
  </div>;
}
