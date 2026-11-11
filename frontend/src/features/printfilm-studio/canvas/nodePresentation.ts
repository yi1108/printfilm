/** Source nodeScaffold metrics, independent of whether the prompt panel is open. */
export function mediaNodeWidth(kind: string, naturalWidth = 0, naturalHeight = 0): number {
  if (kind === 'text' || kind === 'script') return 360
  if (kind === 'audio') return 300
  if (naturalWidth > 0 && naturalHeight > 0) return Math.max(160, Math.min(800, 240 * naturalWidth / naturalHeight + 18))
  return 220
}

export function imageNodeSize(naturalWidth: number, naturalHeight: number, preferredWidth?: number, variants = 1) {
  const width = Math.max(160, Math.min(800, preferredWidth || mediaNodeWidth('image', naturalWidth, naturalHeight)))
  return { width, height: Math.round((width - 18) * naturalHeight / Math.max(1, naturalWidth) + 46 + (variants > 1 ? 52 : 0)) }
}

export function showNodePanels(selected: boolean, selectionCount: number, dragging: boolean, suppressed: boolean): boolean {
  return selected && selectionCount <= 1 && !dragging && !suppressed
}

export function cleanNodeTitle(value: string, previous: string): string {
  return value.trim().slice(0, 200) || previous
}
