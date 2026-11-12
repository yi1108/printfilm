export type PanelRect = { left: number; top: number; width: number; height: number }
export type PanelViewport = { width: number; height: number }
export type PanelInteraction = 'move' | 'left' | 'right' | 'bottom'
const clamp = (value: number, min: number, max: number) => Math.max(min, Math.min(value, Math.max(min, max)))

export function clampPanel(rect: PanelRect, viewport: PanelViewport, docked: boolean): PanelRect {
  const gap = docked ? 0 : Math.min(15, viewport.width / 2, viewport.height / 2)
  const verticalGap = docked ? Math.min(20, viewport.height / 2) : gap
  const maxWidth = docked && viewport.width >= 720 ? viewport.width * .45 : viewport.width - gap * 2
  const width = clamp(rect.width, Math.min(320, maxWidth), maxWidth)
  const height = docked ? viewport.height - verticalGap * 2 : clamp(rect.height, Math.min(240, viewport.height - gap * 2), viewport.height - gap * 2)
  return { width, height, left: docked ? viewport.width - width : clamp(rect.left, gap, viewport.width - gap - width), top: docked ? verticalGap : clamp(rect.top, gap, viewport.height - gap - height) }
}

export function movePanel(rect: PanelRect, mode: PanelInteraction, dx: number, dy: number, viewport: PanelViewport, docked: boolean): PanelRect {
  if (docked && mode !== 'left') return clampPanel(rect, viewport, true)
  const gap = docked ? 0 : 15
  const right = rect.left + rect.width
  const next = { ...rect }
  if (mode === 'move') { next.left += dx; next.top += dy }
  if (mode === 'left') { next.width = clamp(rect.width - dx, Math.min(320, right - gap), right - gap); next.left = right - next.width }
  if (mode === 'right') next.width = clamp(rect.width + dx, Math.min(320, viewport.width - gap - rect.left), viewport.width - gap - rect.left)
  if (mode === 'bottom') next.height = clamp(rect.height + dy, Math.min(240, viewport.height - gap - rect.top), viewport.height - gap - rect.top)
  return clampPanel(next, viewport, docked)
}

export function initialPanel(viewport: PanelViewport): PanelRect {
  return clampPanel({ width: 500, height: viewport.height * .8, left: viewport.width - 515, top: viewport.height * .2 - 15 }, viewport, false)
}
