import { useEffect, useState } from 'react'
import { getToken } from '@/lib/auth'
import { MarketplaceRequestError } from './errors'

export type Item = { id: number; version?: number; [key: string]: unknown }
export type Listing = { items: Item[]; meta: { page: number; page_size: number; total: number } }

// 管理端使用原管理员 token，但下游 API 完全隔离。
export async function request<T>(path: string, method = 'GET', body?: unknown): Promise<T> {
  let response: Response
  try {
    response = await fetch(path, { method, headers: { Authorization: `Bearer ${getToken() ?? ''}`, ...(body !== undefined ? { 'Content-Type': body instanceof Blob ? 'application/octet-stream' : 'application/json' } : {}) }, body: body === undefined ? undefined : body instanceof Blob ? body : JSON.stringify(body) })
  } catch (cause) {
    throw new MarketplaceRequestError(undefined, 0, '暂时无法连接服务，请检查网络后重试。', cause)
  }
  const value = await response.json().catch(() => ({}))
  if (!response.ok) throw new MarketplaceRequestError(value?.detail, response.status)
  return value as T
}

/** 管理端在线打开授权函，不把 OSS 地址交给浏览器直接下载。 */
export async function letterFile(id: number): Promise<Blob> {
  let response: Response
  try {
    response = await fetch(`/api/marketplace/authorizations/${id}/file`, { headers: { Authorization: `Bearer ${getToken() ?? ''}` } })
  } catch (cause) {
    throw new MarketplaceRequestError(undefined, 0, '授权函暂时无法打开，请检查网络后重试。', cause)
  }
  if (!response.ok) {
    const value = await response.json().catch(() => ({}))
    throw new MarketplaceRequestError(value?.detail, response.status, '授权函暂时无法打开，请稍后重试。')
  }
  return response.blob()
}

// 管理端菜单也由服务端能力发现控制，不另造前端开关。
export function useMarketplaceStatus() {
  const [state, setState] = useState({ enabled: false, loading: true, error: '' })
  const [revision, setRevision] = useState(0)
  useEffect(() => {
    let active = true
    setState({ enabled: false, loading: true, error: '' })
    request<{ enabled: boolean }>('/api/marketplace/capabilities')
      .then(value => { if (active) setState({ enabled: value.enabled, loading: false, error: '' }) })
      .catch(error => { if (active) setState({ enabled: false, loading: false, error: error instanceof Error ? error.message : '服务状态读取失败。' }) })
    return () => { active = false }
  }, [revision])
  return { ...state, retry: () => setRevision(value => value + 1) }
}

export function useMarketplaceEnabled() {
  return useMarketplaceStatus().enabled
}

// 管理员签名必须走原身份鉴权，不拼接 OSS 地址。
export async function assetUrl(id: number, purpose = 'original') {
  return (await request<{ url: string }>(`/api/marketplace/media/asset/${id}/${purpose}`)).url
}

/** 管理端在页面内预览图片或 PDF，不把 OSS 地址交给浏览器下载。 */
export async function assetFile(id: number, purpose = 'original'): Promise<Blob> {
  const response = await fetch(`/api/marketplace/media/asset/${id}/inline?purpose=${encodeURIComponent(purpose)}`, { headers: { Authorization: `Bearer ${getToken() ?? ''}` } })
  if (!response.ok) {
    const value = await response.json().catch(() => ({}))
    throw new Error(typeof value.detail === 'string' ? value.detail : '文件暂时无法预览')
  }
  const type = response.headers.get('content-type') || 'application/octet-stream'
  const blob = await response.blob()
  return blob.type ? blob : new Blob([blob], { type })
}
