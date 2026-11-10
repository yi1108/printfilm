import type { ToolRunRecord } from '../api/tools.ts'
import type { AssetDetailRecord } from './assetDetails.ts'
import { formatGenerationErrorMessage } from './generationError.ts'

/** 只接收参数标量，忽略请求引用、对象和内部追踪信息。 */
function scalar(value: unknown): string | number | boolean | undefined {
  return typeof value === 'string' || typeof value === 'boolean' || (typeof value === 'number' && Number.isFinite(value)) ? value : undefined
}

/** 时长允许旧记录的“8s”，但不得把空值或布尔值变成秒数。 */
function seconds(value: unknown): number | undefined {
  if (typeof value !== 'string' && typeof value !== 'number') return undefined
  const parsed = Number(String(value).replace(/\s*s$/i, ''))
  return Number.isFinite(parsed) && parsed > 0 ? parsed : undefined
}

/** 将独立生成记录适配为全局资产详情，预览和下载始终使用所选正式结果。 */
export function toolRunDetailAsset(record: ToolRunRecord, resultIndex = 0): AssetDetailRecord {
  // 原始提示词与参数来自已提交的任务，不能使用当前生成表单覆盖。
  const params = record.params || {}
  const url = record.kind === 'text' ? null : record.urls[resultIndex] || record.urls[0] || null
  const duration = seconds(params.duration_sec ?? params.duration)
  const labels: Record<string, string> = { video: '视频生成', image: '图片生成', audio: '音频生成', text: '文字生成' }
  const statuses: Record<string, string> = { queued: '任务正在排队，结果会自动更新。', running: '任务正在生成，结果会自动更新。', succeeded: '任务已完成，暂无可预览的媒体结果。', failed: '生成失败。', cancelled: '任务已取消。' }
  const textContent = record.text_content || formatGenerationErrorMessage(record.error) || statuses[record.status] || `任务状态：${record.status}`

  return {
    id: record.id,
    name: labels[record.kind] || '生成记录',
    type: record.kind === 'text' || !url ? 'text' : record.kind,
    url,
    // 视频首帧只作已有视频的 poster；尚无成片时不能把图片作为视频下载或播放。
    cover: record.kind === 'image' ? url || record.preview_url
      : record.kind === 'video' && url && record.preview_url !== url ? record.preview_url : null,
    updated_at: record.finished_at || record.created_at,
    references: record.references,
    params: {
      ...((record.kind === 'text' || !url) ? { textContent } : {}),
      media_metadata: {
        source: 'generated',
        model_id: scalar(params.model_id ?? params.model),
        prompt: record.prompt,
        created_at: record.finished_at || record.created_at,
        parameter_source: 'request',
        parameters: Object.fromEntries(Object.entries({
          aspect_ratio: scalar(params.aspect_ratio ?? params.ratio),
          resolution: scalar(params.resolution), size: scalar(params.size),
          ...(record.kind === 'video' && duration !== undefined ? { requested_duration_sec: duration } : {}),
          media_duration_sec: seconds(params.media_duration_sec),
          video_mode: scalar(params.video_mode), image_style_id: scalar(params.image_style_id),
          generate_audio: scalar(params.generate_audio), watermark: scalar(params.watermark),
          camera_fixed: scalar(params.camera_fixed), seed: scalar(params.seed), count: scalar(params.count),
          negative: scalar(params.negative), strength: scalar(params.strength), motion: scalar(params.motion),
          ...(record.kind === 'audio' ? { speaker: scalar(params.speaker ?? params.voice ?? params.voice_id) } : {}),
        }).filter(([, value]) => value !== undefined && value !== '')),
      },
    },
  }
}
