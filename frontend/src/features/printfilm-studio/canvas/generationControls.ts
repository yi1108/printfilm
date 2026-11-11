import type { MediaModelOption } from '../../../api'
export type GenerationControls = { ratios: string[]; resolutions: string[]; durations: string[] }
export function generationControls(model: Partial<MediaModelOption> | undefined, video: boolean): GenerationControls {
  const ratios = model?.allowed_aspect_ratios?.length ? model.allowed_aspect_ratios : ['16:9', '9:16', '1:1', '3:2', '2:3']
  const resolutions = model?.available_resolutions?.length ? model.available_resolutions : model?.allowed_resolutions?.length ? model.allowed_resolutions : video ? ['480p', '720p', '1080p'] : ['1K', '2K', '4K']
  const min = Math.max(1, Math.ceil(model?.duration_min || 5)), max = Math.min(60, Math.floor(model?.duration_max || 10))
  const durations = max >= min ? Array.from({ length: max - min + 1 }, (_, index) => String(min + index)) : []
  return { ratios: video ? ratios.filter((ratio) => ratio !== 'auto') : ['auto', ...['1:1','3:2','2:3'].filter(ratio=>ratios.includes(ratio))], resolutions, durations }
}
