import { useMarketplaceLocale } from './useMarketplaceLocale'
import { marketText as mt } from './translate'
import type { ReactNode } from 'react'
import { ArrowLeft, ArrowUpRight, FolderOpen, ShieldCheck } from 'lucide-react'
import { Link, useSearchParams } from 'react-router-dom'
import Button from '../../components/ui/Button'

/** 只接受站内相对地址，避免把返回链到外部网站。 */
export function internalReturn(value: string | null | undefined): string | undefined {
  if (!value) return
  const path = value.trim()
  if (!path.startsWith('/') || path.startsWith('//') || path.includes('\\') || path.includes('://')) return
  return path
}

/** 把来源页带到下一步地址上，已有查询参数时追加 from。 */
export function withReturn(path: string, from: string | undefined): string {
  if (!from) return path
  return `${path}${path.includes('?') ? '&' : '?'}from=${encodeURIComponent(from)}`
}

// 模块内统一页头。地址带站内 from 时回到来源页，否则用调用方指定的广场。
export function PageHeading({ title, description, back, backLabel = mt("返回广场") }: { title: string; description: string; back?: string; backLabel?: string }) {
  useMarketplaceLocale()
  const [search] = useSearchParams()
  const from = internalReturn(search.get('from'))
  const href = from || back
  const label = from ? mt("返回上一页") : backLabel
  return <header className="pf-market-page-heading">{href && <Link className="pf-market-back" to={href}><ArrowLeft size={15} />{label}</Link>}<h1>{title}</h1><p>{description}</p></header>
}

// 空数据、空搜索和个人工作台共用真实空态，不填充示例作品。
export function EmptyState({ title, description, action, to, children }: { title: string; description: string; action?: string; to?: string; children?: ReactNode }) {
  useMarketplaceLocale()
  return <div className="pf-market-empty"><div className="pf-market-empty-icon" aria-hidden><FolderOpen size={30} strokeWidth={1.4} /></div><h3>{title}</h3><p>{description}</p>{action && to && <Button to={to} variant="dark" icon>{action}<ArrowUpRight size={16} /></Button>}{children}</div>
}

// 发布表单按内容分组，数字仅表示填写顺序。
export function FormSection({ step, title, description, children }: { step: string; title: string; description?: string; children: ReactNode }) {
  useMarketplaceLocale()
  return <section className="pf-market-form-section"><header><span>{step}</span><div><h2>{title}</h2>{description && <p>{description}</p>}</div></header><div className="pf-market-fields">{children}</div></section>
}

// 侧栏展示实际发布规则，不把流程说明显示为已完成状态。
export function PublishGuide({ recruit = false, saleType = 'copyright_contact' }: { recruit?: boolean; saleType?: 'free' | 'copyright_contact' | 'platform_unlock' }) {
  useMarketplaceLocale()
  const steps = recruit ? [[mt("说明需求"), mt("写清用途、预算和交付要求。")], [mt("提交审核"), mt("审核通过后进入招募广场。")], [mt("联系客服"), mt("创作者先联系客服表达接单意向。")], [mt("线下合作"), mt("客服协调需求、预算、合同及交付。")]] : [[mt("完善作品"), mt("上传视频与封面，填写作品介绍。")], [mt("确认版权"), mt("PrintFilm 作品使用有效授权函，其他平台作品提交证明材料；暂缺材料可联系客服。")], [mt("提交审核"), mt("作品与版权材料一并提交，由管理员统一审核。")], [mt("上架发布"), mt("审核通过后，由你主动上架。")]]
  const saleNotice = saleType === 'free' ? mt("上架后可完整免费观看。免费不代表可任意商用，使用仍须遵守作者授权范围。") : saleType === 'platform_unlock' ? mt("观众按标价购买所购版本的永久在线播放权益，不包含版权转让；创作者按已确定的比例获得收益。") : mt("版权合作参考价供洽谈使用。最终价格、授权范围、转让手续与相关费用请和客服确认，咨询不代表成交。")
  return <aside className="pf-market-guide"><div className="pf-market-guide-heading"><ShieldCheck size={21} /><h2>{recruit ? mt("从需求到合作") : mt("从作品到市场")}</h2></div><ol>{steps.map(([title, description], index) => <li key={title}><span>{String(index + 1).padStart(2, '0')}</span><div><strong>{title}</strong><p>{description}</p></div></li>)}</ol><div className="pf-market-guide-note"><strong>{recruit ? mt("先明确，再合作") : mt("了解收益与授权")}</strong><p>{recruit ? mt("创作者通过平台客服接单。具体合作条件在线下协商确认，咨询不代表已接单或成交。") : saleNotice}</p>{!recruit && <p>{mt("版权证明不能代替音乐、字体、肖像等素材的必要授权。")}</p>}</div></aside>
}

