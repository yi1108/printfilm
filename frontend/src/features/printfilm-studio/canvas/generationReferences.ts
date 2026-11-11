export type MediaKind = 'image' | 'video' | 'audio'
export type StudioVideoMode = 'text_to_video' | 'omni_reference' | 'image_to_video' | 'first_last_frame'
export const VIDEO_MODES: { id: StudioVideoMode; label: string }[] = [
  { id: 'text_to_video', label: '文生视频' }, { id: 'omni_reference', label: '全能参考' },
  { id: 'image_to_video', label: '图生视频' }, { id: 'first_last_frame', label: '首尾帧' },
]
export function videoReferenceError(kinds: MediaKind[], mode: StudioVideoMode, limits?: { images: number; videos: number; audios: number }): string | undefined {
  if (mode === 'text_to_video') return kinds.length ? '文生视频不使用媒体参考，请移除引用或切换生成方式' : undefined
  if (mode === 'image_to_video' && (kinds.length !== 1 || kinds[0] !== 'image')) return '图生视频需要一张首帧图片'
  if (mode === 'first_last_frame' && (kinds.length !== 2 || kinds.some((kind) => kind !== 'image'))) return '首尾帧需要两张图片，按引用顺序分别作为首帧、尾帧'
  if (mode === 'omni_reference' && !kinds.length) return '请选择至少一份参考素材'
  if (kinds.length > 12) return '最多支持 12 份参考素材'
  if (limits) for (const [kind, key, label] of [['image', 'images', '图片'], ['video', 'videos', '视频'], ['audio', 'audios', '音频']] as const) {
    if (kinds.filter((item) => item === kind).length > limits[key]) return `当前模型最多支持 ${limits[key]} 份${label}参考`
  }
}
export function videoFileReferences(kinds: MediaKind[], preferReference = false, explicitMode?: StudioVideoMode) {
  if (explicitMode) {
    const frames = explicitMode === 'image_to_video' || explicitMode === 'first_last_frame'
    return { mode: explicitMode === 'text_to_video' ? 'text_to_video' as const : frames ? 'first_last_frame' as const : 'omni_reference' as const,
      references: explicitMode === 'text_to_video' ? [] : kinds.map((kind, file_index) => ({ file_index, role: frames ? (file_index === 0 ? 'first_frame' as const : 'last_frame' as const) : kind === 'video' ? 'reference_video' as const : kind === 'audio' ? 'reference_audio' as const : 'reference_image' as const })) }
  }
  if (!kinds.length) return { mode: 'text_to_video' as const, references: [] }
  const frameMode = !preferReference && kinds.length <= 2 && kinds.every((kind) => kind === 'image')
  return {
    mode: frameMode ? 'first_last_frame' as const : 'omni_reference' as const,
    references: kinds.map((kind, file_index) => ({ file_index, role: frameMode ? (file_index === 0 ? 'first_frame' as const : 'last_frame' as const) : kind === 'video' ? 'reference_video' as const : kind === 'audio' ? 'reference_audio' as const : 'reference_image' as const })),
  }
}
