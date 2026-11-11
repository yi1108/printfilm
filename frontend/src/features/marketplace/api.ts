import { getActiveLocale } from '../../i18n/detect.ts'
import { marketText as mt } from './translate.ts'
import { explainMarketplaceError, marketplaceErrorCode } from './messages'

/** 下游独立客户端；不修改原 api.ts。金额统一以分传输。 */
export type Row = {
  app_editions?: ('domestic' | 'international')[];
  is_featured?: boolean; is_pinned?: boolean;
  id: number; title?: string; description?: string; category?: string; category_code?: string; category_label?: string; category_labels?: { zh: string; en: string }; author?: string;
  price_fen?: number; copyright_price_fen?: number; unlock_price_fen?: number; sale_type?: 'free' | 'copyright_contact' | 'platform_unlock'; share_bps?: number | null; budget_fen?: number; quote_fen?: number; wanted_count?: number;
  requirements?: string; license_scope?: string; image_ids?: number[]; deadline_at?: string;
  version?: number; asset_id?: number | null; cover_asset_id?: number | null; source?: string; tags?: string[];
  audit_status?: string; listed?: boolean; blocked?: boolean; reason?: string; media_status?: string;
  preview_status?: string; preview_error?: string;
  basic_status?: string; full_status?: string; owner_id?: number; state?: string; status?: string;
  rights_complete?: boolean; rights_ready?: boolean; rights_source?: string | null;
  filename?: string; kind?: string; error?: string; fingerprint?: string; duration_seconds?: number; episode_count?: number; free_episode_count?: number;
  recruit_id?: number; recruit_title?: string; selection?: string; withdrawn?: boolean;
  can_review?: boolean; can_purchase?: boolean; submission_count?: number;
  is_owner?: boolean; is_open?: boolean; can_submit?: boolean; can_contact?: boolean;
  rights_id?: number; route?: string; official_reference?: string; note?: string;
  historical?: boolean; message?: string; link?: string; read?: boolean; created_at?: string;
}
export type Listing = { items: Row[]; meta: { page: number; page_size: number; total: number } }
export type Capabilities = { enabled: boolean; storage_configured: boolean }
export type Handoff = {
  id: number; status: string; label: string; error: string; authorization_ready: boolean
  target_kind: string; target_id: number; work_id: number | null; episode_id: number | null
  series_id: number | null; asset_id: number | null
  phase?: string; error_code?: string | null; retryable?: boolean; target_version?: number
}
export type RightsRecord = {
  id?: number; asset_id: number; version: number; details?: Record<string, string>;
  certificate_asset_id?: number | null; evidence_ids?: number[]; valid_until?: string | null;
  preview_status?: string; preview_error?: string;
  basic_status?: string; full_status?: string; reason?: string; blocked?: boolean;
}

// 使用与用户端相同的 API 域名约定，但隔离请求实现。
export const base = import.meta.env.VITE_API_BASE ?? `${window.location.protocol}//${window.location.hostname}:8000`

// 统一解析中文业务错误；不把原项目令牌发给 OSS。
export async function request<T>(path: string, method = 'GET', body?: unknown, signal?: AbortSignal): Promise<T> {
  const token = localStorage.getItem('token')
  const binary = body instanceof Blob
  let response: Response
  try {
    response = await fetch(`${base}/api/marketplace${path}`, {
      method, signal, headers: { 'Accept-Language': getActiveLocale(), ...(token ? { Authorization: `Bearer ${token}` } : {}), ...(body !== undefined ? { 'Content-Type': binary ? 'application/octet-stream' : 'application/json' } : {}) },
      body: body === undefined ? undefined : binary ? body : JSON.stringify(body),
    })
  } catch (cause) {
    if (signal?.aborted) throw cause
    throw new Error(mt("网络连接失败，请检查网络后重试。"), { cause })
  }
  const result = await response.json().catch(() => ({}))
  if (!response.ok) {
    if (response.status === 401) window.location.assign(`/auth?next=${encodeURIComponent(window.location.pathname + window.location.search)}`)
    const detail = result?.detail
    throw Object.assign(new Error(explainMarketplaceError(detail, response.status)), { code: marketplaceErrorCode(detail) || result?.error?.code, status: response.status })
  }
  return result as T
}

/** 已签署授权函的文件流。默认由接口 inline 返回，页面再用本地对象地址预览。 */
export async function letterFile(id: number): Promise<Blob> {
  const token = localStorage.getItem('token')
  let response: Response
  try {
    response = await fetch(`${base}/api/marketplace/authorizations/${id}/file`, {
      headers: { 'Accept-Language': getActiveLocale(), ...(token ? { Authorization: `Bearer ${token}` } : {}) },
    })
  } catch {
    throw new Error(mt("授权函暂时无法打开"))
  }
  if (!response.ok) {
    if (response.status === 401) window.location.assign(`/auth?next=${encodeURIComponent(window.location.pathname + window.location.search)}`)
    const result = await response.json().catch(() => ({}))
    const detail = result?.detail
    throw Object.assign(new Error(explainMarketplaceError(detail, response.status)), { code: marketplaceErrorCode(detail) || result?.error?.code, status: response.status })
  }
  return response.blob()
}

// 只在需要观看时申请短时链接，不能把 object_key 放到前端。
export async function media(kind: string, id: number, purpose: string) {
  return (await request<{ url: string }>(`/media/${kind}/${id}/${purpose}`)).url
}

// 续传键只用本地指纹。HTTPS 用 SHA-256；HTTP 页面没有 crypto.subtle，改用同一段字节的纯计算。
async function sampleDigest(sample: ArrayBuffer): Promise<string> {
  const subtle = globalThis.crypto?.subtle
  if (subtle) {
    const hash = await subtle.digest('SHA-256', sample)
    return Array.from(new Uint8Array(hash), value => value.toString(16).padStart(2, '0')).join('')
  }
  const bytes = new Uint8Array(sample)
  let high = 0x811c9dc5
  let low = 0x01000193
  for (let index = 0; index < bytes.length; index++) {
    high = Math.imul(high ^ bytes[index], 0x01000193)
    low = Math.imul(low ^ bytes[bytes.length - 1 - index], 0x01000193)
  }
  const hex = (value: number) => (value >>> 0).toString(16).padStart(8, '0')
  return hex(high) + hex(low)
}

// 保留用户选择的文件；使用首尾片段指纹区分续传，不读取整段视频。
export async function upload(file: File, kind: string, progress: (percent: number) => void, signal?: AbortSignal): Promise<number> {
  const sample = await new Blob([file.slice(0, 65536), file.slice(-65536)]).arrayBuffer()
  const digest = await sampleDigest(sample)
  const key = `marketplace-upload:${file.name}:${file.size}:${file.lastModified}:${digest}`
  type Session = { id: number; asset_id: number; state: string; part_size: number; uploaded_parts: number[]; expires_at: string }
  let session: Session | undefined
  signal?.throwIfAborted()
  try {
  const stored = localStorage.getItem(key)
  if (stored) {
    try {
      const candidate = await request<Session>(`/uploads/${stored}`)
      if (candidate.state === 'uploading' && Date.parse(candidate.expires_at) > Date.now()) session = candidate
    } catch { localStorage.removeItem(key) }
  }
  if (!session) {
    session = await request<Session>('/uploads', 'POST', { filename: file.name, size_bytes: file.size, kind })
    localStorage.setItem(key, String(session.id))
  }
  const count = Math.ceil(file.size / session.part_size)
  const uploaded = new Set(session.uploaded_parts)
  for (let number = 1; number <= count; number++) {
    if (!uploaded.has(number)) {
      const part = file.slice((number - 1) * session.part_size, number * session.part_size)
      let success = false
      for (let attempt = 0; attempt < 3; attempt++) {
        try { await request(`/uploads/${session.id}/parts/${number}`, 'PUT', part, signal); success = true; break }
        catch (error) { if (signal?.aborted || attempt === 2) throw error }
      }
      if (success) uploaded.add(number)
    }
    progress(Math.floor(uploaded.size / count * 100))
  }
  signal?.throwIfAborted()
  await request(`/uploads/${session.id}/complete`, 'POST', undefined, signal)
  localStorage.removeItem(key)
  return session.asset_id
  } catch (error) {
    if (signal?.aborted && session) {
      try { await request(`/uploads/${session.id}`, 'DELETE'); localStorage.removeItem(key) }
      catch { throw new Error(mt("取消未确认，请到我的文件检查状态；重新选择相同文件可恢复上传。")) }
      throw new Error(mt("已取消上传"))
    }
    throw error
  }
}

// 以分展示人民币，避免浮点金额进入业务接口。
export const money = (value?: number) => `¥${((value ?? 0) / 100).toFixed(2)}`
// 北京时间展示，服务端保留 UTC。
export const date = (value?: string) => value ? new Date(value).toLocaleString(getActiveLocale() === 'en' ? 'en-GB' : 'zh-CN', { timeZone: 'Asia/Shanghai' }) : '—'
// 将UTC转为当前浏览器datetime-local值，避免表单回填时改变时区。
export function localDate(value: string) { const date = new Date(value); return new Date(date.getTime() - date.getTimezoneOffset() * 60000).toISOString().slice(0, 16) }
// 状态不在客户端推断，仅翻译后端结果。
export const labels: Record<string, string> = new Proxy<Record<string, string>>({ draft: '草稿', preview_failed: '短试看生成失败', pending: '待审核', approved: '已通过', rejected: '已驳回', missing: '未提交', ready: '已就绪', processing: '处理中', uploading: '上传中', failed: '失败', open: '征集中', closed: '已关闭', expired: '已到期', to_review: '待看', candidate: '候选', not_selected: '不采用', pending_materials: '待材料', reviewing: '材料核验中', supplement: '待补正', applying: '办理中', certificated: '已取得证书', cancelled: '已取消', existing: '已有证书', self_service: '自行办理', assisted: '客服协办' }, { get: (target, key: string) => target[key] ? mt(target[key]) : undefined })


