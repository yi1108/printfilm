import type { Edge } from '@xyflow/react'
import type { StudioNodeRecord } from './nodeOperations.ts'

export const storySection = (node: StudioNodeRecord): string | undefined => {
  if (node.type === 'script') return '剧本'
  const kind = String(node.data.storyKind || node.type)
  if (['character', 'character_prompt'].includes(kind)) return '人物'
  if (['scene', 'scene_prompt'].includes(kind)) return '场景'
  if (['shot_prompt', 'shot_video', 'shot_reference', 'shot', 'shot_outline'].includes(kind) || node.type === 'storyboard') return '分镜'
  return undefined
}
export const sectionKind: Record<string, string> = { 剧本: 'script_group', 人物: 'character_group', 场景: 'scene_group', 分镜: 'shot_video_group' }

const numberOf = (value: string) => {
  if (/^\d+$/.test(value)) return Number(value)
  const digits = '零一二三四五六七八九', normalized = value.replace(/两/g, '二')
  let total = 0, current = 0
  for (const char of normalized) {
    const unit = ({ 十: 10, 百: 100, 千: 1000 } as Record<string, number>)[char]
    if (unit) { total += (current || 1) * unit; current = 0 }
    else { const digit = digits.indexOf(char); if (digit < 0) return -1; current = digit }
  }
  return total + current
}

export function episodeOf(node: StudioNodeRecord, byId: Map<string, StudioNodeRecord>): { key: string; label: string; number?: number } {
  const chain: StudioNodeRecord[] = [], seen = new Set<string>()
  let current: StudioNodeRecord | undefined = node
  while (current && !seen.has(current.id)) { chain.push(current); seen.add(current.id); current = current.parentId ? byId.get(current.parentId) : undefined }
  const script = byId.get(String(node.data.sourceScriptId || ''))
  if (script && !seen.has(script.id)) chain.push(script)
  // Explicit metadata takes precedence over numbers mentioned in shot titles.
  for (const item of chain) {
    const data = item.data, number = Number(data.episodeNumber ?? data.episode_number)
    if (Number.isInteger(number) && number > 0) return { key: `episode-${number}`, label: `第${number}集`, number }
    const id = data.episodeId ?? data.episode_id
    if (id !== undefined && id !== null && id !== '') return { key: `episode-id-${id}`, label: String(data.episodeTitle || data.episodeName || `分集 ${id}`) }
    if (data.episodeKey) return { key: String(data.episodeKey), label: String(data.episodeLabel || data.episodeTitle || data.episodeKey) }
  }
  for (const item of chain) {
    const match = String(item.data.label || '').match(/第\s*([零一二三四五六七八九十百两\d]+)\s*集/)
    if (match) { const number = numberOf(match[1]); return { key: `episode-${number > 0 ? number : match[1]}`, label: match[0], ...(number > 0 ? { number } : {}) } }
  }
  return { key: '', label: '' }
}

/** Each writing/output pair shares a row; long lists continue in adjacent lanes. */
export function layoutStoryPairs(ids: string[], byId: Map<string, StudioNodeRecord>, edges: Edge[], size: (node: StudioNodeRecord) => { width: number; height: number }) {
  const compare = (a: string, b: string) => Number(byId.get(a)!.data.shotIndex || 0) - Number(byId.get(b)!.data.shotIndex || 0) || String(byId.get(a)!.data.label || a).localeCompare(String(byId.get(b)!.data.label || b), 'zh-CN', { numeric: true }) || a.localeCompare(b)
  const remaining = new Set(ids), rows: string[][] = []
  const media = ids.filter((id) => !['text', 'script', 'storyboard'].includes(byId.get(id)!.type || '')).sort(compare)
  for (const id of media) {
    if (!remaining.delete(id)) continue
    const node = byId.get(id)!
    const writer = ids.find((candidate) => remaining.has(candidate) && candidate === node.data.promptNodeId)
      || ids.find((candidate) => remaining.has(candidate) && byId.get(candidate)!.data.outputNodeId === id)
      || ids.filter((candidate) => remaining.has(candidate) && byId.get(candidate)!.type === 'text' && edges.some((edge) => edge.source === candidate && edge.target === id)).sort(compare)[0]
    if (writer) remaining.delete(writer)
    rows.push(writer ? [writer, id] : [id])
  }
  rows.push(...[...remaining].sort(compare).map((id) => [id]))
  rows.sort((a, b) => compare(a[a.length - 1], b[b.length - 1]))
  const positions = new Map<string, { x: number; y: number }>(), order: string[] = []
  let x = 32, height = 240
  for (let start = 0; start < rows.length; start += 8) {
    const lane = rows.slice(start, start + 8)
    const leftWidth = Math.max(...lane.map((row) => size(byId.get(row[0])!).width))
    const rightWidth = Math.max(0, ...lane.map((row) => row[1] ? size(byId.get(row[1])!).width : 0))
    let y = 72
    for (const row of lane) {
      const rowHeight = Math.max(...row.map((id) => size(byId.get(id)!).height))
      row.forEach((id, index) => { positions.set(id, { x: x + (index ? leftWidth + 96 : 0), y }); order.push(id) })
      y += rowHeight + 72
    }
    height = Math.max(height, y - 40)
    x += leftWidth + (rightWidth ? rightWidth + 96 : 0) + 112
  }
  return { positions, order, width: Math.max(360, x - 80), height }
}
