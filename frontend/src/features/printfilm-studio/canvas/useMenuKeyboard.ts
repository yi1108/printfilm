import { useEffect, useRef } from 'react'
import type { KeyboardEvent } from 'react'

function menuItems(menu: HTMLElement) {
  return [...menu.querySelectorAll<HTMLButtonElement>('button[role="menuitem"]:not(:disabled)')]
    .filter((item) => item.closest('[role="menu"]') === menu && item.getAttribute('aria-disabled') !== 'true' && !item.closest('[hidden], [aria-hidden="true"]'))
}

/** Keep keyboard navigation inside the menu's scroller, without moving the canvas. */
export function focusMenuItem(item: HTMLElement | undefined) {
  if (!item) return
  item.focus({ preventScroll: true })
  const scroller = item.closest<HTMLElement>('.pf-add-list, .pf-context-menu')
  if (!scroller) return
  const bounds = scroller.getBoundingClientRect()
  const itemBounds = item.getBoundingClientRect()
  if (itemBounds.top < bounds.top) scroller.scrollTop += itemBounds.top - bounds.top
  else if (itemBounds.bottom > bounds.bottom) scroller.scrollTop += itemBounds.bottom - bounds.bottom
}

/** Menus own their keyboard events, so deleting/typing cannot change the canvas behind them. */
export function useMenuKeyboard(onClose: () => void) {
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null
    const menu = ref.current
    if (!menu) return
    focusMenuItem(menuItems(menu)[0] || menu)
    return () => {
      const focused = document.activeElement
      // Clicking another input while a menu is open must not steal its focus back.
      if (focused !== document.body && focused && !menu.contains(focused)) return
      if (previous?.isConnected) previous.focus({ preventScroll: true })
      else document.querySelector<HTMLElement>('.react-flow__pane')?.focus({ preventScroll: true })
    }
  }, [])
  const onKeyDown = (event: KeyboardEvent<HTMLElement>) => {
    event.stopPropagation()
    if (event.key === 'Escape' || event.key === 'Tab') { event.preventDefault(); onClose(); return }
    const target = event.target as HTMLElement
    if (target.closest('input, textarea, select, [contenteditable="true"]')) return
    if (event.key === 'Enter' || event.key === ' ') {
      const button = target.closest<HTMLButtonElement>('button')
      if (button && !button.disabled && button.getAttribute('aria-disabled') !== 'true') {
        event.preventDefault()
        if (!event.repeat) button.click()
      }
      return
    }
    if (!['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(event.key)) return
    event.preventDefault()
    const menu = target.closest<HTMLElement>('[role="menu"]') || ref.current
    if (!menu) return
    const items = menuItems(menu)
    if (!items.length) return
    const current = items.indexOf(document.activeElement as HTMLButtonElement)
    const next = event.key === 'Home' ? 0 : event.key === 'End' ? items.length - 1
      : current < 0 ? event.key === 'ArrowDown' ? 0 : items.length - 1
        : (current + (event.key === 'ArrowDown' ? 1 : -1) + items.length) % items.length
    focusMenuItem(items[next])
  }
  return { ref, onKeyDown, tabIndex: -1 }
}
