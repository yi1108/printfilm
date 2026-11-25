import { useEffect, useState } from "react";
import { useI18n } from "../i18n";
type ReturnConfig = { android_epay_package_name:string; android_epay_app_scheme:string; android_epay_return_base_url:string };
export default function PaymentReturnPage() {
  const { locale } = useI18n();
  const en = locale === "en";
  const [href,setHref] = useState("");
  const [error,setError] = useState(false);
  const order = new URLSearchParams(window.location.search).get("order") || "";
  useEffect(()=>{
    let active=true;
    if (!/^PFA[a-f0-9]{32}$/.test(order)) { setError(true); return; }
    fetch("/api/billing/android-epay/return-config",{cache:"no-store"})
      .then(async r=>{ if(!r.ok) throw Error(); return await r.json() as ReturnConfig; })
      .then(c=>{
        const scheme = c.android_epay_app_scheme;
        const pkg = c.android_epay_package_name;
        if (!scheme) return; // Manual return is a normal, supported payment flow.
        if (!/^[a-z][a-z0-9+.-]{1,39}$/.test(scheme) ||
            ["http","https","javascript","file","intent","data"].includes(scheme)) throw Error();
        if (pkg && !/^[A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z][A-Za-z0-9_]*)+$/.test(pkg)) throw Error();
        if(active) setHref(pkg
          ? `intent://payments/return?order=${encodeURIComponent(order)}#Intent;scheme=${scheme};package=${pkg};end`
          : `${scheme}://payments/return?order=${encodeURIComponent(order)}`);

      }).catch(()=>{if(active)setError(true);});
    return ()=>{active=false;};
  },[order]);
  return <main className="mx-auto max-w-lg space-y-6 px-6 py-16">
    <h1 className="text-2xl font-bold">{en?"Return to the app to check payment":"返回 App 确认支付结果"}</h1>
    <p>{en?"This page does not confirm payment. The app will check the server order and refresh your points.":"此页面不代表付款成功。App 将查询服务端订单，并刷新积分。请勿重复付款。"}</p>
    {href && <a className="inline-block rounded bg-blue-600 px-5 py-3 text-white" href={href}>{en?"Open app":"打开 App"}</a>}
    <p>{error?(en?"Return link unavailable. Open the app manually and check your order.":"返回链接暂不可用，请手动打开 App 查询原订单。"):(en?"If your browser blocks the link, open the app manually.":"请返回 App 查看订单和积分；若支持打开 App，也可点击上方按钮。")}</p>
  </main>;
}
