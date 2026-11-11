/** Match Toonflow's default canvas bindings without intercepting editors or Agent. */
export function canvasShortcut(event: Pick<KeyboardEvent, 'key' | 'ctrlKey' | 'metaKey' | 'altKey' | 'shiftKey' | 'isComposing' | 'repeat'>): string | undefined {
  if (event.isComposing || event.repeat) return
  const key = event.key.toLowerCase(), primary = event.ctrlKey || event.metaKey
  if (key === 'escape') return 'escape'
  if (primary || event.altKey) {
    if (key === 'g') return event.shiftKey ? 'ungroup' : primary && event.altKey ? 'mergeGroup' : 'group'
    if (event.altKey) return !primary && event.shiftKey && key === 'f' ? 'arrange' : undefined
    if (key === 'z') return event.shiftKey ? 'redo' : 'undo'
    if (key === '=' || key === '+') return 'zoomIn'
    if (key === '-') return 'zoomOut'
    if (event.shiftKey) return
    return ({ c: 'copy', x: 'cut', v: 'paste', d: 'duplicate', y: 'redo', f: 'search', a: 'selectAll', '0': 'fitView', s: 'save' } as Record<string, string>)[key]
  }
  if (event.shiftKey) return key === 'f' ? 'search' : undefined
  return ({ v: 'select', h: 'hand', ' ': 'pan', tab: 'add', delete: 'remove', backspace: 'remove' } as Record<string, string>)[key]
}

export function isCanvasKeyboardTarget(target: EventTarget | null): boolean {
  if (!(target instanceof Element)) return false
  if (target.closest('input,textarea,select,button,a,video,audio,[contenteditable]:not([contenteditable="false"]),[role="textbox"],[role="slider"],[role="dialog"],[role="menu"],.pf-agent-panel,.pf-agent-float,.pf-add-menu,.pf-context-menu')) return false
  return target === document.body || target === document.documentElement || !!target.closest('.pf-flow-area')
}
