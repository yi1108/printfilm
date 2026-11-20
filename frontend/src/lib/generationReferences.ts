import type { ToolReferenceAsset, ToolReferenceInput } from '../api/tools'

export type VideoGenerationMode = 'text_to_video' | 'first_last_frame' | 'omni_reference'
export type GenerationReferenceKind = 'image' | 'video' | 'audio'
export type GenerationReferenceLimits = { images: number; videos: number; audios: number; total?: number }
export type GenerationReference = {
  id: string
  role: ToolReferenceInput['role']
  kind: GenerationReferenceKind
  name: string
  url: string
  file?: File
  assetId?: number
}

/** 混合参考下媒体类型到提交角色的固定映射。 */
export const roleForReferenceKind: Record<GenerationReferenceKind, ToolReferenceInput['role']> = {
  image: 'reference_image',
  video: 'reference_video',
  audio: 'reference_audio',
}

/** 按资产真实媒体类型分类，兼容角色、场景、道具等业务类型。 */
export function toolReferenceAssetKind(asset: ToolReferenceAsset): GenerationReferenceKind {
  if (asset.media_kind === 'audio' || asset.media_kind === 'video' || asset.media_kind === 'image') return asset.media_kind
  if (asset.asset_type === 'video' || asset.type === 'video') return 'video'
  if (asset.asset_type === 'audio' || asset.type === 'audio' || asset.type === 'voice') return 'audio'
  return 'image'
}

/** 把资产包装成参考资料条目，仅提交资产 ID，媒体地址只用于本地预览。 */
export function referenceFromAsset(asset: ToolReferenceAsset, role: ToolReferenceInput['role'], fallbackName: string): GenerationReference {
  return {
    id: crypto.randomUUID(),
    role,
    kind: toolReferenceAssetKind(asset),
    name: asset.name || fallbackName,
    url: asset.url || asset.cover || '',
    assetId: asset.id,
  }
}

/** 数量上限校验：返回双语错误文案，通过时返回 null。 */
export function checkGenerationReferenceCounts(
  next: GenerationReference[],
  limits: GenerationReferenceLimits | undefined,
  frameMode: boolean,
  t: (zh: string, en: string) => string,
): string | null {
  const max = generationReferenceLimits(limits)
  const counts = { image: 0, video: 0, audio: 0 }
  for (const reference of next) counts[reference.kind] += 1
  if (counts.image > max.images || counts.video > max.videos || counts.audio > max.audios || (!frameMode && next.length > max.total)) {
    return t(
      `参考资料超出上限：图片 ${max.images} 张、视频 ${max.videos} 段、音频 ${max.audios} 段，最多 ${max.total} 份。`,
      `Reference limit: ${max.images} images, ${max.videos} videos, ${max.audios} audio clips; ${max.total} files in total.`,
    )
  }
  return null
}

/** 优先使用模型目录的上限，目录尚未加载时保留原默认值。 */
export function generationReferenceLimits(limits?: GenerationReferenceLimits): Required<GenerationReferenceLimits> {
  return { images: limits?.images ?? 9, videos: limits?.videos ?? 3, audios: limits?.audios ?? 3, total: limits?.total ?? 12 }
}

/** 扩展名与 MIME 同时符合服务端格式范围，未提供 MIME 时按扩展名识别。 */
export function generationReferenceFileKind(file: Pick<File, 'type' | 'name'>): GenerationReferenceKind | null {
  const kind = /\.(png|jpe?g|webp)$/i.test(file.name) ? 'image'
    : /\.(mp3|wav|m4a|aac|ogg|flac)$/i.test(file.name) ? 'audio'
    : /\.(mp4|mov|webm)$/i.test(file.name) ? 'video' : null
  if (!kind) return null
  const mime = file.type.toLowerCase()
  return !mime || mime === 'application/octet-stream' || mime.startsWith(`${kind}/`) ? kind : null
}

/** 提交前校验模式、资料类型和数量，切换模型后同样保留并检查原有选择。 */
export function validateGenerationReferences(
  mode: VideoGenerationMode,
  value: GenerationReference[],
  limits?: GenerationReferenceLimits,
): string | null {
  if (mode === 'text_to_video') return value.length ? '文生视频无需参考资料，请切换生成方式后使用。' : null
  const max = generationReferenceLimits(limits)
  const counts = { image: 0, video: 0, audio: 0 }
  for (const reference of value) {
    if (!reference.file && (!reference.assetId || reference.assetId < 1)) return '参考资料已失效，请重新上传或从资产库选择。'
    if (reference.file && reference.file.size === 0) return '参考文件不能为空，请重新选择。'
    if (reference.file && reference.file.size > 40 * 1024 * 1024) return '单个参考文件不能超过 40MB。'
    if (reference.file && generationReferenceFileKind(reference.file) !== reference.kind) return '参考文件格式或媒体类型不支持，请重新选择。'
    counts[reference.kind] += 1
    const expectedRole = reference.kind === 'image' ? 'reference_image' : reference.kind === 'video' ? 'reference_video' : 'reference_audio'
    if (mode === 'omni_reference' && reference.role !== expectedRole) return '全能参考请使用图片、视频或音频参考资料。'
    if (mode === 'first_last_frame' && (reference.kind !== 'image' || !['first_frame', 'last_frame'].includes(reference.role))) return '首尾帧仅支持首帧和尾帧图片。'
  }
  if (counts.image > max.images) return max.images === 0 ? '当前模型不支持参考图片，请切换模型。' : `当前模型最多支持 ${max.images} 张参考图片，请移除多余图片。`
  if (counts.video > max.videos) return max.videos === 0 ? '当前模型不支持参考视频，请切换模型。' : `当前模型最多支持 ${max.videos} 段参考视频，请移除多余视频。`
  if (counts.audio > max.audios) return max.audios === 0 ? '当前模型不支持参考音频，请切换模型。' : `当前模型最多支持 ${max.audios} 段参考音频，请移除多余音频。`
  if (mode === 'first_last_frame') {
    if (max.images < 1) return '当前模型不支持首尾帧，请切换模型。'
    if (!value.some(item => item.role === 'first_frame')) return '请上传或从资产库选择首帧图片。'
    if (value.filter(item => item.role === 'first_frame').length > 1 || value.filter(item => item.role === 'last_frame').length > 1) return '首帧和尾帧分别只能选择一张图片。'
  } else {
    if (!value.length) return '请上传或从资产库选择至少一份参考资料。'
    if (value.length > max.total) return `全能参考最多支持 ${max.total} 份资料，请移除多余资料。`
  }
  return null
}

/** 文件索引对应实际 multipart 顺序；资产只提交 ID，由服务端校验归属。 */
export function serializeGenerationReferences(value: GenerationReference[]): { files: File[]; references: ToolReferenceInput[] } {
  const files: File[] = []
  const references = value.map(item => {
    if (item.file) {
      const file_index = files.length
      files.push(item.file)
      return { role: item.role, file_index }
    }
    return { role: item.role, asset_id: item.assetId }
  })
  return { files, references }
}
