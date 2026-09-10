import type { ButtonHTMLAttributes, ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { cn } from '../../lib/cn'

export type ButtonVariant = 'lime' | 'dark' | 'ghost' | 'outline' | 'text'
export type ButtonSize = 'sm' | 'md' | 'lg'

type CommonProps = {
  children: ReactNode
  variant?: ButtonVariant
  size?: ButtonSize
  icon?: boolean
  block?: boolean
  className?: string
}

type ButtonAsButton = CommonProps &
  Omit<ButtonHTMLAttributes<HTMLButtonElement>, 'className'> & {
    to?: undefined
  }

type ButtonAsLink = CommonProps & {
  to: string
  disabled?: boolean
  type?: never
  onClick?: () => void
}

type Props = ButtonAsButton | ButtonAsLink

// 组装按钮 class
function buttonClass(props: {
  variant: ButtonVariant
  size: ButtonSize
  icon?: boolean
  block?: boolean
  className?: string
}) {
  return cn(
    'pf-btn',
    `pf-btn-${props.variant}`,
    props.size === 'sm' && 'pf-btn-sm',
    props.size === 'lg' && 'pf-btn-lg',
    props.icon && 'pf-btn-icon',
    props.block && 'pf-btn-block',
    props.className,
  )
}

/** PRINTFILM 统一按钮：lime / dark / ghost / outline / text；可作 Link */
export default function Button(props: Props) {
  const {
    children,
    variant = 'ghost',
    size = 'md',
    icon,
    block,
    className,
    ...rest
  } = props

  const cls = buttonClass({ variant, size, icon, block, className })

  if ('to' in props && props.to) {
    const { to, disabled, onClick } = props
    if (disabled) {
      return (
        <span className={cn(cls, 'is-disabled')} aria-disabled="true">
          {children}
        </span>
      )
    }
    return (
      <Link to={to} className={cls} onClick={onClick}>
        {children}
      </Link>
    )
  }

  const buttonProps = rest as ButtonHTMLAttributes<HTMLButtonElement>
  return (
    <button type={buttonProps.type || 'button'} className={cls} {...buttonProps}>
      {children}
    </button>
  )
}
