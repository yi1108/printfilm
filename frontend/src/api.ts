import { throwApiError } from './lib/apiError'

function defaultApiBase() {
  if (typeof window !== 'undefined' && window.location?.hostname) {
    const { protocol, hostname } = window.location
    // Same host as Vite; API listens on 8000 for LAN + local
    return `${protocol}//${hostname}:8000`
  }
  return 'http://127.0.0.1:8000'
}

// Empty string = same-origin (nginx proxies /api). Undefined = LAN default :8000.
const _viteApiBase = import.meta.env.VITE_API_BASE
const API_BASE =
  _viteApiBase === undefined || _viteApiBase === null ? defaultApiBase() : String(_viteApiBase)

function authHeaders(): HeadersInit {
  const token = localStorage.getItem('token')
  return token
    ? { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' }
    : { 'Content-Type': 'application/json' }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: { ...authHeaders(), ...(init?.headers || {}) },
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }))
    throwApiError(res.status, err.detail, res.statusText)
  }
  return res.json()
}

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

/** Template voice_preset alias → openspeech speaker id */
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

export type Project = {
  id: number
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
  style_prompt?: string
  character_prompt?: string
  extra_prompt?: string
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
}

export type UsageSummary = {
  period: string
  tokens: number
  charge_fen: number
  charge_yuan: number
  cost_fen: number
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
  async uploadAvatar(file: File) {
    const token = localStorage.getItem('token')
    const form = new FormData()
    form.append('file', file)
    const res = await fetch(`${API_BASE}/api/auth/avatar`, {
      method: 'POST',
      headers: token ? { Authorization: `Bearer ${token}` } : {},
      body: form,
    })
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: res.statusText }))
      const detail = err.detail
      const message =
        typeof detail === 'string'
          ? detail
          : Array.isArray(detail)
            ? detail.map((d: { msg?: string }) => d.msg || JSON.stringify(d)).join('; ')
            : res.statusText
      throw new Error(message || '头像上传失败')
    }
    return res.json() as Promise<User>
  },
  templates() {
    return request<Template[]>('/api/templates')
  },
  createProject(body: {
    template_id: string
    title: string
    source_type: 'theme' | 'script'
    source_text: string
    resolution_mode?: 'preview' | 'hd'
    pipeline_mode?: PipelineMode
    output_ratio?: string
    voice_id?: string
    style_prompt?: string
    character_prompt?: string
    extra_prompt?: string
  }) {
    return request<Project>('/api/projects', { method: 'POST', body: JSON.stringify(body) })
  },
  updateProject(
    id: number,
    body: {
      title?: string
      source_type?: 'theme' | 'script'
      source_text?: string
      template_id?: string
      pipeline_mode?: PipelineMode
      output_ratio?: string
      resolution_mode?: 'preview' | 'hd'
      voice_id?: string
      style_prompt?: string
      character_prompt?: string
      extra_prompt?: string
      cover_url?: string | null
    },
  ) {
    return request<Project>(`/api/projects/${id}`, {
      method: 'PATCH',
      body: JSON.stringify(body),
    })
  },
  async uploadCover(id: number, file: File) {
    const token = localStorage.getItem('token')
    const form = new FormData()
    form.append('file', file)
    const res = await fetch(`${API_BASE}/api/projects/${id}/cover`, {
      method: 'POST',
      headers: token ? { Authorization: `Bearer ${token}` } : {},
      body: form,
    })
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: res.statusText }))
      const detail = err.detail
      const message =
        typeof detail === 'string'
          ? detail
          : Array.isArray(detail)
            ? detail.map((d: { msg?: string }) => d.msg || JSON.stringify(d)).join('; ')
            : res.statusText
      throw new Error(message || '封面上传失败')
    }
    return res.json() as Promise<Project>
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
  async downloadZip(ids: number[]) {
    const res = await fetch(`${API_BASE}/api/projects/download-zip`, {
      method: 'POST',
      headers: authHeaders(),
      body: JSON.stringify({ ids }),
    })
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: res.statusText }))
      const detail = err.detail
      const message =
        typeof detail === 'string'
          ? detail
          : Array.isArray(detail)
            ? detail.map((d: { msg?: string }) => d.msg || JSON.stringify(d)).join('; ')
            : res.statusText
      throw new Error(message || '打包下载失败')
    }
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
  expandContent(topic: string, mode: 'theme' | 'script' = 'theme') {
    return request<{ title: string; content: string }>('/api/content/expand', {
      method: 'POST',
      body: JSON.stringify({ topic, mode }),
    })
  },
  publish(projectId: number) {
    return request<Work>(`/api/projects/${projectId}/publish`, { method: 'POST' })
  },
  works() {
    return request<Work[]>('/api/works')
  },
  wallet() {
    return request<Wallet>('/api/billing/wallet')
  },
  billingSkus() {
    return request<{ skus: BillingSku[]; pay_types: string[]; markup: number }>('/api/billing/skus')
  },
  createBillingOrder(sku_id: string, pay_type: 'alipay' | 'wxpay') {
    return request<{
      out_trade_no: string
      sku_id: string
      sku_name: string
      submit_url: string
      amount_fen: number
      credit_fen: number
      pay_type: string
      trade_no?: string
      qrcode?: string
      payurl?: string
      img?: string
      qr_payload?: string
      /** qr=原生扫码；redirect=新开易支付收银台 */
      pay_mode?: 'qr' | 'redirect' | string
      expire_seconds?: number
    }>('/api/billing/orders', {
      method: 'POST',
      body: JSON.stringify({ sku_id, pay_type }),
    })
  },
  getBillingOrder(outTradeNo: string) {
    return request<{
      out_trade_no: string
      status: string
      amount_fen: number
      credit_fen: number
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
    return request<BillingPreflight>(`/api/billing/preflight?${q.toString()}`)
  },
  eventsUrl(projectId: number) {
    return `${API_BASE}/api/projects/${projectId}/events`
  },
}
