import { useEffect, useState } from 'react';
import { api } from '@/api/client';
import { useAdminModelSettings } from '@/hooks/useAdminModelSettings';
import { Button } from '@/components/ui/button';
import { Switch } from '@/components/ui/switch';
import { LabeledControl, SettingsPanel } from './SettingsPanel';

type Status = { configured: boolean; missing: string[]; environment: string; notification_url: string;
  notification_https: boolean; unified_wallet_enabled: boolean; wallet_environment: string; wallet_environment_matches: boolean; runtime_running: boolean };

export function AppleConnectionSettings() {
  const { form, loading, saving, patchField, save } = useAdminModelSettings();
  const [privateKey, setPrivateKey] = useState('');
  const [keyName, setKeyName] = useState('');
  const [clearKey, setClearKey] = useState(false);
  const [status, setStatus] = useState<Status | null>(null);
  const [error, setError] = useState('');
  const [checking, setChecking] = useState(false);
  async function check() {
    setChecking(true); setError('');
    try { setStatus(await api<Status>('/api/admin/settings/apple/status')); }
    catch (cause) { setError((cause as Error).message); }
    finally { setChecking(false); }
  }
  useEffect(() => { void check(); }, []);

  async function upload(files: FileList | null, key: boolean) {
    if (!files?.length) return;
    setError('');
    try {
      const selected = Array.from(files);
      if (selected.reduce((sum, file) => sum + file.size, 0) > (key ? 16384 : 45000)) throw new Error('文件过大，请选择私钥或根证书文件。');
      if (key) {
        setPrivateKey(await selected[0].text()); setKeyName(selected[0].name); setClearKey(false);
      } else {
        const certificates = await Promise.all(selected.map(async file => {
          const data = new Uint8Array(await file.arrayBuffer());
          const text = new TextDecoder().decode(data);
          if (text.includes('-----BEGIN CERTIFICATE-----')) return text.trim();
          const base64 = btoa(String.fromCharCode(...data));
          return '-----BEGIN CERTIFICATE-----\n' + base64.match(/.{1,64}/g)?.join('\n') + '\n-----END CERTIFICATE-----';
        }));
        patchField('apple_root_certificates', certificates.join('\n'));
      }
    } catch (cause) { setError((cause as Error).message); }
  }

  async function submit() {
    if (!form) return;
    const saved = await save({
      apple_sandbox_enabled: form.apple_sandbox_enabled, apple_sandbox_user_ids: form.apple_sandbox_user_ids,
      apple_iap_enabled: form.apple_iap_enabled, apple_environment: form.apple_environment, apple_bundle_id: form.apple_bundle_id.trim(),
      apple_app_id: form.apple_app_id, apple_issuer_id: form.apple_issuer_id.trim(), apple_key_id: form.apple_key_id.trim(),
      apple_private_key: privateKey || undefined, clear_apple_private_key: clearKey,
      apple_root_certificates: form.apple_root_certificates,
    }, 'Apple 接入配置已保存');
    if (saved) { setPrivateKey(''); setKeyName(''); setClearKey(false); await check(); }
  }
  return <SettingsPanel title="Apple 支付接入" description="独立保存到系统配置；私钥加密保存且不回显。停止新购不会停止已付款验单和退款通知。">
    {loading || !form ? <p role="status">正在读取 Apple 配置…</p> : <div className="space-y-5">
      <div className="settings-toggle-row"><div><strong>允许 Apple 新购</strong><span>需完成商品配置、统一余额核对及 Sandbox / TestFlight 联调后再开启生产新购。</span></div>
        <Switch aria-label="允许 Apple 新购" checked={form.apple_iap_enabled} onCheckedChange={value => patchField('apple_iap_enabled', value)} /></div>
      <div className="settings-toggle-row"><div><strong>允许白名单账号沙箱新购</strong><span>正式环境保持 Production；测试积分独立，不能用于正式 AI 或创作者结算。关闭只暂停新购和测试解锁，已付款验单及退款继续处理。</span></div>
        <Switch aria-label="允许沙箱新购" checked={form.apple_sandbox_enabled} onCheckedChange={value => patchField('apple_sandbox_enabled', value)} /></div>
      <LabeledControl label="沙箱测试用户 ID" hint="填写后台用户编号，用英文逗号分隔（例如 123,456）。这些账号的 App 钱包和视频权益显示为 Sandbox；Web 余额与 AI 仍使用正式钱包。移出前请完成测试核对。">
        <input className="settings-input" value={form.apple_sandbox_user_ids} onChange={e => patchField('apple_sandbox_user_ids', e.target.value.replace(/\s/g, ''))} />
      </LabeledControl>
      <div className="settings-field-grid">
        <LabeledControl label="交易环境" hint="仅影响 Apple 渠道，不改变统一钱包及 AI 消费环境。正式站请保留 Production。同部署沙箱请使用上方白名单开关，不要切换正式钱包环境。"><select className="settings-input" value={form.apple_environment} onChange={e => patchField('apple_environment', e.target.value as 'Production' | 'Sandbox')}><option value="Production">Production（生产）</option><option value="Sandbox">Sandbox（沙箱测试）</option></select></LabeledControl>
        <LabeledControl label="Bundle ID"><input className="settings-input" value={form.apple_bundle_id} onChange={e => patchField('apple_bundle_id', e.target.value)} placeholder="com.deep.printfilm" /></LabeledControl>
        <LabeledControl label="Apple App ID" hint="App Store Connect 应用的数字 Apple ID；生产必填，不是 Bundle ID。"><input className="settings-input" type="number" min="0" step="1" value={form.apple_app_id || ''} onChange={e => patchField('apple_app_id', Number(e.target.value))} /></LabeledControl>
        <LabeledControl label="Issuer ID"><input className="settings-input" value={form.apple_issuer_id} onChange={e => patchField('apple_issuer_id', e.target.value)} /></LabeledControl>
        <LabeledControl label="Key ID"><input className="settings-input" value={form.apple_key_id} onChange={e => patchField('apple_key_id', e.target.value)} /></LabeledControl>
        <LabeledControl label="Apple .p8 私钥" hint={clearKey ? '保存后清除。' : keyName ? '已选择新私钥，保存后生效。' : form.has_apple_private_key ? '已配置；不上传则保留。' : '尚未配置，请上传内购服务器 API 私钥。'}>
          <input className="settings-input" type="file" accept=".p8,.pem" onChange={e => { void upload(e.target.files, true); e.target.value = ''; }} />
          <Button type="button" variant="outline" onClick={() => { setClearKey(!clearKey); setPrivateKey(''); setKeyName(''); }}>{clearKey ? '撤销清除' : '清除私钥'}</Button>
        </LabeledControl>
        <LabeledControl label="Apple 根证书" hint="从 Apple PKI 获取根 CA 证书，可多选 DER / CER / PEM；本次上传替换完整证书集合。">
          <input className="settings-input" type="file" multiple accept=".cer,.der,.pem" onChange={e => { void upload(e.target.files, false); e.target.value = ''; }} />
          <p className="text-sm text-muted-foreground">{form.apple_root_certificates ? '已载入根证书集合' : '尚未配置根证书'}</p>
        </LabeledControl>
      </div>
      <p className="text-sm">根证书来源：<a href="https://www.apple.com/certificateauthority/" target="_blank" rel="noopener noreferrer" className="underline">Apple PKI</a>。配置检查只校验身份字段、证书和私钥可解析性，不证明凭证权限或商品可售。</p>
      {status && <div className="rounded-lg border p-4 space-y-2 text-sm">
        <p>已保存配置：{status.configured ? '配置完整，仍需真实联调' : '待补充：' + status.missing.join('、')}</p>
        <p>统一钱包：{status.unified_wallet_enabled ? '已启用' : '未启用'} · 通知处理：{status.runtime_running ? '运行中' : '尚未运行'}</p>
        <p>钱包环境：{status.wallet_environment}{!status.wallet_environment_matches && ' · 与 Apple 环境不匹配：已阻止新购及跨环境入账，AI 消费仍按钱包环境执行。'}</p>
        <p className="break-all">通知地址（App Store Server Notifications V2）：{status.notification_url}</p>
        {!status.notification_https && <p className="text-destructive">请先在“站点工具”配置可公网访问的 HTTPS 后端基址。</p>}
        <Button type="button" variant="outline" onClick={() => { void navigator.clipboard.writeText(status.notification_url).catch(() => setError('复制失败，请手动复制通知地址。')); }}>复制通知地址</Button>
      </div>}
      <div className="flex flex-wrap gap-2"><Button type="button" disabled={saving} onClick={() => void submit()}>{saving ? '保存中…' : '保存 Apple 接入配置'}</Button>
        <Button type="button" variant="outline" disabled={checking || saving} onClick={() => void check()}>{checking ? '检查中…' : '检查已保存配置'}</Button></div>
    </div>}
    {error && <p role="alert" className="text-destructive text-sm mt-4">{error}</p>}
  </SettingsPanel>;
}
