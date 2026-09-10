import { useEffect, useId, useRef, useState } from 'react'
import { ChevronDown } from 'lucide-react'
import { cn } from '../../lib/cn'

export type FilterOption = {
  value: string
  label: string
}

type Props = {
  label?: string
  options: FilterOption[]
  value: string
  onChange: (value: string) => void
  className?: string
  disabled?: boolean
}

/** 品牌风格自定义下拉，避免原生 option 的蓝色高亮 */
export default function FilterSelect({
  label,
  options,
  value,
  onChange,
  className,
  disabled,
}: Props) {
  const [open, setOpen] = useState(false)
  const rootRef = useRef<HTMLDivElement>(null)
  const listId = useId()
  const current = options.find((opt) => opt.value === value) || options[0]

  useEffect(() => {
    if (!open) return
    const onPointer = (e: MouseEvent) => {
      if (!rootRef.current?.contains(e.target as Node)) setOpen(false)
    }
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setOpen(false)
    }
    window.addEventListener('mousedown', onPointer)
    window.addEventListener('keydown', onKey)
    return () => {
      window.removeEventListener('mousedown', onPointer)
      window.removeEventListener('keydown', onKey)
    }
  }, [open])

  return (
    <div className={cn('pf-filter-select', open && 'is-open', className)} ref={rootRef}>
      {label ? <span className="sr-only">{label}</span> : null}
      <button
        type="button"
        className="pf-filter-trigger"
        aria-label={label}
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-controls={listId}
        disabled={disabled}
        onClick={() => setOpen((v) => !v)}
      >
        <span className="pf-filter-trigger-label">{current?.label || '请选择'}</span>
        <ChevronDown size={15} strokeWidth={2} className="pf-filter-chevron" aria-hidden />
      </button>
      {open ? (
        <ul id={listId} className="pf-filter-menu" role="listbox" aria-label={label}>
          {options.map((opt) => {
            const selected = opt.value === value
            return (
              <li key={opt.value || 'all'} role="none">
                <button
                  type="button"
                  role="option"
                  aria-selected={selected}
                  className={cn('pf-filter-option', selected && 'is-selected')}
                  onClick={() => {
                    onChange(opt.value)
                    setOpen(false)
                  }}
                >
                  {opt.label}
                </button>
              </li>
            )
          })}
        </ul>
      ) : null}
    </div>
  )
}
