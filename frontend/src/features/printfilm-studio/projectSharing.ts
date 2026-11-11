import { createJsonRequester } from '../../api/client'

const request = createJsonRequester()
export type ProjectSharing = {
  is_owner: boolean
  members: { id: number; name: string; role: 'owner' | 'member' }[]
  invitations: { id: string; created_at: string; expires_at: string; status: 'active' | 'expired' | 'revoked' }[]
}
export const projectSharingApi = {
  info: (id: number) => request<{ id: number; title: string; is_owner: boolean }>(`/api/printfilm-studio/projects/${id}/info`),
  shared: () => request<{ items: { id: number; title: string }[] }>('/api/printfilm-studio/shared-canvases'),
  get: (id: number) => request<ProjectSharing>(`/api/printfilm-studio/projects/${id}/sharing`),
  invite: (id: number, days: number) => request<{ id: string; token: string; expires_at: string }>(`/api/printfilm-studio/projects/${id}/sharing/invitations`, { method: 'POST', body: JSON.stringify({ expires_days: days }) }),
  revoke: (id: number, invitationId: string) => request(`/api/printfilm-studio/projects/${id}/sharing/invitations/${invitationId}`, { method: 'DELETE' }),
  remove: (id: number, userId: number) => request(`/api/printfilm-studio/projects/${id}/sharing/members/${userId}`, { method: 'DELETE' }),
  accept: (token: string) => request<{ project_id: number }>('/api/printfilm-studio/canvas-invitations/accept', { method: 'POST', body: JSON.stringify({ token }) }),
}
