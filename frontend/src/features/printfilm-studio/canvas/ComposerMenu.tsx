import { useEffect, useLayoutEffect, useRef, useState, type ReactNode } from 'react'
import { createPortal } from 'react-dom'
import { Check, ChevronDown } from 'lucide-react'

/** Portal keeps the menu readable and outside the canvas transform/clipping. */
export function ComposerMenu({ label, value, children, wide = false, disabled = false, className = '', menuClassName = '', matchWidth = false }: { label: string; value: ReactNode; children: (close: () => void) => ReactNode; wide?: boolean; disabled?: boolean; className?: string; menuClassName?: string; matchWidth?: boolean }) {
  const [open, setOpen] = useState(false)
  const [position, setPosition] = useState<{left:number;top:number;width?:number}>({ left: 0, top: 0 })
  const trigger = useRef<HTMLButtonElement>(null)
  const panel = useRef<HTMLDivElement>(null)
  const close = () => { setOpen(false); trigger.current?.focus() }
  useLayoutEffect(() => {
    if (!open) return
    const place = () => {
      const rect = trigger.current?.getBoundingClientRect()
      if (!rect) return
      const width = Math.min(matchWidth ? Math.max(300, rect.width) : wide ? 340 : 260, window.innerWidth - 24)
      const height = panel.current?.offsetHeight || 280
      setPosition({ width, left: Math.max(12, Math.min(rect.left, window.innerWidth - width - 12)), top: rect.bottom + height + 10 < window.innerHeight ? rect.bottom + 8 : Math.max(12, rect.top - height - 8) })
    }
    place()
    window.addEventListener('resize', place)
    window.addEventListener('scroll', place, true)
    return () => { window.removeEventListener('resize', place); window.removeEventListener('scroll', place, true) }
  }, [open, wide, matchWidth])
  useEffect(() => {
    if (!open) return
    panel.current?.querySelector<HTMLElement>('[aria-checked="true"],button:not(:disabled)')?.focus()
    const dismiss = (event: PointerEvent) => { if (!panel.current?.contains(event.target as Node) && !trigger.current?.contains(event.target as Node)) setOpen(false) }
    document.addEventListener('pointerdown', dismiss)
    return () => document.removeEventListener('pointerdown', dismiss)
  }, [open])
  return <span className={`pf-composer-menu-anchor ${className}`}>
    <button ref={trigger} type="button" disabled={disabled} className="pf-composer-param" aria-label={label} aria-haspopup="dialog" aria-expanded={open} onClick={() => setOpen(!open)}>{value}<ChevronDown size={14} /></button>
    {open && createPortal(<div ref={panel} role="dialog" aria-label={`${label}选项`} className={`pf-composer-popover${wide ? ' is-wide' : ''} ${menuClassName}`} style={position} onMouseDown={(event) => event.stopPropagation()} onClick={(event) => event.stopPropagation()} onKeyDown={(event) => {
      event.stopPropagation()
      if (event.key === 'Escape') { event.preventDefault(); close() }
      if (['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(event.key)) {
        event.preventDefault()
        const items = [...(panel.current?.querySelectorAll<HTMLButtonElement>('button:not(:disabled)') || [])]
        const index = items.indexOf(document.activeElement as HTMLButtonElement)
        items[event.key === 'Home' ? 0 : event.key === 'End' ? items.length - 1 : (index + (event.key === 'ArrowDown' ? 1 : -1) + items.length) % items.length]?.focus()
      }
    }}>{children(close)}</div>, trigger.current?.closest('dialog') || document.body)}
  </span>
}

export function ComposerSelect({ label, value, options, onChange }: { label: string; value: string; options: { id: string; label: string; disabled?: boolean; hint?: string }[]; onChange: (value: string) => void }) {
  return <ComposerMenu label={label} value={options.find((item) => item.id === value)?.label || value || '默认模型'}>{(close) => <div role="group" aria-label={label}>{options.map((item) => <button type="button" role="menuitemradio" aria-checked={item.id === value} disabled={item.disabled} key={item.id} onClick={() => { onChange(item.id); close() }}><span>{item.label}{item.hint && <small>{item.hint}</small>}</span>{item.id === value && <Check size={16} />}</button>)}</div>}</ComposerMenu>
}
