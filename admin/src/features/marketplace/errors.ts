import { points } from '../../lib/points.ts'
const messages: Record<string, string> = {
  MARKETPLACE_STORAGE_UNAVAILABLE: '文件服务暂未配置，请检查后台文件服务设置。',
  MARKETPLACE_PAYMENT_UNAVAILABLE: '支付服务暂不可用，请检查支付配置后重试。',
  MARKETPLACE_REVENUE_CONFIG_REQUIRED: '请先配置并启用平台抽成比例，再提交平台投放收益作品。',
  MARKETPLACE_RIGHTS_REQUIRED: '请补齐版权材料后再操作。',
  MARKETPLACE_EPISODE_NOT_READY: '完整播放版本尚未就绪，请稍后重试。',
  MARKETPLACE_ENTITLEMENT_REQUIRED: '尚未取得该版本的完整播放权益。',
  MARKETPLACE_SOURCE_NOT_READY: '源成片尚未完成，请完成所选分集的全部分镜视频后重新同步。',
  MARKETPLACE_SOURCE_CHANGED: '源成片已更新，请重新选择后同步。',
  MARKETPLACE_SOURCE_INCOMPATIBLE: '分镜视频规格不一致，请统一画面比例后重新同步。',
  MARKETPLACE_TARGET_CHANGED: '市场草稿已更新，请刷新查看后重新操作。',
  MARKETPLACE_SYNC_IN_PROGRESS: '成片正在同步，请等待同步完成后再保存或提交。',
  MARKETPLACE_SUBMISSIONS_DISABLED: '招募由客服撮合，请在招募详情中联系客服接单。',
}
const fields: Record<string, string> = {
  version: '内容版本', title: '标题', reason: '审核原因', checks: '审核检查项', owner_id: '创作者编号', user_id: '购买用户编号',
  amount_fen: '金额', platform_share_bps: '平台抽成比例', enabled: '启用状态', status: '状态', note: '备注', names: '分类名称',
  name: '客服名称', wechat: '微信号', hours: '服务时间', qr_asset_id: '客服二维码', resolution: '举报处理结果',
}

function record(value: unknown): Record<string, unknown> | null {
  return value !== null && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : null
}

function readableText(value: string) {
  const text = value.trim().replace(/^Value error,\s*/i, '')
  return /[\u3400-\u9fff]/.test(text) ? text : undefined
}

function boundary(value: unknown, field: string): string {
  if ((typeof value !== 'number' && typeof value !== 'string') || value === '' || !Number.isFinite(Number(value))) return '允许范围'
  if (field === 'unlock_price_fen') return points(Number(value))
  return field.endsWith('_fen') ? `¥${(Number(value) / 100).toFixed(2)}` : String(value)
}

function explainValidation(value: Record<string, unknown>, field: string) {
  const raw = typeof value.msg === 'string' ? value.msg : ''
  const translated = readableText(raw)
  if (translated) return translated
  const ctx = record(value.ctx) || {}
  const length = (key: string) => typeof ctx[key] === 'number' && Number.isInteger(ctx[key]) && Number(ctx[key]) >= 0 ? String(ctx[key]) : '规定数量'
  switch (value.type) {
    case 'missing': return '这是必填项'
    case 'string_too_short': return `至少填写 ${length('min_length')} 个字符`
    case 'string_too_long': return `不能超过 ${length('max_length')} 个字符`
    case 'too_short': return `至少需要 ${length('min_length')} 项`
    case 'too_long': return `最多允许 ${length('max_length')} 项`
    case 'greater_than': return `数值须大于 ${boundary(ctx.gt, field)}`
    case 'greater_than_equal': return `数值不能小于 ${boundary(ctx.ge, field)}`
    case 'less_than': return `数值须小于 ${boundary(ctx.lt, field)}`
    case 'less_than_equal': return `数值不能大于 ${boundary(ctx.le, field)}`
    case 'int_parsing': case 'int_type': case 'int_from_float': return '请填写整数'
    case 'float_parsing': case 'float_type': case 'finite_number': return '请填写有效数字'
    case 'literal_error': return ctx.expected === 'True' ? '请勾选确认' : '请选择有效选项'
    case 'bool_parsing': case 'bool_type': return '请确认此选项'
    case 'extra_forbidden': return '此项不支持提交，请刷新后重试'
  }
  if (/field required/i.test(raw)) return '这是必填项'
  if (/valid integer/i.test(raw)) return '请填写整数'
  if (/valid number/i.test(raw)) return '请填写数字'
  const bound = raw.match(/(greater than or equal to|less than or equal to|greater than|less than|at least|at most)\s+(-?[\d.]+)/i)
  if (bound) {
    if (/string/i.test(raw)) return `请填写${/at least/i.test(bound[1]) ? '至少' : '不超过'} ${bound[2]} 个字符`
    return `数值${/greater|at least/i.test(bound[1]) ? /or equal|at least/i.test(bound[1]) ? '不能小于' : '须大于' : /or equal|at most/i.test(bound[1]) ? '不能大于' : '须小于'} ${boundary(bound[2], field)}`
  }
  return '请检查填写内容'
}

function validationMessage(detail: unknown[]) {
  const lines = detail.flatMap(entry => {
    const value = record(entry)
    if (!value) return []
    const parts = (Array.isArray(value.loc) ? value.loc : []).filter(part => (typeof part === 'string' || typeof part === 'number') && !['body', 'query', 'path'].includes(String(part)))
    const field = String(parts.findLast(part => typeof part === 'string') || '')
    const location = parts.map(part => typeof part === 'number' ? `第 ${part + 1} 项` : fields[String(part)] || '表单内容').join('的')
    const message = explainValidation(value, field)
    return [location ? `${location}：${message}` : message]
  })
  return [...new Set(lines)].join('；') || '请检查表单内容和必填字段。'
}

function fallbackMessage(status: number) {
  if (status === 401) return '登录已过期，请重新登录后继续。'
  if (status === 403) return '当前账号没有执行此操作的权限。'
  if (status === 404) return '内容不存在或暂不可访问，请刷新后重试。'
  if (status === 409) return '内容状态已变化，请刷新后重新操作。'
  if (status === 422) return '请检查表单内容和必填字段。'
  if (status === 429) return '操作过于频繁，请稍后再试。'
  return '暂时无法完成操作，请稍后重试。'
}

export class MarketplaceRequestError extends Error {
  code: string | undefined
  status: number

  constructor(detail: unknown, status: number, fallback?: string, cause?: unknown) {
    const object = record(detail)
    const raw = typeof detail === 'string' ? detail : typeof object?.message === 'string' ? object.message : ''
    const match = raw.match(/^(MARKETPLACE_[A-Z_]+)(?=[:：\s]|$)/)
    const code = typeof object?.code === 'string' ? object.code : match?.[1]
    const text = match ? raw.slice(match[0].length).replace(/^\s*[:：]?\s*/, '') : raw
    const message = Array.isArray(detail) ? validationMessage(detail) : readableText(text) || (code ? messages[code] : undefined) || fallback || fallbackMessage(status)
    super(message, { cause })
    this.name = 'MarketplaceRequestError'
    this.code = code
    this.status = status
  }
}
