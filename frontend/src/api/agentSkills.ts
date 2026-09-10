/** Agent Skill API：列表 / 上传 / 启用 / 删除 */

import { getDramaApiBase } from './drama'

/** 组装请求头；FormData 时不要强行 JSON */
function authHeaders(json = true): HeadersInit {
  const token = localStorage.getItem('token')
  const headers: Record<string, string> = {}
  if (token) headers.Authorization = `Bearer ${token}`
  if (json) headers['Content-Type'] = 'application/json'
  return headers
}

/** 带登录态请求 Agent Skill API */
async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${getDramaApiBase()}${path}`, {
    ...init,
    headers: { ...authHeaders(init?.body instanceof FormData ? false : true), ...(init?.headers || {}) },
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }))
    const detail = err.detail
    throw new Error(typeof detail === 'string' ? detail : '请求失败')
  }
  return res.json()
}

export type AgentSkill = {
  id: number
  slug: string
  name: string
  description: string
  tasks: string[]
  is_builtin: boolean
  is_active: boolean
  user_id: number | null
  body: string
  created_at?: string | null
  updated_at?: string | null
}

/** 列出内置 + 当前用户 Skill */
export function listAgentSkills() {
  return request<{ items: AgentSkill[] }>('/api/drama/skills')
}

/** 上传 markdown 文本 */
export function uploadAgentSkillMarkdown(markdown: string) {
  return request<AgentSkill>('/api/drama/skills', {
    method: 'POST',
    body: JSON.stringify({ markdown }),
  })
}

/** 上传 .md 文件 */
export async function uploadAgentSkillFile(file: File) {
  const token = localStorage.getItem('token')
  const body = new FormData()
  body.append('file', file)
  const res = await fetch(`${getDramaApiBase()}/api/drama/skills/upload`, {
    method: 'POST',
    headers: token ? { Authorization: `Bearer ${token}` } : undefined,
    body,
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }))
    throw new Error(typeof err.detail === 'string' ? err.detail : '上传失败')
  }
  return res.json() as Promise<AgentSkill>
}

/** 启用/停用或改正文 */
export function patchAgentSkill(skillId: number, body: { markdown?: string; is_active?: boolean }) {
  return request<AgentSkill>(`/api/drama/skills/${skillId}`, {
    method: 'PATCH',
    body: JSON.stringify(body),
  })
}

/** 删除用户 Skill（内置不可删） */
export function deleteAgentSkill(skillId: number) {
  return request<{ ok: boolean }>(`/api/drama/skills/${skillId}`, { method: 'DELETE' })
}

/** 按勾选 Skill 优化提示词（保留 @asset 引用） */
export function optimizePromptWithSkills(body: {
  prompt: string
  skill_ids: number[]
  task?: 'video_prompt' | 'image_prompt' | 'shot_plan'
}) {
  return request<{ prompt: string }>('/api/drama/skills/optimize', {
    method: 'POST',
    body: JSON.stringify({
      prompt: body.prompt,
      skill_ids: body.skill_ids,
      task: body.task || 'video_prompt',
    }),
  })
}
