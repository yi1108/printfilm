import { cn } from '../../lib/cn'

export type PillOption<T extends string = string> = {
  value: T
  label: string
}

type Props<T extends string> = {
  options: PillOption<T>[]
  value: T
  onChange: (value: T) => void
  ariaLabel?: string
  className?: string
}

/** 统一胶囊筛选（分类 Tab） */
export default function PillFilter<T extends string>({
  options,
  value,
  onChange,
  ariaLabel,
  className,
}: Props<T>) {
  return (
    <div className={cn('pf-pill-row', className)} role="tablist" aria-label={ariaLabel}>
      {options.map((opt) => (
        <button
          key={opt.value}
          type="button"
          role="tab"
          className={cn('pf-pill lime', value === opt.value && 'active')}
          aria-selected={value === opt.value}
          onClick={() => onChange(opt.value)}
        >
          {opt.label}
        </button>
      ))}
    </div>
  )
}
