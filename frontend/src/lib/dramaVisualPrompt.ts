/** 从资产 params 读取/拼装视觉生图提示词（对齐 manju buildCharacterParams + 弱提示检测） */
import type { DramaAsset } from '../api/drama'

const WEAK_PROMPT = /^(character|scene|prop|material|none|image|audio|video)\s+\S+$/i

const GENERIC_MARKERS = [
  '影视级写实环境空间',
  '构图层次分明、光影有戏剧张力',
  '适合短剧横屏拍摄',
  '影视级写实场景，构图清晰，适合短剧拍摄',
  '影视级写实人物',
  '白底全身定妆照',
]

const MIN_LEN: Record<string, number> = {
  character: 120,
  scene: 100,
  prop: 70,
  material: 70,
  video: 8,
}

// 是否模板化套话
function isGenericTemplate(text: string): boolean {
  if (text.length >= 180) return false
  return GENERIC_MARKERS.some((m) => text.includes(m))
}

// 判断提示词是否过短、占位或模板化
function isWeakVisualPrompt(prompt: string, assetName: string, kind: string): boolean {
  const text = prompt.trim()
  /* 含 @asset: 引用的是用户正文，不要当弱占位清掉 */
  if (/@asset:\d+/.test(text)) return false
  const kindLower = kind.toLowerCase()
  const minLen = MIN_LEN[kindLower] ?? 60
  if (text.length < minLen) return true
  const name = assetName.trim()
  if (name && (text.toLowerCase() === `${kindLower} ${name}`.toLowerCase() || text === name)) {
    return true
  }
  if (WEAK_PROMPT.test(text)) return true
  if (isGenericTemplate(text)) return true
  return false
}

// 按 manju buildCharacterParams 规则拼接
function manjuJoinCharacterPrompt(params: Record<string, unknown>): string {
  const visual = String(params.visualImage || params.visualPrompt || '').trim()
  const title = String(params.title || '').trim()
  const roleType = String(params.roleType || '').trim()
  const coreTags = String(params.coreTags || '').trim()
  const personality = String(params.personality || '').trim()
  const parts = [
    visual,
    title ? `身份：${title}` : '',
    roleType ? `定位：${roleType}` : '',
    coreTags ? `标签：${coreTags}` : '',
    personality ? `性格：${personality}` : '',
  ].filter(Boolean)
  return parts.join('。')
}

/**
 * 读取资产视觉提示词：完整描述优先，过短/模板化时从角色字段拼装。
 */
export function readVisualPrompt(asset: DramaAsset): string {
  const params = (asset.params || {}) as Record<string, unknown>
  const kind = (asset.type || '').toLowerCase()
  const name = asset.name || ''

  const canvas = params.canvas
  const canvasGen =
    canvas && typeof canvas === 'object'
      ? (canvas as Record<string, unknown>).generation
      : null
  const canvasPrompt =
    canvasGen && typeof canvasGen === 'object'
      ? String((canvasGen as Record<string, unknown>).prompt || '').trim()
      : ''
  const stored =
    String(params.visualPrompt || params.visualImage || canvasPrompt || '').trim()

  if (stored && !isWeakVisualPrompt(stored, name, kind)) {
    return stored
  }

  if (kind === 'character') {
    const composed = manjuJoinCharacterPrompt(params)
    if (composed && !isWeakVisualPrompt(composed, name, kind)) return composed
  }

  if (kind === 'scene' && name) {
    return `场景：${name}，影视级写实场景，构图清晰，适合短剧拍摄`
  }

  if (stored) return stored
  return `${kind} ${name}`.trim()
}

/**
 * 画布/编辑用提示词：过滤「character 新角色」等弱占位，避免误填。
 */
export function readEditableVisualPrompt(asset: DramaAsset): string {
  const kind = (asset.type || '').toLowerCase()
  const name = asset.name || ''
  const prompt = readVisualPrompt(asset).trim()
  if (!prompt || isWeakVisualPrompt(prompt, name, kind)) return ''
  return prompt
}

/** 文本是否为弱视觉提示词（占位/过短/模板） */
export function isWeakEditablePrompt(prompt: string, name = '', kind = ''): boolean {
  return isWeakVisualPrompt(prompt, name, kind)
}
