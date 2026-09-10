/** 漫剧生图：模型 / 比例 / 清晰度选项（对齐 manju generationOptions） */

export type ImageGenerationModelId = 'seedream-5.0' | 'seedream-4.5'

export type GenerationAspectRatioId =
  | 'auto'
  | '16:9'
  | '21:9'
  | '9:16'
  | '4:3'
  | '3:4'
  | '1:1'

export type GenerationResolution = '3K' | '4K'

export type ImageGenerationOptions = {
  image_style_id?: string
  model_id: ImageGenerationModelId
  aspect_ratio: GenerationAspectRatioId
  resolution: GenerationResolution
}

/** 图片清晰度列表 */
export const GENERATION_RESOLUTION_OPTIONS: GenerationResolution[] = ['3K', '4K']

/** 比例列表 */
export const GENERATION_ASPECT_RATIO_OPTIONS: Array<{
  id: GenerationAspectRatioId
  label: string
}> = [
  { id: 'auto', label: '自动' },
  { id: '16:9', label: '16:9' },
  { id: '21:9', label: '21:9' },
  { id: '9:16', label: '9:16' },
  { id: '4:3', label: '4:3' },
  { id: '3:4', label: '3:4' },
  { id: '1:1', label: '1:1' },
]

/** Seedream 生图模型 */
export const IMAGE_GENERATION_MODELS: Array<{
  id: ImageGenerationModelId
  label: string
  description: string
}> = [
  {
    id: 'seedream-5.0',
    label: 'Seedream 5.0',
    description: '更智能的理解与推理，支持多图融合。',
  },
  {
    id: 'seedream-4.5',
    label: 'Seedream 4.5',
    description: '擅长图片编辑与复杂场景还原。',
  },
]

/** 默认生图选项（角色偏竖构图） */
export const DEFAULT_IMAGE_GENERATION_OPTIONS: ImageGenerationOptions = {
  model_id: 'seedream-5.0',
  aspect_ratio: '3:4',
  resolution: '3K',
}

/** 场景默认横构图 */
export function defaultOptionsForAssetKind(kind: string | undefined | null): ImageGenerationOptions {
  const k = String(kind || '').toLowerCase()
  if (k === 'scene') {
    return { model_id: 'seedream-5.0', aspect_ratio: '16:9', resolution: '3K' }
  }
  return { ...DEFAULT_IMAGE_GENERATION_OPTIONS }
}

/** 格式化比例·清晰度触发文案 */
export function formatOutputSettingsLabel(
  aspectRatio: GenerationAspectRatioId,
  resolution: GenerationResolution,
): string {
  if (aspectRatio === 'auto') return `自动 · ${resolution}`
  return `${aspectRatio} · ${resolution}`
}

/** 解析模型展示名 */
export function getImageModelLabel(modelId: string | undefined | null): string {
  return IMAGE_GENERATION_MODELS.find((m) => m.id === modelId)?.label ?? 'Seedream 5.0'
}
