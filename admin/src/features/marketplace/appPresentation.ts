import { points } from '../../lib/points.ts'
/** App运营只展示明确允许的业务字段，避免将Apple签名和支付密钥带到页面。 */
export const appPanels = {
  products: '苹果充值商品', transactions: '苹果交易', notifications: '苹果通知', wallets: '统一积分账户',
  'recharge-orders': '各渠道充值订单', 'funding-sources': '资金来源', 'funding-reviews': 'Web资金对账',
  debts: '欠费记录', repayments: '欠费偿还',
  'wallet-entries': '统一积分流水', 'unlock-orders': '积分解锁订单', adjustments: '退款与收益冲正',
  media: 'App播放准备', revenue: 'App收益明细', settlements: '月度对账', payouts: '创作者打款',
} as const
export type AppPanel = keyof typeof appPanels

const names: Record<string, string> = {
  payment_amount_minor: '原币实付（最小单位）', storefront: 'Apple商店地区', valuation_status: '财务核算状态',
  expected_prices: '固定售价', fx_snapshot: '财务汇率快照',
  spendable_fen: '实际可消费积分', pending_commitment_fen: '任务预留积分', sku_id: '共同套餐编号', balance_fen: '平台可用积分', frozen_fen: '冻结额度', debt_fen: '未补齐欠费',
  delta_fen: '积分变动', frozen_delta_fen: '冻结变动', frozen_after: '变动后冻结',
  source_type: '资金来源', source_ref: '来源编号', total_units: '到账积分', total_amount_fen: '来源实付',
  available_units: '来源可用积分', cause_type: '欠费原因', cause_ref: '原因编号', origin_lot_id: '原充值来源',
  units: '积分', debt_id: '欠费编号', allocation_id: '使用记录编号', repaid_units: '已补齐积分',
  outstanding_units: '未补齐积分', reviewed_at: '核对时间', pay_type: '支付渠道', credit_fen: '到账额度',
  product_id: '苹果商品编号', coins: '积分', price_fen: '苹果参考价', enabled: '可新购', used: '已有交易',
  environment: '交易环境', user_id: '用户编号', owner_id: '创作者编号', transaction_id: '苹果交易编号',
  original_transaction_id: '原始交易编号', apple_transaction_id: '充值记录编号', status: '状态', currency: '币种',
  amount_fen: '金额', balance_coins: '积分余额', balance: '积分余额', available_coins: '可用积分',
  remaining_coins: '批次剩余币数', coin_amount: '消费积分', coins_delta: '币数变动', delta_coins: '币数变动',
  balance_after: '变动后积分', balance_after_coins: '变动后积分', kind: '业务类型', action: '操作',
  publication_id: '发布版本编号', order_id: '订单编号', out_trade_no: '订单号',
  notification_type: '通知类型', notification_uuid: '通知编号', attempts: '处理次数', error: '处理说明',
  next_attempt_at: '下次处理时间', settlement_status: '对账状态', revoked_at: '退款时间', signed_at: '苹果签名时间',
  paid_at: '付款时间', created_at: '创建时间', updated_at: '更新时间', note: '备注', reason: '原因',
  title: '内容标题', content_type: '内容类型', content_id: '内容编号', version: '内容版本', asset_id: '视频资产编号',
  playback_status: '播放准备', media_status: '文件状态', mode: '播放用途', variant: '播放用途', month: '对账月份',
  gross_fen: '用户实付总额', platform_fen: '平台分成', creator_fen: '创作者收益', revenue_gross_fen: '分摊实付金额',
  channel_fee_fen: '渠道费', tax_fen: '相关税费', received_fen: '实际到账', net_platform_fen: '平台净收益',
  share_bps: '平台抽成（万分比）', transaction_ids: '充值记录编号', ledger_ids: '收益账目编号',
  settlement_id: '对账记录编号', payout_id: '打款记录编号', operator_id: '操作人编号', processed_at: '处理时间',
  active: '有效状态', refunded_at: '退款时间', reconciled_at: '对账确认时间', anomaly: '核对说明',
  eligible: '可结算', reference: '业务关联编号', unlock_id: '解锁记录编号', debt_offset_fen: '历史退款抵扣',
}
const labels: Record<string, string> = {
  pending_fx: '待汇率核算', valued: '已核算',
  web_order: 'Web充值', apple_transaction: '苹果充值', signup_grant: '注册赠额', admin_grant: '管理员赠额',
  source_refund: '退款追回', ai_overage: 'AI实际费用超出预扣', legacy_overage: '历史欠费',
  debt_created: '记录欠费', debt_repay: '补齐欠费', debt_release: '退回代偿资金', debt_cancelled: '取消追偿',
  repayment_void: '代偿来源退款', freeze: 'AI预扣冻结', settle: 'AI实际结算', unfreeze: '退回未用冻结',
  consume: '余额消费', grant: '赠额到账', adjust: '管理员调整',
  alipay: '支付宝', wxpay: '微信支付', apple_iap: '苹果内购', platform_balance: '平台余额',
  Production: '生产', Sandbox: '沙箱', pending: '待处理', processing: '处理中', running: '处理中', paid: '已付款',
  refunded: '已退款', refund_reversed: '退款已撤销', failed: '处理失败', done: '已完成', ready: '已就绪',
  approved: '审核通过', draft: '草稿', none: '未准备', cancelled: '已取消', revoked: '已撤销',
  credited: '已到账', quarantined: '待人工核查', ignored: '无需处理', reconciled: '已对账', unsettled: '待对账',
  settled: '已结算', restricted: '播放受限', purchase: '充值', credit: '充值到账', topup: '充值到账',
  unlock: '扣币解锁', debit: '消费扣币', refund: '退款扣回', refund_return: '有效币退回',
  refund_reversal: '退款撤销返还', refund_restore: '退款撤销返还', reversal: '收益冲正',
  work: '单视频', series_episode: '短剧分集', full: '完整播放', preview: '短试看',
  ONE_TIME_CHARGE: '一次性购买', REFUND: '苹果退款', REFUND_REVERSED: '苹果撤销退款',
  CONSUMPTION_REQUEST: '消费信息请求', TEST: '苹果测试通知',
  offset_only: '已全额抵扣',
}

/** 界面金额使用元，财务接口仍使用整数分。 */
export function appMoney(value: unknown) {
  return typeof value === 'number' && Number.isFinite(value) ? `¥${(value / 100).toFixed(2)}` : '—'
}

/** 只返回白名单字段，不对服务端返回的任意对象执行序列化。 */
export function appRecordFields(item: Record<string, unknown>, panel?: AppPanel): Array<[string, string]> {
  return Object.entries(item).flatMap(([key, value]) => {
    if (!names[key] || value === null || value === undefined || value === '') return []
    let text: string
    if (key === 'expected_prices' && typeof value === 'object') text = Object.entries(value).map(([currency, amount]) => `${currency} ${(Number(amount) / 100).toFixed(2)}`).join(' / ')
    else if (key === 'fx_snapshot' && typeof value === 'object') { const rate = value as Record<string, unknown>; text = rate.cny_per_unit ? `版本 ${rate.version} · ${rate.cny_per_unit} CNY · ${rate.source}` : '待核算' }
    else if (typeof value === 'boolean') text = value ? '是' : '否'
    else if (['spendable_fen', 'pending_commitment_fen', 'debt_fen', 'frozen_delta_fen', 'frozen_after', 'available_units', 'units', 'repaid_units', 'outstanding_units', 'balance_coins', 'balance', 'available_coins', 'remaining_coins', 'coin_amount', 'coins_delta', 'delta_coins', 'balance_after', 'balance_after_coins', 'balance_fen', 'frozen_fen', 'credit_fen', 'bonus_fen', 'charge_fen', 'delta_fen', 'balance_after_fen', 'unlock_price_fen', 'coins', 'total_units', 'remaining_units', 'debt_units', 'available_fen'].includes(key)) text = points(value)
    else if (key.endsWith('_fen')) text = appMoney(value)
    else if (Array.isArray(value)) text = value.filter(entry => typeof entry === 'number' || typeof entry === 'string').join('、') || '—'
    else if (typeof value === 'number' || typeof value === 'string') {
      const state = String(value)
      if (key === 'settlement_status') text = ({ pending: '待对账', reconciled: '已对账', paid: '已打款', revoked: '已冲正' } as Record<string, string>)[state] || labels[state] || state
      else if (key === 'status' && panel === 'unlock-orders') text = ({ paid: '已解锁', revoked: '已撤销' } as Record<string, string>)[state] || labels[state] || state
      else if (key === 'status' && panel === 'payouts' && state === 'paid') text = '已打款'
      else if (key === 'status' && panel === 'media' && state === 'done') text = '已就绪'
      else text = labels[state] || state
    }
    else return []
    return [[names[key], text] as [string, string]]
  })
}

/** 精确解析以元填写的金额；只有净到账允许负数，所有场景拒绝指数及额外小数。 */
export function appAmountFen(value: FormDataEntryValue | null, allowZero = true, allowNegative = false): number {
  const text = String(value ?? '').trim()
  if (!(allowNegative ? /^-?\d+(?:\.\d{1,2})?$/ : /^\d+(?:\.\d{1,2})?$/).test(text)) throw new Error(allowNegative ? '金额须为数字，最多保留两位小数。' : '金额须为非负数字，最多保留两位小数。')
  const [whole, decimal = ''] = text.replace(/^-/, '').split('.')
  const fen = (Number(whole) * 100 + Number(decimal.padEnd(2, '0'))) * (text.startsWith('-') ? -1 : 1)
  if (!Number.isSafeInteger(fen) || (!allowZero && fen <= 0)) throw new Error('请填写有效金额。')
  return fen
}

/** 财务记录关联服务端编号，不能用逗号分隔的任意字符串代替。 */
export function appRecordIds(value: FormDataEntryValue | null): number[] {
  const values = String(value ?? '').trim().split(/[\s,，]+/).filter(Boolean)
  if (!values.length || values.some(value => !/^[1-9]\d*$/.test(value) || !Number.isSafeInteger(Number(value)))) throw new Error('请填写有效记录编号，多个编号用逗号分隔。')
  const ids = values.map(Number)
  if (new Set(ids).size !== ids.length) throw new Error('记录编号不能重复。')
  return ids
}
