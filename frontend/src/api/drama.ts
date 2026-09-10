import { throwApiError } from '../lib/apiError'

function defaultApiBase() {
  if (typeof window !== 'undefined' && window.location?.hostname) {
    const { protocol, hostname } = window.location
    return `${protocol}//${hostname}:8000`
  }
  return 'http://127.0.0.1:8000'
}

const _viteApiBase = import.meta.env.VITE_API_BASE
const API_BASE =
  _viteApiBase === undefined || _viteApiBase === null ? defaultApiBase() : String(_viteApiBase)

/** 导出 API 根地址，供静态资源 URL 拼接 */
export function getDramaApiBase() {
  return API_BASE
}

/** 将 /static 相对路径补全为可访问的绝对 URL */
export function resolveDramaMediaUrl(url?: string | null): string {
  if (!url) return ''
  if (url.startsWith('http://') || url.startsWith('https://') || url.startsWith('data:')) {
    return url
  }
  if (url.startsWith('/')) return `${API_BASE}${url}`
  return url
}

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
    throwApiError(res.status, err.detail, '请求失败')
  }
  return res.json()
}

export type DramaScript = {
  id: number
  name: string
  source?: string | null
  summary?: Record<string, unknown> | null
  episode_content?: { episodes?: DramaEpisodeBody[] } | DramaEpisodeBody[] | null
  params?: Record<string, unknown> | null
  project_id: number
}

export type DramaEpisodeBody = {
  episodeNumber?: number
  title?: string
  body?: string
}

export type DramaProjectUsageStats = {
  charge_fen: number
  charge_yuan: number
  cost_fen: number
  cost_yuan: number
  tokens: number
  calls: number
  image_gens: number
  video_gens: number
}

export type DramaTaskBrief = {
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
  drama_project_id?: number | null
  episode_id?: number | null
  fragment_id?: number | null
  asset_id?: number | null
  created_at?: string
  updated_at?: string
}

export type DramaProject = {
  id: number
  user_id: number
  title: string
  description?: string | null
  content?: Record<string, unknown> | null
  params?: Record<string, unknown> | null
  created_at?: string
  updated_at?: string
  script?: DramaScript | null
  asset_count: number
  episode_count: number
  workflow?: 'script' | 'canvas'
  usage?: DramaProjectUsageStats
  active_tasks?: DramaTaskBrief[]
}

export type DramaProjectListItem = {
  id: number
  title: string
  description?: string | null
  created_at?: string
  updated_at?: string
  episode_count: number
  asset_count: number
  has_script: boolean
  cover_url?: string | null
  cover_pending?: boolean
  workflow?: 'script' | 'canvas'
  usage?: DramaProjectUsageStats
  active_tasks?: DramaTaskBrief[]
}

export type DramaAsset = {
  id: number
  type: string
  asset_type: string
  name?: string | null
  cover?: string | null
  url?: string | null
  params?: Record<string, unknown> | null
  project_id: number
}

export type SeedAssetsResult = {
  assets: DramaAsset[]
  created_count: number
  prompts_refreshed: number
  props_updated: number
  llm_errors: string[]
  status?: string
  message?: string | null
}

export type DramaFragment = {
  id: number
  episode_id: number
  sort_order: number
  content: string
  cover: string
  video: string
  duration_sec?: number | null
  params?: Record<string, unknown> | null
  asset_ids: number[]
}

export type DramaEpisode = {
  id: number
  name: string
  params?: Record<string, unknown> | null
  project_id: number
  fragments: DramaFragment[]
  active_tasks?: DramaTaskBrief[]
}

export type DramaScriptSummaryResult = {
  ok?: boolean
  queued?: boolean
  status?: string
  task_id?: string | null
  summary?: Record<string, unknown>
  text?: string
  script: DramaScript
  projectTitle?: string
}

export type DramaEpisodeScriptResult = {
  ok?: boolean
  queued?: boolean
  status?: string
  task_id?: string | null
  episodes: DramaEpisodeBody[]
  total_generated: number
  total_target: number
  done: boolean
  script: DramaScript
}

export type DramaImageGenerateResult = {
  ok: boolean
  queued: boolean
  status: string
  task_id?: string | null
  asset_id?: number | null
  asset?: DramaAsset | null
}

export type DramaVideoGenerateResult = DramaImageGenerateResult

export type DramaVoicePromptResult = {
  ok: boolean
  voice_prompt: string
  speaker?: string
  sample_text?: string
  asset_id: number
}

export type DramaVoiceGenerateResult = {
  ok: boolean
  asset: DramaAsset
}

export const dramaApi = {
  listProjects: () => request<DramaProjectListItem[]>('/api/drama/projects'),
  createProject: (body: {
    title?: string
    description?: string
    source?: string
    episode_count?: number
    image_style_id?: string
    workflow?: 'script' | 'canvas'
  }) =>
    request<DramaProject>('/api/drama/projects', { method: 'POST', body: JSON.stringify(body) }),
  getProject: (id: number) => request<DramaProject>(`/api/drama/projects/${id}`),
  updateProject: (id: number, body: { title?: string; description?: string; params?: Record<string, unknown> | null }) =>
    request<DramaProject>(`/api/drama/projects/${id}`, { method: 'PATCH', body: JSON.stringify(body) }),
  deleteProject: (id: number) =>
    request<{ ok: boolean }>(`/api/drama/projects/${id}`, { method: 'DELETE' }),

  getScript: (projectId: number) => request<DramaScript>(`/api/drama/scripts/${projectId}`),
  updateScript: (
    projectId: number,
    body: {
      image_style_id?: string
      summary?: Record<string, unknown>
      episode_content?: unknown
      source?: string
      name?: string
    },
  ) =>
    request<DramaScript>(`/api/drama/scripts/${projectId}`, {
      method: 'PATCH',
      body: JSON.stringify(body),
    }),

  scriptSummary: (body: {
    project_id: number
    creative?: string
    episode_count?: number
    image_style_id?: string
  }) =>
    request<DramaScriptSummaryResult>('/api/drama/agents/script_summary', {
      method: 'POST',
      body: JSON.stringify(body),
    }),
  episodeScript: (body: { project_id: number; batch_size?: number; force?: boolean }) =>
    request<DramaEpisodeScriptResult>('/api/drama/agents/episode_script', {
      method: 'POST',
      body: JSON.stringify(body),
    }),
  route: (message: string) =>
    request<{ agent: string; action: string }>('/api/drama/agents/route', {
      method: 'POST',
      body: JSON.stringify({ message }),
    }),
  chat: (message: string, project_id?: number) =>
    request<{ reply: string }>('/api/drama/ai/chat', {
      method: 'POST',
      body: JSON.stringify({ message, project_id }),
    }),

  listAssets: async (projectId?: number, options?: { libraryOnly?: boolean }) => {
    const params = new URLSearchParams()
    if (projectId != null) params.set('project_id', String(projectId))
    if (options?.libraryOnly) params.set('library_only', 'true')
    const query = params.toString()
    const list = await request<DramaAsset[]>(
      query ? `/api/drama/assets?${query}` : '/api/drama/assets',
    )
    return Array.isArray(list) ? list : []
  },
  createAsset: (body: Partial<DramaAsset> & { project_id: number }) =>
    request<DramaAsset>('/api/drama/assets', { method: 'POST', body: JSON.stringify(body) }),
  updateAsset: (id: number, body: Partial<DramaAsset>) =>
    request<DramaAsset>(`/api/drama/assets/${id}`, { method: 'PATCH', body: JSON.stringify(body) }),
  uploadAssetMedia: async (assetId: number, file: File) => {
    const token = localStorage.getItem('token')
    const form = new FormData()
    form.append('file', file)
    const res = await fetch(`${API_BASE}/api/drama/assets/${assetId}/upload`, {
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
      throw new Error(message || '上传失败')
    }
    return res.json() as Promise<DramaAsset>
  },
  deleteAsset: (id: number) =>
    request<{ ok: boolean }>(`/api/drama/assets/${id}`, { method: 'DELETE' }),
  seedAssets: async (
    projectId: number,
    options?: { refreshPrompts?: boolean; reextractProps?: boolean },
  ) => {
    const params = new URLSearchParams({ project_id: String(projectId) })
    if (options?.refreshPrompts) params.set('refresh_prompts', 'true')
    if (options?.reextractProps) params.set('reextract_props', 'true')
    const result = await request<SeedAssetsResult>(`/api/drama/assets/seed_from_script?${params}`, {
      method: 'POST',
    })
    return {
      ...result,
      assets: Array.isArray(result?.assets) ? result.assets : [],
      created_count: result?.created_count ?? 0,
      prompts_refreshed: result?.prompts_refreshed ?? 0,
      props_updated: result?.props_updated ?? 0,
      llm_errors: Array.isArray(result?.llm_errors) ? result.llm_errors : [],
      status: result?.status ?? 'done',
      message: result?.message ?? null,
    }
  },

  listEpisodes: (projectId: number) =>
    request<DramaEpisode[]>(`/api/drama/episodes?project_id=${projectId}`),
  getEpisode: (id: number) => request<DramaEpisode>(`/api/drama/episodes/${id}`),
  updateEpisode: (id: number, body: { name?: string; params?: Record<string, unknown> | null }) =>
    request<DramaEpisode>(`/api/drama/episodes/${id}`, {
      method: 'PATCH',
      body: JSON.stringify(body),
    }),
  seedEpisodes: (projectId: number, force = false) =>
    request<DramaEpisode[]>(
      `/api/drama/episodes/seed_from_script?project_id=${projectId}${force ? '&force=true' : ''}`,
      { method: 'POST' },
    ),
  /** 单集 AI（LLM）重新分镜；轮询 episode.params.fragment_plan_status */
  planEpisodeFragments: (
    episodeId: number,
    body?: { force?: boolean; fallback_rules?: boolean; skill_ids?: number[]; subtitle_enabled?: boolean },
  ) =>
    request<DramaEpisode>(`/api/drama/episodes/${episodeId}/plan_fragments`, {
      method: 'POST',
      body: JSON.stringify({
        force: body?.force ?? true,
        fallback_rules: body?.fallback_rules ?? true,
        skill_ids: body?.skill_ids,
        subtitle_enabled: body?.subtitle_enabled,
      }),
    }),
  saveFragments: (
    episodeId: number,
    fragments: Array<{
      id?: number
      sort_order: number
      content: string
      cover?: string
      video?: string
      duration_sec?: number | null
      params?: Record<string, unknown> | null
      asset_ids?: number[]
    }>,
  ) =>
    request<DramaEpisode>(`/api/drama/episodes/${episodeId}/fragments`, {
      method: 'POST',
      body: JSON.stringify({ fragments }),
    }),
  generateEpisode: (episodeId: number, fragment_ids?: number[]) =>
    request<{
      ok: boolean
      fragment_ids: number[]
      status: string
      deferred_count?: number
      user_job_limit?: number
      remaining_not_queued?: number
    }>(`/api/drama/episodes/${episodeId}/generate`, {
      method: 'POST',
      body: JSON.stringify({ fragment_ids }),
    }),
  generateStatus: (episodeId: number) =>
    request<{
      episode_id: number
      done: number
      failed: number
      running: number
      total: number
      tasks: DramaTaskBrief[]
      fragments: Array<{ fragment_id: number; status: string; video?: string; cover?: string }>
    }>(`/api/drama/episodes/${episodeId}/generate_status`),

  /** 服务端统一重编码拼接本集（浏览器无损失败时回退） */
  composeEpisode: (episodeId: number, fragmentIds?: number[]) =>
    request<{ ok: boolean; video_url: string; episode_id: number }>(
      `/api/drama/episodes/${episodeId}/compose`,
      {
        method: 'POST',
        body: JSON.stringify({ fragment_ids: fragmentIds }),
      },
    ),

  cancelEpisodeGenerate: (episodeId: number) =>
    request<{ ok: boolean; episode_id: number; fragments: number }>(
      `/api/drama/episodes/${episodeId}/cancel_generate`,
      { method: 'POST' },
    ),

  activateFragmentVideoVersion: (fragmentId: number, versionId: string) =>
    request<{
      ok: boolean
      fragment_id: number
      video: string
      cover: string
      lastFrameUrl?: string | null
      video_versions: Array<Record<string, unknown>>
    }>(`/api/drama/fragments/${fragmentId}/activate_video_version`, {
      method: 'POST',
      body: JSON.stringify({ version_id: versionId }),
    }),

  cancelAllVideoJobs: () =>
    request<{ ok: boolean; purged: number; revoked: number; fragments: number }>(
      '/api/drama/cancel_video_jobs',
      { method: 'POST' },
    ),

  generateImage: (body: {
    project_id: number
    asset_id?: number
    prompt: string
    name?: string
    asset_type_kind?: string
    image_style_id?: string
    model_id?: string
    aspect_ratio?: string
    resolution?: string
  }) =>
    request<DramaImageGenerateResult>('/api/drama/generation/image', {
      method: 'POST',
      body: JSON.stringify(body),
    }),

  generateVideo: (body: {
    project_id: number
    asset_id: number
    prompt: string
    model_id?: string
    aspect_ratio?: string
    resolution?: string
    duration_sec?: number
    image_style_id?: string
    reference_asset_ids?: number[]
  }) =>
    request<DramaVideoGenerateResult>('/api/drama/generation/video', {
      method: 'POST',
      body: JSON.stringify(body),
    }),

  generateVoice: (body: {
    project_id: number
    asset_id?: number
    name?: string
    voice_prompt: string
    sample_text?: string
    speaker?: string
    character_asset_id?: number
  }) =>
    request<DramaVoiceGenerateResult>('/api/drama/generation/voice', {
      method: 'POST',
      body: JSON.stringify(body),
    }),

  suggestVoicePrompt: (body: { project_id: number; asset_id: number }) =>
    request<DramaVoicePromptResult>('/api/drama/generation/voice_prompt', {
      method: 'POST',
      body: JSON.stringify(body),
    }),

  getCanvas: (projectId: number) =>
    request<{ project_id: number; nodes: unknown[]; edges: unknown[] }>(
      `/api/drama/canvas/${projectId}`,
    ),
  saveCanvas: (body: { project_id: number; nodes: unknown[]; edges: unknown[] }) =>
    request<{ ok: boolean }>('/api/drama/canvas', { method: 'POST', body: JSON.stringify(body) }),
}
