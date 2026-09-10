/**
 * 科普分镜脚本内 @duration 解析、校验与分段预览
 * 常量与后端 seedance_segments 对齐（单段 3–12s，镜合计 ≤30s）
 */

/** 单段时长下限（秒） */
export const SEGMENT_DURATION_MIN = 3

/** 单段时长上限（秒） */
export const SEGMENT_DURATION_MAX = 12

/** 单镜脚本内 @duration 合计上限（秒） */
export const SHOT_DURATION_MAX = 30

/** 时长快捷选项（秒） */
export const SEGMENT_DURATION_PRESETS = [4, 6, 8, 10, 12] as const

/** 与后端一致的字幕 cue */
export const SUBTITLE_CUE = '【字幕：全程简体中文字幕，旁白逐句同步烧录】'

/** 与后端一致的旁白前缀（科普自然偏快；旧稿「慢速清晰」仍可识别） */
export const NARRATION_PREFIX = '【旁白·自然语速·同步字幕】'

/** 脚本编辑区 placeholder */
export const SEGMENT_SCRIPT_PLACEHOLDER = `${SUBTITLE_CUE}\n【BGM：轻快专业，音量低于人声】\n@duration:4\n过肩工位操作画面…\n@duration:8\n${NARRATION_PREFIX}口播内容…`

const DURATION_TOKEN_PATTERN = /@duration:(\d+)/g

export type SegmentBeatView = { duration: number; text: string }

/**
 * 从脚本中提取全部 @duration 秒数（保留顺序）
 * @param content 逐段分镜脚本文本
 */
export function extractDurations(content: string): number[] {
  const durations: number[] = []
  for (const match of content.matchAll(DURATION_TOKEN_PATTERN)) {
    const seconds = Number(match[1])
    if (Number.isFinite(seconds) && seconds > 0) {
      durations.push(seconds)
    }
  }
  return durations
}

/**
 * 合计脚本内 @duration 秒数
 * @param content 逐段分镜脚本文本
 */
export function sumDuration(content: string): number {
  return extractDurations(content).reduce((sum, value) => sum + value, 0)
}

/**
 * 校验单个时长是否在科普单段合法区间
 * @param seconds 时长秒数
 */
export function isValidSegmentDuration(seconds: number): boolean {
  return (
    Number.isFinite(seconds) &&
    seconds >= SEGMENT_DURATION_MIN &&
    seconds <= SEGMENT_DURATION_MAX
  )
}

/**
 * 校验脚本内时长标签：单段范围 + 合计 ≤ 镜上限
 * @param content 逐段分镜脚本文本
 */
export function validateSegmentScriptDuration(content: string): {
  valid: boolean
  total: number
  durations: number[]
  message?: string
} {
  const durations = extractDurations(content)
  const total = durations.reduce((sum, value) => sum + value, 0)

  if (durations.length === 0) {
    return { valid: true, total: 0, durations }
  }

  if (durations.some((value) => !isValidSegmentDuration(value))) {
    return {
      valid: false,
      total,
      durations,
      message: `单个 @duration 需在 ${SEGMENT_DURATION_MIN}–${SEGMENT_DURATION_MAX} 秒之间`,
    }
  }

  if (total > SHOT_DURATION_MAX) {
    return {
      valid: false,
      total,
      durations,
      message: `镜头时长合计不能超过 ${SHOT_DURATION_MAX} 秒（当前 ${total}s）`,
    }
  }

  return { valid: true, total, durations }
}

/**
 * 解析脚本为字幕/BGM cues 与带时长的正文段（列表预览用）
 * @param script 逐段分镜脚本
 */
export function parseSegmentScript(script: string | undefined | null): {
  cues: string[]
  beats: SegmentBeatView[]
} {
  /*
   * cues 字幕/BGM 行
   * beats 带 duration 的正文段
   * pendingDur 上一段 @duration 值
   */
  const cues: string[] = []
  const beats: SegmentBeatView[] = []
  let pendingDur = 0

  const lines = String(script || '')
    .replace(/\r\n/g, '\n')
    .split('\n')
    .map((l) => l.trim())
    .filter(Boolean)

  for (const line of lines) {
    if (line.startsWith('【字幕') || line.startsWith('【BGM')) {
      cues.push(line)
      continue
    }
    const m = line.match(/^@duration:(\d+)/)
    if (m) {
      pendingDur = Number(m[1]) || 0
      continue
    }
    if (pendingDur > 0 || beats.length === 0) {
      beats.push({ duration: pendingDur || 0, text: line })
      pendingDur = 0
    } else {
      beats.push({ duration: 0, text: line })
    }
  }

  return { cues, beats }
}

const NARRATION_LINE_PREFIX = /^【旁白[^】]*】/

/** 脚本行是否为旁白口播（字幕 cue 含「旁白」二字但不算） */
export function isNarrationScriptLine(line: string): boolean {
  const stripped = line.trim()
  if (stripped.startsWith('【字幕') || stripped.startsWith('【BGM')) return false
  return NARRATION_LINE_PREFIX.test(stripped)
}

/** 去掉旁白前缀，得到可朗读正文 */
export function stripNarrationPrefix(line: string): string {
  return line.trim().replace(NARRATION_LINE_PREFIX, '').trim()
}

/** 从脚本提取旁白正文（多段拼接） */
export function narrationFromScript(script: string | undefined | null): string {
  const parts: string[] = []
  for (const line of String(script || '').replace(/\r\n/g, '\n').split('\n')) {
    if (isNarrationScriptLine(line)) {
      const text = stripNarrationPrefix(line)
      if (text) parts.push(text)
    }
  }
  return parts.join('')
}

/** 从脚本提取首段画面（非旁白、非 cue） */
export function firstVisualFromScript(script: string | undefined | null): string {
  for (const line of String(script || '').replace(/\r\n/g, '\n').split('\n')) {
    const stripped = line.trim()
    if (
      !stripped ||
      stripped.startsWith('@duration:') ||
      stripped.startsWith('【字幕') ||
      stripped.startsWith('【BGM') ||
      isNarrationScriptLine(stripped)
    ) {
      continue
    }
    return stripped.replace(/^【[^】]*】/, '').trim() || stripped
  }
  return ''
}

/** 把弹窗旁白写回脚本中的旁白段 */
export function replaceNarrationInScript(script: string, narration: string): string {
  const text = narration.trim()
  const lines = String(script || '').replace(/\r\n/g, '\n').split('\n')
  const out: string[] = []
  let replaced = false
  for (const raw of lines) {
    const stripped = raw.trim()
    if (text && isNarrationScriptLine(stripped) && !replaced) {
      const prefix = stripped.match(NARRATION_LINE_PREFIX)?.[0] || NARRATION_PREFIX
      out.push(`${prefix}${text}`)
      replaced = true
      continue
    }
    out.push(raw.replace(/\s+$/, ''))
  }
  if (text && !replaced) {
    out.push('@duration:6')
    out.push(`${NARRATION_PREFIX}${text}`)
  }
  return out.join('\n').trim()
}

/** 把弹窗首帧画面写回脚本第一段 visual */
export function replaceFirstVisualInScript(script: string, visual: string): string {
  const text = visual.trim()
  if (!text) return String(script || '').trim()
  const lines = String(script || '').replace(/\r\n/g, '\n').split('\n')
  const out: string[] = []
  let replaced = false
  let cueEnd = 0
  for (let i = 0; i < lines.length; i += 1) {
    const stripped = lines[i].trim()
    if (stripped.startsWith('【字幕') || stripped.startsWith('【BGM') || !stripped) {
      cueEnd = i + 1
      continue
    }
    break
  }
  for (const raw of lines) {
    const stripped = raw.trim()
    if (
      !replaced &&
      stripped &&
      !stripped.startsWith('@duration:') &&
      !stripped.startsWith('【字幕') &&
      !stripped.startsWith('【BGM') &&
      !isNarrationScriptLine(stripped)
    ) {
      out.push(text)
      replaced = true
      continue
    }
    out.push(raw.replace(/\s+$/, ''))
  }
  if (!replaced) {
    const extra = [`@duration:${SEGMENT_DURATION_MIN}`, text]
    return [...out.slice(0, cueEnd), ...extra, ...out.slice(cueEnd)].join('\n').trim()
  }
  return out.join('\n').trim()
}
