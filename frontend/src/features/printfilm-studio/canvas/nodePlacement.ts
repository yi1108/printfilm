type Point = { x: number; y: number }
type Rect = { left: number; top: number; width: number; height: number }
type Viewport = Point & { zoom: number }

/** Place new nodes in the visible workspace, independently of the menu's position. */
export function newNodePosition(
  canvas: Rect,
  visible: Rect,
  viewport: Viewport,
  size: { width: number; height: number },
  pointer?: Point,
  occupied: Rect[] = [],
): Point {
  const zoom = viewport.zoom > 0 ? viewport.zoom : 1
  const width = size.width * zoom, height = size.height * zoom
  const left = visible.left + Math.min(24, visible.width / 4)
  const top = visible.top + Math.min(80, visible.height / 4)
  const right = Math.max(left, visible.left + visible.width - width - 24)
  const bottom = Math.max(top, visible.top + visible.height - height - 80)
  let x = Math.max(left, Math.min(right, pointer?.x ?? visible.left + (visible.width - width) / 2))
  let y = Math.max(top, Math.min(bottom, pointer?.y ?? visible.top + (visible.height - height) / 2))
  if (!pointer && occupied.length) {
    const overlap = (cx: number, cy: number) => occupied.reduce((sum, rect) => sum + Math.max(0, Math.min(cx + width + 12, rect.left + rect.width) - Math.max(cx - 12, rect.left)) * Math.max(0, Math.min(cy + height + 24, rect.top + rect.height) - Math.max(cy - 24, rect.top)), 0)
    const preferred = { x, y }; let best = overlap(x, y), distance = 0
    for (let row = 0; row <= 8; row++) for (let col = 0; col <= 8; col++) {
      const cx = left + (right - left) * col / 8, cy = top + (bottom - top) * row / 8
      const score = overlap(cx, cy), delta = (cx - preferred.x) ** 2 + (cy - preferred.y) ** 2
      if (score < best || score === best && delta < distance) { x = cx; y = cy; best = score; distance = delta }
    }
  }
  return { x: (x - canvas.left - viewport.x) / zoom, y: (y - canvas.top - viewport.y) / zoom }
}

/** Keep the menu on screen without changing the original canvas insertion point. */
export function nodeMenuPosition(pointer: Point, screen: { width: number; height: number }) {
  return {
    left: Math.max(12, Math.min(pointer.x, screen.width - 264 - 12)),
    top: Math.max(12, Math.min(pointer.y, screen.height - Math.min(480, screen.height * .7) - 12)),
    position: pointer,
  }
}
