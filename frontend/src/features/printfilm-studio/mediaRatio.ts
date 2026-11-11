/** Explicit user choices win; missing/automatic ratios use the workspace defaults. */
export function studioMediaRatio(kind: 'image' | 'video', value?: unknown): string {
  const ratio = typeof value === 'string' ? value.trim() : ''
  return ratio && ratio !== 'auto' ? ratio : kind === 'video' ? '16:9' : '2:3'
}
