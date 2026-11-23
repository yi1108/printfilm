import { useAdminModelSettings } from "@/hooks/useAdminModelSettings";
import { SettingsPanel } from "./SettingsPanel";
import { Button } from "@/components/ui/button";

const optionalFields = [
  ["android_epay_package_name", "Android 包名（可选，用于定向打开 App）"],
  ["android_epay_sha256_fingerprints", "发布证书 SHA-256（仅 HTTPS App Links 需要，与包名配套）"],
  ["android_epay_return_base_url", "返回站点（留空使用已配置的公网 HTTPS 网站；本地部署请填写公网网站）"],
  ["android_epay_app_scheme", "返回 App 协议（可选，填写客户端已支持的协议）"],
] as const;
const switches = [
  ["android_epay_enabled", "允许国内 Android 网页充值"],
  ["android_epay_alipay_enabled", "启用手机支付宝收银台"],
  ["android_epay_wxpay_enabled", "启用手机微信收银台"],
] as const;
export function AndroidEpaySettings() {
  const { form, patchField, save, saving } = useAdminModelSettings();
  return <SettingsPanel title="App 复用网页支付" description="使用现有网页支付商户及统一积分账户。充值订单在原有「各渠道充值订单」中查看，可按 App / Web 来源筛选。">
    <div className="space-y-4">
      <p>网页充值无需填写 Android 包名、证书指纹或返回协议。支付后可手动返回 App 查询订单及积分。</p>
      {form && <>
        {switches.map(([key,label])=><label key={key} className="flex items-center gap-2"><input type="checkbox" checked={form[key]} onChange={e=>patchField(key,e.target.checked)}/>{label}</label>)}
        <details className="space-y-3"><summary>可选：支付后返回 App</summary>
          <p>仅在已发布 App 支持相应链接时填写。填写配置不会为 App 自动增加接收链接的能力；不配置也能付款到账。Scheme 无需证书指纹。</p>
          {optionalFields.map(([key,label])=><label key={key} className="block">{label}<textarea className="admin-input block w-full" value={form[key]} onChange={e=>patchField(key,e.target.value)}/></label>)}
        </details>
        <details><summary>高级：收银台域名</summary><label className="block">额外可信收银台主机（可选，英文逗号分隔）<textarea className="admin-input block w-full" value={form.android_epay_checkout_hosts} onChange={e=>patchField("android_epay_checkout_hosts",e.target.value)}/></label><p>默认允许现有支付服务主机。仅在供应商使用其他收银台域名时填写。</p></details>
        <Button disabled={saving} onClick={()=>void save(Object.fromEntries([...switches,...optionalFields,["android_epay_checkout_hosts",""] as const].map(([k])=>[k,form[k]])))}>保存网页支付设置</Button>
      </>}
      <p>付款结果以服务端确认的订单为准；页面返回或打开 App 不代表到账。</p>
    </div>
  </SettingsPanel>;
}
