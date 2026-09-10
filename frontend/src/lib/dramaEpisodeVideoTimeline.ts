/** 分集视频预览：跨分镜全局时间轴工具 */
import type { DramaFragment } from '../api/drama'

// DramaEpisodeVideoTimelineSegment 分集时间轴上的分镜区间
export type DramaEpisodeVideoTimelineSegment = {
  fragmentId: number
  index: number
  durationSec: number
  startSec: number
  endSec: number
  hasVideo: boolean
}

// 从分镜正文合计 @duration 秒数
function sumFragmentContentDuration(content: string): number {
  const re = /@duration:(\d+)/g
  let total = 0
  let m: RegExpExecArray | null
  while ((m = re.exec(content || ''))) {
    const sec = Number(m[1])
    if (sec > 0) total += sec
  }
  return total
}

// 解析分镜在时间轴上的时长（秒）
function resolveEpisodeFragmentTimelineDuration(fragment: DramaFragment): number {
  const fromTags = sumFragmentContentDuration(fragment.content)
  if (fromTags > 0) return Math.min(30, Math.max(4, fromTags))
  const fallback = fragment.duration_sec && fragment.duration_sec > 0 ? fragment.duration_sec : 8
  return Math.min(30, Math.max(4, fallback))
}

// 根据分集全部分镜构建时间轴分段
export function buildEpisodeVideoTimelineSegments(
  fragments: DramaFragment[],
): DramaEpisodeVideoTimelineSegment[] {
  let cursor = 0

  return fragments.flatMap((fragment, index) => {
    const durationSec = resolveEpisodeFragmentTimelineDuration(fragment)

    if (durationSec <= 0) {
      return []
    }

    const startSec = cursor
    const endSec = cursor + durationSec

    cursor = endSec

    return [
      {
        fragmentId: fragment.id,
        index,
        durationSec,
        startSec,
        endSec,
        hasVideo: Boolean(fragment.video),
      },
    ]
  })
}

// 计算分集时间轴总时长
export function resolveEpisodeVideoTimelineTotalDuration(
  segments: DramaEpisodeVideoTimelineSegment[],
): number {
  if (segments.length === 0) {
    return 0
  }

  return segments[segments.length - 1]?.endSec ?? 0
}

// 将分镜内播放时间映射为全局时间轴位置
export function resolveGlobalTimeFromFragmentPlayback(
  segment: DramaEpisodeVideoTimelineSegment,
  localTimeSec: number,
  localDurationSec: number,
): number {
  if (localDurationSec <= 0) {
    return segment.startSec
  }

  const ratio = Math.min(1, Math.max(0, localTimeSec / localDurationSec))

  return segment.startSec + ratio * segment.durationSec
}

// 将全局时间轴位置映射为分镜内播放时间
export function resolveFragmentPlaybackFromGlobalTime(
  segments: DramaEpisodeVideoTimelineSegment[],
  globalTimeSec: number,
): {
  segment: DramaEpisodeVideoTimelineSegment
  localTimeSec: number
} | null {
  if (segments.length === 0) {
    return null
  }

  const clampedGlobalTime = Math.min(
    Math.max(0, globalTimeSec),
    resolveEpisodeVideoTimelineTotalDuration(segments),
  )

  const segment =
    segments.find(
      (item) => clampedGlobalTime >= item.startSec && clampedGlobalTime < item.endSec,
    ) ?? segments[segments.length - 1]

  if (!segment) {
    return null
  }

  const localTimeSec = Math.min(
    segment.durationSec,
    Math.max(0, clampedGlobalTime - segment.startSec),
  )

  return {
    segment,
    localTimeSec,
  }
}

// 解析当前全局时间所在的分镜索引
export function resolveEpisodeVideoTimelineSegmentIndex(
  segments: DramaEpisodeVideoTimelineSegment[],
  globalTimeSec: number,
): number {
  if (segments.length === 0) {
    return 0
  }

  const matched = segments.find(
    (segment) => globalTimeSec >= segment.startSec && globalTimeSec < segment.endSec,
  )

  return matched?.index ?? segments[segments.length - 1]?.index ?? 0
}

// 计算单个分镜区间内的已播放比例（0–1）
export function resolveEpisodeTimelineSegmentFillRatio(
  segment: DramaEpisodeVideoTimelineSegment,
  globalTimeSec: number,
): number {
  if (globalTimeSec >= segment.endSec) {
    return 1
  }

  if (globalTimeSec <= segment.startSec) {
    return 0
  }

  const span = segment.endSec - segment.startSec

  if (span <= 0) {
    return 0
  }

  return (globalTimeSec - segment.startSec) / span
}

// 将秒数格式化为 mm:ss
export function formatVideoTimelineClock(seconds: number): string {
  const safeSeconds = Math.max(0, Math.floor(seconds))
  const minutes = Math.floor(safeSeconds / 60)
  const remainSeconds = safeSeconds % 60

  return `${String(minutes).padStart(2, '0')}:${String(remainSeconds).padStart(2, '0')}`
}

// 将进度条点击比例映射为全局播放时间
export function resolveVideoTimelineSeekTime(ratio: number, totalDurationSec: number): number {
  if (totalDurationSec <= 0) {
    return 0
  }

  const clampedRatio = Math.min(1, Math.max(0, ratio))

  return clampedRatio * totalDurationSec
}

// 查找下一个可播放视频的分镜 ID
export function resolveNextPlayableFragmentId(
  segments: DramaEpisodeVideoTimelineSegment[],
  currentFragmentId: number,
): number | null {
  const currentIndex = segments.findIndex((segment) => segment.fragmentId === currentFragmentId)

  if (currentIndex < 0) {
    return null
  }

  for (let index = currentIndex + 1; index < segments.length; index += 1) {
    const segment = segments[index]

    if (segment?.hasVideo) {
      return segment.fragmentId
    }
  }

  return null
}
