/** 漫剧视频输出规格（画幅 / 清晰度）：分集 params 优先，可回退 project.params */
export const DRAMA_RATIO_OPTIONS = ['9:16', '16:9', '1:1'] as const
export const DRAMA_RES_OPTIONS = ['480p', '720p', '1080p'] as const

export type DramaAspectRatio = (typeof DRAMA_RATIO_OPTIONS)[number]
export type DramaResolution = (typeof DRAMA_RES_OPTIONS)[number]

// 从 project.params 读取画幅，非法值回退 9:16
export function readProjectAspectRatio(
  params: Record<string, unknown> | null | undefined,
): DramaAspectRatio {
  const ratio = String(params?.aspect_ratio || '').trim()
  if ((DRAMA_RATIO_OPTIONS as readonly string[]).includes(ratio)) {
    return ratio as DramaAspectRatio
  }
  return '9:16'
}

// 从 project.params 读取清晰度，非法值回退 480p
export function readProjectResolution(
  params: Record<string, unknown> | null | undefined,
): DramaResolution {
  const res = String(params?.resolution || '').trim()
  if ((DRAMA_RES_OPTIONS as readonly string[]).includes(res)) {
    return res as DramaResolution
  }
  return '480p'
}

// 从多层 params 中取第一个合法画幅
export function pickDramaAspectRatio(
  ...sources: Array<Record<string, unknown> | null | undefined>
): DramaAspectRatio {
  for (const params of sources) {
    const ratio = String(params?.aspect_ratio || '').trim()
    if ((DRAMA_RATIO_OPTIONS as readonly string[]).includes(ratio)) {
      return ratio as DramaAspectRatio
    }
  }
  return '9:16'
}

// 从多层 params 中取第一个合法清晰度
export function pickDramaResolution(
  ...sources: Array<Record<string, unknown> | null | undefined>
): DramaResolution {
  for (const params of sources) {
    const res = String(params?.resolution || '').trim()
    if ((DRAMA_RES_OPTIONS as readonly string[]).includes(res)) {
      return res as DramaResolution
    }
  }
  return '480p'
}

// 分集画幅：episode.params → project.params → 默认
export function readEpisodeAspectRatio(
  episodeParams: Record<string, unknown> | null | undefined,
  projectParams?: Record<string, unknown> | null | undefined,
): DramaAspectRatio {
  return pickDramaAspectRatio(episodeParams, projectParams)
}

// 分集清晰度：episode.params → project.params → 默认
export function readEpisodeResolution(
  episodeParams: Record<string, unknown> | null | undefined,
  projectParams?: Record<string, unknown> | null | undefined,
): DramaResolution {
  return pickDramaResolution(episodeParams, projectParams)
}

// 分镜规格：本镜生成时写入的 params → 分集 → 项目
export function readFragmentVideoDimensions(
  fragmentParams: Record<string, unknown> | null | undefined,
): { w: number; h: number } | null {
  const gen = fragmentParams?.generation
  const genObj =
    gen && typeof gen === 'object' && !Array.isArray(gen)
      ? (gen as Record<string, unknown>)
      : null
  const w = Number(fragmentParams?.video_width ?? genObj?.video_width)
  const h = Number(fragmentParams?.video_height ?? genObj?.video_height)
  if (Number.isFinite(w) && Number.isFinite(h) && w > 0 && h > 0) {
    return { w: Math.round(w), h: Math.round(h) }
  }
  return null
}

// 根据像素推断标准画幅；非标准时返回「宽×高」
export function inferAspectRatioFromPixels(width: number, height: number): string {
  if (width <= 0 || height <= 0) return '9:16'
  const ratio = width / height
  const candidates: Array<[string, number]> = [
    ['9:16', 9 / 16],
    ['16:9', 16 / 9],
    ['1:1', 1],
  ]
  let best = candidates[0]
  let bestDiff = Math.abs(ratio - best[1])
  for (const item of candidates.slice(1)) {
    const diff = Math.abs(ratio - item[1])
    if (diff < bestDiff) {
      best = item
      bestDiff = diff
    }
  }
  if (bestDiff <= 0.08) return best[0]
  return `${width}×${height}`
}

export function readFragmentOutputLabel(
  fragmentParams: Record<string, unknown> | null | undefined,
  episodeParams?: Record<string, unknown> | null | undefined,
  projectParams?: Record<string, unknown> | null | undefined,
): string {
  const resolution = pickDramaResolution(fragmentParams, episodeParams, projectParams)
  const dims = readFragmentVideoDimensions(fragmentParams)
  if (dims) {
    return formatProjectOutputLabel(inferAspectRatioFromPixels(dims.w, dims.h), resolution)
  }
  return formatProjectOutputLabel(
    pickDramaAspectRatio(fragmentParams, episodeParams, projectParams),
    resolution,
  )
}

// 格式化顶栏展示文案
export function formatProjectOutputLabel(aspectRatio: string, resolution: string): string {
  return `${aspectRatio} · ${resolution}`
}
