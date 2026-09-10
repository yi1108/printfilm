/**
 * 短剧剪辑节奏公式（社区 Skill 六式，用于分镜时长建议 / 整集导出规划）
 * 对齐 docs/EPISODE_RULES.md §10 P3
 */

export type DramaEditRhythmId =
  | 'breath'
  | 'heartbeat'
  | 'wave'
  | 'elastic'
  | 'pulse'
  | 'silence_hammer'

export type DramaEditRhythmPreset = {
  id: DramaEditRhythmId
  label: string
  hint: string
  /** 相对节拍权重，会归一化到目标总秒数 */
  weights: number[]
}

export const DRAMA_EDIT_RHYTHM_PRESETS: DramaEditRhythmPreset[] = [
  {
    id: 'breath',
    label: '呼吸式',
    hint: '缓入—展开—回落，适合建立与抒情',
    weights: [3, 5, 4, 3],
  },
  {
    id: 'heartbeat',
    label: '心跳式',
    hint: '短促加速，适合冲突与对峙',
    weights: [2, 2, 3, 2, 4],
  },
  {
    id: 'wave',
    label: '海浪式',
    hint: '层层推高再泄力，适合高潮戏',
    weights: [3, 4, 5, 6, 3],
  },
  {
    id: 'elastic',
    label: '弹性时间',
    hint: '关键动作拉长，其余压缩',
    weights: [2, 6, 2, 3],
  },
  {
    id: 'pulse',
    label: '脉冲式',
    hint: '规律跳动，适合卡点与群像',
    weights: [3, 3, 3, 3],
  },
  {
    id: 'silence_hammer',
    label: '静默锤击',
    hint: '蓄势静场后猛切，适合反转',
    weights: [5, 2, 6],
  },
]

const SEGMENT_MIN = 3
const SEGMENT_MAX = 12

// 按节奏公式为 N 段分配秒数（钳制 3–12，合计贴近 targetTotal）
export function suggestRhythmDurations(
  segmentCount: number,
  rhythmId: DramaEditRhythmId,
  targetTotal = 15,
): number[] {
  const count = Math.max(1, Math.floor(segmentCount))
  const preset =
    DRAMA_EDIT_RHYTHM_PRESETS.find((p) => p.id === rhythmId) || DRAMA_EDIT_RHYTHM_PRESETS[0]
  const weights: number[] = []
  for (let i = 0; i < count; i++) {
    weights.push(preset.weights[i % preset.weights.length] || 3)
  }
  const sumW = weights.reduce((a, b) => a + b, 0) || 1
  const raw = weights.map((w) => (w / sumW) * Math.max(SEGMENT_MIN * count, targetTotal))
  const clamped = raw.map((v) => Math.max(SEGMENT_MIN, Math.min(SEGMENT_MAX, Math.round(v))))
  // 微调合计：过短则从最大段加，过长则从最大段减
  let total = clamped.reduce((a, b) => a + b, 0)
  const goal = Math.max(SEGMENT_MIN * count, Math.min(30, Math.round(targetTotal)))
  let guard = 0
  while (total < goal && guard < 40) {
    const idx = clamped.indexOf(Math.max(...clamped))
    if (clamped[idx] < SEGMENT_MAX) {
      clamped[idx] += 1
      total += 1
    } else break
    guard += 1
  }
  while (total > goal && guard < 80) {
    const idx = clamped.indexOf(Math.max(...clamped))
    if (clamped[idx] > SEGMENT_MIN) {
      clamped[idx] -= 1
      total -= 1
    } else break
    guard += 1
  }
  return clamped
}

// 整集导出规划：为每镜建议时长（D-2 / 已有分镜条数）
export function suggestEpisodeFragmentDurations(
  fragmentCount: number,
  rhythmId: DramaEditRhythmId,
  /** 单镜目标时长均值 */
  perFragmentTarget = 10,
): number[] {
  const count = Math.max(1, Math.floor(fragmentCount))
  const total = Math.min(30 * count, Math.max(4 * count, perFragmentTarget * count))
  return suggestRhythmDurations(count, rhythmId, total).map((sec) =>
    Math.max(4, Math.min(30, sec)),
  )
}
