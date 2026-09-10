/** API Key 管理客户端（/api/user/api-keys） */

function defaultApiBase() {
  if (typeof window !== 'undefined' && window.location?.hostname) {
    const { protocol, hostname } = window.location
    return `${protocol}//${hostname}:8000`
  }
  return 'http://127.0.0.1:8000'
}

const API_BASE =
  import.meta.env.VITE_API_BASE === undefined || import.meta.env.VITE_API_BASE === null
    ? defaultApiBase()
    : String(import.meta.env.VITE_API_BASE)

export type ApiKeyItem = {
  id: number
  name: string
  key_prefix: string
  created_at: string | null
  last_used_at: string | null
}

export type ApiKeyCreated = ApiKeyItem & {
  secret: string
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const token = localStorage.getItem('token')
  const res = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(init?.headers || {}),
    },
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
    throw new Error(message || '请求失败')
  }
  return res.json() as Promise<T>
}

export function getPublicApiBase() {
  return API_BASE
}

export const apiKeysApi = {
  list() {
    return request<ApiKeyItem[]>('/api/user/api-keys')
  },
  create(name: string) {
    return request<ApiKeyCreated>('/api/user/api-keys', {
      method: 'POST',
      body: JSON.stringify({ name }),
    })
  },
  revoke(id: number) {
    return request<{ ok: boolean }>(`/api/user/api-keys/${id}`, { method: 'DELETE' })
  },
}
