import type { CSSProperties } from 'react'
import { Link } from 'react-router-dom'
import { isBillingError, PRICING_PATH } from '../../lib/billingError'

type Props = {
  message: string | null | undefined
  className?: string
  style?: CSSProperties
  /** 内联链接文案 */
  linkText?: string
  /** 使用 span 而非 p（工具栏条内联错误） */
  inline?: boolean
}

/** 错误提示：余额不足时附带快速跳转充值链接 */
export default function BillingErrorNotice({
  message,
  className = 'pf-error',
  style,
  linkText = '去充值 →',
  inline = false,
}: Props) {
  const text = String(message || '').trim()
  if (!text) return null
  const Tag = inline ? 'span' : 'p'
  if (!isBillingError(text)) {
    return (
      <Tag className={className} style={style} role={inline ? undefined : 'alert'}>
        {text}
      </Tag>
    )
  }
  return (
    <Tag className={className} style={style} role={inline ? undefined : 'alert'}>
      {text}{' '}
      <Link to={PRICING_PATH} className="pf-link pf-billing-topup-link">
        {linkText}
      </Link>
    </Tag>
  )
}
