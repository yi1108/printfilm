export type TourRect = { left: number; top: number; width: number; height: number }

export function tourLayout(target: TourRect | null, viewport: { width: number; height: number }, cardHeight = 250) {
  const margin = 12, gap = 16
  const width = Math.max(0, Math.min(340, viewport.width - margin * 2))
  const height = Math.min(cardHeight, viewport.height - margin * 2)
  const clamp = (value: number, max: number) => Math.max(margin, Math.min(value, max - margin))
  let focus: TourRect | null = null
  if (target && target.width > 0 && target.height > 0) {
    const left = Math.max(4, target.left - 7), top = Math.max(4, target.top - 7)
    const right = Math.min(viewport.width - 4, target.left + target.width + 7)
    const bottom = Math.min(viewport.height - 4, target.top + target.height + 7)
    if (right > left && bottom > top) focus = { left, top, width: right - left, height: bottom - top }
  }
  const centered = { left: (viewport.width - width) / 2, top: (viewport.height - height) / 2 }
  const positions = focus ? [
    { left: focus.left, top: focus.top + focus.height + gap },
    { left: focus.left, top: focus.top - height - gap },
    { left: focus.left - width - gap, top: focus.top },
    { left: focus.left + focus.width + gap, top: focus.top },
  ] : []
  const fits = positions.find(p => p.left >= margin && p.top >= margin && p.left + width <= viewport.width - margin && p.top + height <= viewport.height - margin)
  const position = fits || (focus ? { left: focus.left, top: focus.top > viewport.height / 2 ? focus.top - height - gap : focus.top + focus.height + gap } : centered)
  return { focus, card: { left: clamp(position.left, viewport.width - width), top: clamp(position.top, viewport.height - height), width } }
}
