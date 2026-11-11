import { useEffect, useRef, useState, type PointerEvent, type KeyboardEvent } from 'react'
import { clampPanel, initialPanel, movePanel, type PanelInteraction, type PanelRect } from './panelGeometry'

const viewport = () => ({ width: window.innerWidth, height: window.innerHeight })
const storageKey = 'printfilm-studio:agent-panel'
function restore() {
  try {
    const saved = JSON.parse(localStorage.getItem(storageKey) || 'null')
    if (saved && ['left', 'top', 'width', 'height'].every((key) => typeof saved.rect?.[key] === 'number' && Number.isFinite(saved.rect[key]))) return { docked: saved.docked === true, rect: clampPanel(saved.rect, viewport(), false) }
  } catch { /* Storage is optional in privacy mode. */ }
  return { docked: false, rect: initialPanel(viewport()) }
}

export function useAgentPanel(onDockWidth: (width: number) => void) {
  const [layout, setLayout] = useState(restore)
  const [screen, setScreen] = useState(viewport)
  const active = useRef<{ mode: PanelInteraction; rect: PanelRect; x: number; y: number; pointerId: number; element: HTMLElement } | null>(null)
  const rect = clampPanel(layout.rect, screen, layout.docked)
  useEffect(() => { onDockWidth(layout.docked ? rect.width : 0); return () => onDockWidth(0) }, [layout.docked, rect.width, onDockWidth])
  useEffect(() => { try { localStorage.setItem(storageKey, JSON.stringify(layout)) } catch { /* no storage */ } }, [layout])
  useEffect(() => {
    const resize = () => { active.current = null; setScreen(viewport()) }
    window.addEventListener('resize', resize)
    return () => window.removeEventListener('resize', resize)
  }, [])
  const stop = (event: PointerEvent<HTMLElement>) => {
    const current = active.current
    if (!current || current.pointerId !== event.pointerId) return
    active.current = null
    if (current.element.hasPointerCapture(event.pointerId)) current.element.releasePointerCapture(event.pointerId)
  }
  return {
    rect, docked: layout.docked,
    toggleDock: () => setLayout((value) => ({ ...value, docked: !value.docked })),
    start: (event: PointerEvent<HTMLElement>, mode: PanelInteraction) => {
      if (event.button !== 0 || (layout.docked && mode !== 'left') || (mode === 'move' && (event.target as HTMLElement).closest('button, input, select, textarea, a'))) return
      event.preventDefault(); event.currentTarget.setPointerCapture(event.pointerId)
      active.current = { mode, rect, x: event.clientX, y: event.clientY, pointerId: event.pointerId, element: event.currentTarget }
    },
    keyboard: (event: KeyboardEvent<HTMLElement>, mode: PanelInteraction) => {
      if (!['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown'].includes(event.key)) return
      event.preventDefault()
      const delta = event.key === 'ArrowLeft' || event.key === 'ArrowUp' ? -16 : 16
      setLayout((value) => ({ ...value, rect: movePanel(rect, mode, mode === 'bottom' ? 0 : delta, mode === 'bottom' ? delta : 0, screen, value.docked) }))
    },
    handlers: {
      onPointerMove: (event: PointerEvent<HTMLElement>) => {
        const current = active.current
        if (!current || current.pointerId !== event.pointerId) return
        setLayout((value) => ({ ...value, rect: movePanel(current.rect, current.mode, event.clientX - current.x, event.clientY - current.y, screen, value.docked) }))
      },
      onPointerUp: stop, onPointerCancel: stop, onLostPointerCapture: stop,
    },
  }
}
