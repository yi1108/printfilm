import { useEffect, useState } from 'react';
import { SettingsPanel } from './SettingsPanel';
import { Button } from '@/components/ui/button';
import { request, type Listing } from '@/features/marketplace/api';

type Edition = 'international' | 'domestic';
type Product = { id: string; product_id: string; app_edition: Edition; credit_fen: number; amount_fen: number; expected_prices: Record<string, number> };
const base = '/api/admin/marketplace/app';
const names = { international: '国际版', domestic: '国内版' };

export function AppleProductSettings() {
  const [edition, setEdition] = useState<Edition>('international');
  const [presets, setPresets] = useState<Product[]>([]);
  const [items, setItems] = useState<Listing['items']>([]);
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const [revision, setRevision] = useState(0);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState('');
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');
  useEffect(() => {
    let active = true;
    setLoading(true); setError(''); setMessage(''); setPresets([]); setItems([]);
    async function load() {
      const preset = await request<{ items: Product[] }>(`${base}/product-presets?app_edition=${edition}`);
      const rows: Listing['items'] = [];
      let page = 1;
      while (active) {
        const result = await request<Listing>(`${base}/products?page=${page}&page_size=100`);
        rows.push(...result.items);
        if (rows.length >= result.meta.total || !result.items.length) break;
        page += 1;
      }
      if (active) { setPresets(preset.items); setItems(rows.filter(row => (row.app_edition || 'international') === edition)); }
    }
    void load().catch(cause => { if (active) setError((cause as Error).message); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [edition, revision]);

  async function save(product: Product, productId: string, enabled: boolean) {
    setBusy(productId); setError(''); setMessage('');
    try {
      await request(`${base}/products`, 'PUT', { app_edition: edition, product_id: productId, sku_id: product.id,
        coins: product.credit_fen, price_fen: product.amount_fen, expected_prices: product.expected_prices, enabled });
      setMessage(`${names[edition]} ${product.id} 已${enabled ? '允许新购' : '保存为停用'}。商品还需在对应 App Store Connect 应用中审核可售。`);
      setRevision(value => value + 1);
    } catch (cause) { setError((cause as Error).message); }
    finally { setBusy(''); }
  }

  return <SettingsPanel title="Apple 双版本充值商品" description="两款应用分别登记商品，积分套餐和钱包共用。登记不会在 Apple 创建商品，各档独立保存。"
    actions={<Button type="button" variant="outline" disabled={loading || Boolean(busy)} onClick={() => setRevision(value => value + 1)}>刷新商品</Button>}>
    <div className="flex flex-wrap gap-2 mb-4" role="group" aria-label="Apple 商品所属应用">
      {(['international', 'domestic'] as const).map(value => <Button key={value} type="button" aria-pressed={edition === value} variant={edition === value ? 'default' : 'outline'} disabled={Boolean(busy)} onClick={() => setEdition(value)}>{names[value]}</Button>)}
    </div>
    <p className="text-sm text-muted-foreground mb-4">当前配置：{names[edition]}。请在该应用的 App Store Connect 中创建消耗型商品。售价由 StoreKit 展示；以下金额仅为后台预期。历史商品所属应用、套餐及额度不可改写，停用不影响已付款验单。</p>
    {loading ? <p role="status">正在读取{names[edition]}商品…</p> : <div className="grid gap-4 md:grid-cols-2">{presets.map(product => {
      const key = `${edition}:${product.id}`;
      const productId = (drafts[key] ?? product.product_id).trim();
      const registered = items.filter(row => row.sku_id === product.id);
      const exact = items.find(row => row.product_id === productId);
      return <article key={key} className="rounded-lg border p-4 space-y-3 min-w-0">
        <h4 className="font-medium">{names[edition]} · {product.id}</h4>
        <p className="text-sm">到账 {product.credit_fen.toLocaleString('zh-CN')} 积分 · 含赠额 {(product.credit_fen - product.amount_fen).toLocaleString('zh-CN')} 积分</p>
        <p className="text-sm text-muted-foreground">预期售价：¥{(product.expected_prices.CNY / 100).toFixed(2)} / ${(product.expected_prices.USD / 100).toFixed(2)}</p>
        {registered.map(row => <div key={row.id} className="rounded border p-3 space-y-2">
          <p className="text-sm break-all">{String(row.product_id)}</p>
          <p className="text-sm">{row.enabled ? '已允许新购' : '已停用'} · 已登记映射</p>
          <Button type="button" variant="outline" disabled={Boolean(busy)} onClick={() => void save(product, String(row.product_id), !row.enabled)}>{busy === String(row.product_id) ? '保存中…' : row.enabled ? '停止该商品新购' : '允许该商品新购'}</Button>
        </div>)}
        {!exact && <div className="space-y-2">
          <label className="block text-sm">新商品 Product ID<input className="settings-input mt-1 w-full" aria-label={`${names[edition]} ${product.id} 商品编号`} value={drafts[key] ?? product.product_id} onChange={event => setDrafts(value => ({ ...value, [key]: event.target.value }))} /></label>
          <Button type="button" variant="outline" disabled={Boolean(busy) || !/^[A-Za-z0-9._-]{1,200}$/.test(productId)} onClick={() => void save(product, productId, false)}>登记商品（暂不启用）</Button>
        </div>}
      </article>;
    })}</div>}
    {error && <p role="alert" className="text-sm text-destructive mt-4">{error}</p>}
    {message && <p role="status" className="text-sm mt-4">{message}</p>}
  </SettingsPanel>;
}
