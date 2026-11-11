export type CropRect = { x: number; y: number; width: number; height: number }
export type CropHandle = 'move' | 'n' | 's' | 'e' | 'w' | 'ne' | 'nw' | 'se' | 'sw'
const clamp = (value: number, min: number, max: number) => Math.max(min, Math.min(max, value))
export function centeredCrop(width: number, height: number, ratio?: number): CropRect {
  const w = ratio ? Math.min(width, height * ratio) : width
  const h = ratio ? w / ratio : height
  return { x: (width - w) / 2, y: (height - h) / 2, width: w, height: h }
}
export function dragCrop(start: CropRect, handle: CropHandle, dx: number, dy: number, bounds: { width: number; height: number }, ratio?: number): CropRect {
  if (handle === 'move') return { ...start, x: clamp(start.x + dx, 0, bounds.width - start.width), y: clamp(start.y + dy, 0, bounds.height - start.height) }
  const west = handle.includes('w'), north = handle.includes('n')
  const horizontal = west || handle.includes('e'), vertical = north || handle.includes('s')
  const anchorX = west ? start.x + start.width : start.x, anchorY = north ? start.y + start.height : start.y
  const maxW = west ? anchorX : bounds.width - anchorX, maxH = north ? anchorY : bounds.height - anchorY
  let width = clamp(start.width + (horizontal ? dx * (west ? -1 : 1) : 0), Math.min(16, maxW), maxW)
  let height = clamp(start.height + (vertical ? dy * (north ? -1 : 1) : 0), Math.min(16, maxH), maxH)
  if (ratio) {
    if (!horizontal || vertical && Math.abs(dy * ratio) > Math.abs(dx)) width = height * ratio
    width = Math.min(width, maxW, maxH * ratio); height = width / ratio
  }
  return { x: west ? anchorX - width : anchorX, y: north ? anchorY - height : anchorY, width, height }
}
