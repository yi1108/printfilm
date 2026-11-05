import { useEffect, useState } from 'react';
import { SettingsPanel } from './SettingsPanel';
import { Button } from '@/components/ui/button';
import { request, type Listing } from '@/features/marketplace/api';

type Product = { id: string; product_id: string; credit_fen: number; amount_fen: number; expected_prices: Record<string, number> };
const base = '/api/admin/marketplace/app';

export function AppleProductSettings() {
  const [presets, setPresets] = useState<Product[]>([]);
  const [items, setItems] = useState<Listing['items']>([]);
  const [revision, setRevision] = useState(0);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState('');
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');
  useEffect(() => {
    let active = true;
    setLoading(true); setError('');
    async function load() {
      const preset = await request<{ items: Product[] }>(`${base}/product-presets`);
      const rows: Listing['items'] = [];
      let page = 1;
      while (active) {
        const result = await request<Listing>(`${base}/products?page=${page}&page_size=100`);
        rows.push(...result.items);
        if (rows.length >= result.meta.total || !result.items.length) break;
        page += 1;
      }
      if (active) { setPresets(preset.items); setItems(rows); }
    }
    void load().catch(cause => { if (active) setError((cause as Error).message); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [revision]);

  async function save(product: Product, enabled: boolean) {
    setBusy(product.id); setError(''); setMessage('');
    try {
      await request(`${base}/products`, 'PUT', { product_id: product.product_id, sku_id: product.id,
        coins: product.credit_fen, price_fen: product.amount_fen, expected_prices: product.expected_prices, enabled });
      setMessage(`${product.id} 已${enabled ? '允许新购' : '保存为停用'}。实际购买仍须通过 Apple 配置与统一余额检查。`);
      setRevision(value => value + 1);
    } catch (cause) { setError((cause as Error).message); }
    finally { setBusy(''); }
  }

  return <SettingsPanel title="Apple 内购商品配置" description="与数字资产平台运营共用商品记录，各档单独保存。这里只登记服务器商品映射，不会在 Apple 创建商品或提交审核。"
    actions={<Button type="button" variant="outline" disabled={loading || Boolean(busy)} onClick={() => setRevision(value => value + 1)}>刷新商品</Button>}>
    <p className="text-sm text-muted-foreground mb-4">请在 <a className="underline" href="https://appstoreconnect.apple.com/" target="_blank" rel="noopener noreferrer">App Store Connect</a> 创建对应的消耗型内购商品并配置 CNY / USD 售价。到账为人民币平台额度，含赠额；商品启用不代表 Apple 已审核可售。旧商品额度不可修改。</p>
    {loading ? <p role="status">正在读取商品配置…</p> : <div className="grid gap-4 md:grid-cols-2">{presets.map(product => {
      const item = items.find(row => row.product_id === product.product_id);
      return <article key={product.id} className="rounded-lg border p-4 space-y-3">
        <h4 className="font-medium">{product.id} · {item ? item.enabled ? '已允许新购' : '已停用' : '未登记'}</h4>
        <p className="text-sm break-all">{product.product_id}</p>
        <p className="text-sm">售价：¥{(product.expected_prices.CNY / 100).toFixed(2)} / ${(product.expected_prices.USD / 100).toFixed(2)}</p>
        <p className="text-sm">到账：{product.credit_fen.toLocaleString('zh-CN')} 积分（含赠额 {(product.credit_fen - product.amount_fen).toLocaleString('zh-CN')} 积分）</p>
        <div className="flex flex-wrap gap-2">
          {!item && <Button type="button" variant="outline" disabled={Boolean(busy) || Boolean(error)} onClick={() => void save(product, false)}>登记商品（暂不启用）</Button>}
          {item && <Button type="button" variant="outline" disabled={Boolean(busy)} onClick={() => void save(product, !item.enabled)}>{busy === product.id ? '保存中…' : item.enabled ? '停止该档新购' : '允许该档新购'}</Button>}
        </div>
      </article>;
    })}</div>}
    {error && <p role="alert" className="text-sm text-destructive mt-4">{error}</p>}
    {message && <p role="status" className="text-sm mt-4">{message}</p>}
  </SettingsPanel>;
}
