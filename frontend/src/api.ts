import { workspaceScope } from './features/teams/workspaceScope'
import { createAccountRequests } from './api/account'
import { API_BASE, createJsonRequester, requestResponse, uploadFile } from './api/client'
import { apiErrorMessage } from './api/http'
import { curatedCreationTemplates } from './lib/creationTemplates'
import type { PaymentCurrency, StripePaymentQuote } from './lib/billingPayments'

/** 科普、账号和计费 API 共用 JSON 传输层。 */
const request = createJsonRequester()
// 注销沿用统一的鉴权请求器，不在组件内另建 fetch 或处理令牌。
const accountRequests = createAccountRequests(request)

export type PipelineMode = 'full' | 'image_text'

export type Template = {
  id: string
  name: string
  description: string
  category: string[]
  preview_cover: string
  default_ratio: string
  shot_duration_min: number
  shot_duration_max: number
  is_premium: boolean
  sort_order: number
  style_prefix?: string
  negative_prompt?: string
  llm_system_addon?: string
  seedream_config?: {
    ref_images?: string[]
    strength?: number
    character_prompt?: string
    extra_prompt?: string
    consistency_mode?: 'character' | 'style' | 'diverse'
  }
  audio_config?: {
    voice_preset?: string
    bgm_mood?: string
  }
}

/** 模板音色别名 → 预设 speaker id */
export const VOICE_PRESET_ALIASES: Record<string, string> = {
  narrator_calm: 'zh_female_cancan_uranus_bigtts',
  warm_storyteller: 'zh_female_tianmeixiaoyuan_uranus_bigtts',
  teacher_clear: 'zh_male_shaonianzixin_uranus_bigtts',
  urban_editorial: 'zh_female_shuangkuaisisi_uranus_bigtts',
  retro_host: 'zh_male_shaonianzixin_uranus_bigtts',
  guqin_narrator: 'zh_female_vv_uranus_bigtts',
}

export function defaultsFromTemplate(t: Template): {
  style_prompt: string
  character_prompt: string
  extra_prompt: string
  voice_id: string
  output_ratio: string
} {
  const cfg = t.seedream_config || {}
  const preset = t.audio_config?.voice_preset || ''
  const voice_id =
    VOICE_PRESET_ALIASES[preset] ||
    (preset.startsWith('zh_') ? preset : 'zh_female_cancan_uranus_bigtts')
  return {
    style_prompt: (t.style_prefix || '').trim(),
    character_prompt: (cfg.character_prompt || '').trim(),
    extra_prompt: (cfg.extra_prompt || '').trim(),
    voice_id,
    output_ratio: t.default_ratio || '16:9',
  }
}

export type Shot = {
  video_skip_reason?: string | null
  id: number
  shot_no: number
  duration: number
  narration: string
  overlay_title?: string
  overlay_subtitle?: string
  img_prompt: string
  video_prompt: string
  segment_script?: string
  camera: string
  bgm_mood: string
  image_url: string | null
  video_url: string | null
  audio_url: string | null
  status: string
  version: number
}

export type VoicePreset = {
  id: string
  label: string
  gender: string
  speaker: string
}

/** 项目 voice_id / 模板别名 → 与音色列表一致的 speaker id */
export function resolveVoiceId(raw: string, voices: VoicePreset[]): string {
  const id = (raw || '').trim()
  if (!id) {
    const first = voices[0]
    return first ? first.speaker || first.id : ''
  }
  const alias = VOICE_PRESET_ALIASES[id]
  if (alias) return alias
  const hit = voices.find((v) => v.id === id || v.speaker === id)
  return hit ? hit.speaker || hit.id : id
}

export type Project = {
  id: number
  target_duration_sec?: number
  creation_session_id?: number | null
  template_id: string
  title: string
  source_type: string
  source_text: string
  status: string
  progress: number
  error_msg: string | null
  cover_url: string | null
  final_video_url: string | null
  resolution_mode: string
  pipeline_mode?: PipelineMode
  output_ratio?: string
  voice_id?: string
  character_bible?: string
  bgm_lock?: string
  subtitle_preset?: string
  style_prompt?: string
  character_prompt?: string
  extra_prompt?: string
  image_model?: string
  video_model?: string
  image_resolution?: string
  video_resolution?: string
  ref_image_url: string | null
  created_at: string
  updated_at: string
  shots: Shot[]
  active_tasks?: Array<{
    id: number
    domain: string
    task_type: string
    status: string
    current_step_key?: string | null
    current_step_status?: string | null
    progress_percent?: number
    cancel_requested?: boolean
    provider_task_id?: string | null
    error_message?: string | null
    project_id?: number | null
    shot_id?: number | null
    created_at?: string
    updated_at?: string
  }>
}

export type MediaModelOption = {
  id: string
  label: string
  description: string
  provider: string
  recommended?: boolean
  strategy_id?: string
  strategy_version?: number
  billing_unit?: 'image' | 'second'
  prices?: Record<string, string>
  price_version?: number | null
  available?: boolean
  available_resolutions?: string[]
  reference_limits?: { images: number; audios: number; videos: number }
  defaults?: { resolution: string; aspect_ratio: string; duration?: number; count: number }
  /** 该模型允许的清晰度 */
  allowed_resolutions?: string[]
  /** 该模型允许的画幅比例 */
  allowed_aspect_ratios?: string[]
  /** 视频时长下限（秒） */
  duration_min?: number
  /** 视频时长上限（秒） */
  duration_max?: number
  /** 选用提示（贵慢/清晰度等，不展示具体价） */
  pricing_hint?: string
  /** 大致出片 / 生成耗时提示 */
  eta_hint?: string
}

export type MediaModelsCatalog = {
  generation_defaults?: { image_resolution: string; video_resolution: string }
  price_version?: number | null
  billing_mode?: 'fixed_media' | 'legacy'
  image_models: MediaModelOption[]
  video_models: MediaModelOption[]
  defaults: {
    image_model: string
    video_model: string
  }
}

export type User = {
  id: number
  email: string
  nickname: string
  quota_left: number
  balance_fen?: number
  frozen_fen?: number
  plan?: string
  avatar_url?: string
  phone?: string
}

export type BillingSku = {
  id: string
  name: string
  amount_fen: number
  credit_fen: number
  recommended?: boolean
  stripe_quote?: StripePaymentQuote | null
}

export type BillingOrder = {
  out_trade_no: string
  sku_id: string
  sku_name: string
  amount_fen: number
  credit_fen: number
  pay_type: string
  status: string
  trade_no?: string | null
  paid_at?: string | null
  created_at?: string | null
  payment_currency?: PaymentCurrency | null
  payment_amount_minor?: number | null
  payment_exchange_rate?: string | null
}

export type UsageSummary = {
  period: string
  tokens: number
  charge_fen: number
  charge_yuan: number
  calls: number
  balance_fen: number
  balance_yuan: number
  frozen_fen: number
  frozen_yuan: number
}

export type UsageChargeRecord = {
  id: number
  billing_key: string
  billing_label: string
  model: string
  context: string
  total_tokens: number
  charge_fen: number
  charge_yuan: number
  estimated: boolean
  created_at: string | null
}

export type UsageChargeList = {
  items: UsageChargeRecord[]
  meta: { page: number; page_size: number; total: number }
}

export type Wallet = {
  debt_fen?: number
  spendable_fen?: number
  pending_commitment_fen?: number
  balance_fen: number
  frozen_fen: number
  balance_yuan: number
  frozen_yuan: number
  plan: string
  billing_enabled: boolean
  markup: number
}

export type BillingPreflight = {
  ok: boolean
  billing_enabled: boolean
  balance_fen: number
  balance_yuan?: number
  unit_estimate_fen: number
  unit_estimate_yuan?: number
  pending_commitment_fen: number
  pending_commitment_yuan?: number
  requested_total_fen: number
  requested_total_yuan?: number
  required_total_fen: number
  required_total_yuan?: number
  count?: number
  domain?: string
  task_type?: string
}

export type Work = {
  id: number
  project_id: number
  user_id: number
  title: string
  cover_url: string | null
  video_url: string
  visibility: string
  published_at: string
}

export const api = {
  assetUrl(path: string | null | undefined, cacheBust?: string | number) {
    if (!path) return ''
    if (path.startsWith('http')) return path
    // Only bust when caller passes a stable version (e.g. updated_at) — never Date.now()
    const q = cacheBust != null && cacheBust !== '' ? `?v=${encodeURIComponent(String(cacheBust))}` : ''
    return `${API_BASE}${path}${q}`
  },
  register(email: string, password: string, nickname: string) {
    return request<{ access_token: string }>('/api/auth/register', {
      method: 'POST',
      body: JSON.stringify({ email, password, nickname }),
    })
  },
  login(email: string, password: string) {
    return request<{ access_token: string }>('/api/auth/login', {
      method: 'POST',
      body: JSON.stringify({ email, password }),
    })
  },
  forgotPassword(email: string) {
    return request<{ ok: boolean; message: string }>('/api/auth/forgot-password', {
      method: 'POST',
      body: JSON.stringify({ email }),
    })
  },
  resetPassword(token: string, new_password: string) {
    return request<{ ok: boolean }>('/api/auth/reset-password', {
      method: 'POST',
      body: JSON.stringify({ token, new_password }),
    })
  },
  me() {
    return request<User>('/api/auth/me')
  },
  updateProfile(body: { nickname: string; email: string; phone: string }) {
    return request<User>('/api/auth/me', {
      method: 'PATCH',
      body: JSON.stringify(body),
    })
  },
  changePassword(body: { current_password: string; new_password: string }) {
    return request<{ ok: boolean }>('/api/auth/change-password', {
      method: 'POST',
      body: JSON.stringify(body),
    })
  },
  closeAccount: accountRequests.closeAccount,
  /** 上传用户头像并返回更新后的用户资料。 */
  uploadAvatar(file: File) {
    return uploadFile<User>('/api/auth/avatar', file, (response, detail) => {
      throw new Error(apiErrorMessage(detail, response.statusText) || '头像上传失败')
    })
  },
  templates() {
    return request<Template[]>('/api/templates').then(curatedCreationTemplates)
  },
  getTemplate(id: string) {
    return request<Template>(`/api/templates/${encodeURIComponent(id)}`)
  },
  createProject(body: {
    template_id: string
    title: string
    source_type: 'theme' | 'script'
    source_text: string
    target_duration_sec?: number
    resolution_mode?: 'preview' | 'hd'
    pipeline_mode?: PipelineMode
    output_ratio?: string
    voice_id?: string
    style_prompt?: string
    character_prompt?: string
    extra_prompt?: string
    image_model?: string
    video_model?: string
    image_resolution?: string
    video_resolution?: string
  }) {
    return request<Project>('/api/projects', { method: 'POST', body: JSON.stringify(body) })
  },
  updateProject(
    id: number,
    body: {
      title?: string
      source_type?: 'theme' | 'script'
      source_text?: string
      target_duration_sec?: number
      template_id?: string
      pipeline_mode?: PipelineMode
      output_ratio?: string
      resolution_mode?: 'preview' | 'hd'
      voice_id?: string
      style_prompt?: string
      character_prompt?: string
      extra_prompt?: string
      image_model?: string
      video_model?: string
      image_resolution?: string
      video_resolution?: string
      bgm_lock?: string
      subtitle_preset?: string
      cover_url?: string | null
    },
  ) {
    return request<Project>(`/api/projects/${id}`, {
      method: 'PATCH',
      body: JSON.stringify(body),
    })
  },
  mediaModels() {
    return request<MediaModelsCatalog>('/api/media-models')
  },
  /** 上传科普项目封面并返回项目。 */
  uploadCover(id: number, file: File) {
    return uploadFile<Project>(`/api/projects/${id}/cover`, file, (response, detail) => {
      throw new Error(apiErrorMessage(detail, response.statusText) || '封面上传失败')
    })
  },
  voices() {
    return request<VoicePreset[]>('/api/voices')
  },
  previewVoice(voiceId: string) {
    return request<{ url: string; voice_id: string }>('/api/voices/preview', {
      method: 'POST',
      body: JSON.stringify({ voice_id: voiceId }),
    })
  },
  listProjects(params?: {
    page?: number
    page_size?: number
    status?: 'all' | 'draft' | 'running' | 'done' | 'published' | string
    q?: string
    pipeline_mode?: '' | 'full' | 'image_text' | string
  }) {
    const sp = new URLSearchParams()
    if (params?.page) sp.set('page', String(params.page))
    if (params?.page_size) sp.set('page_size', String(params.page_size))
    if (params?.status && params.status !== 'all') sp.set('status', params.status)
    if (params?.q?.trim()) sp.set('q', params.q.trim())
    if (params?.pipeline_mode) sp.set('pipeline_mode', params.pipeline_mode)
    const qs = sp.toString()
    return request<{
      items: Array<{
        id: number
        title: string
        template_id: string
        status: string
        progress: number
        cover_url: string | null
        final_video_url?: string | null
        error_msg?: string | null
        pipeline_mode?: PipelineMode
        output_ratio?: string
        published?: boolean
        created_at: string
        updated_at?: string
        active_tasks?: Project['active_tasks']
      }>
      meta: { page: number; page_size: number; total: number }
      stats: { total: number; generating: number; done: number; published: number }
    }>(`/api/projects${qs ? `?${qs}` : ''}`)
  },
  /** 打包下载选中项目的视频，保留服务端文件名。 */
  async downloadZip(ids: number[]) {
    const res = await requestResponse('/api/projects/download-zip', {
      method: 'POST',
      body: JSON.stringify({ ids }),
    }, (response, detail) => {
      throw new Error(apiErrorMessage(detail, response.statusText) || '打包下载失败')
    })
    const blob = await res.blob()
    const cd = res.headers.get('Content-Disposition') || ''
    const m = cd.match(/filename="?([^"]+)"?/)
    const filename = m?.[1] || `framecut_videos_${Date.now()}.zip`
    return { blob, filename }
  },
  getProject(id: number) {
    return request<Project>(`/api/projects/${id}`)
  },
  generate(id: number, opts?: { restart?: boolean }) {
    const q = opts?.restart ? '?restart=true' : ''
    return request<Project>(`/api/projects/${id}/generate${q}`, { method: 'POST' })
  },
  cancelProject(id: number) {
    return request<Project>(`/api/projects/${id}/cancel`, { method: 'POST' })
  },
  deleteProject(id: number) {
    return request<{ ok: boolean; id: number }>(`/api/projects/${id}`, { method: 'DELETE' })
  },
  updateShot(projectId: number, shotId: number, body: Partial<Shot>) {
    return request<Shot>(`/api/projects/${projectId}/shots/${shotId}`, {
      method: 'PATCH',
      body: JSON.stringify(body),
    })
  },
  createShot(projectId: number) {
    return request<Shot>(`/api/projects/${projectId}/shots`, { method: 'POST' })
  },
  reorderShots(projectId: number, shotIds: number[]) {
    return request<Project>(`/api/projects/${projectId}/shots/reorder`, {
      method: 'POST',
      body: JSON.stringify({ shot_ids: shotIds }),
    })
  },
  /** 上传分镜图片，保留当前项目响应结构。 */
  uploadShotImage(projectId: number, shotId: number, file: File) {
    return uploadFile<Project>(`/api/projects/${projectId}/shots/${shotId}/image`, file, (_response, detail) => {
      throw new Error(typeof detail === 'string' ? detail : '画面上传失败')
    })
  },
  regenImage(projectId: number, shotId: number) {
    return request<Project>(`/api/projects/${projectId}/shots/${shotId}/regen-image`, {
      method: 'POST',
    })
  },
  regenVideo(projectId: number, shotId: number) {
    return request<Project>(`/api/projects/${projectId}/shots/${shotId}/regen-video`, {
      method: 'POST',
    })
  },
  regenAudio(projectId: number, shotId: number) {
    return request<Project>(`/api/projects/${projectId}/shots/${shotId}/regen-audio`, {
      method: 'POST',
    })
  },
  regenAllAudio(projectId: number) {
    return request<Project>(`/api/projects/${projectId}/regen-audio`, { method: 'POST' })
  },
  compose(projectId: number) {
    return request<Project>(`/api/projects/${projectId}/compose`, { method: 'POST' })
  },
  /** 扩写原始内容；创作参数单独传递，输出语言由内容而非界面语言决定。 */
  expandContent(topic: string, mode: 'theme' | 'script' = 'theme', options?: { target_duration_sec?: number; style?: string }) {
    return request<{ title: string; content: string }>('/api/content/expand', {
      method: 'POST',
      body: JSON.stringify({ topic, mode, ...options }),
    })
  },
  publish(projectId: number) {
    return request<Work>(`/api/projects/${projectId}/publish`, { method: 'POST' })
  },
  works() {
    return request<Work[]>('/api/works')
  },
  wallet() {
    return request<Wallet>('/api/billing/wallet?view=production')
  },
  billingSkus(language: 'zh' | 'en' = 'zh') {
    return request<{ skus: BillingSku[]; pay_types: string[]; markup: number; stripe_unavailable_reason?: string | null }>(`/api/billing/skus?language=${language}`)
  },
  createBillingOrder(sku_id: string, pay_type: 'alipay' | 'wxpay' | 'stripe', language: 'zh' | 'en' = 'zh') {
    return request<{
      out_trade_no: string
      sku_id: string
      sku_name: string
      submit_url: string
      amount_fen: number
      credit_fen: number
      pay_type: string
      payment_currency?: PaymentCurrency
      payment_amount_minor?: number
      payment_exchange_rate?: string
      trade_no?: string
      qrcode?: string
      payurl?: string
      img?: string
      qr_payload?: string
      /** qr=原生扫码；redirect=托管收银台 */
      pay_mode?: 'qr' | 'redirect' | string
      expire_seconds?: number
    }>('/api/billing/orders', {
      method: 'POST',
      body: JSON.stringify({ sku_id, pay_type, language }),
    })
  },
  getBillingOrder(outTradeNo: string) {
    return request<{
      out_trade_no: string
      status: string
      amount_fen: number
      credit_fen: number
      payment_currency?: PaymentCurrency
      payment_amount_minor?: number
      payment_exchange_rate?: string
    }>(`/api/billing/orders/${encodeURIComponent(outTradeNo)}`)
  },
  /** 关闭待支付订单 */
  closeBillingOrder(outTradeNo: string) {
    return request<{ out_trade_no: string; status: string }>(
      `/api/billing/orders/${encodeURIComponent(outTradeNo)}/close`,
      { method: 'POST' },
    )
  },
  listBillingOrders(limit = 50) {
    return request<{ orders: BillingOrder[] }>(`/api/billing/orders?limit=${limit}`)
  },
  usageSummary() {
    return request<UsageSummary>('/api/billing/usage/summary')
  },
  usageEvents(page = 1, pageSize = 20) {
    return request<UsageChargeList>(
      `/api/billing/usage/events?page=${page}&page_size=${pageSize}`,
    )
  },
  billingAlertsPending() {
    return request<{
      items: Array<{
        id: number
        kind: string
        title: string
        message: string
        milestone_fen: number
        milestone_yuan: number
        created_at?: string | null
      }>
    }>('/api/billing/alerts/pending')
  },
  billingAlertAck(alertId: number) {
    return request<{ ok: boolean }>(`/api/billing/alerts/${alertId}/ack`, { method: 'POST' })
  },
  billingPreflight(params: { domain: string; task_type: string; count?: number }) {
    const q = new URLSearchParams({
      domain: params.domain,
      task_type: params.task_type,
      count: String(params.count ?? 1),
    })
    if (workspaceScope.teamId !== null && params.domain === 'drama') q.set('team_id', String(workspaceScope.teamId))
    return request<BillingPreflight>(`/api/billing/preflight?${q.toString()}`)
  },
  eventsUrl(projectId: number) {
    return `${API_BASE}/api/projects/${projectId}/events`
  },
}
