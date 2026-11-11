import type { CSSProperties } from 'react'
import { pointText } from '../../lib/points'
import { useI18n } from '../../i18n'
import { Link } from 'react-router-dom'
import { isBillingError, billingPointsMessage, PRICING_PATH } from '../../lib/billingError'
import { workspaceScope } from '../../features/teams/workspaceScope'
import { formatCopyrightError, formatGenerationErrorMessage } from '../../lib/generationError'

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
  linkText,
  inline = false,
}: Props) {
  useI18n()
  const text = String(message || '').trim()
  if (!text) return null
  const Tag = inline ? 'span' : 'p'
  if (formatCopyrightError(text) || !isBillingError(text)) {
    return (
      <Tag className={className} style={style} role={inline ? undefined : 'alert'}>
        {formatGenerationErrorMessage(text)}
      </Tag>
    )
  }
  return (
    <Tag className={className} style={style} role={inline ? undefined : 'alert'}>
      {billingPointsMessage(text)}{' '}
      <Link to={workspaceScope.teamId === null ? PRICING_PATH : `/teams/${workspaceScope.teamId}?tab=billing`} className="pf-link pf-billing-topup-link">
        {workspaceScope.teamId === null ? (linkText || pointText('去充值 →', 'Top up →')) : pointText('查看团队用量 →', 'View team usage →')}
      </Link>
    </Tag>
  )
}
